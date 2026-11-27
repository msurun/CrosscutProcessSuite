// Unit tests for deterministic QP decisions and engineering-unit MPC predictions.
// Synthetic SISO cases isolate constraints, state handover and solver failure behavior.
#include <gtest/gtest.h>

#include <cmath>
#include <limits>
#include <stdexcept>

#include "crosscut/mpc.hpp"

namespace {
using namespace crosscut::mpc;
constexpr double kTolerance = 2e-5;  // Engineering-unit feasibility allowance.

Controller controller() {
  return {{{{2.0}}, {{120.0}}, {{60.0}}, 60.0},
          {{-5}, {5}, {-10}, {10}, {0}, {0.5}, {0.5}, {1}, {20}, {10}},
          {10, 3, 0.2}};
}

Inputs inputs() { return {{0}, {0}, {1}, {}}; }

TEST(MpcQp, SolvesAnUnconstrainedQuadratic) {
  const auto solution = solve({{{2}}, {-4}, {{1}}, {-10}, {10}});
  ASSERT_TRUE(solution.solved);
  EXPECT_NEAR(solution.values[0], 2, kTolerance);
}

TEST(MpcQp, RespectsAnActiveUpperBound) {
  const auto solution = solve({{{2}}, {-4}, {{1}}, {-10}, {1}});
  ASSERT_TRUE(solution.solved);
  EXPECT_NEAR(solution.values[0], 1, kTolerance);
}

TEST(MpcQp, CertifiesInfeasibility) {
  const auto solution = solve({{{2}}, {0}, {{1}, {1}}, {1, -2}, {2, 0}});
  EXPECT_FALSE(solution.solved);
  EXPECT_EQ(solution.status, "primal infeasible");
  EXPECT_LE(solution.iterations, 10000);
}

TEST(MpcQp, RelaxesOnlyTheLowerPriorityCv) {
  const auto solution = solve_priorities(
      {{{2}}, {0}, {{1}, {1}, {1}}, {1, -2, -5}, {2, 0, 5}}, {0, 1}, {1, 0.1});
  ASSERT_TRUE(solution.solved) << solution.status;
  EXPECT_EQ(solution.relaxed, std::vector<std::size_t>{1});
  EXPECT_GE(solution.values[0], 1 - kTolerance);
}

TEST(MpcQp, RejectsNonfiniteCost) {
  const double invalid = std::numeric_limits<double>::quiet_NaN();
  EXPECT_THROW(solve({{{2}}, {invalid}, {{1}}, {-1}, {1}}), std::invalid_argument);
}

TEST(MpcQp, SolvesASemidefiniteTrackingCost) {
  const auto solution = solve({{{2, 2}, {2, 2}}, {-2, -2},
                               {{1, 0}, {0, 1}}, {-5, -5}, {5, 5}});
  ASSERT_TRUE(solution.solved);
  EXPECT_NEAR(solution.values[0] + solution.values[1], 1, kTolerance);
}

TEST(MpcQp, RejectsMalformedConstraintRows) {
  EXPECT_THROW(solve({{{2}}, {0}, {{1, 2}}, {-1}, {1}}), std::invalid_argument);
}

TEST(Mpc, StepResponseUsesOneSampleDeadTime) {
  const auto matrix = move_matrix(controller());
  EXPECT_DOUBLE_EQ(matrix[0][0], 0);
  EXPECT_NEAR(matrix[1][0], 2 * (1 - std::exp(-0.5)), 1e-12);
  EXPECT_DOUBLE_EQ(matrix[1][1], 0);
}

TEST(Mpc, InitialisationHoldsActualInputs) {
  const auto configuration = controller();
  const auto measurement = inputs();
  const auto outcome = cycle(configuration, initialise(configuration, measurement), measurement);
  EXPECT_EQ(outcome.first.status, "initialised");
  EXPECT_EQ(outcome.first.moves, Vector{0});
  EXPECT_FALSE(outcome.second.is_initial);
}

TEST(Mpc, PlansABoundedMoveAfterInitialisation) {
  const auto configuration = controller();
  const auto measurement = inputs();
  auto state = initialise(configuration, measurement);
  state.is_initial = false;
  const auto outcome = cycle(configuration, state, measurement);
  ASSERT_EQ(outcome.first.status, "solved") << outcome.first.reason;
  EXPECT_GT(outcome.first.moves[0], 0);
  EXPECT_LE(outcome.first.moves[0], 0.5 + kTolerance);
  EXPECT_NEAR(outcome.first.steady_mvs[0], 0.5, kTolerance);
}

TEST(Mpc, RefusedMovesProduceNoPhantomBias) {
  const auto configuration = controller();
  const auto measurement = inputs();
  auto state = initialise(configuration, measurement);
  state.is_initial = false;
  const auto first = cycle(configuration, state, measurement);
  const auto second = cycle(configuration, first.second, measurement);
  EXPECT_NEAR(second.first.bias[0], 0, 1e-12);
  EXPECT_NEAR(first.first.moves[0], second.first.moves[0], 1e-12);
}

TEST(Mpc, ThirdHardFailureShedsAndLatches) {
  auto configuration = controller();
  configuration.limits.mv_lower = {1};
  configuration.limits.move_max = {0.1};
  auto state = initialise(configuration, inputs());
  state.is_initial = false;
  state.infeasible_cycles = 2;
  const auto outcome = cycle(configuration, state, inputs());
  EXPECT_EQ(outcome.first.status, "shed");
  EXPECT_EQ(outcome.first.moves, Vector{0});
  EXPECT_TRUE(outcome.second.is_shed);
}

TEST(Mpc, RejectsMalformedStateBeforePrediction) {
  const auto configuration = controller();
  auto state = initialise(configuration, inputs());
  state.model_state.history.clear();
  EXPECT_THROW(cycle(configuration, state, inputs()), std::invalid_argument);
}

TEST(Mpc, PublicAdvanceRejectsMalformedHistory) {
  const auto configuration = controller();
  EXPECT_THROW(advance(configuration.model, {}, {0}), std::invalid_argument);
}

TEST(Mpc, MoveMatrixRejectsReversedHorizons) {
  auto configuration = controller();
  configuration.settings.move_horizon = 11;
  EXPECT_THROW(move_matrix(configuration), std::invalid_argument);
}
}  // namespace
