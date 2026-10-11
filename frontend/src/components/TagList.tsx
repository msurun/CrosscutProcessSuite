// src/components/TagList.tsx

import { useMemo, useState } from "react";
import type { ChangeEvent, ReactElement } from "react";

import type { TagInfo } from "../api";

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
}: TagListProps): ReactElement {
  const [query, setQuery] = useState("");

  // Recompute only when the tags or the query change, not on every render.
  const visibleTags = useMemo(() => filterTags(tags, query), [tags, query]);

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
      {visibleTags.length === 0 ? (
        <p>{emptyLabel}</p>
      ) : (
        <ul>
          {visibleTags.map((tag) => (
            <li key={tag.id}>
              <TagRow
                tag={tag}
                isSelected={selected.includes(tag.id)}
                onToggle={onToggle}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
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
