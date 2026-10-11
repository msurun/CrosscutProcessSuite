#include "crosscut/fopdt.hpp"

#include <cmath>
#include <stdexcept>

namespace crosscut {

namespace {

void require_valid_parameters(double tau_s, double delay_s, double dt_s) {
  // Written as negated "greater than" so that NaN is rejected too.
  if (!(tau_s > 0.0) || !(dt_s > 0.0) || !(delay_s >= 0.0)) {
    throw std::invalid_argument("tau_s and dt_s must be positive and delay_s non-negative");
  }
}

}  // namespace

Fopdt::Fopdt(double gain, double tau_s, double delay_s, double dt_s, double initial_output)
    : gain_(gain), decay_per_step_(0.0), output_(initial_output) {
  require_valid_parameters(tau_s, delay_s, dt_s);
  decay_per_step_ = std::exp(-dt_s / tau_s);
  // nearbyint rounds half to even in the default rounding mode, like Python's round().
  const auto delay_in_samples = static_cast<std::size_t>(std::nearbyint(delay_s / dt_s));
  delayed_inputs_.assign(delay_in_samples, 0.0);
}

double Fopdt::update(double input) {
  double input_after_delay = input;
  if (!delayed_inputs_.empty()) {
    input_after_delay = delayed_inputs_[oldest_input_index_];
    delayed_inputs_[oldest_input_index_] = input;
    oldest_input_index_ = (oldest_input_index_ + 1) % delayed_inputs_.size();
  }
  // Exact solution over one step for a constant input: the old output decays towards gain * input.
  output_ = decay_per_step_ * output_ + gain_ * (1.0 - decay_per_step_) * input_after_delay;
  return output_;
}

}  // namespace crosscut
