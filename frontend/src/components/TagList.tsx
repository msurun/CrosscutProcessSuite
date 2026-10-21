// src/components/TagList.tsx

import { useMemo, useState } from "react";
import type { ChangeEvent, ReactElement } from "react";

import type { LoopSummary, TagInfo } from "../api";
import { groupTagsByLoop, type LoopTags } from "../tagGroups";

/**
 * Case-insensitive substring match of `query` against `id` and `description`.
 *
 * Returns every tag whose id or description contains the query. An empty or
 * whitespace-only query matches all tags. The input is never mutated.
 */
export function filterTags(tags: readonly TagInfo[], query: string): TagInfo[] {
  const needle = query.trim().toLowerCase();
  if (needle === "") {
    return [...tags];
  }

  return tags.filter((tag) =>
    matchesQuery(tag.id, needle) || matchesQuery(tag.description ?? "", needle)
  );
}

/** Whether a single haystack contains the already-lowercased needle. */
function matchesQuery(haystack: string, needle: string): boolean {
  return haystack.toLowerCase().includes(needle);
}

interface TagListProps {
  /** All tags the user can choose from, in the order they should be shown. */
  tags: TagInfo[];
  /** Ids of the tags currently selected. */
  selected: readonly string[];
  /** Called with the tag id when the user checks or unchecks a tag. */
  onToggle: (tagId: string) => void;
  /** Already-translated label and placeholder of the search input. */
  searchLabel: string;
  /** Already-translated message shown when the search matches nothing. */
  emptyLabel: string;
  /** Analysed loops used to group the tags; without them the tag-name prefix decides. */
  loops?: readonly LoopSummary[];
  /** Heading of the group of tags that belong to no loop. */
  otherLabel?: string;
}

/**
 * Searchable checkbox list of tags.
 *
 * The search box only narrows what is displayed; selections are held by the
 * parent, so filtering never changes which tags are checked.
 */
export function TagList({
  tags,
  selected,
  onToggle,
  searchLabel,
  emptyLabel,
  loops = [],
  otherLabel = "",
}: TagListProps): ReactElement {
  const [query, setQuery] = useState("");

  // Recompute only when the tags or the query change, not on every render.
  const groups = useMemo(() => groupTagsByLoop(filterTags(tags, query), loops), [tags, query, loops]);

  function handleQueryChange(event: ChangeEvent<HTMLInputElement>): void {
    setQuery(event.target.value);
  }

  return (
    <div className="tag-list">
      <input
        type="search"
        aria-label={searchLabel}
        placeholder={searchLabel}
        value={query}
        onChange={handleQueryChange}
      />
      {groups.length === 0 ? (
        <p>{emptyLabel}</p>
      ) : (
        groups.map((group) => (
          <LoopGroup key={group.loop} group={group} heading={group.loop || otherLabel} selected={selected} onToggle={onToggle} />
        ))
      )}
    </div>
  );
}

interface LoopGroupProps {
  group: LoopTags;
  heading: string;
  selected: readonly string[];
  onToggle: (tagId: string) => void;
}

/** One loop heading with its tags listed per unit. */
function LoopGroup({ group, heading, selected, onToggle }: LoopGroupProps): ReactElement {
  return (
    <section className="tag-group">
      <h3 className="tag-group-heading">{heading}</h3>
      {group.units.map((units) => (
        <ul key={units.unit} aria-label={units.unit || undefined}>
          {units.tags.map((tag) => (
            <li key={tag.id}>
              <TagRow tag={tag} isSelected={selected.includes(tag.id)} onToggle={onToggle} />
            </li>
          ))}
        </ul>
      ))}
    </section>
  );
}

interface TagRowProps {
  tag: TagInfo;
  isSelected: boolean;
  onToggle: (tagId: string) => void;
}

/** One checkbox row: the tag id, its unit and the checkbox itself. */
function TagRow({ tag, isSelected, onToggle }: TagRowProps): ReactElement {
  return (
    <label>
      <input
        type="checkbox"
        checked={isSelected}
        onChange={() => onToggle(tag.id)}
      />{" "}
      {tag.id} <span className="tag-unit">{tag.unit}</span>
    </label>
  );
}
