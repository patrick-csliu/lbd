// A file being measured (name.lbd.writing, plan 9; server: live.py): one status line, the same in
// Explore, Figure and the Library. It says where it is measured (here, on another computer, no sign
// lately, stopped) and how far (time left, %, points, the slow outer axes: each a setting), and
// offers Recover once the measurement stopped. The numbers never jump: every part sits in a box as
// wide as the widest text it can take (sent by the server), with digits of one width.

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { api, baseName, LiveStatus, MeasurementSettings } from "./api";
import { ConfirmDialog, ConfirmRequest } from "./menu";
import { useToast } from "./toast";

export const DEFAULT_MEASUREMENTS: MeasurementSettings = {
  progress: true,
  time: true,
  percent: true,
  points: true,
  axes: true,
  notify: false,
};

/** The measurement settings (App provides them from /api/state). */
export const MeasurementsContext = createContext<MeasurementSettings>(DEFAULT_MEASUREMENTS);

const POLL_MS = 2000;

const clock = (t: number | null) => (t === null ? "" : new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));

/** A system notification, when the setting is on and the page is in the background. */
export function notifyInBackground(settings: MeasurementSettings, title: string, body: string): void {
  if (!settings.notify || !document.hidden || typeof Notification === "undefined") return;
  if (Notification.permission !== "granted") return;
  try {
    new Notification(title, { body });
  } catch {
    // a browser that refuses notifications from a page: the message in the page stays
  }
}

/** What the state is, in words. */
function headline(st: LiveStatus): string {
  switch (st.state) {
    case "measuring":
      return "Measuring";
    case "elsewhere":
      return st.computer ? `Measuring on ${st.computer}` : `Not being written on this computer (last changed ${clock(st.since)})`;
    case "silent":
      return `No sign from ${st.computer ?? "the computer measuring it"} since ${clock(st.since)}: it probably stopped, or the sync is paused`;
    case "stopped":
      return "Stopped before finishing";
    default:
      return "";
  }
}

export function MeasuringStatus({
  path,
  value,
  onRecovered,
}: {
  path: string;
  /** the value shown (its progress); else the one with the most points */
  value?: string;
  onRecovered?: (path: string, copy: boolean) => void;
}) {
  const settings = useContext(MeasurementsContext);
  const toast = useToast();
  const [st, setSt] = useState<LiveStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const last = useRef<LiveStatus["state"] | null>(null);
  const settingsRef = useRef(settings);
  settingsRef.current = settings;

  useEffect(() => {
    let stop = false;
    let timer = 0;
    const poll = async () => {
      if (!document.hidden || settingsRef.current.notify) {
        try {
          const now = await api.live(path, value);
          if (stop) return;
          setSt(now);
          setError(null);
          const was = last.current;
          last.current = now.state;
          // told once when a measurement that was going stops (or goes quiet)
          if ((was === "measuring" || was === "elsewhere") && (now.state === "stopped" || now.state === "silent")) {
            const text = `${baseName(path).replace(/\.writing$/i, "")}: ${headline(now)}.`;
            toast(text, "warning");
            notifyInBackground(settingsRef.current, "LBD: a measurement stopped", text);
          }
        } catch (e) {
          if (!stop) setError((e as Error).message);
        }
      }
      if (!stop) timer = window.setTimeout(poll, POLL_MS);
    };
    poll();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [path, value, toast]);

  if (error) return <div className="measuring-status error small">{error}</div>;
  if (!st || st.state === "gone") return null;
  const shown = settings.progress ? (st.progress ?? []).filter((p) => settings[p.kind]) : [];
  const canRecover = st.state === "stopped" || st.state === "silent";
  const elsewhere = st.state === "silent" || (st.state === "elsewhere" && st.computer !== null);
  const recover = () =>
    setConfirm({
      title: elsewhere ? "Recover a copy" : "Recover",
      text: elsewhere
        ? `This file is measured on ${st.computer ?? "another computer"} and synced here; this computer can't know whether ` +
          "that measurement still runs. Recover makes a copy here, " +
          `"${baseName(path).replace(/\.lbd\.writing$/i, "")} (recovered).lbd", with everything it holds now, and leaves the file ` +
          "being written as it is (changing it would travel back through the sync)."
        : "Its measurement ended without finishing the file. Recover makes it an .lbd file with everything it holds.",
      action: elsewhere ? "Make a copy" : "Recover",
      onConfirm: async () => {
        const r = await api.recoverFile(path);
        toast(r.copy ? `Copied as ${baseName(r.path)}; the file being measured is left as it is.` : `Recovered as ${baseName(r.path)}`);
        onRecovered?.(r.path, r.copy);
      },
    });
  return (
    <div className={`measuring-status ${st.state}`} role="status" aria-label="Measurement">
      <span className="measuring-dot" aria-hidden="true" />
      <strong>{headline(st)}</strong>
      {shown.map((p) => (
        <span key={p.kind} className="measuring-part">
          <span className="measuring-text">{p.text}</span>
          <span className="measuring-width" aria-hidden="true">
            {p.width}
          </span>
        </span>
      ))}
      {canRecover && (
        <button className="primary small" onClick={recover}>
          {elsewhere ? "Recover a copy…" : "Recover…"}
        </button>
      )}
      {st.note && <span className="muted small"> ({st.note})</span>}
      {confirm && <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />}
    </div>
  );
}
