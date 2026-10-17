// This browser tab as one of the viewer's open pages. The rules live on the server
// (viewer/src/lbd_viewer/pages.py); this file keeps the page connected to them:
//   - register (a number: Page 1, 2, ...), and report focus, so files go to the page used last;
//   - the long poll: wait for commands (open, show, transfer, events, the page list) and hand
//     them to the App, one at a time, in order. Each poll confirms the command handled before
//     (`after`), so a command whose answer got lost on the way is sent again, never skipped;
//   - after sleep (laptop, frozen background tab) the viewer may have dropped the page: register
//     anew and let the App re-check its tabs (some may now be open in another page);
//   - say goodbye when the tab closes, so its files are free at once.
import { useEffect, useRef, useState } from "react";
import { api, ApiError, PageCommand } from "./api";

export interface PageInfo {
  id: string;
  number: number;
}

export interface PageHandlers {
  /** Handle one command; the next one waits until this resolves (commands keep their order). */
  onCommand: (page: PageInfo, command: PageCommand) => Promise<void> | void;
  /** The page was registered. `again`: after being dropped (sleep); re-check the open tabs. */
  onRegistered: (page: PageInfo, again: boolean) => Promise<void> | void;
  /** Handling a command failed (a bug): say so. The command counts as handled, so it isn't
   *  sent again and again. */
  onCommandFailed: (command: PageCommand, error: unknown) => void;
}

/** Register this tab as a page and keep it connected; returns the page once registered. */
export function usePage(handlers: PageHandlers): PageInfo | null {
  const [page, setPage] = useState<PageInfo | null>(null);
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    let stopped = false;
    let current: PageInfo | null = null;
    let handled = 0; // id of the last command handled: the next poll confirms it

    const register = async (again: boolean) => {
      const r = await api.registerPage();
      current = { id: r.page, number: r.number };
      handled = 0;
      setPage(current);
      document.title = `LBD Viewer · Page ${current.number}`;
      await handlersRef.current.onRegistered(current, again);
    };

    const focus = () => {
      if (current) api.pageFocus(current.id).catch(() => undefined);
    };
    const visible = () => document.visibilityState === "visible" && focus();
    const bye = () => current && api.pageBye(current.id);

    const loop = async () => {
      let failures = 0;
      try {
        await register(false);
        focus();
      } catch {
        return; // no session: the App shows why (its state request fails the same way)
      }
      while (!stopped && current) {
        try {
          const command = await api.pageNext(current.id, handled);
          failures = 0;
          if (command && command.id > handled && !stopped) {
            try {
              await handlersRef.current.onCommand(current, command);
            } catch (e) {
              handlersRef.current.onCommandFailed(command, e);
            }
            handled = command.id;
          }
        } catch (e) {
          if (stopped) return;
          if (e instanceof ApiError && e.status === 404) {
            await register(true).catch(() => undefined); // dropped while asleep: back as a new page
            continue;
          }
          if (e instanceof ApiError && e.status === 403) return; // session gone: the App says so
          failures += 1; // the viewer restarting, or a network hiccup: wait, then retry
          await new Promise((resolve) => setTimeout(resolve, Math.min(10_000, 500 * 2 ** failures)));
        }
      }
    };

    window.addEventListener("focus", focus);
    document.addEventListener("visibilitychange", visible);
    window.addEventListener("pagehide", bye);
    loop();
    return () => {
      stopped = true;
      window.removeEventListener("focus", focus);
      document.removeEventListener("visibilitychange", visible);
      window.removeEventListener("pagehide", bye);
      bye();
    };
  }, []);

  return page;
}

let flashing: number | null = null;

/** Ask for the user's attention: bring the window forward if the browser allows it; otherwise
 *  flash the tab's title ("● message") until the page is looked at. */
export function attention(message: string) {
  window.focus();
  if (document.hasFocus() || flashing !== null) return;
  const title = document.title;
  let on = false;
  flashing = window.setInterval(() => {
    on = !on;
    document.title = on ? `● ${message}` : title;
  }, 900);
  const stop = () => {
    if (flashing !== null) window.clearInterval(flashing);
    flashing = null;
    document.title = title;
    window.removeEventListener("focus", stop);
  };
  window.addEventListener("focus", stop);
}
