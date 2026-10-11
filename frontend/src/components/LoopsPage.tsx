// src/components/LoopsPage.tsx
import { useEffect, useState } from "react";

import { fetchLoops, type LoopSummary } from "../api";
import type { Translate } from "../findings";
import { BenefitPage } from "./BenefitPage";
import { LoopDetail } from "./LoopDetail";
import { TuningPage } from "./TuningPage";
import { LoopsOverview } from "./LoopsOverview";

/** Whether the loop list is being fetched, has arrived, or failed. */
type LoadStatus = "loading" | "ready" | "error";

/** The three pieces of state the loop list needs while it loads. */
interface LoopsState {
  loops: LoopSummary[];
  status: LoadStatus;
  errorReason: string;
}

/**
 * Loads the loops of a dataset and reports where the request stands.
 *
 * Returns the loops, the status ("loading", "ready" or "error") and, when the
 * status is "error", the reason the request failed.
 */
function useLoops(datasetId: string): LoopsState {
  const [loops, setLoops] = useState<LoopSummary[]>([]);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [errorReason, setErrorReason] = useState("");

  useEffect(() => {
    // A late response from a previous dataset must not overwrite the current one.
    let isCancelled = false;
    setStatus("loading");
    setErrorReason("");

    fetchLoops(datasetId)
      .then((loadedLoops) => {
        if (isCancelled) {
          return;
        }
        setLoops(loadedLoops);
        setStatus("ready");
      })
      .catch((error: unknown) => {
        if (isCancelled) {
          return;
        }
        setErrorReason(error instanceof Error ? error.message : String(error));
        setStatus("error");
      });

    return () => {
      isCancelled = true;
    };
  }, [datasetId]);

  return { loops, status, errorReason };
}

/**
 * Page that lists the loops of a dataset, or shows one loop's detail.
 *
 * Shows a loading or error message instead of the list when the request is
 * still running or has failed. Opening a loop switches to the detail view;
 * going back clears the selection.
 */
export function LoopsPage({ datasetId, t }: { datasetId: string; t: Translate }) {
  const { loops, status, errorReason } = useLoops(datasetId);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [subview, setSubview] = useState<"detail" | "tuning" | "benefit">("detail");

  useEffect(() => {
    // A loop selected for another dataset does not exist here.
    setSelectedName(null);
    setSubview("detail");
  }, [datasetId]);

  if (status === "loading") {
    return <p className="status">{t("trends.loading")}</p>;
  }

  if (status === "error") {
    return <p className="status status-error">{t("trends.error", { reason: errorReason })}</p>;
  }

  const selectedLoop = loops.find((loop) => loop.name === selectedName);
  if (selectedLoop !== undefined && subview === "tuning") {
    return (
      <TuningPage
        datasetId={datasetId}
        loopName={selectedLoop.name}
        t={t}
        onBack={() => setSubview("detail")}
      />
    );
  }
  if (selectedLoop !== undefined && subview === "benefit") {
    return (
      <BenefitPage
        datasetId={datasetId}
        loopName={selectedLoop.name}
        t={t}
        onBack={() => setSubview("detail")}
      />
    );
  }
  if (selectedLoop !== undefined) {
    return (
      <LoopDetail
        datasetId={datasetId}
        loop={selectedLoop}
        t={t}
        onBack={() => setSelectedName(null)}
        onOpenTuning={() => setSubview("tuning")}
        onOpenBenefit={() => setSubview("benefit")}
      />
    );
  }

  return (
    <>
      <h2>{t("loops.title")}</h2>
      <LoopsOverview loops={loops} t={t} onOpen={setSelectedName} />
    </>
  );
}
