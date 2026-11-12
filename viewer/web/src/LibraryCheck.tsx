/** The Library's "Check folders now" (plan 16, 16.21): looks through the open folders at once,
 * for a file that should be there but isn't listed yet. Nothing silent: it says "Checking…", then
 * how many files are new (or that nothing is new), and names every folder it couldn't read.
 * Also how the folders are watched (WatchingNote), so a slow file can be explained. */
import { useCallback, useState } from "react";
import { api, FolderWatch, LibraryCheck } from "./api";

type Outcome = { state: "checking" } | { state: "done"; found: LibraryCheck } | { state: "failed"; message: string };

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** "3 new files, 1 changed" or "Nothing new". */
export function checkSummary(found: LibraryCheck): string {
  const parts: string[] = [];
  if (found.new.length) parts.push(`${plural(found.new.length, "new file")}`);
  if (found.changed.length) parts.push(`${found.changed.length} changed`);
  if (found.moved.length) parts.push(`${found.moved.length} moved or renamed`);
  if (found.gone.length) parts.push(`${found.gone.length} gone`);
  return parts.length ? parts.join(", ") : "Nothing new";
}

function seconds(s: number | null): string {
  return s === null ? "" : s >= 60 && s % 60 === 0 ? `${s / 60} min` : `${s} s`;
}

/** How the open folders are watched (plan 16, 16.20), for the status line: by the system's
 * notifications (a new file in about a second) or timed checks; point at it for each folder. */
export function WatchingNote({ watching }: { watching: FolderWatch[] | undefined }) {
  if (!watching || watching.length === 0) return null;
  const notified = watching.filter((w) => w.how === "notifications");
  const timed = watching.filter((w) => w.how === "timed");
  const everies = [...new Set(timed.map((w) => seconds(w.every)))];
  const timedText = `checked every ${everies.join(" or ")}`;
  const text = !timed.length
    ? "New files: noticed at once"
    : !notified.length
      ? `New files: ${watching.length === 1 ? "the folder is" : "the folders are"} ${timedText}`
      : `New files: noticed at once in ${notified.length}, ${timedText} in ${timed.length} of the folders`;
  const tip =
    watching
      .map((w) => (w.how === "notifications" ? `${w.path}: the system tells LBD at once` : `${w.path}: checked every ${seconds(w.every)} (${w.reason})`))
      .join("\n") + "\nEvery folder is also checked in full every few minutes, and by Check folders now.";
  return (
    <span className="library-watching muted" title={tip}>
      {text}
    </span>
  );
}

/** The button (for the Library's top bar) and what it found (for under the status line).
 * `onChecked`: the index may have changed: show the list again now. */
export function useFolderCheck(onChecked: () => void) {
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const check = useCallback(() => {
    setOutcome({ state: "checking" });
    api
      .libraryCheck()
      .then((found) => {
        setOutcome({ state: "done", found });
        onChecked();
      })
      .catch((e) => setOutcome({ state: "failed", message: `The folders couldn't be checked: ${(e as Error).message}` }));
  }, [onChecked]);

  const button = (
    <button
      className="library-check-button"
      onClick={check}
      disabled={outcome?.state === "checking"}
      title="Look through the open folders now for new, changed and removed data files (they are noticed by themselves too: see Help)"
    >
      Check folders now
    </button>
  );

  let result = null;
  if (outcome) {
    const errors = outcome.state === "done" ? outcome.found.errors : [];
    result = (
      <div className={"library-check" + (outcome.state === "failed" || errors.length ? " warn" : "")} role="status" aria-label="Check folders now">
        <span>
          {outcome.state === "checking" && "Checking the folders…"}
          {outcome.state === "done" && checkSummary(outcome.found)}
          {outcome.state === "failed" && outcome.message}
        </span>
        {errors.length > 0 && (
          <span className="library-check-errors">
            {" · "}Couldn't read:
            <ul>
              {errors.map((e) => (
                <li key={e.path}>
                  <code>{e.path}</code>: {e.error}
                </li>
              ))}
            </ul>
          </span>
        )}
        {outcome.state !== "checking" && (
          <button className="icon subtle" aria-label="Close" title="Close" onClick={() => setOutcome(null)}>
            ×
          </button>
        )}
      </div>
    );
  }
  return { button, result };
}
