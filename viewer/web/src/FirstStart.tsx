// The first start's questions (plan 18, 18.8): only what would cause harm or surprise if left at its
// default. Everything else stays in Settings.
// 1. The data folders.
// 2. For each folder: on this computer only, synced with other computers, or in the cloud with files
//    kept online only (asked, never guessed). A folder kept online only turns "Read each file's
//    details" off, so the Library doesn't download every file.
// 3. If a folder is synced: how LBD edits data files (in place or copy and swap), both explained.
// 4. Which previews the Library draws: of every file (which reads every file), of the selected file
//    and rows near it, or only when asked. Every file can't be chosen while a folder is kept online only.
// 5. Whether LBD checks online for new versions.
// Every question starts with its first answer (that can be chosen) chosen. Nothing is saved, and nothing starts (no folder
// is read), until Start: the answers are kept here until then, the folders too.
// It can't be closed: closed half-way (the page closed), it is shown again next time. Settings from
// before it, with folders in them (an upgrade), get only question 5.

import { useEffect, useRef, useState } from "react";
import { api, ApiError, AppState, baseName, DataFileEdits, PreviewMode } from "./api";
import { EDIT_TEXTS } from "./askFirst";
import { PREVIEW_CHOICES } from "./LibraryPage";

type FolderKind = "local" | "synced" | "online";
const KINDS: [FolderKind, string, string][] = [
  ["local", "On this computer only", "Not copied to other computers by a sync tool"],
  ["synced", "Synced with other computers", "A sync tool (Synology Drive, OneDrive, Dropbox, …) keeps a copy here and on other computers"],
  ["online", "In the cloud, files kept online only", "A file is downloaded when it is opened"],
];

/** The questions still to ask with these settings, or null when there are none. */
export function firstStartNeeded(state: AppState): "all" | "updates" | null {
  if (!state.first_start_done) return "all";
  return state.check_updates === null ? "updates" : null;
}

export function FirstStart({ state, onSettings }: { state: AppState; onSettings: (s: AppState) => void }) {
  const needed = firstStartNeeded(state);
  const ref = useRef<HTMLDialogElement>(null);
  const [step, setStep] = useState<"folders" | "kinds" | "edits" | "previews" | "updates">(needed === "all" ? "folders" : "updates");
  const [roots, setRoots] = useState<string[]>(state.roots); // e.g. a folder given to lbd-view
  const [kinds, setKinds] = useState<Record<string, FolderKind>>({});
  const [edits, setEdits] = useState<DataFileEdits>("in_place");
  const [previews, setPreviews] = useState<PreviewMode>("all");
  const [updates, setUpdates] = useState(true);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);
  if (!needed) return null;

  const kindOf = (r: string): FolderKind => kinds[r] ?? "local";
  const anySynced = roots.some((r) => kindOf(r) === "synced");
  const online = roots.some((r) => kindOf(r) === "online");
  // every file's preview reads every file: not while a folder is kept online only (its details aren't read)
  const previewsChosen: PreviewMode = online && previews === "all" ? "nearby" : previews;
  const addFolder = (path: string) => {
    setError(null);
    setRoots((rs) => (rs.includes(path) ? rs : [...rs, path]));
    setTyped("");
  };
  const browse = async () => {
    setError(null);
    try {
      const r = await api.pickFolder();
      if (r.path) addFolder(r.path);
    } catch (e) {
      // no system dialog here (e.g. Linux without tkinter): the path box below still works
      setError(e instanceof ApiError && e.status === 501 ? "There is no folder dialog here: type the folder's path below." : (e as Error).message);
    }
  };
  const finish = async () => {
    setSaving(true);
    setError(null);
    try {
      if (needed === "all") {
        // the Library settings first, so the folders are read as asked from the start
        await api.setLibrary({ read_headers: !online, previews: previewsChosen, notice_seen: true, ...(anySynced ? { data_file_edits: edits } : {}) });
        const saved = (await api.state()).roots; // as saved now: Start may be clicked again after a problem
        for (const r of saved) if (!roots.includes(r)) await api.removeRoot(r);
        for (const r of roots) {
          try {
            await api.addRoot(r); // a folder added already is kept once
          } catch (e) {
            setStep("folders");
            throw new Error(`${(e as Error).message}. Remove it from the list, or correct its path and add it again.`);
          }
        }
      }
      onSettings(await api.setFirstStart({ check_updates: updates, ...(needed === "all" ? { first_start_done: true } : {}) }));
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  };
  const next = () =>
    setStep(step === "folders" ? "kinds" : step === "kinds" ? (anySynced ? "edits" : "previews") : step === "edits" ? "previews" : "updates");
  const back = () =>
    setStep(step === "updates" ? "previews" : step === "previews" ? (anySynced ? "edits" : "kinds") : step === "edits" ? "kinds" : "folders");
  const ready = step !== "folders" || roots.length > 0;

  return (
    <dialog
      ref={ref}
      className="first-start"
      aria-label="Welcome to LBD Viewer"
      onCancel={(e) => e.preventDefault()} // it can't be closed: the answers are needed
    >
      <h2>{needed === "all" ? "Welcome to LBD Viewer" : "One question"}</h2>
      {step === "folders" && (
        <section aria-label="Your data folders">
          <p>Which folders hold your data? LBD lists the data files in them, in the Library. More can be added later.</p>
          <ul className="first-start-folders">
            {roots.map((r) => (
              <li key={r}>
                <span title={r}>{r}</span>
                <button
                  className="icon"
                  title="Remove this folder from the list"
                  aria-label={`Remove ${r}`}
                  onClick={() => setRoots((rs) => rs.filter((x) => x !== r))}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
          <button className="first-start-browse" onClick={browse}>
            Add a folder…
          </button>
          <form
            className="row-controls first-start-type"
            onSubmit={(e) => {
              e.preventDefault();
              if (typed.trim()) addFolder(typed.trim());
            }}
          >
            <input aria-label="A folder's path" placeholder="or type a folder's path" value={typed} onChange={(e) => setTyped(e.target.value)} />
            <button type="submit" disabled={!typed.trim()}>
              Add
            </button>
          </form>
        </section>
      )}
      {step === "kinds" && (
        <section aria-label="Where each folder is kept">
          <p>Where is each folder kept? LBD treats a folder that a sync tool copies to other computers, or one in the cloud, with more care.</p>
          {roots.map((r) => (
            <fieldset key={r} className="first-start-kind">
              <legend title={r}>{baseName(r) || r}</legend>
              {KINDS.map(([kind, name, tip]) => (
                <label key={kind} className="check" title={tip}>
                  <input type="radio" name={`kind-${r}`} checked={kindOf(r) === kind} onChange={() => setKinds((k) => ({ ...k, [r]: kind }))} />
                  {name}
                </label>
              ))}
            </fieldset>
          ))}
          <p className="muted small">
            In the cloud, with files kept online only: LBD doesn't read each file's details (that would download every file);
            the Library lists names, sizes and dates. Settings → Library can change it later.
          </p>
        </section>
      )}
      {step === "edits" && (
        <section aria-label="How LBD edits data files">
          <p>A synced folder: how should LBD change a finished data file (its labels, a saved view, its id)?</p>
          {(Object.keys(EDIT_TEXTS) as DataFileEdits[]).map((key) => (
            <label key={key} className="check first-start-choice">
              <input type="radio" name="edits" checked={edits === key} onChange={() => setEdits(key)} />
              <span>
                <strong>{EDIT_TEXTS[key].name}</strong>: {EDIT_TEXTS[key].text}
              </span>
            </label>
          ))}
          <p className="muted small">Settings → Library → Edit data files can change it later.</p>
        </section>
      )}
      {step === "previews" && (
        <section aria-label="Draw previews of">
          <p>
            Which files should the Library draw a preview of? A preview of every file shows at once, but every file in your folders is read
            for it, in the background.
          </p>
          {PREVIEW_CHOICES.map(([mode, name]) => (
            <label key={mode} className="check" title={mode === "all" && online ? "Not for a folder kept online only: it would download every file" : undefined}>
              <input type="radio" name="previews" checked={previewsChosen === mode} disabled={mode === "all" && online} onChange={() => setPreviews(mode)} />
              {name}
            </label>
          ))}
          <p className="muted small">
            {online ? "Every file can't be chosen while a folder is kept online only. " : ""}Settings → Library → Draw previews of can change it later.
          </p>
        </section>
      )}
      {step === "updates" && (
        <section aria-label="New versions">
          <p>
            Should LBD check online for new versions? Once a day when it starts, it asks GitHub for the latest release, sending only the
            program's name and version. It never downloads or installs anything by itself.
          </p>
          <label className="check">
            <input type="radio" name="updates" checked={updates === true} onChange={() => setUpdates(true)} />
            Yes, check for new versions
          </label>
          <label className="check">
            <input type="radio" name="updates" checked={updates === false} onChange={() => setUpdates(false)} />
            No, never go online
          </label>
          <p className="muted small">Settings → About can change it later.</p>
        </section>
      )}
      {error && (
        <p className="dialog-error" role="alert">
          {error}
        </p>
      )}
      <div className="row-controls first-start-buttons">
        {needed === "all" && step !== "folders" && <button onClick={back}>Back</button>}
        {step === "updates" ? (
          <button className="primary" disabled={!ready || saving} onClick={finish}>
            {needed === "all" ? "Start" : "OK"}
          </button>
        ) : (
          <button className="primary" disabled={!ready} onClick={next}>
            Next
          </button>
        )}
      </div>
    </dialog>
  );
}
