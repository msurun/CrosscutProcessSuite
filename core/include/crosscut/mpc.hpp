// Pure two-layer MPC cycle, matching the Python reference's engineering-unit contract.
// State is explicit so a host can reconcile refused moves without hidden solver history.
#pragma once

#include <utility>

#include "crosscut/qp.hpp"

namespace crosscut::mpc {

struct Model {
  Matrix gains, time_constants_s, dead_times_s;
  double cycle_s = 60.0;
};
struct Limits {
  Vector mv_lower, mv_upper, cv_lower, cv_upper, priorities;
  Vector move_max, rate_max, target_rate, funnel_start, funnel_end;
};
struct Settings {
  int prediction_horizon = 60, move_horizon = 8;
  double move_suppression = 1.0;
};
struct Controller { Model model; Limits limits; Settings settings; };
struct ModelState { Matrix paths, history; };
struct State {
  ModelState model_state;
  Vector target;
  int infeasible_cycles = 0;
  bool is_initial = true, is_shed = false;
  // An empty prior state means no proposal has yet been advanced.
  ModelState prior_model_state;
};
struct Inputs { Vector measured_cvs, actual_mvs, targets, disturbances; };
struct Result {
  Vector moves, steady_mvs, target_cvs, bias;
  Matrix move_plan, predicted_cvs;
  std::vector<std::string> active_constraints;
  std::vector<std::size_t> relaxed_cvs;
  std::string status, reason;
  int iterations = 0;
  double solve_time_s = 0.0;
};

// Reject malformed, nonfinite or physically invalid configuration and state.
void validate(const Controller& controller, const State& state, const Inputs& inputs);
// Exact held-input ZOH advance; paths are (CV,input), history is newest first.
ModelState advance(const Model& model, const ModelState& state, const Vector& inputs);
// Produce a time-major (Np*CV,Nc*MV) step-response convolution matrix.
Matrix move_matrix(const Controller& controller);
// Initialise paths/history at the actual inputs; first cycle holds for bumpless entry.
State initialise(const Controller& controller, const Inputs& inputs);
// Return a proposal and next explicit state; no I/O or warm starts occur.
std::pair<Result, State> cycle(const Controller& controller, State state, const Inputs& inputs);

}  // namespace crosscut::mpc
