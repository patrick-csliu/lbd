// The Explore settings (server: config.EXPLORE_DEFAULTS): how many visible traces a vertical or
// horizontal cursor marks at its line. More makes every cursor move slower.

import { useEffect, useState } from "react";
import { api, AppState, ExploreSettings as Settings } from "./api";
import type { KeepParts } from "./keep";
import { useToast } from "./toast";
import { Setting, SettingsGroup } from "./settingsUi";

/** The look options and the plot types that have them (config.LOOKS_DEFAULTS), as the settings name them. */
const LOOK_NAMES: Record<string, string> = { grid: "Grid", points: "Show points" };
const KIND_NAMES: Record<string, string> = { curve: "Curves", scatter: "Scatter" };
const LOOK_HELP: Record<string, string> = {
  grid: "On: new plots of this type start with grid lines. Off: as the style says.",
  points: "On: new plots of this type start with a dot on the stored points. Off: without.",
};

/** The parts of a file's view that can be kept (keep.ts KeepParts), as the settings list them. */
const KEEP_LIST: [keyof KeepParts, string, string][] = [
  ["panels", "Panels and layout", "How many panels, their order, side by side or stacked"],
  ["plot", "Plot type, values and axes", "What each panel plots"],
  ["traces", "Traces", "Which traces are drawn, or make a map"],
  ["colours", "Colours and scales", "The colour map, and log or linear scales"],
  ["limits", "Colour limits", "The colour range"],
  ["sliders", "Slider positions", "Where each slider is"],
  ["operations", "Operations and equations", "Off by default: a file opens as stored"],
  ["zoom", "Zoom", "The view's limits (and a 3D plot's angle); never after the file changed"],
  ["sync", "Sync", "Which panels follow each other"],
  ["cursor_options", "Cursor options", "Cursor type, cuts, every trace at the line, move together"],
];

export function ExploreSettings({ settings, onSettings }: { settings: Settings; onSettings: (s: AppState) => void }) {
  const toast = useToast();
  const [text, setText] = useState(String(settings.line_traces));
  useEffect(() => setText(String(settings.line_traces)), [settings.line_traces]);

  const save = async () => {
    const n = Number(text.trim());
    if (!Number.isInteger(n) || n < 0) {
      toast("Type a whole number of traces.", "error");
      setText(String(settings.line_traces));
      return;
    }
    if (n === settings.line_traces) return;
    try {
      onSettings(await api.setExplore({ line_traces: n }));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const setPanels = async (n: number) => {
    try {
      onSettings(await api.setExplore({ new_panels: n }));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <>
    <SettingsGroup title="Panels">
      <Setting
        id="explore.new_panels"
        name="Panels for a new file"
        help="A file opened in Explore for the first time shows its first value; or a panel per value, up to this many. + Panel → Open all opens the others later."
      >
        <select aria-label="Panels for a new file" value={settings.new_panels} onChange={(e) => setPanels(Number(e.target.value))}>
          <option value={1}>First value only</option>
          {[2, 3, 4, 5].map((n) => (
            <option key={n} value={n}>
              At most {n} values
            </option>
          ))}
          <option value={6}>All values (up to 6)</option>
        </select>
      </Setting>
    </SettingsGroup>
    <SettingsGroup title="New plots start with">
      {Object.entries(settings.looks).flatMap(([kind, options]) =>
        Object.entries(options).map(([option, on]) => {
          const name = `${LOOK_NAMES[option] ?? option} on ${KIND_NAMES[kind] ?? kind}`;
          return (
            <Setting key={`${kind}.${option}`} id={`explore.looks.${kind}.${option}`} name={name} help={LOOK_HELP[option] ?? ""}>
              <input
                type="checkbox"
                aria-label={name}
                checked={on}
                onChange={async (e) => {
                  try {
                    onSettings(await api.setExplore({ looks: { ...settings.looks, [kind]: { ...options, [option]: e.target.checked } } }));
                  } catch (err) {
                    toast((err as Error).message, "error");
                  }
                }}
              />
            </Setting>
          );
        }),
      )}
      <p className="muted small">In Explore only; a tick under Display still changes one plot.</p>
    </SettingsGroup>
    <SettingsGroup title="Kept when a file is opened again">
      {KEEP_LIST.map(([key, name, help]) => (
        <Setting key={key} id={`explore.keep.${key}`} name={name} help={help}>
          <input
            type="checkbox"
            aria-label={`Keep ${name.toLowerCase()}`}
            checked={settings.keep[key]}
            onChange={async (e) => {
              try {
                onSettings(await api.setExplore({ keep: { ...settings.keep, [key]: e.target.checked } }));
              } catch (err) {
                toast((err as Error).message, "error");
              }
            }}
          />
        </Setting>
      ))}
      <p className="muted small">Cursor positions always start afresh. A file's ⋯ → Reset all starts its whole view afresh.</p>
    </SettingsGroup>
    <SettingsGroup title="Cursors">
      <Setting
        id="explore.line_traces"
        name="Every trace at a cursor line, at most"
        help="A vertical or horizontal cursor on curves marks where it meets each visible trace and lists the crossings, up to this many traces. A high number can make every cursor move slow."
      >
        <span className="settings-number-unit">
          <input
            className="settings-number"
            aria-label="Most traces marked at a cursor line"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onBlur={save}
            onKeyDown={(e) => e.key === "Enter" && save()}
          />
          <span className="unit">traces</span>
        </span>
      </Setting>
    </SettingsGroup>
    </>
  );
}
