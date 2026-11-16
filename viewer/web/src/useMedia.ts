import { useEffect, useState } from "react";

/** Whether a CSS media query matches now; follows the window as it is resized. */
export function useMedia(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const m = window.matchMedia(query);
    const on = () => setMatches(m.matches);
    on();
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [query]);
  return matches;
}

/** Below this width the side panels (the Files sidebar, the Library's filters) slide over the
 * content when asked for, instead of taking a column of their own. */
export const DRAWER_MEDIA = "(max-width: 1279px)";
/** Below this width the Library shows one pane at a time: the list, or the selected file. */
export const ONE_PANE_MEDIA = "(max-width: 899px)";
