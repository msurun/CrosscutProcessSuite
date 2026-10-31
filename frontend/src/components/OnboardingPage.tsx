// frontend/src/components/OnboardingPage.tsx
/**
 * Automated dataset onboarding and readiness evaluation page (Phase 1, #39).
 * Evaluates prerequisite data conditions across control loops, anomaly detection,
 * and soft sensors, presenting traffic-light status and actionable remediation advice.
 */

import { useCallback, useEffect, useState } from "react";
import {
  fetchDatasetReadiness,
  type DatasetReadiness,
  type ModuleReadiness,
  type ReadinessStatus,
} from "../api";
import type { Translate } from "../findings";

export interface OnboardingPageProps {
  datasetId: string;
  t: Translate;
}

export function statusChipClass(status: ReadinessStatus): string {
  if (status === "ok") return "status-chip status-chip--ok";
  if (status === "warning") return "status-chip status-chip--warning";
  return "status-chip status-chip--problem";
}

interface ModuleCardProps {
  moduleKey: string;
  verdict: ModuleReadiness;
  t: Translate;
}

export function ModuleCard({ moduleKey, verdict, t }: ModuleCardProps) {
  const chipClass = statusChipClass(verdict.status);
  const statusLabel = t(`onboarding.status.${verdict.status}`);
  const title = t(`onboarding.modules.${moduleKey}`);
  const itemsText = t("onboarding.itemsChecked", { count: verdict.items_checked });

  return (
    <article className="config-card" data-testid={`onboarding-module-${moduleKey}`}>
      <header className="config-card-header">
        <div>
          <h3>{title}</h3>
          <span className="dataset-meta">{itemsText}</span>
        </div>
        <span className={chipClass} role="status">
          {statusLabel}
        </span>
      </header>
      <div className="onboarding-card-body">
        {verdict.reasons.length > 0 ? (
          <div className="onboarding-reasons">
            <h4>{t("onboarding.whatToFix")}</h4>
            <ul className="onboarding-reasons-list">
              {verdict.reasons.map((reason, idx) => (
                <li key={idx}>{reason}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="status status-ok">{t("onboarding.allChecksPassed")}</p>
        )}
      </div>
    </article>
  );
}

export function OnboardingPage({ datasetId, t }: OnboardingPageProps) {
  const [data, setData] = useState<DatasetReadiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(() => {
    if (!datasetId) return;
    setLoading(true);
    setError(null);
    fetchDatasetReadiness(datasetId)
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
        setLoading(false);
      });
  }, [datasetId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading) {
    return <p className="status">{t("onboarding.loading")}</p>;
  }

  if (error || !data) {
    return (
      <div className="notice notice-warning" role="alert">
        <p>{error || t("trends.error", { reason: "Failed to evaluate readiness" })}</p>
        <button type="button" className="filter-chip" onClick={loadData}>
          {t("onboarding.retry")}
        </button>
      </div>
    );
  }

  const overallClass = statusChipClass(data.verdict);
  const overallLabel = t(`onboarding.status.${data.verdict}`);

  return (
    <div className="onboarding-page" data-testid="onboarding-page">
      <header className="page-header">
        <div>
          <h2>{t("onboarding.title")}</h2>
          <p className="page-subtitle">{t("onboarding.subtitle")}</p>
        </div>
        <div className="onboarding-overall-badge">
          <span>{t("onboarding.overallVerdict")}: </span>
          <span className={overallClass} role="status" data-testid="onboarding-overall-verdict">
            {overallLabel}
          </span>
        </div>
      </header>

      <section className="onboarding-modules-grid">
        {Object.entries(data.modules).map(([key, mod]) => (
          <ModuleCard key={key} moduleKey={key} verdict={mod} t={t} />
        ))}
      </section>
    </div>
  );
}

