// Save as CSV (plan 5): the numbers a panel shows, with the choices the user makes (which numbers,
// how much, the layout, the panels; units are always as stored). The server says how big the file will be and which
// choices can't be made (with why); the file is written in the background with progress and Cancel
// (server: export.py, lbd.plot.tables).

import { FormEvent, useEffect, useRef, useState } from "react";
import { api, ApiError, ExportChoice, ExportCut, ExportJob, ExportPlan } from "./api";
import { HelpLink } from "./help";

/** One panel the dialog can save: its session and its view now (plot units). */
export interface ExportSource {
  session: string;
  view: { xlim: number[]; ylim: number[] } | null;
  kind: string;
  file: string; // the data file: the Save dialog starts in its folder
  name?: string; // the panel's name, for "left out: ..."
  cut?: ExportCut; // a row, column or trace through the cursor, instead of what the panel shows
}

interface Props {
  /** The panel asked from first, then the others (for "all panels"); none: only the whole file. */
  sources: ExportSource[];
  /** No panel: the file to save whole (the Library, the file's menu). */
  file?: string;
  onClose: () => void;
  onSaved: (paths: string[]) => void;
}

const CHOICE_KEY = "lbd.exportChoice";
const DEFAULT: ExportChoice = { numbers: "shown", zoomed: false, layout: "rows", rows_are: "t" };

/** What each choice does (its tooltip). */
const TIPS: Record<string, string> = {
  "numbers:shown": "The numbers drawn in the panel: complex mode, operations and equations applied",
  "numbers:both": "Each column as drawn, followed by the file's own numbers (a complex value: its real and imaginary part)",
  "numbers:stored": "The file's own numbers, unchanged (a complex value: its real and imaginary part)",
  "zoomed:false": "All the chosen traces, every point, also outside the zoom; the slider where it is",
  whole: "Every point of every slider position as stored, like converting the file: the values on the same axes, one table",
  "zoomed:true": "Only the points inside the panel's zoom",
  "layout:rows": "A column for each axis, then for each value; a row per data point. Good for Origin, pandas, Excel filters",
  "layout:matrix": "A 2-D grid (a map, or curves of a series): the first row and the first column hold the axes",
  "rows_are:t": "Each row of the grid is a trace (or a map's row)",
  "rows_are:x": "Each row of the grid is a point of the horizontal axis",
  "panels:this": "Only the active panel",
  "panels:all": "Every panel with the same axes in one file, a column per panel",
};
const BAD_NAME = /[\\/:*?"<>|]/;

function remembered(): ExportChoice {
  try {
    // (a "units" choice remembered from before LBD 2.0 is left out: units are always as stored)
    const { units: _gone, ...kept } = JSON.parse(localStorage.getItem(CHOICE_KEY) ?? "{}");
    return { ...DEFAULT, ...kept };
  } catch {
    return DEFAULT;
  }
}

export function size(bytes: number): string {
  for (const [unit, f] of [["GB", 1e9], ["MB", 1e6], ["kB", 1e3]] as const) {
    if (bytes >= f) return `${(bytes / f).toPrecision(3)} ${unit}`;
  }
  return `${bytes} bytes`;
}

export default function ExportDialog({ sources, file, onClose, onSaved }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [choice, setChoice] = useState<ExportChoice>(remembered);
  const [all, setAll] = useState(false);
  const [plan, setPlan] = useState<ExportPlan | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [folder, setFolder] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<ExportJob | null>(null);
  const [step, setStep] = useState<1 | 2>(1); // the choices, then what will be written and Save
  const [noDialog, setNoDialog] = useState(false); // no system Save dialog here: the name is typed
  const panelless = sources.length === 0;
  const [whole, setWhole] = useState(panelless); // the whole file, not what the panel shows
  const [group, setGroup] = useState<string | null>(null); // the whole file: which values
  const dataFile = file ?? sources[0]?.file ?? "";
  const several = sources.length > 1;
  const used = all ? sources : sources.slice(0, 1);
  const names = used.map((s, k) => s.name ?? `Panel ${k + 1}`);
  const cut = sources[0]?.cut ?? null;
  const cuts = cut ? used.map((s) => s.cut!) : null;
  // a cut is one line: all of it, one point per row
  const asked: ExportChoice = cut ? { ...choice, zoomed: false, layout: "rows" } : choice;
  const views = asked.zoomed ? used.map((s) => s.view ?? { xlim: [], ylim: [] }) : null;

  useEffect(() => ref.current?.showModal(), []);

  // The plan (size, options, a name) again whenever a choice changes, a moment after the last one.
  useEffect(() => {
    let live = true;
    const timer = window.setTimeout(() => {
      (whole ? api.fileCsv(dataFile, group, asked) : api.exportCsv(used.map((s) => s.session), asked, views, undefined, names, cuts))
        .then((p) => {
          if (!live) return;
          setPlan(p);
          setError(null);
          if (name === null || !noDialog) {
            const cut = Math.max(p.path.lastIndexOf("/"), p.path.lastIndexOf("\\")) + 1;
            setFolder(p.path.slice(0, cut));
            setName(p.path.slice(cut));
          }
        })
        .catch((e) => live && setError(e instanceof Error ? e.message : String(e)));
    }, 150);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(choice), all, whole, group]);

  // While writing: how far it is, then "Saved" (or what went wrong).
  useEffect(() => {
    if (!job || job.state !== "writing") return;
    const timer = window.setTimeout(async () => {
      try {
        const now = (await api.exports()).jobs.find((j) => j.id === job.id);
        if (!now) return setError("The file isn't being written any more.");
        setJob(now);
        if (now.state === "done") {
          onSaved(now.paths);
          onClose();
        } else if (now.state === "failed") setError(`Not saved: ${now.error}`);
        else if (now.state === "cancelled") setError("Cancelled: nothing was saved.");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [job, onClose, onSaved]);

  const set = (patch: Partial<ExportChoice>) =>
    setChoice((c) => {
      const next = { ...c, ...patch };
      try {
        localStorage.setItem(CHOICE_KEY, JSON.stringify(next));
      } catch {
        // a choice not remembered is only a convenience lost
      }
      return next;
    });

  const nameProblem =
    name === null ? null : !name.trim() ? "Give the file a name." : !name.toLowerCase().endsWith(".csv") ? "The name must end in .csv." : BAD_NAME.test(name) ? 'A name can\'t contain \\ / : * ? " < > |' : null;
  const est = plan?.estimate ?? null;
  const writing = job?.state === "writing";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!plan || plan.error || writing || name === null) return;
    if (step === 1) return setStep(2);
    if (noDialog && nameProblem) return;
    try {
      let target = folder + name.trim();
      if (!noDialog) {
        try {
          const picked = await api.pickSave(dataFile, name.trim(), "csv", "Save as CSV");
          if (picked.path === null) return; // cancelled: nothing written, the dialog stays
          target = picked.path;
        } catch (err) {
          if (err instanceof ApiError && err.status === 501) {
            setNoDialog(true); // this computer has no Save dialog: the name is typed here
            setError(null);
            return;
          }
          throw err;
        }
      }
      const out = whole ? await api.fileCsv(dataFile, group, asked, target) : await api.exportCsv(used.map((s) => s.session), asked, views, target, names, cuts);
      setError(null);
      setJob({ id: out.job, paths: out.paths, state: "writing", error: null, path: out.paths[0], what: "", fraction: 0, seconds: 0 });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const radio = <K extends keyof ExportChoice>(key: K, value: ExportChoice[K], label: string, why: string | null = null) => (
    <label className={"check" + (why ? " muted" : "")} title={why ? `Not available: ${why}. ${TIPS[`${key}:${value}`] ?? ""}` : TIPS[`${key}:${value}`]}>
      <input type="radio" name={`export-${key}`} checked={choice[key] === value} disabled={!!why || writing} onChange={() => set({ [key]: value } as Partial<ExportChoice>)} />
      {label}
    </label>
  );
  const left = job && job.fraction > 0.02 ? (job.seconds / job.fraction) * (1 - job.fraction) : null;

  return (
    <dialog ref={ref} className="confirm-dialog export-dialog" onCancel={(e) => (writing ? e.preventDefault() : onClose())} aria-labelledby="export-title">
      <form onSubmit={submit}>
        <h3 id="export-title">{cut ? `Save this ${cut.which} as CSV` : panelless ? "Save the whole file as CSV" : "Save as CSV"}</h3>
        <p className="muted small">
          A table of numbers that Excel, Origin and <code>numpy.loadtxt</code> read, in the units stored in the file. The data file is
          not changed. Point at a choice for what it does. <HelpLink page="viewer/explore.html" anchor="save-as-csv" topic="Save as CSV" />
        </p>
        {step === 1 && (
          <>
        {!whole && (
        <fieldset>
          <legend>Numbers</legend>
          {radio("numbers", "shown", "as shown", plan?.options.shown ?? null)}
          {radio("numbers", "both", "as shown + stored", plan?.options.both ?? null)}
          {radio("numbers", "stored", "stored", plan?.options.stored ?? null)}
        </fieldset>
        )}
        {!cut && (
          <>
        {!panelless && (
        <fieldset>
          <legend>How much</legend>
          <label className="check" title={TIPS["zoomed:false"]}>
            <input type="radio" name="export-much" checked={!whole && !choice.zoomed} disabled={writing} onChange={() => { setWhole(false); set({ zoomed: false }); }} />
            what the panel shows
          </label>
          <label className={"check" + (plan?.options.zoomed && !whole ? " muted" : "")} title={!whole && plan?.options.zoomed ? `Not available: ${plan.options.zoomed}` : TIPS["zoomed:true"]}>
            <input type="radio" name="export-much" checked={!whole && choice.zoomed} disabled={writing || (!whole && !!plan?.options.zoomed)} onChange={() => { setWhole(false); set({ zoomed: true }); }} />
            the zoomed range
          </label>
          <label className="check" title={TIPS["whole"]}>
            <input type="radio" name="export-much" checked={whole} disabled={writing} onChange={() => setWhole(true)} />
            the whole file
          </label>
        </fieldset>
        )}
        {whole && plan?.groups && plan.groups.length > 1 && (
          <fieldset>
            <legend>Values</legend>
            {plan.groups.map((g) => (
              <label key={g.key} className="check" title="Values on the same axes: a table holds one such group. For another, save again">
                <input type="radio" name="export-group" checked={(group ?? plan.group) === g.key} disabled={writing} onChange={() => setGroup(g.key)} />
                {g.label}: {g.rows.toLocaleString()} rows
              </label>
            ))}
          </fieldset>
        )}
        <fieldset>
          <legend>Layout</legend>
          {radio("layout", "rows", "one data point per row")}
          {radio("layout", "matrix", "table (matrix)")}
          {choice.layout === "matrix" && (
            <span className="export-sub">
              rows are {radio("rows_are", "t", "the traces / map rows")}
              {radio("rows_are", "x", "the horizontal axis")}
            </span>
          )}
        </fieldset>
          </>
        )}
        {several && !whole && (
          <fieldset>
            <legend>Panels</legend>
            <label className="check" title={TIPS["panels:this"]}>
              <input type="radio" name="export-panels" checked={!all} disabled={writing} onChange={() => setAll(false)} />
              this panel
            </label>
            <label className="check" title={TIPS["panels:all"]}>
              <input type="radio" name="export-panels" checked={all} disabled={writing} onChange={() => setAll(true)} />
              {cut ? "all panels with the same cut" : "all panels with the same axes"}
            </label>
          </fieldset>
        )}
          </>
        )}
        {step === 1 && plan?.error && (
          <div className="export-size small" role="status">
            {plan.error}
          </div>
        )}
        {step === 2 && (
          <>
            <div className="export-summary small" role="status">
              {est ? (
                <>
                  <strong>
                    About {size(est.bytes)}: {est.rows.toLocaleString()} rows × {est.columns.toLocaleString()} columns
                  </strong>
                  {est.bytes > 200e6 && <>, about {Math.max(1, Math.round(est.bytes / 20e6 / 60))} min to write</>}
                  {plan && plan.columns.length > 0 && <div className="muted">Columns: {plan.columns.join(", ")}</div>}
                </>
              ) : (
                "Working out the size…"
              )}
            </div>
            {plan && plan.left_out.length > 0 && (
              <p className="export-warning small">
                Left out ({cut ? "no cut along this axis at this place" : "other axes"}; a save writes one file): {plan.left_out.join(", ")}.
              </p>
            )}
            {est?.warnings.map((w) => (
              <p key={w} className="export-warning small">
                {w}
              </p>
            ))}
            {noDialog && (
              <label className="export-name">
                File name (this computer has no Save dialog: it is saved next to the data file)
                <input value={name ?? ""} disabled={name === null || writing} onChange={(e) => setName(e.target.value)} aria-invalid={!!nameProblem} />
              </label>
            )}
          </>
        )}
        {writing && job && (
          <div role="status">
            <progress max={1} value={job.fraction} aria-label="Written so far" />
            <span className="muted small">
              {" "}
              {Math.round(job.fraction * 100)} %{left !== null ? `, about ${Math.ceil(left)} s left` : ""}
            </span>
          </div>
        )}
        {((noDialog && nameProblem) || error) && <p className="dialog-error">{error ?? nameProblem}</p>}
        <div className="dialog-buttons">
          {writing && job ? (
            <button type="button" onClick={() => api.cancelExport(job.id).catch((e) => setError(e instanceof Error ? e.message : String(e)))}>
              Cancel saving
            </button>
          ) : (
            <>
              <button type="button" onClick={onClose}>
                Cancel
              </button>
              {step === 2 && (
                <button type="button" onClick={() => setStep(1)}>
                  Back
                </button>
              )}
            </>
          )}
          <button type="submit" className="primary" disabled={(noDialog && !!nameProblem) || !plan || !!plan.error || writing || name === null}>
            {step === 1 ? "Next" : noDialog ? "Save" : "Save…"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
