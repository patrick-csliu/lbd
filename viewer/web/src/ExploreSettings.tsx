// The Explore settings (server: config.EXPLORE_DEFAULTS): how many visible traces a vertical or
// horizontal cursor marks at its line. More makes every cursor move slower.

import { useEffect, useState } from "react";
import { api, AppState, ExploreSettings as Settings } from "./api";
import { useToast } from "./toast";
import { Setting, SettingsGroup } from "./settingsUi";

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
