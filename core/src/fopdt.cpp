// Implementation of the FOPDT plant model declared in crosscut/fopdt.hpp.
// Validates the parameters, rounds the dead time to whole samples and steps the exact decay.
#include "crosscut/fopdt.hpp"

#include <cmath>
#include <stdexcept>

namespace crosscut {

namespace {

// A process with a time constant <= 0 or a sampling step <= 0 has no meaning (division by zero in
// the decay factor, or time standing still). A negative dead time would mean the output reacts
// before the input changes.
void require_valid_parameters(double tau_s, double delay_s, double dt_s) {
  // Written as negated "greater than" so that NaN is rejected too: every comparison with NaN
  // is false, so `tau_s <= 0` would let NaN through.
  if (!(tau_s > 0.0) || !(dt_s > 0.0) || !(delay_s >= 0.0)) {
    throw std::invalid_argument("tau_s and dt_s must be positive and delay_s non-negative");
  }
}

}  // namespace

// The model is  tau * dy/dt + y = gain * u(t - delay): after a change of the input the output moves
// towards gain * input along an exponential curve, but only after the dead time has passed.
//
// The simulation works in steps of dt_s seconds, so the dead time becomes a whole number of steps
// and the exponential becomes one multiplication per step (see update()).
Fopdt::Fopdt(double gain, double tau_s, double delay_s, double dt_s, double initial_output)
    : gain_(gain), decay_per_step_(0.0), output_(initial_output) {
  require_valid_parameters(tau_s, delay_s, dt_s);

  // Over one step the gap between the output and its target shrinks by this factor. Because
  // it is the exact solution of the equation (not an Euler approximation), the result does not
  // depend on the step size, as long as the input is constant within a step.
  decay_per_step_ = std::exp(-dt_s / tau_s);

  // The delay is rounded to the nearest whole number of steps. nearbyint rounds half to even in
  // the default rounding mode, which is also what Python's round() does; the Python reference
  // implementation relies on that, so the two must agree for the parity test to hold.
  const auto delay_in_samples = static_cast<std::size_t>(std::nearbyint(delay_s / dt_s));

  // Inputs that have not "arrived" at the process yet. They start at zero: the model describes
  // deviations from the operating point, so "nothing was changed before" means 0.
  delayed_inputs_.assign(delay_in_samples, 0.0);
}

double Fopdt::update(double input) {
  // Dead time as a queue: the input that left the queue now is the one that was put in
  // `delay_samples` calls ago. delayed_inputs_ is a ring: `oldest_input_index_` points at the
  // oldest stored input; it is read first and then overwritten with the newest one, so the queue
  // always holds exactly the last `delay_samples` inputs.
  double input_after_delay = input;  // with no dead time the input acts immediately
  if (!delayed_inputs_.empty()) {
    input_after_delay = delayed_inputs_[oldest_input_index_];
    delayed_inputs_[oldest_input_index_] = input;
    oldest_input_index_ = (oldest_input_index_ + 1) % delayed_inputs_.size();
  }

  // The target of the output is gain * input_after_delay. Each step the output covers the share
  // (1 - decay_per_step_) of the remaining distance to the target:
  //   new = old + (1 - decay) * (target - old) = decay * old + (1 - decay) * target
  output_ = decay_per_step_ * output_ + gain_ * (1.0 - decay_per_step_) * input_after_delay;
  return output_;
}

}  // namespace crosscut
