// The parts the Settings dialog (SettingsDialog.tsx) is made of: one row per setting (its name, a
// line or two of help, its control on the right), a sub-heading, an on/off switch, and a choice of
// two or three (radio buttons drawn as one segmented control).

import { ReactNode, useEffect, useState } from "react";

/** One setting: name (bold) and help on the left, the control on the right. `id` lets "Find a
 * setting" point at it; `sub`: it depends on the setting above (indented). */
export function Setting({ id, name, help, children, sub = false, disabled = false }: { id: string; name: ReactNode; help?: ReactNode; children: ReactNode; sub?: boolean; disabled?: boolean }) {
  return (
    <div className={"setting-row" + (sub ? " sub" : "") + (disabled ? " disabled" : "")} data-setting={id}>
      <div className="setting-name">{name}</div>
      <div className="setting-control">{children}</div>
      {help && <div className="setting-help">{help}</div>}
    </div>
  );
}

/** A sub-heading in a section, with a line above it. */
export function SettingsGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="settings-group">
      <h4>{title}</h4>
      {children}
    </div>
  );
}

/** An on/off switch (a checkbox, so it is found by its label and ticked like one). */
export function Switch({ label, checked, onChange, disabled = false, title }: { label: string; checked: boolean; onChange: (on: boolean) => void; disabled?: boolean; title?: string }) {
  // shown at once; the viewer's answer (or a refusal, with the old value) follows
  const [on, setOn] = useState(checked);
  useEffect(() => setOn(checked), [checked]);
  return (
    <label className={"switch" + (disabled ? " disabled" : "")} title={title}>
      <input
        type="checkbox"
        role="switch"
        aria-label={label}
        checked={on}
        disabled={disabled}
        onChange={(e) => {
          setOn(e.target.checked);
          onChange(e.target.checked);
        }}
      />
      <span className="switch-track" aria-hidden="true" />
    </label>
  );
}

/** Two or three choices side by side (radio buttons, found by their labels). */
export function Segmented<T extends string>({ name, label, value, options, onChange }: { name: string; label: string; value: T; options: [T, string, string?][]; onChange: (v: T) => void }) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map(([v, text, title]) => (
        <label key={v} className={value === v ? "on" : ""} title={title}>
          <input type="radio" name={name} checked={value === v} onChange={() => onChange(v)} />
          {text}
        </label>
      ))}
    </div>
  );
}
