// A map bigger than the memory available is summarised once, reading the file strip by strip
// (server: summaries.py, plan 6d). While Explore waits for that, this shows how far it is and
// a Cancel button; the open (or new plot settings) request then answers "cancelled".

import { useEffect, useState } from "react";
import { api, SummaryJob } from "./api";

export function SummaryProgress({ path }: { path: string }) {
  const [job, setJob] = useState<SummaryJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let stop = false;
    let timer = 0;
    const poll = async () => {
      try {
        const { making } = await api.summaries();
        if (stop) return;
        setJob(making.find((j) => j.path === path) ?? null);
      } catch {
        // the server is busy or gone: the page's own request reports it
      }
      if (!stop) timer = window.setTimeout(poll, 500);
    };
    poll();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [path]);

  if (!job) return null;
  const left = job.fraction > 0.02 ? (job.seconds / job.fraction) * (1 - job.fraction) : null;
  return (
    <div className="summary-progress" role="status">
      <div>
        This map is larger than the memory available: {job.what}, once; it is kept for next time.
      </div>
      <progress max={1} value={job.fraction} aria-label="Summary made so far" />
      <span className="muted small">
        {Math.round(job.fraction * 100)} %{left !== null ? `, about ${Math.ceil(left)} s left` : ""}
      </span>{" "}
      <button
        onClick={() =>
          api.cancelSummary(path).catch((e) => setError(e instanceof Error ? e.message : String(e)))
        }
      >
        Cancel
      </button>
      {error && <div className="field-error">{error}</div>}
    </div>
  );
}
