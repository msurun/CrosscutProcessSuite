// src/components/Stepper.tsx

/**
 * Ordered progress indicator for a multi-step process.
 *
 * Shows every step at once so the user can see where they are and what comes
 * next. State is conveyed by shape and by a translated word, never by colour
 * alone.
 */

/**
 * Lifecycle state of a single step.
 *
 * - "todo": not reached yet.
 * - "active": the step the user is on now.
 * - "done": finished successfully.
 * - "blocked": cannot proceed until something else is resolved.
 */
export type StepState = "todo" | "active" | "done" | "blocked";

/** One step of the process, with labels already translated by the caller. */
export interface StepInfo {
  id: string;
  label: string;
  state: StepState;
  detail?: string;
}

/**
 * The decorative marker per state.
 *
 * Each state gets a distinct glyph shape (hollow circle, half-filled circle,
 * tick, filled square) so the meaning survives for colour-blind users and in
 * greyscale print. Decorative only: the state word is announced instead.
 */
const STATE_MARKER: Record<StepState, string> = {
  todo: "\u25CB", // hollow circle
  active: "\u25D0", // half-filled circle
  done: "\u2713", // check mark
  blocked: "\u25A0", // filled square
};

type StepperProps = {
  steps: StepInfo[];
  /** Already-translated accessible name for the ordered list. */
  ariaLabel: string;
  /** Already-translated word for each state, shown next to its marker. */
  stateLabels: Record<StepState, string>;
};

/**
 * Returns the id of the step that should carry `aria-current="step"`.
 *
 * Prefers the first active step; when nothing is active, falls back to the
 * first blocked step so the user's attention lands on the obstacle. Returns
 * `undefined` when no step qualifies.
 */
function findCurrentStepId(steps: StepInfo[]): string | undefined {
  const activeStep = steps.find((step) => step.state === "active");
  if (activeStep !== undefined) {
    return activeStep.id;
  }
  const blockedStep = steps.find((step) => step.state === "blocked");
  return blockedStep?.id;
}

/**
 * Renders one step as a list item: number, label, state marker and word, and
 * an optional detail line.
 *
 * `isCurrent` becomes `aria-current="step"`; pass `undefined` for steps that
 * are not the current one so the attribute is omitted entirely.
 */
function StepItem({
  step,
  position,
  isCurrent,
  stateLabels,
}: {
  step: StepInfo;
  position: number;
  isCurrent: boolean | undefined;
  stateLabels: Record<StepState, string>;
}) {
  return (
    <li
      className={`stepper-step stepper-step--${step.state}`}
      aria-current={isCurrent ? "step" : undefined}
    >
      <span className="stepper-number" aria-hidden="true">
        {position}
      </span>
      <span className="stepper-label">{step.label}</span>
      <span className="stepper-marker" aria-hidden="true">
        {STATE_MARKER[step.state]}
      </span>
      <span className="stepper-state">{stateLabels[step.state]}</span>
      {step.detail !== undefined && (
        <span className="stepper-detail">{step.detail}</span>
      )}
    </li>
  );
}

/**
 * Renders an ordered list of process steps with the current one marked.
 *
 * The single current step (first active, else first blocked) carries
 * `aria-current="step"`; see {@link findCurrentStepId}.
 */
export function Stepper({ steps, ariaLabel, stateLabels }: StepperProps) {
  const currentStepId = findCurrentStepId(steps);

  return (
    <ol className="stepper" aria-label={ariaLabel}>
      {steps.map((step, index) => (
        <StepItem
          key={step.id}
          step={step}
          position={index + 1}
          isCurrent={step.id === currentStepId}
          stateLabels={stateLabels}
        />
      ))}
    </ol>
  );
}
