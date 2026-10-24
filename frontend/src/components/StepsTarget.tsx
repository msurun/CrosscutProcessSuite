// Target of the Steps view: analyse one control loop, or a tag pair (a stepped driver tag and
// its response tag). Renders the radio choice and the loop or the two tag selects it picks.
import type { TagInfo } from "../api";
import type { Translate } from "../findings";

/** What the Steps view analyses: one control loop, or a stepped tag and its response tag. */
export type TargetChoice = "loop" | "tags";

const TARGET_CHOICES: readonly TargetChoice[] = ["loop", "tags"];

/** Current target choice, its values and the handlers that change them. */
export interface TargetFieldsProps {
  choice: TargetChoice;
  onChoice: (choice: TargetChoice) => void;
  loop: string;
  loopNames: string[];
  onLoop: (loop: string) => void;
  tagNames: string[];
  driver: string;
  output: string;
  onDriver: (tag: string) => void;
  onOutput: (tag: string) => void;
  t: Translate;
}

/** Distinct tag names of a dataset, sorted alphabetically. */
export function sortedTagNames(tags: TagInfo[]): string[] {
  const names = new Set(tags.map((tag) => tag.id));
  return [...names].sort((a, b) => a.localeCompare(b));
}

/** Radio choice between a control loop and a tag pair. */
function TargetRadios({ choice, onChoice, t }: Pick<TargetFieldsProps, "choice" | "onChoice" | "t">) {
  return (
    <div className="field" role="radiogroup">
      {TARGET_CHOICES.map((option) => (
        <label key={option} className="field-label">
          <input type="radio" name="steps-target" value={option} checked={choice === option}
            onChange={() => onChoice(option)} />
          {` ${t(`steps.target.${option}`)}`}
        </label>
      ))}
    </div>
  );
}

/** The loop select of the loop mode. */
function LoopField({ loop, loopNames, onLoop, t }: Pick<TargetFieldsProps, "loop" | "loopNames" | "onLoop" | "t">) {
  return (
    <div className="field">
      <label className="field-label" htmlFor="steps-loop">{t("steps.loop")}</label>
      <select id="steps-loop" className="field-input" value={loop}
        onChange={(event) => onLoop(event.target.value)}>
        {loopNames.map((name) => <option key={name} value={name}>{name}</option>)}
      </select>
    </div>
  );
}

/** One tag select; the first option is an empty choice. */
function TagSelect({ id, label, value, tagNames, onChange }: {
  id: string;
  label: string;
  value: string;
  tagNames: string[];
  onChange: (tag: string) => void;
}) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>{label}</label>
      <select id={id} className="field-input" value={value}
        onChange={(event) => onChange(event.target.value)}>
        <option value="">{"—"}</option>
        {tagNames.map((name) => <option key={name} value={name}>{name}</option>)}
      </select>
    </div>
  );
}

/** The stepped-tag and response-tag selects of the tag-pair mode. */
function TagPairFields({ driver, output, tagNames, onDriver, onOutput, t }: Pick<TargetFieldsProps, "driver" | "output" | "tagNames" | "onDriver" | "onOutput" | "t">) {
  return (
    <>
      <TagSelect id="steps-driver" label={t("steps.driver")} value={driver}
        tagNames={tagNames} onChange={onDriver} />
      <TagSelect id="steps-output" label={t("steps.output")} value={output}
        tagNames={tagNames} onChange={onOutput} />
    </>
  );
}

/** The target radio choice followed by the loop select or the two tag selects. */
export function TargetFields(props: TargetFieldsProps) {
  return (
    <>
      <TargetRadios choice={props.choice} onChoice={props.onChoice} t={props.t} />
      {props.choice === "loop" ? <LoopField {...props} /> : <TagPairFields {...props} />}
    </>
  );
}
