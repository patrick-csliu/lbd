// Save as CSV (plan 5): the numbers a panel shows, with the choices the user makes (which numbers,
// how much, the layout, the panels, the units). The server says how big the file will be and which
// choices can't be made (with why); the file is written in the background with progress and Cancel
// (server: export.py, lbd.plot.tables).

import { FormEvent, useEffect, useRef, useState } from "react";
import { api, ExportChoice, ExportJob, ExportPlan } from "./api";

/** One panel the dialog can save: its session and its view now (plot units). */
export interface ExportSource {
  session: string;
  view: { xlim: number[]; ylim: number[] } | null;
  kind: "curve" | "heatmap";
}

interface Props {
  /** The panel asked from first, then the others (for "all panels"). */
  sources: ExportSource[];
  onClose: () => void;
  onSaved: (paths: string[]) => void;
}

const CHOICE_KEY = "lbd.exportChoice";
const DEFAULT: ExportChoice = { numbers: "shown", zoomed: false, layout: "rows", rows_are: "t", units: "stored" };
const BAD_NAME = /[\\/:*?"<>|]/;

function remembered(): ExportChoice {
  try {
    return { ...DEFAULT, ...JSON.parse(localStorage.getItem(CHOICE_KEY) ?? "{}") };
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

export default function ExportDialog({ sources, onClose, onSaved }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [choice, setChoice] = useState<ExportChoice>(remembered);
  const [all, setAll] = useState(false);
  const [plan, setPlan] = useState<ExportPlan | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [folder, setFolder] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<ExportJob | null>(null);
  const several = sources.length > 1;
  const used = all ? sources : sources.slice(0, 1);

  useEffect(() => ref.current?.showModal(), []);

  // The plan (size, options, a name) again whenever a choice changes, a moment after the last one.
  useEffect(() => {
    let live = true;
    const timer = window.setTimeout(() => {
      api
        .exportCsv(used.map((s) => s.session), choice, choice.zoomed ? used.map((s) => s.view ?? { xlim: [], ylim: [] }) : null)
        .then((p) => {
          if (!live) return;
          setPlan(p);
          setError(null);
          if (name === null) {
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
  }, [JSON.stringify(choice), all]);

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
    if (nameProblem || !plan || plan.error || writing || name === null) return;
    try {
      const out = await api.exportCsv(
        used.map((s) => s.session),
        choice,
        choice.zoomed ? used.map((s) => s.view ?? { xlim: [], ylim: [] }) : null,
        folder + name.trim(),
      );
      setError(null);
      setJob({ id: out.job, paths: out.paths, state: "writing", error: null, path: out.paths[0], what: "", fraction: 0, seconds: 0 });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const radio = <K extends keyof ExportChoice>(key: K, value: ExportChoice[K], label: string, why: string | null = null) => (
    <label className={"check" + (why ? " muted" : "")} title={why ?? undefined}>
      <input type="radio" name={`export-${key}`} checked={choice[key] === value} disabled={!!why || writing} onChange={() => set({ [key]: value } as Partial<ExportChoice>)} />
      {label}
    </label>
  );
  const left = job && job.fraction > 0.02 ? (job.seconds / job.fraction) * (1 - job.fraction) : null;

  return (
    <dialog ref={ref} className="confirm-dialog export-dialog" onCancel={(e) => (writing ? e.preventDefault() : onClose())} aria-labelledby="export-title">
      <form onSubmit={submit}>
        <h3 id="export-title">Save as CSV</h3>
        <p className="muted small">
          A table of numbers that Excel, Origin and <code>numpy.loadtxt</code> read. The data file is not changed.
        </p>
        <fieldset>
          <legend>Numbers</legend>
          {radio("numbers", "shown", "as shown")}
          {radio("numbers", "both", "as shown + stored", plan?.options.both ?? null)}
          {radio("numbers", "stored", "stored", plan?.options.stored ?? null)}
        </fieldset>
        <fieldset>
          <legend>How much</legend>
          {radio("zoomed", false, "everything")}
          {radio("zoomed", true, "the zoomed range", plan?.options.zoomed ?? null)}
        </fieldset>
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
        <fieldset>
          <legend>Units</legend>
          {radio("units", "stored", "stored (Hz)")}
          {radio("units", "shown", "as on screen (GHz)")}
        </fieldset>
        {several && (
          <fieldset>
            <legend>Panels</legend>
            <label className="check">
              <input type="radio" name="export-panels" checked={!all} disabled={writing} onChange={() => setAll(false)} />
              this panel
            </label>
            <label className="check">
              <input type="radio" name="export-panels" checked={all} disabled={writing} onChange={() => setAll(true)} />
              all panels (one file when they share their axes)
            </label>
          </fieldset>
        )}
        <label className="export-name">
          File name
          <input value={name ?? ""} disabled={name === null || writing} onChange={(e) => setName(e.target.value)} aria-invalid={!!nameProblem} />
        </label>
        <div className="export-size small" role="status">
          {plan?.error
            ? plan.error
            : est
              ? `About ${size(est.bytes)}, ${est.rows.toLocaleString()} rows × ${est.columns.toLocaleString()} columns${est.files > 1 ? `, in ${est.files} files` : ""}`
              : "Working out the size…"}
        </div>
        {est?.warnings.map((w) => (
          <p key={w} className="export-warning small">
            {w}
          </p>
        ))}
        {writing && job && (
          <div role="status">
            <progress max={1} value={job.fraction} aria-label="Written so far" />
            <span className="muted small">
              {" "}
              {Math.round(job.fraction * 100)} %{left !== null ? `, about ${Math.ceil(left)} s left` : ""}
            </span>
          </div>
        )}
        {(nameProblem || error) && <p className="dialog-error">{error ?? nameProblem}</p>}
        <div className="dialog-buttons">
          {writing && job ? (
            <button type="button" onClick={() => api.cancelExport(job.id).catch((e) => setError(e instanceof Error ? e.message : String(e)))}>
              Cancel saving
            </button>
          ) : (
            <button type="button" onClick={onClose}>
              Cancel
            </button>
          )}
          <button type="submit" className="primary" disabled={!!nameProblem || !plan || !!plan.error || writing || name === null}>
            {est?.big ? "Save anyway" : "Save"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
