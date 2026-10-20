// src/components/ValveTestPage.tsx
//
// Guided valve stroke test for one loop: settings -> safety checklist -> operator procedure ->
// recorded data -> result. The test is carried out by the operator by hand; this page prepares
// the procedure and analyses the record. Nothing is written to the plant.

import { useReducer, useRef, useState } from "react";

import {
  ApiError,
  analyseValveCsv,
  analyseValveWindow,
  planValveTest,
  type LoopSummary,
  type ValveAnalysis,
  type ValvePlanRequest,
} from "../api";
import type { Translate } from "../findings";
import {
  initialState,
  parseSettings,
  valveErrorMessage,
  valveReducer,
  type Phase,
  type Settings,
  type ValveAction,
} from "../valveTest";
import { Stepper, type StepInfo, type StepState } from "./Stepper";
import { ValveChecklist } from "./ValveChecklist";
import { ValvePlanView } from "./ValvePlanView";
import { ValveRecordStep } from "./ValveRecordStep";
import { ValveResultView } from "./ValveResultView";
import { ValveSettingsForm } from "./ValveSettingsForm";

/** The wizard steps in order, with the phase that shows each one. */
const STEPS: readonly { id: Phase; labelKey: string }[] = [
  { id: "setup", labelKey: "valve.step.settings" },
  { id: "checklist", labelKey: "valve.step.checklist" },
  { id: "plan", labelKey: "valve.step.procedure" },
  { id: "record", labelKey: "valve.step.record" },
  { id: "result", labelKey: "valve.step.result" },
];

/** Names of the server's request fields and the form fields they belong to. */
const FIELD_OF_SERVER_KEY: Record<string, keyof Settings> = {
  op_start: "opStart",
  dwell_s: "dwellS",
  op_low: "opLow",
  op_high: "opHigh",
  pv_band: "pvBand",
  step_sizes: "stepSizes",
  steps_per_leg: "stepsPerLeg",
};

/** Error code used for a failed request that never got an answer from the server. */
const NETWORK_CODE = "network";

/** Props of the valve test page. */
interface ValveTestPageProps {
  datasetId: string;
  loop: LoopSummary;
  t: Translate;
  onBack: () => void;
}

/** Step states for the stepper: earlier phases are done, the current one is active. */
function stepStates(phase: Phase): StepInfo["state"][] {
  // The result is the last step: once it is shown, nothing is left to do.
  const current = phase === "result" ? STEPS.length : STEPS.findIndex((step) => step.id === phase);
  return STEPS.map((_, index): StepState => (index < current ? "done" : index === current ? "active" : "todo"));
}

/** What went wrong, as the reducer stores it: a code, the field and a message. */
function errorInfo(error: unknown): { code: string | null; field: string | null; message: string } {
  if (error instanceof ApiError) return { code: error.code, field: error.field, message: error.message };
  return { code: NETWORK_CODE, field: null, message: String(error) };
}

/** The sentence for a stored error, translated. */
function errorText(t: Translate, error: { code: string | null; field: string | null; message: string }): string {
  if (error.code === NETWORK_CODE) return t("valve.error.network");
  return valveErrorMessage(t, new ApiError(0, error.message, error.code, error.field));
}

/** Runs an API call and reports its outcome to the reducer. */
async function runCall(dispatch: (action: ValveAction) => void, call: () => Promise<ValveAction>): Promise<void> {
  try {
    dispatch(await call());
  } catch (error: unknown) {
    dispatch({ type: "failed", error: errorInfo(error) });
  }
}

/** The valve stroke test wizard for one loop. */
export function ValveTestPage({ datasetId, loop, t, onBack }: ValveTestPageProps) {
  const [state, dispatch] = useReducer(valveReducer, undefined, initialState);
  const [invalidField, setInvalidField] = useState<keyof Settings | null>(null);
  // The request the plan was made from; the analysis calls send it again.
  const request = useRef<ValvePlanRequest | null>(null);

  const submitSettings = () => {
    const parsed = parseSettings(state.settings);
    if (!parsed.ok) {
      setInvalidField(parsed.field);
      return;
    }
    setInvalidField(null);
    request.current = parsed.request;
    dispatch({ type: "planRequested" });
    void runCall(dispatch, async () => ({ type: "planReady", plan: await planValveTest(parsed.request) }));
  };

  const analyse = (call: (plan: ValvePlanRequest) => Promise<ValveAnalysis>) => {
    if (request.current === null) return;
    const plan = request.current;
    dispatch({ type: "analysisRequested" });
    void runCall(dispatch, async () => ({ type: "analysed", analysis: await call(plan) }));
  };

  const serverField = state.error?.field ? (FIELD_OF_SERVER_KEY[state.error.field] ?? null) : null;
  const message = state.error ? errorText(t, state.error) : null;
  const states = stepStates(state.phase);
  const steps: StepInfo[] = STEPS.map((step, index) => ({ id: step.id, label: t(step.labelKey), state: states[index] }));

  return (
    <section className="valve-test">
      <button type="button" className="link-button" onClick={onBack}>
        ← {t("loops.back")}
      </button>
      <h2>{t("valve.title")}</h2>
      <p className="banner" role="note">
        {t("valve.banner")}
      </p>
      <Stepper
        steps={steps}
        ariaLabel={t("valve.stepper")}
        stateLabels={{
          todo: t("tuning.stepState.todo"),
          active: t("tuning.stepState.active"),
          done: t("tuning.stepState.done"),
          blocked: t("tuning.stepState.blocked"),
        }}
      />
      {state.phase === "setup" && (
        <>
          <ValveSettingsForm
            settings={state.settings}
            invalidField={invalidField ?? serverField}
            busy={state.busy}
            onChange={(key, value) => {
              setInvalidField(null);
              dispatch({ type: "editSetting", key, value });
            }}
            onSubmit={submitSettings}
            t={t}
          />
          {message !== null && (
            <p role="alert" className="status status-error">
              {message}
            </p>
          )}
        </>
      )}
      {state.phase === "checklist" && (
        <ValveChecklist
          checks={state.checks}
          onToggle={(index) => dispatch({ type: "toggleCheck", index })}
          onContinue={() => dispatch({ type: "acceptChecklist" })}
          onBack={() => dispatch({ type: "backTo", phase: "setup" })}
          t={t}
        />
      )}
      {state.phase === "plan" && state.plan !== null && (
        <ValvePlanView
          plan={state.plan}
          onRecord={() => dispatch({ type: "showRecord" })}
          onBack={() => dispatch({ type: "backTo", phase: "checklist" })}
          t={t}
        />
      )}
      {state.phase === "record" && (
        <ValveRecordStep
          datasetId={datasetId}
          loop={loop}
          busy={state.busy}
          errorText={message}
          onAnalyseWindow={(window) => analyse((plan) => analyseValveWindow(datasetId, loop.name, plan, window))}
          onAnalyseCsv={(csv) => analyse((plan) => analyseValveCsv(plan, csv))}
          onBack={() => dispatch({ type: "backTo", phase: "plan" })}
          t={t}
        />
      )}
      {state.phase === "result" && state.analysis !== null && (
        <ValveResultView
          analysis={state.analysis}
          loop={loop}
          onAgain={() => dispatch({ type: "backTo", phase: "record" })}
          onNewPlan={() => dispatch({ type: "backTo", phase: "setup" })}
          t={t}
        />
      )}
    </section>
  );
}
