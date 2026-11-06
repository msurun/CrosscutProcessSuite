// frontend/src/components/TuningProposalDetail.tsx
/**
 * Read-only detail of one tuning proposal (ADR 014): the old -> new table, confidence with its
 * reasons, caveats, the model preview, the source, the expiry and the KPI review. All server
 * text is rendered as text (React escapes it); nothing here changes anything.
 */

import type { Translate } from "../findings";
import { formatHash, parseHash } from "../route";
import type { PreviewPair, TuningApplied, TuningItem, TuningProposal, TuningReview } from "../tuningApi";
import {
  appliedUnverified,
  baseStatus,
  codeMessage,
  expiryText,
  invalidKey,
  isApplying,
  reasonText,
  refusedDetailText,
  reviewUntrusted,
  statusDetail,
  statusLevel,
} from "../tuningRules";
import { StatusChip, type StatusLevel } from "./StatusChip";

const SIGNIFICANT_DIGITS = 5;
const REVIEW_METRICS = [
  "n", "service_factor", "error_std", "iae_per_h", "out_travel_per_h",
  "oscillating", "sp_moves", "saturation_share",
] as const;

/** A number with at most five significant digits; "-" for a missing value. */
export function formatValue(value: number | boolean | null | undefined, t: Translate): string {
  if (typeof value === "boolean") return value ? t("tuning.proposals.yes") : t("tuning.proposals.no");
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return String(Number(value.toPrecision(SIGNIFICANT_DIGITS)));
}

/** Status chip: icon plus text, so the status never depends on colour alone. */
export function ProposalStatusChip({ status, t }: { status: string; t: Translate }) {
  const base = baseStatus(status);
  const detail = statusDetail(status);
  let label = t(`tuning.proposals.status.${base}`);
  if (base === "reviewed") label = `${label}: ${t(`tuning.proposals.verdict.${detail}`)}`;
  if (base === "refused" && detail) label = `${label}: ${refusedDetailText(detail, t)}`;
  return <StatusChip level={statusLevel(status)} label={label} />;
}

/** The old -> new table of the items: parameter, DCS tag, old, new, unit and vendor form. */
export function ItemsTable({ proposal, t }: { proposal: TuningProposal; t: Translate }) {
  const caption = t("tuning.proposals.items.caption", { form: proposal.vendor_form.key });
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={caption}>
      <table className="loops-table" data-testid="tuning-items">
        <caption className="hint">{caption}</caption>
        <thead>
          <tr>
            <th>{t("tuning.proposals.items.param")}</th>
            <th>{t("tuning.proposals.items.target")}</th>
            <th>{t("tuning.proposals.items.from")}</th>
            <th>{t("tuning.proposals.items.to")}</th>
            <th>{t("tuning.proposals.items.unit")}</th>
          </tr>
        </thead>
        <tbody>
          {proposal.items.map((item) => (
            <ItemRow key={item.target} item={item} t={t} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ItemRow({ item, t }: { item: TuningItem; t: Translate }) {
  return (
    <tr data-testid={`tuning-item-${item.param}`}>
      <td>{t(`tuning.proposals.param.${item.param}`)}</td>
      <td>{item.target}</td>
      <td>{formatValue(item.from, t)}</td>
      <td>
        <strong>{formatValue(item.to, t)}</strong>
      </td>
      <td>{item.unit}</td>
    </tr>
  );
}

function confidenceLevel(level: string): StatusLevel {
  if (level === "high") return "ok";
  return level === "medium" ? "warning" : "problem";
}

/** Confidence level (text + icon) with the reasons behind it. */
export function ConfidenceBlock({ proposal, t }: { proposal: TuningProposal; t: Translate }) {
  const { level, reasons } = proposal.confidence;
  return (
    <section data-testid="tuning-confidence">
      <h4>{t("tuning.proposals.confidence.title")}</h4>
      <StatusChip level={confidenceLevel(level)} label={t(`tuning.proposals.confidence.${level}`)} />
      <ul>
        {reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
      <p className="hint">
        {t("tuning.proposals.evidence", { evidence: t(`tuning.proposals.evidence.${proposal.vendor_form.evidence}`) })}
      </p>
    </section>
  );
}

/** The caveats copied from the vendor form. */
export function CaveatsBlock({ proposal, t }: { proposal: TuningProposal; t: Translate }) {
  if (proposal.caveats.length === 0) return null;
  return (
    <section data-testid="tuning-caveats">
      <h4>{t("tuning.proposals.caveats")}</h4>
      <ul>
        {proposal.caveats.map((caveat) => (
          <li key={caveat}>{caveat}</li>
        ))}
      </ul>
    </section>
  );
}

function pairText(pair: PreviewPair, t: Translate): string {
  return `${formatValue(pair.current, t)} -> ${formatValue(pair.proposed, t)}`;
}

/** Model simulation current vs proposed, always labelled as a prediction. */
export function PreviewBlock({ proposal, t }: { proposal: TuningProposal; t: Translate }) {
  const p = proposal.preview;
  return (
    <section data-testid="tuning-preview">
      <h4>{t("tuning.proposals.preview.title")}</h4>
      <p className="hint">{t("tuning.proposals.preview.label")}</p>
      <dl className="key-numbers">
        <dt>{t("tuning.proposals.preview.iae")}</dt>
        <dd>{formatValue(p.iae_ratio, t)}</dd>
        <dt>{t("tuning.proposals.preview.overshoot")}</dt>
        <dd>{pairText(p.overshoot_pct, t)}</dd>
        <dt>{t("tuning.proposals.preview.settling")}</dt>
        <dd>{pairText(p.settling_time_s, t)}</dd>
        <dt>{t("tuning.proposals.preview.ms")}</dt>
        <dd>{pairText(p.ms, t)}</dd>
      </dl>
    </section>
  );
}

/** Method, robustness, step test and the data window the proposal was computed from. */
export function SourceBlock({ proposal, t }: { proposal: TuningProposal; t: Translate }) {
  const s = proposal.source;
  return (
    <section data-testid="tuning-source">
      <h4>{t("tuning.proposals.source.title")}</h4>
      <dl className="key-numbers">
        <dt>{t("tuning.proposals.source.method")}</dt>
        <dd>{s.method}</dd>
        <dt>{t("tuning.proposals.source.robustness")}</dt>
        <dd>{formatValue(s.robustness, t)}</dd>
        <dt>{t("tuning.proposals.source.stepTest")}</dt>
        <dd>{s.step_test_id ?? t("tuning.proposals.source.none")}</dd>
        <dt>{t("tuning.proposals.source.window")}</dt>
        <dd>{windowText(proposal)}</dd>
      </dl>
    </section>
  );
}

function windowText(proposal: TuningProposal): string {
  const w = proposal.source.window;
  if (w === undefined) return "-";
  const origin = w.dataset_id ?? "history";
  return `${origin}: ${w.start} - ${w.end}`;
}

function ReviewTable({ review, t }: { review: TuningReview; t: Translate }) {
  const before = review.before ?? {};
  const after = review.after ?? {};
  if (Object.keys(before).length === 0 && Object.keys(after).length === 0) return null;
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={t("tuning.proposals.review.title")}>
      <table className="loops-table" data-testid="tuning-review-metrics">
        <thead>
          <tr>
            <th>{t("tuning.proposals.review.metric")}</th>
            <th>{t("tuning.proposals.review.before")}</th>
            <th>{t("tuning.proposals.review.after")}</th>
          </tr>
        </thead>
        <tbody>
          {REVIEW_METRICS.map((name) => (
            <tr key={name}>
              <td>{t(`tuning.proposals.metric.${name}`)}</td>
              <td>{formatValue(before[name], t)}</td>
              <td>{formatValue(after[name], t)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function verdictLevel(verdict: string): StatusLevel {
  if (verdict === "worse" || verdict === "worse_early") return "problem";
  return verdict === "improved" ? "ok" : "unused";
}

/** KPI review after the change: verdict, reasons, before/after metrics and the fixed caveat note. */
export function ReviewBlock({ proposal, t }: { proposal: TuningProposal; t: Translate }) {
  const review = proposal.review;
  if (review === null) return null;
  return (
    <section data-testid="tuning-review">
      <h4>{t("tuning.proposals.review.title")}</h4>
      <StatusChip level={verdictLevel(review.verdict)} label={t(`tuning.proposals.verdict.${review.verdict}`)} />{" "}
      {proposal.rollback_recommended && (
        <span data-testid="tuning-rollback-recommended">
          <StatusChip level="problem" label={t("tuning.proposals.rollbackRecommended")} />
        </span>
      )}
      <ul>
        {(review.reasons ?? []).map((code) => (
          <li key={code}>{reasonText(code, t)}</li>
        ))}
      </ul>
      {(reviewUntrusted(review.reasons) || appliedUnverified(proposal)) && (
        <p className="notice notice-warning" role="status" data-testid="tuning-review-unavailable">
          {t("tuning.proposals.review.unavailable")}
        </p>
      )}
      <ReviewTable review={review} t={t} />
      <p className="hint" data-testid="tuning-review-note">
        {t("tuning.proposals.review.note")}
      </p>
    </section>
  );
}

function readText(value: number | null | undefined, t: Translate): string {
  return value === null || value === undefined ? t("tuning.proposals.applied.unknown") : formatValue(value, t);
}

/** Values read before and after the write, per item; null / missing values are shown as unknown. */
function AppliedValues({ proposal, applied, t }: { proposal: TuningProposal; applied: TuningApplied; t: Translate }) {
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={t("tuning.proposals.applied.valuesCaption")}>
      <table className="loops-table" data-testid="tuning-applied-values">
        <caption className="hint">{t("tuning.proposals.applied.valuesCaption")}</caption>
        <thead>
          <tr>
            <th>{t("tuning.proposals.items.target")}</th>
            <th>{t("tuning.proposals.applied.readBefore")}</th>
            <th>{t("tuning.proposals.applied.readAfter")}</th>
          </tr>
        </thead>
        <tbody>
          {proposal.items.map((item) => (
            <tr key={item.target}>
              <td>{item.target}</td>
              <td>{readText(applied.from_read?.[item.target], t)}</td>
              <td>{readText(applied.to_read?.[item.target], t)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AppliedBlock({ proposal, t }: { proposal: TuningProposal; t: Translate }) {
  const applied = proposal.applied;
  if (applied === null) return null;
  return (
    <section data-testid="tuning-applied">
      <h4>{t("tuning.proposals.applied.title")}</h4>
      <p>{t("tuning.proposals.applied.text", { time: applied.t, approver: applied.approver })}</p>
      {applied.source !== undefined && (
        <p className="hint" data-testid="tuning-applied-source">
          {t("tuning.proposals.applied.source", { source: t(`tuning.proposals.applied.source.${applied.source}`) })}
        </p>
      )}
      {appliedUnverified(proposal) && (
        <div className="notice notice-warning" role="status" data-testid="tuning-applied-warning">
          <p>{t(invalidKey(applied.invalid))}</p>
          <p>{t("tuning.proposals.applied.unavailable")}</p>
        </div>
      )}
      <AppliedValues proposal={proposal} applied={applied} t={t} />
    </section>
  );
}

/** Explains the "applying" status: the outcome is not confirmed, a person may have to check. */
function ApplyingNotice({ t }: { t: Translate }) {
  const href = formatHash({ ...parseHash(window.location.hash), view: "gateway", loop: null, sub: "detail" });
  return (
    <div className="notice notice-warning" role="status" data-testid="tuning-applying">
      <p>{t("tuning.proposals.applying.text")}</p>
      <a href={href}>{t("tuning.proposals.applying.link")}</a>
    </div>
  );
}

/** The whole read-only detail panel of a proposal. */
export function TuningProposalDetail({ proposal, nowMs, t }: { proposal: TuningProposal; nowMs: number; t: Translate }) {
  const expiry = expiryText(proposal, nowMs, t);
  return (
    <div data-testid="tuning-detail">
      <h3>{t("tuning.proposals.detail.title", { loop: proposal.loop_id })}</h3>
      <p>
        <ProposalStatusChip status={proposal.status} t={t} />
        {expiry && (
          <span className="hint" data-testid="tuning-expiry">
            {" "}
            {expiry}
          </span>
        )}
      </p>
      {isApplying(proposal.status) && <ApplyingNotice t={t} />}
      {baseStatus(proposal.status) === "refused" && (
        <p className="notice notice-warning" role="status" data-testid="tuning-refusal">
          {codeMessage(statusDetail(proposal.status), t)}
        </p>
      )}
      <p className="hint">
        {t("tuning.proposals.detail.by", { user: proposal.created_by, time: proposal.created_at })}
        {proposal.rollback_of !== null && ` ${t("tuning.proposals.detail.rollbackOf", { id: proposal.rollback_of })}`}
      </p>
      <ItemsTable proposal={proposal} t={t} />
      <ConfidenceBlock proposal={proposal} t={t} />
      <CaveatsBlock proposal={proposal} t={t} />
      <PreviewBlock proposal={proposal} t={t} />
      <SourceBlock proposal={proposal} t={t} />
      <AppliedBlock proposal={proposal} t={t} />
      <ReviewBlock proposal={proposal} t={t} />
    </div>
  );
}
