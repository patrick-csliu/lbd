// A new version of LBD (plan 16.25; server: updates.py). Settings → About shows what the last
// check found, with the release page, the install command and "Check now". The reminder window
// appears on the first start of a day when a newer version is known; the server hands it to one
// page only. LBD never downloads or installs anything itself.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, RemindChoice, UpdatesState } from "./api";
import { Setting } from "./settingsUi";

function when(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** The install command with a Copy button (one per system: install.ps1, install.sh, install-macos.sh). */
function InstallCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState<string | null>(null);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied("Copied");
    } catch {
      setCopied("Select it and copy it"); // the browser refused the clipboard
    }
    setTimeout(() => setCopied(null), 2000);
  };
  return (
    <div className="update-command">
      <code>{command}</code>
      <button className="small" onClick={() => void copy()}>
        {copied ?? "Copy"}
      </button>
    </div>
  );
}

/** Settings → About: the newest version, its page, the install command, Check now. */
export function UpdateSettings() {
  const [state, setState] = useState<UpdatesState | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.updates().then(setState, (e: Error) => setError(e.message));
  }, []);
  const checkNow = async () => {
    setChecking(true);
    setError(null);
    try {
      setState(await api.checkUpdates());
    } catch (e) {
      setError((e as Error).message); // says why: no internet, a proxy, an unexpected answer
    } finally {
      setChecking(false);
    }
  };
  return (
    <Setting
      id="about.updates"
      name="New version"
      help="Asks GitHub for the latest release once a day when LBD Viewer starts, sending only the program's name and version. LBD never downloads or installs anything by itself."
    >
      <div className="update-info">
        {state?.newer ? (
          <p>
            <strong>LBD {state.latest} is available.</strong>{" "}
            <a href={state.url} target="_blank" rel="noreferrer">
              The release page
            </a>{" "}
            says what is new.
          </p>
        ) : (
          <p>{state?.latest ? `This is the latest version (${state.latest} on GitHub).` : "Not checked yet."}</p>
        )}
        {state?.newer && state.install_command && (
          <>
            <p className="muted small">To install it, run this in a terminal (PowerShell on Windows), or download the installer from the release page:</p>
            <InstallCommand command={state.install_command} />
          </>
        )}
        <p className="muted small">
          Last checked: {when(state?.checked_at ?? null)}{" "}
          <button className="small" onClick={checkNow} disabled={checking}>
            {checking ? "Checking…" : "Check now"}
          </button>
        </p>
        {error && <p className="dialog-error" role="alert">{error}</p>}
      </div>
    </Setting>
  );
}

/** The reminder window: asked once when the page opens; the server gives it to one page only.
 *  While the start's check still runs, it asks once more a little later. */
export function UpdateReminder({ onOpenAbout }: { onOpenAbout: () => void }) {
  const [state, setState] = useState<UpdatesState | null>(null);
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    let stop = false;
    const ask = async (again: boolean) => {
      try {
        const s = await api.updates(true);
        if (stop) return;
        if (s.remind) setState(s);
        else if (s.checking && again) setTimeout(() => void ask(false), 6000);
      } catch {
        /* the viewer's other requests show connection problems; a reminder isn't worth one */
      }
    };
    void ask(true);
    return () => {
      stop = true;
    };
  }, []);
  useEffect(() => {
    if (state) ref.current?.showModal();
  }, [state]);
  const choose = useCallback(
    async (choice: RemindChoice) => {
      setState(null);
      try {
        await api.remindUpdates(choice);
      } catch {
        /* the reminder was already counted as "later" today */
      }
      if (choice === "install") onOpenAbout();
    },
    [onOpenAbout],
  );
  if (!state) return null;
  return (
    <dialog ref={ref} className="confirm-dialog update-reminder" onCancel={() => void choose("later")} aria-labelledby="update-title">
      <h3 id="update-title">LBD {state.latest} is available</h3>
      <p>
        You have {state.current}. Settings → About shows the release page and how to install it.
      </p>
      <div className="dialog-buttons">
        <button onClick={() => void choose("never")} title={`No reminder for ${state.latest}; a later version reminds again`}>
          Never remind
        </button>
        <button onClick={() => void choose("later")} autoFocus>
          Remind later
        </button>
        <button className="primary" onClick={() => void choose("install")}>
          Install…
        </button>
      </div>
    </dialog>
  );
}
