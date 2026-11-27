// Dependency-free dense ADMM for bounded convex MPC quadratic programs.
// Diagonal equilibration and fixed stopping rules keep results repeatable across cycles.
#include "crosscut/qp.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <numeric>
#include <stdexcept>

namespace crosscut::mpc {
namespace {
constexpr int MAX_ITERATIONS = 10000;  // Iterations per priority attempt.
constexpr int CHECK_INTERVAL = 25;  // Iterations between residual/certificate checks.
constexpr int SCALE_ITERATIONS = 10;  // Fixed Ruiz equilibration passes.
constexpr double SOLVER_TOLERANCE = 1e-7;  // Scaled absolute and relative residual units.
constexpr double ACCEPTANCE_TOLERANCE = 2e-5;  // Constraint engineering units.
constexpr double INFEASIBILITY_TOLERANCE = 1e-7;  // Relative dual-ray residual.
constexpr double SIGMA = 1e-6;  // Proximal regularisation; does not change the objective.
constexpr double RELAXATION = 1.6;  // ADMM over-relaxation, dimensionless.
constexpr double SLACK_PENALTY = 1000.0;  // Relative squared CV-slack cost.
constexpr double INFINITY_VALUE = std::numeric_limits<double>::infinity();

double norm(const Vector& values) {
  double maximum = 0.0;
  for (double value : values) maximum = std::max(maximum, std::abs(value));
  return maximum;
}

double dot(const Vector& left, const Vector& right) {
  return std::inner_product(left.begin(), left.end(), right.begin(), 0.0);
}

Vector multiply(const Matrix& matrix, const Vector& values) {
  Vector product(matrix.size());
  for (std::size_t row = 0; row < matrix.size(); ++row) product[row] = dot(matrix[row], values);
  return product;
}

Vector transpose_multiply(const Matrix& matrix, const Vector& values, std::size_t columns) {
  Vector product(columns, 0.0);
  for (std::size_t row = 0; row < matrix.size(); ++row)
    for (std::size_t column = 0; column < columns; ++column)
      product[column] += matrix[row][column] * values[row];
  return product;
}

Vector difference(const Vector& left, const Vector& right) {
  Vector result(left.size());
  for (std::size_t index = 0; index < left.size(); ++index) result[index] = left[index] - right[index];
  return result;
}

void validate_matrix(const Matrix& matrix, std::size_t rows, std::size_t columns) {
  if (matrix.size() != rows) throw std::invalid_argument("QP matrix has an incorrect row count");
  for (const auto& row : matrix) {
    if (row.size() != columns) throw std::invalid_argument("QP matrix has an incorrect column count");
    for (double value : row)
      if (!std::isfinite(value)) throw std::invalid_argument("QP coefficients must be finite");
  }
}

void validate_symmetry(const Matrix& quadratic) {
  constexpr double SYMMETRY_TOLERANCE = 1e-10;  // Relative coefficient tolerance.
  for (std::size_t row = 0; row < quadratic.size(); ++row)
    for (std::size_t column = 0; column < row; ++column)
      if (std::abs(quadratic[row][column] - quadratic[column][row]) >
          SYMMETRY_TOLERANCE * (1.0 + std::abs(quadratic[row][column])))
        throw std::invalid_argument("QP quadratic cost must be symmetric");
}

void validate_program(const Program& program) {
  const auto size = program.linear.size();
  if (size == 0 || program.lower.size() != program.upper.size())
    throw std::invalid_argument("QP requires decisions and matching lower/upper bounds");
  validate_matrix(program.quadratic, size, size);
  validate_symmetry(program.quadratic);
  validate_matrix(program.matrix, program.lower.size(), size);
  for (double value : program.linear)
    if (!std::isfinite(value)) throw std::invalid_argument("QP linear cost must be finite");
  for (std::size_t row = 0; row < program.lower.size(); ++row)
    if (std::isnan(program.lower[row]) || std::isnan(program.upper[row]) ||
        program.lower[row] == INFINITY_VALUE || program.upper[row] == -INFINITY_VALUE)
      throw std::invalid_argument("QP bounds may only use outward-facing infinities");
}

bool consistent(const Program& program) {
  for (std::size_t row = 0; row < program.lower.size(); ++row)
    if (program.lower[row] > program.upper[row]) return false;
  return true;
}

struct ScaledProgram {
  Program program;
  Vector decision_scale;
};

void scale_columns(ScaledProgram& scaled, const Vector& factors) {
  auto& program = scaled.program;
  for (std::size_t column = 0; column < factors.size(); ++column) {
    scaled.decision_scale[column] *= factors[column];
    program.linear[column] *= factors[column];
    for (auto& row : program.matrix) row[column] *= factors[column];
    for (std::size_t row = 0; row < factors.size(); ++row)
      program.quadratic[row][column] *= factors[row] * factors[column];
  }
}

void equilibrate(ScaledProgram& scaled) {
  auto& program = scaled.program;
  Vector factors(program.linear.size(), 1.0);
  for (std::size_t column = 0; column < factors.size(); ++column) {
    double maximum = norm(program.quadratic[column]);
    for (const auto& row : program.matrix) maximum = std::max(maximum, std::abs(row[column]));
    if (maximum > 1e-12) factors[column] = 1.0 / std::sqrt(maximum);
  }
  scale_columns(scaled, factors);
  for (std::size_t row = 0; row < program.matrix.size(); ++row) {
    const double maximum = norm(program.matrix[row]);
    const double factor = maximum > 1e-12 ? 1.0 / std::sqrt(maximum) : 1.0;
    for (auto& value : program.matrix[row]) value *= factor;
    program.lower[row] *= factor;
    program.upper[row] *= factor;
  }
}

ScaledProgram scale_program(const Program& original) {
  ScaledProgram scaled{original, Vector(original.linear.size(), 1.0)};
  for (int iteration = 0; iteration < SCALE_ITERATIONS; ++iteration) equilibrate(scaled);
  double maximum = norm(scaled.program.linear);
  for (const auto& row : scaled.program.quadratic) maximum = std::max(maximum, norm(row));
  const double factor = 1.0 / std::max(1.0, maximum);
  for (auto& value : scaled.program.linear) value *= factor;
  for (auto& row : scaled.program.quadratic)
    for (auto& value : row) value *= factor;
  return scaled;
}

Matrix normal_matrix(const Program& program, double penalty) {
  Matrix normal = program.quadratic;
  for (std::size_t row = 0; row < normal.size(); ++row) {
    normal[row][row] += SIGMA;
    for (std::size_t column = 0; column <= row; ++column) {
      double value = 0.0;
      for (const auto& constraint : program.matrix) value += constraint[row] * constraint[column];
      normal[row][column] += penalty * value;
      normal[column][row] = normal[row][column];
    }
  }
  return normal;
}

Matrix factorize(Matrix normal) {
  for (std::size_t row = 0; row < normal.size(); ++row) {
    for (std::size_t column = 0; column <= row; ++column) {
      double value = normal[row][column];
      for (std::size_t index = 0; index < column; ++index)
        value -= normal[row][index] * normal[column][index];
      if (row == column && !(value > 0.0))
        throw std::invalid_argument("QP quadratic cost must be positive semidefinite");
      normal[row][column] = row == column ? std::sqrt(value) : value / normal[column][column];
    }
  }
  return normal;
}

Vector solve_factor(const Matrix& factor, Vector right) {
  for (std::size_t row = 0; row < right.size(); ++row) {
    for (std::size_t column = 0; column < row; ++column)
      right[row] -= factor[row][column] * right[column];
    right[row] /= factor[row][row];
  }
  for (std::size_t index = right.size(); index > 0; --index) {
    const auto row = index - 1;
    for (std::size_t column = row + 1; column < right.size(); ++column)
      right[row] -= factor[column][row] * right[column];
    right[row] /= factor[row][row];
  }
  return right;
}

struct Iterates {
  Vector decisions;
  Vector projected;
  Vector dual;
  Vector dual_change;
  double penalty = 0.1;  // Initial scaled constraint penalty.
};

void update_decisions(const Program& program, const Matrix& factor, Iterates& state) {
  Vector right(state.projected.size());
  for (std::size_t row = 0; row < right.size(); ++row)
    right[row] = state.penalty * state.projected[row] - state.dual[row];
  right = transpose_multiply(program.matrix, right, state.decisions.size());
  for (std::size_t index = 0; index < right.size(); ++index)
    right[index] += SIGMA * state.decisions[index] - program.linear[index];
  state.decisions = solve_factor(factor, std::move(right));
}

void update_projection(const Program& program, Iterates& state) {
  const Vector applied = multiply(program.matrix, state.decisions);
  for (std::size_t row = 0; row < applied.size(); ++row) {
    const double relaxed = RELAXATION * applied[row] + (1.0 - RELAXATION) * state.projected[row];
    state.projected[row] = std::clamp(relaxed + state.dual[row] / state.penalty,
                                    program.lower[row], program.upper[row]);
    state.dual_change[row] = state.penalty * (relaxed - state.projected[row]);
    state.dual[row] += state.dual_change[row];
  }
}

struct Residuals {
  double primal;
  double dual;
  double primal_scale;
  double dual_scale;
};

Residuals residuals(const Program& program, const Iterates& state) {
  const Vector applied = multiply(program.matrix, state.decisions);
  const Vector gradient = multiply(program.quadratic, state.decisions);
  const Vector dual_gradient = transpose_multiply(program.matrix, state.dual, state.decisions.size());
  Vector stationarity(gradient.size());
  for (std::size_t index = 0; index < gradient.size(); ++index)
    stationarity[index] = gradient[index] + program.linear[index] + dual_gradient[index];
  return {norm(difference(applied, state.projected)), norm(stationarity),
          std::max(norm(applied), norm(state.projected)),
          std::max({norm(gradient), norm(program.linear), norm(dual_gradient)})};
}

bool converged(const Residuals& residual) {
  return residual.primal <= SOLVER_TOLERANCE * (1.0 + residual.primal_scale) &&
         residual.dual <= SOLVER_TOLERANCE * (1.0 + residual.dual_scale);
}

bool infeasible(const Program& program, const Iterates& state) {
  const double magnitude = norm(state.dual_change);
  if (magnitude < 1e-10) return false;
  const Vector stationarity = transpose_multiply(program.matrix, state.dual_change,
                                                state.decisions.size());
  if (norm(stationarity) > INFEASIBILITY_TOLERANCE * magnitude) return false;
  double support = 0.0;
  for (std::size_t row = 0; row < state.dual_change.size(); ++row) {
    const double value = state.dual_change[row];
    if (std::abs(value) < INFEASIBILITY_TOLERANCE * magnitude) continue;
    const double bound = value > 0.0 ? program.upper[row] : program.lower[row];
    if (!std::isfinite(bound)) return false;
    support += bound * value;
  }
  return support < -INFEASIBILITY_TOLERANCE * magnitude;
}

bool certified(const Program& program, const Vector& values) {
  for (double value : values) if (!std::isfinite(value)) return false;
  const Vector applied = multiply(program.matrix, values);
  for (std::size_t row = 0; row < applied.size(); ++row)
    if (applied[row] < program.lower[row] - ACCEPTANCE_TOLERANCE ||
        applied[row] > program.upper[row] + ACCEPTANCE_TOLERANCE) return false;
  return true;
}

Solution accepted(const Program& original, const ScaledProgram& scaled,
                  const Iterates& state, int iterations) {
  Vector values = state.decisions;
  for (std::size_t index = 0; index < values.size(); ++index)
    values[index] *= scaled.decision_scale[index];
  if (!certified(original, values))
    return {{}, "constraint residual exceeds acceptance tolerance", iterations, {}, false};
  return {values, "solved", iterations, {}, true};
}

bool adapt_penalty(const Residuals& residual, Iterates& state) {
  constexpr double MINIMUM_PENALTY = 1e-6;
  constexpr double MAXIMUM_PENALTY = 1e6;
  const double primal = residual.primal / std::max(1e-12, residual.primal_scale);
  const double dual = residual.dual / std::max(1e-12, residual.dual_scale);
  const double ratio = std::sqrt(primal / std::max(1e-12, dual));
  if (ratio >= 0.2 && ratio <= 5.0) return false;
  const double updated = std::clamp(state.penalty * ratio, MINIMUM_PENALTY, MAXIMUM_PENALTY);
  if (updated == state.penalty) return false;
  state.penalty = updated;
  return true;
}

void split_slack_row(Program& program, std::size_t row, std::size_t column, double weight) {
  // A_cv*x-s <= upper and A_cv*x+s >= lower use symmetric slack in CV units.
  Vector lower_row = program.matrix[row];
  lower_row[column] = 1.0;
  program.matrix[row][column] = -1.0;
  program.matrix.push_back(lower_row);
  program.lower.push_back(program.lower[row]);
  program.upper.push_back(INFINITY_VALUE);
  program.lower[row] = -INFINITY_VALUE;
  program.quadratic[column][column] = 2.0 * SLACK_PENALTY * weight;
}

Program slack_program(const Program& original, const std::vector<std::size_t>& enabled,
                      const Vector& weights) {
  Program program = original;
  const auto size = original.linear.size();
  const auto total = size + enabled.size();
  program.linear.resize(total, 0.0);
  program.quadratic.resize(total, Vector(total, 0.0));
  for (auto& row : program.quadratic) row.resize(total, 0.0);
  for (auto& row : program.matrix) row.resize(total, 0.0);
  for (std::size_t index = 0; index < enabled.size(); ++index)
    split_slack_row(program, enabled[index], size + index, weights[enabled[index]]);
  return program;
}

void append_slack_bounds(Program& program, std::size_t original_size) {
  for (std::size_t column = original_size; column < program.linear.size(); ++column) {
    Vector row(program.linear.size(), 0.0);
    row[column] = 1.0;
    program.matrix.push_back(row);
    program.lower.push_back(0.0);
    program.upper.push_back(INFINITY_VALUE);
  }
}
Solution iterate(const Program& program, const ScaledProgram& scaled) {
  const auto& problem = scaled.program;
  Iterates state{Vector(problem.linear.size()), Vector(problem.lower.size()),
                 Vector(problem.lower.size()), Vector(problem.lower.size())};
  Matrix factor = factorize(normal_matrix(problem, state.penalty));
  // ADMM splits z=A*x: solve (P+sigma*I+rho*A'A)x, project z onto [l,u], update dual.
  // Decisions x retain MV units; z and CV slack retain their constraint engineering units.
  for (int iteration = 1; iteration <= MAX_ITERATIONS; ++iteration) {
    update_decisions(problem, factor, state);
    update_projection(problem, state);
    if (iteration % CHECK_INTERVAL != 0) continue;
    const auto residual = residuals(problem, state);
    if (converged(residual)) return accepted(program, scaled, state, iteration);
    if (infeasible(problem, state)) return {{}, "primal infeasible", iteration, {}, false};
    if (iteration % (2 * CHECK_INTERVAL) == 0 && adapt_penalty(residual, state))
      factor = factorize(normal_matrix(problem, state.penalty));
  }
  return {{}, "maximum iterations reached", MAX_ITERATIONS, {}, false};
}

void validate_priorities(const Program& program, const Vector& priorities, const Vector& weights) {
  if (priorities.size() != weights.size() || priorities.size() > program.lower.size())
    throw std::invalid_argument("CV priorities and weights must match the leading constraint rows");
  for (std::size_t row = 0; row < priorities.size(); ++row)
    if (!std::isfinite(priorities[row]) || priorities[row] < 0.0 ||
        !std::isfinite(weights[row]) || weights[row] <= 0.0)
      throw std::invalid_argument("CV priorities must be finite nonnegative and weights positive");
}

Vector priority_groups(const Vector& priorities) {
  Vector groups = priorities;
  std::sort(groups.begin(), groups.end(), std::greater<double>());
  groups.erase(std::unique(groups.begin(), groups.end()), groups.end());
  return groups;
}

Solution softened_solution(const Program& program, const Vector& weights,
                           const std::vector<std::size_t>& enabled) {
  Program softened = slack_program(program, enabled, weights);
  append_slack_bounds(softened, program.linear.size());
  return solve(softened);
}
}  // namespace

Solution solve(const Program& program) {
  validate_program(program);
  if (!consistent(program)) return {{}, "inconsistent hard bounds", 0, {}, false};
  return iterate(program, scale_program(program));
}

Solution solve_priorities(const Program& program, const Vector& priorities, const Vector& weights) {
  validate_priorities(program, priorities, weights);
  Solution result = solve(program);
  std::vector<std::size_t> enabled;
  int iterations = result.iterations;
  for (double priority : priority_groups(priorities)) {
    if (result.solved || (result.status != "primal infeasible" &&
                          result.status != "inconsistent hard bounds")) break;
    for (std::size_t row = 0; row < priorities.size(); ++row)
      if (priorities[row] == priority) enabled.push_back(row);
    result = softened_solution(program, weights, enabled);
    iterations += result.iterations;
  }
  if (result.solved) result.values.resize(program.linear.size());
  result.iterations = iterations;
  result.relaxed = enabled;
  return result;
}
}  // namespace crosscut::mpc
