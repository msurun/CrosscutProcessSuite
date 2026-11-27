// Dense quadratic programs for the two MPC planning layers.
// The solver owns no history and certifies actuator bounds before returning decisions.
#pragma once

#include <cstddef>
#include <string>
#include <vector>

namespace crosscut::mpc {
using Vector = std::vector<double>;
using Matrix = std::vector<Vector>;

// Minimise 0.5*x'P*x+q'x with lower <= matrix*x <= upper, in engineering units.
struct Program {
  Matrix quadratic;
  Vector linear;
  Matrix matrix;
  Vector lower;
  Vector upper;
};

// Decisions are usable only when solved is true; relaxed lists CV constraint rows.
struct Solution {
  Vector values;
  std::string status;
  int iterations = 0;
  std::vector<std::size_t> relaxed;
  bool solved = false;
};

// Solve a fresh dense QP with a deterministic iteration cap; reject malformed inputs.
Solution solve(const Program& program);

// Permit symmetric CV slack from lowest priority upward, keeping all MV rows hard.
Solution solve_priorities(const Program& program, const Vector& priorities,
                          const Vector& weights);
}  // namespace crosscut::mpc
