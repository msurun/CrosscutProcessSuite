// frontend/src/components/DisabledReason.tsx
/**
 * Accessible wrapper that renders controls as aria-disabled while keeping them focusable.
 * Explains the missing permission or requirement using aria-describedby.
 */

import { cloneElement, useId } from "react";
import type { KeyboardEvent, ReactElement, SyntheticEvent } from "react";
import type { Translate } from "../findings";

export interface DisabledReasonProps {
  disabled: boolean;
  reason: string;
  children: ReactElement;
  t?: Translate;
  requiredRole?: string;
}

function resolveRoleName(requiredRole: string | undefined, t: Translate): string {
  if (!requiredRole) return "";
  const key = `auth.role.${requiredRole}`;
  const label = t(key);
  return !label || label === key ? requiredRole : label;
}

function resolveReasonText(reason: string, t?: Translate, requiredRole?: string): string {
  if (t && reason.startsWith("auth.reason.")) {
    return t(reason, { role: resolveRoleName(requiredRole, t) });
  }
  return reason;
}

function mergeDescribedBy(existing?: string, nextId?: string): string | undefined {
  if (!existing) return nextId;
  if (!nextId) return existing;
  return `${existing} ${nextId}`.trim();
}

function preventDisabledAction(event: SyntheticEvent): void {
  event.preventDefault();
  event.stopPropagation();
}

function handleDisabledKeyDown(e: KeyboardEvent): void {
  if (e.key === "Enter" || e.key === " ") {
    preventDisabledAction(e);
  }
}

function buildDisabledProps(describedBy: string | undefined, displayText: string) {
  return {
    "aria-disabled": "true",
    "aria-describedby": describedBy,
    title: displayText,
    onClick: preventDisabledAction,
    onKeyDown: handleDisabledKeyDown,
  };
}

function TooltipReasonText({ id, text }: { id: string; text: string }) {
  const style = {
    position: "absolute" as const,
    width: 1,
    height: 1,
    padding: 0,
    margin: -1,
    overflow: "hidden",
    clip: "rect(0, 0, 0, 0)",
    border: 0,
  };
  return (
    <span id={id} className="disabled-reason-text" role="tooltip" data-testid="disabled-reason-text" style={style}>
      {text}
    </span>
  );
}

export function DisabledReason({ disabled, reason, children, t, requiredRole }: DisabledReasonProps) {
  const reasonId = useId();
  if (!disabled) return children;

  const displayText = resolveReasonText(reason, t, requiredRole);
  const existing = (children.props as { "aria-describedby"?: string })["aria-describedby"];
  const describedBy = mergeDescribedBy(existing, reasonId);
  const disabledProps = buildDisabledProps(describedBy, displayText);

  return (
    <span className="disabled-reason-wrapper" style={{ display: "inline-flex", position: "relative" }}>
      {cloneElement(children, disabledProps)}
      <TooltipReasonText id={reasonId} text={displayText} />
    </span>
  );
}
