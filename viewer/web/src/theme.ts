// The viewer's colours: the ⚙ setting "theme" is "system" (follow the operating system), "light"
// or "dark". styles.css has the light colours on :root and the dark ones on
// :root[data-theme="dark"]; this file sets that attribute.
//
// The setting lives on the server (settings.json), so every page and every later session uses it.
// A copy is kept in this browser too, so the page starts in the right colours before the
// server's answer arrives (no white flash in dark mode).
import type { Theme } from "./api";

const STORE_KEY = "lbd-theme";
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
let current: Theme = "system";

function show() {
  const dark = current === "dark" || (current === "system" && darkQuery.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

// "System" follows the operating system also when it switches while the page is open.
darkQuery.addEventListener("change", show);

/** Use this theme now, and remember it in this browser for the next page load. */
export function applyTheme(theme: Theme) {
  current = theme;
  show();
  try {
    localStorage.setItem(STORE_KEY, theme);
  } catch {
    /* storage unavailable: the next load starts from "system" until the server answers */
  }
}

/** Before the first render: the theme this browser used last (else "system"). */
export function applyStoredTheme() {
  let stored: string | null = null;
  try {
    stored = localStorage.getItem(STORE_KEY);
  } catch {
    /* storage unavailable */
  }
  current = stored === "light" || stored === "dark" ? stored : "system";
  show();
}
