// Evaluate a first-order plus dead-time path for model-editor unit-step plots.
// This pure calculation uses continuous seconds and engineering-unit deviations.

export interface FopdtParameters {
  gain: number;
  timeConstantS: number;
  deadTimeS: number;
}

/** Return the output deviation for a unit input step at zero seconds. */
export function fopdtStep(parameters: FopdtParameters, timeS: number): number {
  const { gain, timeConstantS, deadTimeS } = parameters;
  if (![gain, timeConstantS, deadTimeS, timeS].every(Number.isFinite)) {
    throw new RangeError("FOPDT parameters and plot time must be finite");
  }
  if (timeConstantS <= 0 || deadTimeS < 0) {
    throw new RangeError("Time constant must be positive and dead time nonnegative");
  }
  // One scalar path: y(t)=K*(1-exp(-(t-theta)/tau)) for t>theta, otherwise zero.
  // K has CV units/input unit; tau, theta and t are seconds. The input step is one unit.
  if (timeS <= deadTimeS) return 0;
  const elapsedS = timeS - deadTimeS;
  return gain * -Math.expm1(-elapsedS / timeConstantS);
}
