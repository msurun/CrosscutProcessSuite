// src/components/ValveSettingsForm.test.tsx
// Behaviour tests for ValveSettingsForm: fields, change/submit callbacks, invalid and busy state.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Settings } from "../valveTest";
import { defaultSettings } from "../valveTest";
import { ValveSettingsForm } from "./ValveSettingsForm";

/** Fake translator: the key plus stringified params. */
const t = (key: string, params?: Record<string, string | number>) =>
  key + (params ? JSON.stringify(params) : "");

/** Renders the form; overrides tweak the props a test is about. */
function setup(overrides: { invalidField?: keyof Settings | null; busy?: boolean } = {}) {
  const onChange = vi.fn();
  const onSubmit = vi.fn();
  const view = render(
    <ValveSettingsForm
      settings={defaultSettings()}
      invalidField={overrides.invalidField ?? null}
      busy={overrides.busy ?? false}
      onChange={onChange}
      onSubmit={onSubmit}
      t={t}
    />,
  );
  return { onChange, onSubmit, container: view.container };
}

describe("ValveSettingsForm", () => {
  it("shows the default values in the labelled fields", () => {
    setup();

    expect(screen.getByLabelText(/^valve\.settings\.opStart/)).toHaveValue("50");
    expect(screen.getByLabelText(/^valve\.settings\.dwell/)).toHaveValue("120");
    expect(screen.getByLabelText(/^valve\.settings\.stepSizes/)).toHaveValue("1, 0.25");
  });

  it("reports the settings key and typed text on change", () => {
    const { onChange } = setup();

    fireEvent.change(screen.getByLabelText(/^valve\.settings\.opLow/), { target: { value: "5,5" } });

    expect(onChange).toHaveBeenCalledWith("opLow", "5,5");
  });

  it("links help text to the input with aria-describedby", () => {
    setup();

    const input = screen.getByLabelText(/^valve\.settings\.dwell/);
    expect(input).toHaveAttribute("aria-describedby", "valve-dwell-help");
    expect(screen.getByText("valve.settings.dwellHelp")).toHaveAttribute("id", "valve-dwell-help");
  });

  it("shows no alert when every field is valid", () => {
    setup();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("marks only the invalid field and shows one alert", () => {
    setup({ invalidField: "dwellS" });

    expect(screen.getByLabelText(/^valve\.settings\.dwell/)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText(/^valve\.settings\.opStart/)).toHaveAttribute("aria-invalid", "false");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent("valve.settings.invalid");
  });

  it("keeps the advanced section closed for a main-field error", () => {
    const { container } = setup({ invalidField: "opStart" });

    expect(container.querySelector("details")).not.toHaveAttribute("open");
  });

  it("opens the advanced section when one of its fields is invalid", () => {
    const { container } = setup({ invalidField: "stepsPerLeg" });

    expect(container.querySelector("details")).toHaveAttribute("open");
  });

  it("calls onSubmit when the button is pressed", () => {
    const { onSubmit } = setup();

    fireEvent.click(screen.getByRole("button", { name: "valve.settings.create" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("disables the button and shows the busy text while busy", () => {
    setup({ busy: true });

    expect(screen.getByRole("button", { name: "valve.settings.creating" })).toBeDisabled();
  });
});
