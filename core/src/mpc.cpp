// Engineering-unit FOPDT prediction and two-layer receding-horizon control.
// Mirrors planning.py and engine.py while keeping all host state explicit.
#include "crosscut/mpc.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <numeric>
#include <set>
#include <stdexcept>

namespace crosscut::mpc {
namespace {
constexpr double kAcceptance = 2e-5;  // Constraint residual in engineering units.
constexpr int kShedCycles = 3;  // Consecutive infeasible cycles before shedding.

void require(bool condition, const std::string& message) {
  if (!condition) throw std::invalid_argument(message);
}

void check_vector(const Vector& values, std::size_t size, const std::string& name) {
  require(values.size() == size, name + " has the wrong number of values");
  require(std::all_of(values.begin(), values.end(), [](double value) {
    return std::isfinite(value);
  }), name + " must contain finite engineering-unit values");
}

void check_matrix(const Matrix& values, std::size_t rows, std::size_t columns) {
  require(values.size() == rows, "Matrix has the wrong number of rows");
  for (const auto& row : values) check_vector(row, columns, "Matrix row");
}

Vector join(Vector first, const Vector& second) {
  first.insert(first.end(), second.begin(), second.end());
  return first;
}

Vector multiply(const Matrix& matrix, const Vector& values) {
  Vector result;
  for (const auto& row : matrix)
    result.push_back(std::inner_product(row.begin(), row.end(), values.begin(), 0.0));
  return result;
}

Vector sums(const Matrix& matrix) {
  Vector result;
  for (const auto& row : matrix) result.push_back(std::accumulate(row.begin(), row.end(), 0.0));
  return result;
}

Vector weights(const Vector& priorities) {
  const std::set<double> ordered(priorities.begin(), priorities.end());
  Vector result;
  for (double priority : priorities) {
    const auto rank = std::distance(ordered.begin(), ordered.find(priority));
    result.push_back(std::pow(10.0, -static_cast<double>(rank)));
  }
  return result;
}

void check_intervals(const Limits& limits) {
  for (std::size_t input = 0; input < limits.mv_lower.size(); ++input) {
    require(limits.mv_lower[input] <= limits.mv_upper[input], "MV bounds are reversed");
    require(limits.move_max[input] >= 0 && limits.rate_max[input] >= 0,
            "Move and rate bounds must be nonnegative");
  }
  for (std::size_t output = 0; output < limits.cv_lower.size(); ++output) {
    require(limits.cv_lower[output] <= limits.cv_upper[output], "CV bounds are reversed");
    require(limits.priorities[output] >= 0 && limits.target_rate[output] >= 0,
            "Priorities and target rates must be nonnegative");
    require(limits.funnel_end[output] >= 0 &&
            limits.funnel_start[output] >= limits.funnel_end[output], "Invalid funnel widths");
  }
}

void check_limits(const Controller& controller) {
  const auto& limits = controller.limits;
  const auto count = limits.mv_lower.size(), outputs = controller.model.gains.size();
  require(count > 0 && count <= controller.model.gains.front().size(), "Invalid MV count");
  for (const auto* values : {&limits.mv_lower, &limits.mv_upper, &limits.move_max,
                             &limits.rate_max}) check_vector(*values, count, "MV limits");
  for (const auto* values : {&limits.cv_lower, &limits.cv_upper, &limits.priorities,
       &limits.target_rate, &limits.funnel_start, &limits.funnel_end})
    check_vector(*values, outputs, "CV limits");
  check_intervals(limits);
}

std::size_t delay_depth(const Model& model) {
  double maximum = 0;
  for (const auto& row : model.dead_times_s)
    for (double delay : row) maximum = std::max(maximum, std::nearbyint(delay / model.cycle_s));
  require(maximum < 1000000, "Delay history exceeds one million samples; reduce the model");
  return static_cast<std::size_t>(maximum) + 1;
}

void check_model(const Model& model) {
  require(!model.gains.empty() && !model.gains.front().empty(), "Model must be nonempty");
  require(std::isfinite(model.cycle_s) && model.cycle_s > 0, "cycle_s must be positive");
  for (const auto* matrix : {&model.gains, &model.time_constants_s, &model.dead_times_s})
    check_matrix(*matrix, model.gains.size(), model.gains.front().size());
  for (const auto& row : model.time_constants_s)
    for (double value : row) require(value > 0, "Time constants must be positive");
  for (const auto& row : model.dead_times_s)
    for (double value : row) require(value >= 0, "Dead times must be nonnegative");
}

void check_state(const Model& model, const ModelState& state) {
  check_matrix(state.paths, model.gains.size(), model.gains.front().size());
  check_matrix(state.history, delay_depth(model), model.gains.front().size());
}

void check_settings(const Settings& settings) {
  require(settings.move_horizon >= 1 && settings.prediction_horizon >= settings.move_horizon,
          "Require 1 <= move horizon <= prediction horizon");
  require(std::isfinite(settings.move_suppression) && settings.move_suppression > 0,
          "Move suppression must be finite and positive");
}

ModelState advance_unchecked(const Model& model, const ModelState& state, const Vector& inputs) {
  auto next = state;
  next.history.insert(next.history.begin(), inputs);
  for (std::size_t output = 0; output < model.gains.size(); ++output) {
    for (std::size_t input = 0; input < inputs.size(); ++input) {
      const auto delay = static_cast<std::size_t>(std::nearbyint(
          model.dead_times_s[output][input] / model.cycle_s));
      // Exact ZOH: x_next=a*x+K*(1-a)*u_delayed, a=exp(-Ts/tau).
      // Paths are (CV,input) in CV units; newest-first history stores input units.
      const double decay = std::exp(-model.cycle_s / model.time_constants_s[output][input]);
      next.paths[output][input] = decay * state.paths[output][input] +
          model.gains[output][input] * (1 - decay) * next.history[delay][input];
    }
  }
  next.history.pop_back();
  return next;
}

Program tracking_program(const Matrix& matrix, const Vector& error,
                         const Vector& cost_weights, double suppression) {
  // ||G*x+e||_Q^2+R||x||^2 => P=2(G'QG+RI), q=2G'Qe.
  // Rows are CV engineering units, columns are MV engineering units.
  const auto size = matrix.front().size();
  Program program{Matrix(size, Vector(size)), Vector(size), matrix, {}, {}};
  for (std::size_t column = 0; column < size; ++column) {
    program.quadratic[column][column] = 2 * suppression;
    for (std::size_t row = 0; row < matrix.size(); ++row) {
      program.linear[column] += 2 * matrix[row][column] * cost_weights[row] * error[row];
      for (std::size_t other = 0; other < size; ++other)
        program.quadratic[column][other] +=
            2 * matrix[row][column] * cost_weights[row] * matrix[row][other];
    }
  }
  return program;
}

void append_bound(Program& program, Vector row, double lower, double upper) {
  program.matrix.push_back(std::move(row));
  program.lower.push_back(lower);
  program.upper.push_back(upper);
}

Vector steady_offset(const Controller& controller, const Inputs& inputs, const Vector& bias) {
  const auto count = inputs.actual_mvs.size();
  // Held disturbances contribute K_dv*d, while the measured output bias stays constant.
  auto offset = multiply(controller.model.gains, join(Vector(count), inputs.disturbances));
  for (std::size_t output = 0; output < offset.size(); ++output) offset[output] += bias[output];
  return offset;
}

void add_steady_bounds(Program& program, const Limits& limits, const Vector& offset) {
  for (std::size_t output = 0; output < offset.size(); ++output) {
    program.lower.push_back(limits.cv_lower[output] - offset[output]);
    program.upper.push_back(limits.cv_upper[output] - offset[output]);
  }
  const auto count = limits.mv_lower.size();
  for (std::size_t input = 0; input < count; ++input) {
    Vector row(count);
    row[input] = 1;
    append_bound(program, row, limits.mv_lower[input], limits.mv_upper[input]);
  }
}

Solution steady_target(const Controller& controller, const Inputs& inputs, const Vector& bias) {
  const auto& limits = controller.limits;
  const auto count = inputs.actual_mvs.size();
  Matrix gains = controller.model.gains;
  const auto offset = steady_offset(controller, inputs, bias);
  Vector error = offset;
  for (std::size_t output = 0; output < gains.size(); ++output) {
    gains[output].resize(count);
    error[output] -= inputs.targets[output];
  }
  const auto cost_weights = weights(limits.priorities);
  auto program = tracking_program(gains, error, cost_weights, 0);
  add_steady_bounds(program, limits, offset);
  return solve_priorities(program, limits.priorities, cost_weights);
}

Matrix free_response(const Controller& controller, ModelState state, const Inputs& inputs) {
  Matrix free;
  for (int sample = 0; sample < controller.settings.prediction_horizon; ++sample) {
    state = advance_unchecked(controller.model, state, join(inputs.actual_mvs, inputs.disturbances));
    free.push_back(sums(state.paths));
  }
  return free;
}

Vector target_for(const Controller& controller, const State& state,
                  const Inputs& inputs, const Result& result) {
  auto desired = multiply(controller.model.gains, join(result.steady_mvs, inputs.disturbances));
  for (std::size_t output = 0; output < desired.size(); ++output) {
    const double bound = controller.limits.target_rate[output] * controller.model.cycle_s;
    desired[output] = state.target[output] + std::clamp(
        desired[output] + result.bias[output] - state.target[output], -bound, bound);
  }
  return desired;
}

void add_position_bounds(Program& program, const Limits& limits, const Inputs& inputs) {
  const auto count = inputs.actual_mvs.size(), size = program.linear.size();
  // Cumulative rows enforce u[j]=u_now+sum(i<=j)du[i], entirely in MV units.
  for (std::size_t variable = 0; variable < size; ++variable) {
    const auto input = variable % count;
    Vector row(size);
    for (std::size_t previous = input; previous <= variable; previous += count) row[previous] = 1;
    append_bound(program, row, limits.mv_lower[input] - inputs.actual_mvs[input],
                 limits.mv_upper[input] - inputs.actual_mvs[input]);
  }
}

void add_actuators(Program& program, const Controller& controller, const Inputs& inputs) {
  const auto& limits = controller.limits;
  const auto count = inputs.actual_mvs.size(), size = program.linear.size();
  add_position_bounds(program, limits, inputs);
  for (std::size_t variable = 0; variable < size; ++variable) {
    const auto input = variable % count;
    const double bound = std::min(limits.move_max[input],
                                  limits.rate_max[input] * controller.model.cycle_s);
    Vector row(size);
    row[variable] = 1;
    append_bound(program, row, -bound, bound);
  }
}

void add_cv_bands(Program& program, const Controller& controller, const Result& result) {
  const auto& limits = controller.limits;
  const auto outputs = limits.cv_lower.size();
  // Funnel width linearly narrows in CV units over Np rows; intersect operator bounds,
  // then subtract the free response so each constraint acts on the move-induced change.
  for (std::size_t row = 0; row < program.matrix.size(); ++row) {
    const auto output = row % outputs, sample = row / outputs;
    const double fraction = result.predicted_cvs.size() == 1 ? 0 :
        static_cast<double>(sample) / static_cast<double>(result.predicted_cvs.size() - 1);
    const double width = limits.funnel_start[output] + fraction *
        (limits.funnel_end[output] - limits.funnel_start[output]);
    program.lower.push_back(std::max(limits.cv_lower[output], result.target_cvs[output] - width)
                            - result.predicted_cvs[sample][output]);
    program.upper.push_back(std::min(limits.cv_upper[output], result.target_cvs[output] + width)
                            - result.predicted_cvs[sample][output]);
  }
}

Solution dynamic_plan(const Controller& controller, const Inputs& inputs,
                      const Result& result, const Matrix& matrix) {
  Vector error, priorities, cost_weights;
  const auto base_weights = weights(controller.limits.priorities);
  for (const auto& row : result.predicted_cvs) {
    for (std::size_t output = 0; output < row.size(); ++output) {
      error.push_back(row[output] - result.target_cvs[output]);
      priorities.push_back(controller.limits.priorities[output]);
      cost_weights.push_back(base_weights[output]);
    }
  }
  auto program = tracking_program(matrix, error, cost_weights, controller.settings.move_suppression);
  add_cv_bands(program, controller, result);
  add_actuators(program, controller, inputs);
  return solve_priorities(program, priorities, cost_weights);
}

struct ActiveBound {
  const Vector& values;
  std::string kind;
  std::string side;
};

void append_active_bounds(Result& result, const Matrix& values, const ActiveBound& bound) {
  // Diagnostics use one-based future samples and zero-based variable indices.
  for (std::size_t sample = 0; sample < values.size(); ++sample)
    for (std::size_t variable = 0; variable < bound.values.size(); ++variable)
      if (std::abs(values[sample][variable] - bound.values[variable]) <= kAcceptance)
        result.active_constraints.push_back(bound.kind + "[" + std::to_string(variable) + "]." +
                                            bound.side + "@" + std::to_string(sample + 1));
}

void active_bounds(Result& result, const Matrix& positions, const Limits& limits) {
  append_active_bounds(result, positions, {limits.mv_lower, "mv", "lower"});
  append_active_bounds(result, positions, {limits.mv_upper, "mv", "upper"});
  append_active_bounds(result, result.predicted_cvs, {limits.cv_lower, "cv", "lower"});
  append_active_bounds(result, result.predicted_cvs, {limits.cv_upper, "cv", "upper"});
}

Matrix cumulative_positions(Vector position, const Matrix& increments) {
  // u[j]=u_now+sum(i<=j)du[i], with both matrices shaped (Nc,MV) in MV units.
  Matrix positions = increments;
  for (auto& row : positions) {
    for (std::size_t input = 0; input < row.size(); ++input) position[input] += row[input];
    row = position;
  }
  return positions;
}

void apply_plan(Result& result, const Inputs& inputs, const Solution& plan, const Matrix& matrix) {
  const auto count = inputs.actual_mvs.size();
  for (std::size_t index = 0; index < plan.values.size(); ++index)
    result.move_plan[index / count][index % count] = plan.values[index];
  result.moves = cumulative_positions(inputs.actual_mvs, result.move_plan).front();
  const auto response = multiply(matrix, plan.values);
  for (std::size_t row = 0; row < response.size(); ++row)
    result.predicted_cvs[row / result.bias.size()][row % result.bias.size()] += response[row];
}

Result held_result(const Controller& controller, const State& state, const Inputs& inputs) {
  Result result;
  result.moves = inputs.actual_mvs;
  result.target_cvs = state.target;
  result.move_plan = Matrix(static_cast<std::size_t>(controller.settings.move_horizon),
                            Vector(inputs.actual_mvs.size()));
  result.bias = sums(state.model_state.paths);
  for (std::size_t output = 0; output < result.bias.size(); ++output)
    result.bias[output] = inputs.measured_cvs[output] - result.bias[output];
  result.predicted_cvs = free_response(controller, state.model_state, inputs);
  for (auto& row : result.predicted_cvs)
    for (std::size_t output = 0; output < row.size(); ++output) row[output] += result.bias[output];
  result.status = state.is_shed || state.infeasible_cycles + 1 >= kShedCycles ? "shed" : "hold";
  return result;
}

void mark_relaxations(Result& result, const Solution& plan) {
  std::set<std::size_t> relaxed(result.relaxed_cvs.begin(), result.relaxed_cvs.end());
  for (auto row : plan.relaxed) relaxed.insert(row % result.bias.size());
  result.relaxed_cvs.assign(relaxed.begin(), relaxed.end());
  result.status = relaxed.empty() ? "solved" : "relaxed";
  result.reason.clear();
}

Result plan_moves(const Controller& controller, const State& state,
                  const Inputs& inputs, Result result) {
  const auto matrix = move_matrix(controller);
  const auto plan = dynamic_plan(controller, inputs, result, matrix);
  result.iterations += plan.iterations;
  result.reason = plan.status;
  if (!plan.solved) {
    auto held = held_result(controller, state, inputs);
    held.iterations = result.iterations;
    held.reason = plan.status;
    return held;
  }
  mark_relaxations(result, plan);
  apply_plan(result, inputs, plan, matrix);
  active_bounds(result, cumulative_positions(inputs.actual_mvs, result.move_plan), controller.limits);
  return result;
}

Result planned_result(const Controller& controller, const State& state, const Inputs& inputs) {
  auto result = held_result(controller, state, inputs);
  const auto steady = steady_target(controller, inputs, result.bias);
  result.iterations = steady.iterations;
  result.reason = steady.status;
  if (!steady.solved) return result;
  result.steady_mvs = steady.values;
  result.relaxed_cvs = steady.relaxed;
  result.target_cvs = target_for(controller, state, inputs, result);
  return plan_moves(controller, state, inputs, result);
}

double step_coefficient(const Model& model, std::size_t output, std::size_t input,
                        std::size_t sample) {
  const double delay = std::nearbyint(model.dead_times_s[output][input] / model.cycle_s);
  const double elapsed = std::max(static_cast<double>(sample) - delay, 0.0);
  // S[j,c,m]=K*(1-exp(-max(j-delay,0)*Ts/tau)), in CV-unit/MV-unit.
  return model.gains[output][input] *
      (1 - std::exp(-elapsed * model.cycle_s / model.time_constants_s[output][input]));
}

struct MoveBlock { std::size_t sample, move, count; };

void fill_move_block(Matrix& matrix, const Model& model, const MoveBlock& block) {
  const auto outputs = model.gains.size();
  for (std::size_t output = 0; output < outputs; ++output)
    for (std::size_t input = 0; input < block.count; ++input)
      matrix[block.sample * outputs + output][block.move * block.count + input] =
          step_coefficient(model, output, input, block.sample - block.move + 1);
}

void mark_entry_result(Result& result, const State& state) {
  result.status = state.is_initial ? "initialised" : "shed";
  result.reason = state.is_initial ? "bumpless initialisation" : "shed latched; initialise to restart";
  result.solve_time_s = 0;
}

State finish_cycle(const Controller& controller, State state, const Inputs& inputs,
                   const Result& result) {
  state.prior_model_state = state.model_state;
  state.model_state = advance_unchecked(controller.model, state.model_state,
                                        join(result.moves, inputs.disturbances));
  state.target = result.target_cvs;
  state.infeasible_cycles = result.status == "hold" || result.status == "shed" ?
      state.infeasible_cycles + 1 : 0;
  state.is_initial = false;
  state.is_shed = result.status == "shed";
  return state;
}
}  // namespace

void validate(const Controller& controller, const State& state, const Inputs& inputs) {
  check_model(controller.model);
  check_limits(controller);
  const auto outputs = controller.model.gains.size(), count = controller.limits.mv_lower.size();
  check_vector(inputs.actual_mvs, count, "actual_mvs");
  check_vector(inputs.measured_cvs, outputs, "measured_cvs");
  check_vector(inputs.targets, outputs, "targets");
  check_vector(inputs.disturbances, controller.model.gains.front().size() - count, "disturbances");
  check_vector(state.target, outputs, "state target");
  check_state(controller.model, state.model_state);
  if (!state.prior_model_state.paths.empty()) check_state(controller.model, state.prior_model_state);
  check_settings(controller.settings);
  require(state.infeasible_cycles >= 0, "Failure counter must be nonnegative");
}

ModelState advance(const Model& model, const ModelState& state, const Vector& inputs) {
  check_model(model);
  check_state(model, state);
  check_vector(inputs, model.gains.front().size(), "Model inputs");
  return advance_unchecked(model, state, inputs);
}

Matrix move_matrix(const Controller& controller) {
  check_model(controller.model);
  check_limits(controller);
  check_settings(controller.settings);
  const auto& model = controller.model;
  const auto outputs = model.gains.size(), count = controller.limits.mv_lower.size();
  const auto prediction = static_cast<std::size_t>(controller.settings.prediction_horizon);
  const auto moves = static_cast<std::size_t>(controller.settings.move_horizon);
  Matrix matrix(prediction * outputs, Vector(moves * count));
  // Time-major blocks shift the step response so future moves cannot affect past samples.
  for (std::size_t sample = 0; sample < prediction; ++sample)
    for (std::size_t move = 0; move < std::min(sample + 1, moves); ++move)
      fill_move_block(matrix, model, {sample, move, count});
  return matrix;
}

State initialise(const Controller& controller, const Inputs& inputs) {
  check_model(controller.model);
  check_limits(controller);
  const auto held = join(inputs.actual_mvs, inputs.disturbances);
  check_vector(held, controller.model.gains.front().size(), "Initial inputs");
  State state;
  state.target = inputs.measured_cvs;
  state.model_state.history = Matrix(delay_depth(controller.model), held);
  state.model_state.paths = controller.model.gains;
  for (auto& row : state.model_state.paths)
    for (std::size_t input = 0; input < row.size(); ++input) row[input] *= held[input];
  validate(controller, state, inputs);
  return state;
}

std::pair<Result, State> cycle(const Controller& controller, State state, const Inputs& inputs) {
  validate(controller, state, inputs);
  if (!state.prior_model_state.paths.empty())
    state.model_state = advance_unchecked(controller.model, state.prior_model_state,
                                          join(inputs.actual_mvs, inputs.disturbances));
  const auto start = std::chrono::steady_clock::now();
  auto result = state.is_initial || state.is_shed ? held_result(controller, state, inputs) :
                                                  planned_result(controller, state, inputs);
  result.solve_time_s = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
  if (state.is_initial || state.is_shed) mark_entry_result(result, state);
  return {result, finish_cycle(controller, state, inputs, result)};
}
}  // namespace crosscut::mpc
