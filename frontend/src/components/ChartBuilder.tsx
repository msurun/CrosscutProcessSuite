// frontend/src/components/ChartBuilder.tsx
// Editor for a trend chart draft: name, tag picker, series table, axes table and problems.
// Pure and controlled: every edit calls the trendChartModel function and reports the new draft via onChange.
import { useState } from "react";

import type { TagInfo } from "../api";
import type { Translate } from "../findings";
import { groupTagsByLoop } from "../tagGroups";
import {
  addSeries,
  draftProblems,
  moveSeriesToAxis,
  removeSeries,
  setAxisRange,
  setAxisSide,
} from "../trendChartModel";
import type { TrendAxis, TrendChartDraft } from "../trendChartsApi";

/** Props of {@link ChartBuilder}. */
export interface ChartBuilderProps {
  t: Translate;
  /** Data source id stored in every added series. */
  sourceId: string;
  /** Tags the user may pick from. */
  tags: readonly TagInfo[];
  /** The chart being edited. */
  draft: TrendChartDraft;
  /** Called with the new draft after every edit. */
  onChange: (draft: TrendChartDraft) => void;
}

/** Props shared by the sub-components. */
interface PartProps {
  t: Translate;
  draft: TrendChartDraft;
  onChange: (draft: TrendChartDraft) => void;
}

/** Tags whose id or description contains the query (case-insensitive); an empty query keeps all. */
function filterTags(tags: readonly TagInfo[], query: string): TagInfo[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...tags];
  return tags.filter((tag) => `${tag.id} ${tag.description ?? ""}`.toLowerCase().includes(q));
}

/** Parse a number input; an empty or invalid text means "auto" (null). */
function parseLimit(text: string): number | null {
  if (text.trim() === "") return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

/** Axis option text such as "y1 · m3/h · left". */
function axisLabel(t: Translate, axis: TrendAxis): string {
  return `${axis.id} · ${axis.unit || "-"} · ${t(`chartBuilder.side.${axis.side}`)}`;
}

/** The chart name input. */
function NameField({ t, draft, onChange }: PartProps) {
  return (
    <label>
      {t("chartBuilder.name")}
      <input value={draft.name} onChange={(e) => onChange({ ...draft, name: e.target.value })} />
    </label>
  );
}

/** One picker row: tag id, description and its Add button. */
function TagRow({ t, tag, added, onAdd }: { t: Translate; tag: TagInfo; added: boolean; onAdd: (tag: TagInfo) => void }) {
  return (
    <li>
      <span>{tag.id}</span> {tag.description && <small>{tag.description}</small>}{" "}
      <button type="button" disabled={added} aria-label={t("chartBuilder.addTag", { tag: tag.id })} onClick={() => onAdd(tag)}>
        {t("chartBuilder.add")}
      </button>
    </li>
  );
}

/** Search box plus the grouped, filtered list of tags to add. */
function TagPicker({ t, draft, tags, sourceId, onChange }: PartProps & { tags: readonly TagInfo[]; sourceId: string }) {
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const groups = groupTagsByLoop(filterTags(tags, query), []);
  const isAdded = (id: string) => draft.series.some((s) => s.source === sourceId && s.tag === id);
  const add = (tag: TagInfo) => {
    const result = addSeries(draft, { source: sourceId, tag: tag.id, unit: tag.unit ?? "" });
    setError(result.error ? t(`chartBuilder.error.${result.error}`) : "");
    if (!result.error) onChange(result.draft);
  };
  return (
    <section aria-label={t("chartBuilder.pickerTitle")}>
      <label>
        {t("chartBuilder.search")}
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      <p role="status">{error}</p>
      {groups.map((group) =>
        group.units.map((unit) => (
          <div key={`${group.loop}|${unit.unit}`}>
            <h4>{`${group.loop || t("chartBuilder.noLoop")} · ${unit.unit || "-"}`}</h4>
            <ul>
              {unit.tags.map((tag) => (
                <TagRow key={tag.id} t={t} tag={tag} added={isAdded(tag.id)} onAdd={add} />
              ))}
            </ul>
          </div>
        )),
      )}
    </section>
  );
}

/** One series row: colour swatch, name, axis select and Remove. */
function SeriesRow({ t, draft, index, onChange }: PartProps & { index: number }) {
  const series = draft.series[index];
  const name = series.label || series.tag;
  return (
    <tr>
      <td>
        <span aria-hidden="true" style={{ display: "inline-block", width: 14, height: 14, background: series.colour }} />
      </td>
      <td>{name}</td>
      <td>
        <select
          aria-label={t("chartBuilder.axisOf", { tag: name })}
          value={series.axis}
          onChange={(e) => onChange(moveSeriesToAxis(draft, index, e.target.value))}
        >
          {draft.axes.map((axis) => (
            <option key={axis.id} value={axis.id}>
              {axisLabel(t, axis)}
            </option>
          ))}
        </select>
      </td>
      <td>
        <button type="button" aria-label={t("chartBuilder.removeTag", { tag: name })} onClick={() => onChange(removeSeries(draft, index))}>
          {t("chartBuilder.remove")}
        </button>
      </td>
    </tr>
  );
}

/** Table of the chart's series. */
function SeriesTable({ t, draft, onChange }: PartProps) {
  if (draft.series.length === 0) return <p>{t("chartBuilder.noSeries")}</p>;
  return (
    <table aria-label={t("chartBuilder.seriesTitle")}>
      <tbody>
        {draft.series.map((s, i) => (
          <SeriesRow key={`${s.source}/${s.tag}`} t={t} draft={draft} index={i} onChange={onChange} />
        ))}
      </tbody>
    </table>
  );
}

/** One axis row: id, unit, side select, min/max inputs and the read-only pane. */
function AxisRow({ t, draft, axis, onChange }: PartProps & { axis: TrendAxis }) {
  const range = (min: number | null, max: number | null) => onChange(setAxisRange(draft, axis.id, min, max));
  const limit = (value: number | null | undefined) => (value == null ? "" : String(value));
  return (
    <tr>
      <td>{axis.id}</td>
      <td>{axis.unit || "-"}</td>
      <td>
        <select
          aria-label={t("chartBuilder.sideOf", { axis: axis.id })}
          value={axis.side}
          onChange={(e) => onChange(setAxisSide(draft, axis.id, e.target.value as "left" | "right"))}
        >
          <option value="left">{t("chartBuilder.side.left")}</option>
          <option value="right">{t("chartBuilder.side.right")}</option>
        </select>
      </td>
      <td>
        <input
          type="number"
          aria-label={t("chartBuilder.minOf", { axis: axis.id })}
          value={limit(axis.min)}
          onChange={(e) => range(parseLimit(e.target.value), axis.max ?? null)}
        />
      </td>
      <td>
        <input
          type="number"
          aria-label={t("chartBuilder.maxOf", { axis: axis.id })}
          value={limit(axis.max)}
          onChange={(e) => range(axis.min ?? null, parseLimit(e.target.value))}
        />
      </td>
      <td>{axis.pane ?? 0}</td>
    </tr>
  );
}

/** Table of the chart's axes. */
function AxesTable({ t, draft, onChange }: PartProps) {
  if (draft.axes.length === 0) return null;
  return (
    <table aria-label={t("chartBuilder.axesTitle")}>
      <tbody>
        {draft.axes.map((axis) => (
          <AxisRow key={axis.id} t={t} draft={draft} axis={axis} onChange={onChange} />
        ))}
      </tbody>
    </table>
  );
}

/** Translated list of the problems that block saving. */
function ProblemList({ t, draft }: { t: Translate; draft: TrendChartDraft }) {
  const problems = [...new Set(draftProblems(draft))];
  if (problems.length === 0) return null;
  return (
    <ul aria-label={t("chartBuilder.problemsTitle")}>
      {problems.map((code) => (
        <li key={code}>{t(`chartBuilder.problem.${code}`)}</li>
      ))}
    </ul>
  );
}

/** Builder for one trend chart draft. */
export function ChartBuilder({ t, sourceId, tags, draft, onChange }: ChartBuilderProps) {
  return (
    <div>
      <NameField t={t} draft={draft} onChange={onChange} />
      <TagPicker t={t} draft={draft} tags={tags} sourceId={sourceId} onChange={onChange} />
      <SeriesTable t={t} draft={draft} onChange={onChange} />
      <AxesTable t={t} draft={draft} onChange={onChange} />
      <ProblemList t={t} draft={draft} />
    </div>
  );
}
