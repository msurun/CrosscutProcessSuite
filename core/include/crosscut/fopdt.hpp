// First-order lag with dead time (FOPDT): the simplest useful model of an industrial process.
//   tau * dy/dt + y = gain * u(t - delay)
// - gain:     by how much the output settles per unit of input (steady-state output = gain * input)
// - tau_s:    time constant, the time to cover about 63 % of the way to the new steady state
// - delay_s:  dead time, the time before the output starts to react at all
// All signals are deviations from the operating point, so a plant at rest has input = output = 0.
//
// The class is discretized exactly for an input that is constant between two calls of update().
// It mirrors crosscut_sim.core.Fopdt so that both implementations can be compared sample by sample
// (core/tests/test_python_parity.py).
#pragma once

#include <cstddef>
#include <vector>

namespace crosscut {

class Fopdt {
 public:
  // Throws std::invalid_argument unless tau_s > 0, dt_s > 0 and delay_s >= 0.
  // The delay is rounded to a whole number of samples (half to even, like Python's round()).
  Fopdt(double gain, double tau_s, double delay_s, double dt_s, double initial_output = 0.0);

  // Consumes the input of the current step and returns the output of the next step.
  double update(double input);

  [[nodiscard]] double value() const noexcept { return output_; }
  [[nodiscard]] std::size_t delay_samples() const noexcept { return delayed_inputs_.size(); }

 private:
  double gain_;
  double decay_per_step_;  // exp(-dt / tau): the share of the old output that survives one step
  double output_;
  std::vector<double> delayed_inputs_;  // ring buffer holding the last `delay_samples` inputs
  std::size_t oldest_input_index_ = 0;  // next slot to read (and then overwrite) in the ring
};

}  // namespace crosscut
