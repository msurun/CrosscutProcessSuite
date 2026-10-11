#include <gtest/gtest.h>

#include <cmath>
#include <stdexcept>

#include "crosscut/fopdt.hpp"

namespace {

constexpr double kStepResponseTolerance = 1e-12;  // pure floating point rounding
constexpr double kSteadyStateTolerance = 1e-9;    // after 500 samples the residue is below this

TEST(Fopdt, MatchesAnalyticStepResponse) {
  for (const double delay_s : {0.0, 5.0, 7.0}) {
    const double gain = 2.5;
    const double tau_s = 30.0;
    const double dt_s = 1.0;
    crosscut::Fopdt plant(gain, tau_s, delay_s, dt_s);
    const double decay_per_step = std::exp(-dt_s / tau_s);
    const int delay_in_samples = static_cast<int>(delay_s / dt_s);
    for (int sample = 1; sample < 400; ++sample) {
      const double output = plant.update(1.0);
      const double expected =
          sample <= delay_in_samples
              ? 0.0
              : gain * (1.0 - std::pow(decay_per_step, sample - delay_in_samples));
      ASSERT_NEAR(output, expected, kStepResponseTolerance)
          << "delay " << delay_s << ", sample " << sample;
    }
  }
}

TEST(Fopdt, ReachesSteadyStateGainAndReturnsToZero) {
  crosscut::Fopdt plant(-3.0, 10.0, 4.0, 1.0);
  for (int step = 0; step < 500; ++step) plant.update(2.0);
  EXPECT_NEAR(plant.value(), -6.0, kSteadyStateTolerance);
  for (int step = 0; step < 500; ++step) plant.update(0.0);
  EXPECT_NEAR(plant.value(), 0.0, kSteadyStateTolerance);
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
