// Files and folders that change on disk: another program rewrites a data file, adds a file to a
// folder, deletes one. Every shown file and listed folder registers here (`useDiskVersion`); one
// loop per page asks the server for all of them in a single request (/api/changes): every
// CHECK_EVERY ms while the page is visible, at once when it becomes visible again, never while it
// is hidden. The server only reads sizes and times (never opens a file), so this is cheap.
//
// A file's version is its size and modification time (`FileInfo.version`), a folder's is a
// signature of its listing (`DirListing.signature`). Each view compares the version here with
// the one it shows and reloads when they differ.

import { useEffect, useState } from "react";
import { api } from "./api";

export const CHECK_EVERY = 2000;

export type WatchKind = "file" | "dir";

/** What the last check said: `version` is null when the file or folder is gone; `error` when the
 *  server refused the path (e.g. its folder was removed from the list). Nothing yet: {}. */
export interface DiskState {
  version?: string | null;
  error?: string;
}

type Listener = (state: DiskState) => void;

const watched = new Map<string, { kind: WatchKind; path: string; listeners: Set<Listener>; last: DiskState }>();
let timer: number | null = null;
let running = false;

const keyOf = (kind: WatchKind, path: string) => `${kind}\n${path}`;

async function check(): Promise<void> {
  if (running || document.hidden || watched.size === 0) return;
  running = true;
  try {
    const entries = [...watched.values()];
    const files = entries.filter((e) => e.kind === "file").map((e) => e.path);
    const dirs = entries.filter((e) => e.kind === "dir").map((e) => e.path);
    // A failed request (the viewer stopped) is not reported here: the heartbeat in App.tsx
    // reports a viewer that can't be reached. The next check tries again.
    const r = await api.changes(files, dirs).catch(() => null);
    if (!r) return;
    for (const e of entries) {
      const found = e.kind === "file" ? r.files : r.dirs;
      const state: DiskState = e.path in r.errors ? { error: r.errors[e.path] } : e.path in found ? { version: found[e.path] } : {};
      if (state.version === e.last.version && state.error === e.last.error) continue;
      e.last = state;
      e.listeners.forEach((l) => l(state));
    }
  } finally {
    running = false;
  }
}

function start() {
  if (timer !== null) return;
  timer = window.setInterval(check, CHECK_EVERY);
  document.addEventListener("visibilitychange", check);
  window.addEventListener("focus", check);
}

function stop() {
  if (timer === null) return;
  window.clearInterval(timer);
  timer = null;
  document.removeEventListener("visibilitychange", check);
  window.removeEventListener("focus", check);
}

/** Watch a file or folder; `listener` gets each new state. Returns the function that stops it. */
export function watch(kind: WatchKind, path: string, listener: Listener): () => void {
  const key = keyOf(kind, path);
  let entry = watched.get(key);
  if (!entry) {
    entry = { kind, path, listeners: new Set(), last: {} };
    watched.set(key, entry);
  }
  entry.listeners.add(listener);
  if (entry.last.version !== undefined || entry.last.error) listener(entry.last);
  start();
  window.setTimeout(check, 0); // a new file or folder is checked right away, not after 2 s
  return () => {
    entry!.listeners.delete(listener);
    if (entry!.listeners.size === 0) watched.delete(key);
    if (watched.size === 0) stop();
  };
}

/** The version of a file or folder on disk, kept current while the component is shown. */
export function useDiskVersion(kind: WatchKind, path: string): DiskState {
  const [state, setState] = useState<DiskState>({});
  useEffect(() => {
    setState({});
    return watch(kind, path, setState);
  }, [kind, path]);
  return state;
}

/** The last version seen that was a real one (not "gone" or "not checked yet"): a key for views
 *  that just load the file again when it changes, and keep showing it while it is gone. */
export function useLatestVersion(version: string | null | undefined): string | null {
  const [latest, setLatest] = useState<string | null>(null);
  useEffect(() => {
    if (typeof version === "string") setLatest(version);
  }, [version]);
  return latest;
}

/** Ask for a check now (e.g. after the viewer itself changed a folder). */
export function checkNow(): void {
  void check();
}
