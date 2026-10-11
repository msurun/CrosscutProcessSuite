// First-order lag with dead time, exactly discretized: y' = (K u(t - theta) - y) / tau.
// Mirrors crosscut_sim.core.Fopdt so that both implementations can be compared sample by sample.
#pragma once

#include <cstddef>
#include <vector>

namespace crosscut {

class Fopdt {
 public:
  // Throws std::invalid_argument unless tau_s > 0, dt_s > 0 and delay_s >= 0.
  Fopdt(double gain, double tau_s, double delay_s, double dt_s, double y0 = 0.0);

  // Consumes the input of the current step and returns the output of the next step.
  double update(double u);

  [[nodiscard]] double value() const noexcept { return y_; }
  [[nodiscard]] std::size_t delay_samples() const noexcept { return buffer_.size(); }

 private:
  double gain_;
  double a_;
  double y_;
  std::vector<double> buffer_;  // ring buffer holding the last `delay_samples` inputs
  std::size_t head_ = 0;
};

}  // namespace crosscut
