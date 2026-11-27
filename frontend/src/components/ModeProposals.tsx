// Operating-mode and equipment-group proposals from history (#145), on the Site page.
// The engine proposes (GET .../catalogue/proposals/modes); the engineer edits the thresholds,
// accepts (saved with PUT /api/site, like the equipment editor) or rejects. Nothing else is written.
import { useEffect, useState, type ReactElement, type ReactNode } from "react";

import { API_PREFIX, ApiError, fetchDatasets, getJson, sendJson, type DatasetSummary } from "../api";
import type { Translate } from "../findings";
import {
  fetchModeProposals,
  type EquipmentProposal,
  type ModeEvidence,
  type ModeProposal,
  type ModeProposalResponse,
} from "../modeProposalApi";
import { acceptEquipment, acceptMode, formatWindow, parseClauses } from "../modeProposalModel";
import type { SiteDoc } from "./equipmentModel";
import { DraftNotice } from "./DraftNotice";

export interface ModeProposalsProps {
  t: Translate;
}

const SITE_URL = `${API_PREFIX}/site`;
const message = (e: unknown): string => (e instanceof ApiError || e instanceof Error ? e.message : String(e));

/** Collapsible evidence: share of time, thresholds, example windows and the engine's note. */
function Evidence({ evidence, t }: { evidence: ModeEvidence; t: Translate }): ReactElement {
  return (
    <details className="field-howto">
      <summary>{t("modeProposal.evidence")}</summary>
      <ul>
        <li>{t("modeProposal.share", { share: Math.round(evidence.share * 100) })}</li>
        <li>{t("modeProposal.events", { events: evidence.events })}</li>
        {Object.entries(evidence.thresholds).map(([name, value]) => (
          <li key={name}>{`${name}: ${String(value)}`}</li>
        ))}
        {evidence.windows.map((window) => (
          <li key={window[0]}>{t("modeProposal.window", { window: formatWindow(window) })}</li>
        ))}
        <li>{evidence.detail}</li>
      </ul>
    </details>
  );
}

interface RowProps {
  title: string;
  confidence: string;
  evidence: ModeEvidence;
  t: Translate;
  onAccept: () => void;
  onReject: () => void;
  children?: ReactNode;
}

/** Shared row frame: title, confidence badge, body, evidence, Accept and Reject. */
function Row({ title, confidence, evidence, t, onAccept, onReject, children }: RowProps): ReactElement {
  return (
    <li className="mode-proposal">
      <strong>{title}</strong>{" "}
      <span className={`badge badge-${confidence}`}>
        {t("modeProposal.confidence", { level: t(`knowledgeProposal.level.${confidence}`) })}
      </span>
      {children}
      <Evidence evidence={evidence} t={t} />
      <button type="button" className="filter-chip" aria-label={t("modeProposal.acceptItem", { name: title })} onClick={onAccept}>
        {t("modeProposal.accept")}
      </button>{" "}
      <button type="button" className="filter-chip" aria-label={t("modeProposal.rejectItem", { name: title })} onClick={onReject}>
        {t("modeProposal.reject")}
      </button>
    </li>
  );
}

/** A mode row: its clauses with editable values. */
function ModeRow({ proposal, t, onAccept, onReject }: {
  proposal: ModeProposal;
  t: Translate;
  onAccept: (typed: string[]) => void;
  onReject: () => void;
}): ReactElement {
  const clauses = proposal.entry.condition.clauses;
  const [typed, setTyped] = useState(clauses.map((c) => String(c.value)));
  return (
    <Row title={proposal.entry.name} confidence={proposal.confidence} evidence={proposal.evidence} t={t}
      onAccept={() => onAccept(typed)} onReject={onReject}>
      <ul>
        {clauses.map((clause, index) => (
          <li key={`${clause.tag}${clause.op}${index}`}>
            {`${clause.tag} ${clause.op} `}
            <input
              type="text"
              inputMode="decimal"
              size={8}
              value={typed[index]}
              aria-label={t("modeProposal.threshold", { tag: clause.tag, op: clause.op })}
              onChange={(e) => setTyped(typed.map((v, i) => (i === index ? e.target.value : v)))}
            />
          </li>
        ))}
        {proposal.scope_new && <li>{t("modeProposal.newScope", { id: proposal.entry.scope })}</li>}
      </ul>
    </Row>
  );
}

/** Proposed equipment groups with their member tags. */
function GroupList({ groups, t, onAccept, onReject }: {
  groups: EquipmentProposal[];
  t: Translate;
  onAccept: (g: EquipmentProposal) => void;
  onReject: (id: string) => void;
}): ReactElement {
  return (
    <>
      <h3>{t("modeProposal.groups")}</h3>
      <ul>
        {groups.map((g) => (
          <Row key={g.id} title={g.entry.name} confidence={g.confidence} evidence={g.evidence} t={t}
            onAccept={() => onAccept(g)} onReject={() => onReject(g.id)}>
            <p>{t("modeProposal.members", { tags: g.entry.tags.join(", ") })}</p>
          </Row>
        ))}
      </ul>
    </>
  );
}

/** Dataset choice, the proposals loaded for it and the ids the engineer rejected. */
function useProposals(setStatus: (text: string) => void) {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [dataset, setDataset] = useState("");
  const [result, setResult] = useState<ModeProposalResponse | null>(null);
  const [rejected, setRejected] = useState<Set<string>>(new Set());
  useEffect(() => {
    fetchDatasets()
      .then((rows) => { setDatasets(rows); setDataset(rows[0]?.id ?? ""); })
      .catch((e) => setStatus(message(e)));
  }, [setStatus]);
  const load = () => {
    setStatus("");
    fetchModeProposals(dataset)
      .then((r) => { setResult(r); setRejected(new Set()); })
      .catch((e) => setStatus(message(e)));
  };
  const reject = (id: string) => setRejected(new Set(rejected).add(id));
  const drop = (id: string) => setResult((r) => r && {
    ...r, modes: r.modes.filter((m) => m.id !== id), equipment: r.equipment.filter((g) => g.id !== id),
  });
  return { datasets, dataset, setDataset, result, rejected, load, reject, drop };
}

/** Save one accepted change: re-read the site so concurrent edits are not overwritten, apply, PUT. */
async function saveAccepted(change: (site: SiteDoc) => SiteDoc): Promise<void> {
  const site = await getJson<SiteDoc>(SITE_URL);
  await sendJson<unknown>("PUT", SITE_URL, change(site));
}

export function ModeProposals({ t }: ModeProposalsProps): ReactElement {
  const [status, setStatus] = useState("");
  const [saved, setSaved] = useState("");
  const p = useProposals(setStatus);
  const accept = (id: string, change: (site: SiteDoc) => SiteDoc) =>
    saveAccepted(change)
      .then(() => { p.drop(id); setSaved(t("modeProposal.saved", { id })); setStatus(""); })
      .catch((e) => setStatus(message(e)));
  const acceptModeRow = (m: ModeProposal, typed: string[]) => {
    const clauses = parseClauses(m.entry.condition.clauses, typed);
    if (!clauses) return setStatus(t("modeProposal.badValue"));
    const group = p.result?.equipment.find((g) => g.id === m.entry.scope);
    return accept(m.id, (site) => acceptMode(site, m, clauses, group));
  };
  const modes = (p.result?.modes ?? []).filter((m) => !p.rejected.has(m.id));
  const groups = (p.result?.equipment ?? []).filter((g) => !p.rejected.has(g.id));
  return (
    <section className="mode-proposals" aria-label={t("modeProposal.title")}>
      <h2>{t("modeProposal.title")}</h2>
      <p>{t("modeProposal.intro")}</p>
      <label>
        {t("modeProposal.dataset")}{" "}
        <select value={p.dataset} onChange={(e) => p.setDataset(e.target.value)}>
          {p.datasets.map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}
        </select>
      </label>{" "}
      <button type="button" className="filter-chip" disabled={!p.dataset} onClick={p.load}>
        {t("modeProposal.propose")}
      </button>
      {status && <p className="status status-error" role="alert">{status}</p>}
      {saved && <p role="status">{saved}</p>}
      {saved && <DraftNotice t={t} />}
      {p.result && modes.length === 0 && groups.length === 0 && <p>{t("modeProposal.none")}</p>}
      {groups.length > 0 && (
        <GroupList groups={groups} t={t} onReject={p.reject} onAccept={(g) => accept(g.id, (s) => acceptEquipment(s, g))} />
      )}
      {modes.length > 0 && (
        <>
          <h3>{t("modeProposal.modes")}</h3>
          <ul>
            {modes.map((m) => (
              <ModeRow key={m.id} proposal={m} t={t} onAccept={(typed) => acceptModeRow(m, typed)} onReject={() => p.reject(m.id)} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
