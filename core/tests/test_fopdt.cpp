#include <gtest/gtest.h>

#include <cmath>
#include <stdexcept>

#include "crosscut/fopdt.hpp"

namespace {

TEST(Fopdt, MatchesAnalyticStepResponse) {
  for (const double delay_s : {0.0, 5.0, 7.0}) {
    const double gain = 2.5;
    const double tau = 30.0;
    const double dt = 1.0;
    crosscut::Fopdt f(gain, tau, delay_s, dt);
    const double a = std::exp(-dt / tau);
    const int n = static_cast<int>(delay_s / dt);
    for (int j = 1; j < 400; ++j) {
      const double y = f.update(1.0);
      const double expected = j <= n ? 0.0 : gain * (1.0 - std::pow(a, j - n));
      ASSERT_NEAR(y, expected, 1e-12) << "delay " << delay_s << ", sample " << j;
    }
  }
}

TEST(Fopdt, ReachesSteadyStateGainAndReturnsToZero) {
  crosscut::Fopdt f(-3.0, 10.0, 4.0, 1.0);
  for (int i = 0; i < 500; ++i) f.update(2.0);
  EXPECT_NEAR(f.value(), -6.0, 1e-9);
  for (int i = 0; i < 500; ++i) f.update(0.0);
  EXPECT_NEAR(f.value(), 0.0, 1e-9);
}

TEST(Fopdt, DelayIsRoundedToWholeSamples) {
  EXPECT_EQ(crosscut::Fopdt(1.0, 10.0, 8.1, 1.0).delay_samples(), 8U);
  EXPECT_EQ(crosscut::Fopdt(1.0, 10.0, 0.0, 1.0).delay_samples(), 0U);
  EXPECT_EQ(crosscut::Fopdt(1.0, 10.0, 2.5, 1.0).delay_samples(), 2U);  // half to even, like Python
  EXPECT_EQ(crosscut::Fopdt(1.0, 10.0, 3.5, 1.0).delay_samples(), 4U);
}

TEST(Fopdt, RejectsBadParameters) {
  EXPECT_THROW(crosscut::Fopdt(1.0, 0.0, 1.0, 1.0), std::invalid_argument);
  EXPECT_THROW(crosscut::Fopdt(1.0, -1.0, 1.0, 1.0), std::invalid_argument);
  EXPECT_THROW(crosscut::Fopdt(1.0, 1.0, -1.0, 1.0), std::invalid_argument);
  EXPECT_THROW(crosscut::Fopdt(1.0, 1.0, 1.0, 0.0), std::invalid_argument);
}

}  // namespace
