// Plain-data adapter for the pure C++ MPC cycle, without importing Python engine code.
// Nested dictionaries mirror dataclasses.asdict for controller, state and cycle inputs.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "crosscut/mpc.hpp"

namespace py = pybind11;
using namespace pybind11::literals;
using namespace crosscut::mpc;
namespace {
template <typename Value>
Value field(const py::dict& values, const char* name) {
  if (!values.contains(name)) throw py::value_error(std::string("Missing MPC field: ") + name);
  return py::cast<Value>(values[name]);
}

Model read_model(const py::dict& values) {
  return {field<Matrix>(values, "gains"), field<Matrix>(values, "time_constants_s"),
          field<Matrix>(values, "dead_times_s"), field<double>(values, "cycle_s")};
}

Limits read_limits(const py::dict& values) {
  return {field<Vector>(values, "mv_lower"), field<Vector>(values, "mv_upper"),
          field<Vector>(values, "cv_lower"), field<Vector>(values, "cv_upper"),
          field<Vector>(values, "priorities"), field<Vector>(values, "move_max"),
          field<Vector>(values, "rate_max"), field<Vector>(values, "target_rate"),
          field<Vector>(values, "funnel_start"), field<Vector>(values, "funnel_end")};
}

Controller read_controller(const py::dict& values) {
  const auto settings = field<py::dict>(values, "settings");
  return {read_model(field<py::dict>(values, "model")),
          read_limits(field<py::dict>(values, "limits")),
          {field<int>(settings, "prediction_horizon"), field<int>(settings, "move_horizon"),
           field<double>(settings, "move_suppression")}};
}

Inputs read_inputs(const py::dict& values) {
  return {field<Vector>(values, "measured_cvs"), field<Vector>(values, "actual_mvs"),
          field<Vector>(values, "targets"), values.contains("disturbances") ?
          field<Vector>(values, "disturbances") : Vector{}};
}

ModelState read_model_state(const py::dict& values) {
  return {field<Matrix>(values, "paths"), field<Matrix>(values, "history")};
}

State read_state(const py::dict& values) {
  State state;
  state.model_state = read_model_state(field<py::dict>(values, "model_state"));
  state.target = field<Vector>(values, "target");
  state.infeasible_cycles = field<int>(values, "infeasible_cycles");
  state.is_initial = field<bool>(values, "is_initial");
  state.is_shed = field<bool>(values, "is_shed");
  if (values.contains("prior_model_state") && !values["prior_model_state"].is_none())
    state.prior_model_state = read_model_state(field<py::dict>(values, "prior_model_state"));
  return state;
}

py::dict write_model_state(const ModelState& state) {
  return py::dict("paths"_a=state.paths, "history"_a=state.history);
}

py::dict write_state(const State& state) {
  py::dict values("model_state"_a=write_model_state(state.model_state), "target"_a=state.target,
                  "infeasible_cycles"_a=state.infeasible_cycles, "is_initial"_a=state.is_initial,
                  "is_shed"_a=state.is_shed);
  values["prior_model_state"] = state.prior_model_state.paths.empty() ?
      py::object(py::none()) : py::object(write_model_state(state.prior_model_state));
  return values;
}

py::dict write_result(const Result& result) {
  return py::dict("moves"_a=result.moves, "move_plan"_a=result.move_plan,
      "predicted_cvs"_a=result.predicted_cvs, "steady_mvs"_a=result.steady_mvs,
      "target_cvs"_a=result.target_cvs, "bias"_a=result.bias,
      "active_constraints"_a=result.active_constraints, "relaxed_cvs"_a=result.relaxed_cvs,
      "status"_a=result.status, "reason"_a=result.reason, "iterations"_a=result.iterations,
      "solve_time_s"_a=result.solve_time_s);
}

py::tuple run_cycle(const py::dict& controller, const py::dict& state, const py::dict& inputs) {
  const auto configuration = read_controller(controller);
  const auto previous = read_state(state);
  const auto measurements = read_inputs(inputs);
  std::pair<Result, State> outcome;
  { py::gil_scoped_release release; outcome = cycle(configuration, previous, measurements); }
  return py::make_tuple(write_result(outcome.first), write_state(outcome.second));
}
}  // namespace

void bind_mpc(py::module_& module) {
  module.def("mpc_cycle", &run_cycle, py::arg("controller"), py::arg("state"), py::arg("inputs"),
             "Return (result, next_state) dictionaries matching the Python MPC engine cycle.");
  module.def("mpc_initialise", [](const py::dict& controller, const py::dict& inputs) {
    return write_state(initialise(read_controller(controller), read_inputs(inputs)));
  }, py::arg("controller"), py::arg("inputs"), "Build a bumpless explicit MPC state.");
}
