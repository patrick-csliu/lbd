// The "Measurements" settings (plan 9, server: config.MEASUREMENTS_DEFAULTS): what the status line
// of a file being measured shows, and a browser notification when a measurement finishes or stops
// while the page is in the background (off by default; the browser asks for permission once).

import { useState } from "react";
import { api, AppState, MeasurementSettings as Settings } from "./api";
import { useToast } from "./toast";

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
      <div className="settings-title">Measurements</div>
      <p className="settings-note small muted">
        A file being measured shows a status line: where it is measured (here, or on another computer through a synced folder) and
        how far it is.
      </p>
      <label className="settings-choice">
        <input type="checkbox" checked={settings.progress} onChange={(e) => set({ progress: e.target.checked })} />
        Show the progress
      </label>
      {PARTS.map(([key, label]) => (
        <label key={key} className="settings-choice settings-sub">
          <input type="checkbox" checked={settings[key]} disabled={!settings.progress} onChange={(e) => set({ [key]: e.target.checked })} />
          {label}
        </label>
      ))}
      <label className="settings-choice">
        <input type="checkbox" checked={settings.notify} onChange={(e) => setNotify(e.target.checked)} />
        Notify me when a measurement finishes or stops while the viewer is in the background
      </label>
      {note && <p className="settings-note small">{note}</p>}
    </>
  );
}
