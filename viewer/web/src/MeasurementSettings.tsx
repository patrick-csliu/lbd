// The "Measurements" settings (plan 9, server: config.MEASUREMENTS_DEFAULTS): what the status line
// of a file being measured shows, and a browser notification when a measurement finishes or stops
// while the page is in the background (off by default; the browser asks for permission once).

import { useState } from "react";
import { api, AppState, MeasurementSettings as Settings } from "./api";
import { useToast } from "./toast";
import { Setting, SettingsGroup, Switch } from "./settingsUi";

const PARTS: [keyof Settings, string][] = [
  ["time", "Time left"],
  ["percent", "Percentage"],
  ["points", "Points measured"],
  ["axes", "Slow axes (e.g. power 23 of 90)"],
];

export function MeasurementSettings({ settings, onSettings }: { settings: Settings; onSettings: (s: AppState) => void }) {
  const toast = useToast();
  const [note, setNote] = useState<string | null>(null);
  const set = async (changes: Partial<Settings>) => {
    try {
      onSettings(await api.setMeasurements(changes));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const setNotify = async (on: boolean) => {
    setNote(null);
    if (on) {
      if (typeof Notification === "undefined") {
        setNote("This browser has no notifications; the message in the page stays.");
        return;
      }
      const answer = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
      if (answer !== "granted") {
        setNote("The browser didn't allow notifications, so this stays off (allow them in the browser's site settings).");
        return;
      }
    }
    await set({ notify: on });
  };
  return (
    <>
      <p className="settings-intro">
        A file being measured shows a status line: where it is measured (here, or on another computer through a synced folder) and how far it is.
      </p>
      <Setting id="measurements.progress" name="Show the progress">
        <Switch label="Show the progress" checked={settings.progress} onChange={(on) => set({ progress: on })} />
      </Setting>
      {PARTS.map(([key, label]) => (
        <Setting key={key} id={`measurements.${key}`} name={label} sub disabled={!settings.progress}>
          <Switch label={label.replace(/ \(.*\)$/, "")} checked={settings[key]} disabled={!settings.progress} title={settings.progress ? undefined : "Needs Show the progress"} onChange={(on) => set({ [key]: on })} />
        </Setting>
      ))}
      <SettingsGroup title="Notifications">
        <Setting id="measurements.notify" name="Notify me when a measurement ends" help={note ?? "When it finishes or stops while the viewer is in the background (the browser asks once)."}>
          <Switch label="Notify me when a measurement finishes or stops" checked={settings.notify} onChange={setNotify} />
        </Setting>
      </SettingsGroup>
    </>
  );
}
