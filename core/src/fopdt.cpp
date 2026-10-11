#include "crosscut/fopdt.hpp"

#include <cmath>
#include <stdexcept>

namespace crosscut {

Fopdt::Fopdt(double gain, double tau_s, double delay_s, double dt_s, double y0)
    : gain_(gain), a_(0.0), y_(y0) {
  if (!(tau_s > 0.0) || !(dt_s > 0.0) || !(delay_s >= 0.0)) {
    throw std::invalid_argument("tau_s and dt_s must be positive and delay_s non-negative");
  }
  a_ = std::exp(-dt_s / tau_s);
  // nearbyint rounds half to even in the default rounding mode, like Python's round().
  const auto n = static_cast<std::size_t>(std::nearbyint(delay_s / dt_s));
  buffer_.assign(n, 0.0);
}

double Fopdt::update(double u) {
  double u_delayed = u;
  if (!buffer_.empty()) {
    u_delayed = buffer_[head_];
    buffer_[head_] = u;
    head_ = (head_ + 1) % buffer_.size();
  }
  y_ = a_ * y_ + gain_ * (1.0 - a_) * u_delayed;
  return y_;
}

}  // namespace crosscut
