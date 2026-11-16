import { LIBRARY_QUERY_KEY, LibraryQuery } from "./api";

/**
 * The Library's filters (folder, date, search, labels, sort) of this browser tab. They live in
 * App, not in the Library page, so that the Files sidebar of Explore and Figure lists the same
 * files ("Library selection"), and they are kept per browser tab (sessionStorage): two windows
 * can work on two selections, and reloading the page keeps them.
 */

export const NO_FILTERS: LibraryQuery = {
  folder: null,
  q: "",
  date: "",
  sort: "date",
  order: "desc",
  project: "",
  tags: [],
  users: [],
  starred: false,
  conflicts: false,
};

const KEY = LIBRARY_QUERY_KEY;

/** A stored or handed-over query, checked field by field: anything unexpected is left at its default. */
export function parseLibraryQuery(text: string | null): LibraryQuery | null {
  if (!text) return null;
  try {
    const o = JSON.parse(text) as Partial<Record<keyof LibraryQuery, unknown>>;
    const str = (v: unknown, d: string) => (typeof v === "string" ? v : d);
    const strs = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
    return {
      folder: typeof o.folder === "string" ? o.folder : null,
      q: str(o.q, ""),
      date: str(o.date, ""),
      sort: str(o.sort, NO_FILTERS.sort) as LibraryQuery["sort"],
      order: o.order === "asc" ? "asc" : "desc",
      project: str(o.project, ""),
      tags: strs(o.tags),
      users: strs(o.users),
      starred: o.starred === true,
      conflicts: o.conflicts === true,
    };
  } catch {
    return null;
  }
}

/** This tab's filters: handed over in the address (a new browser page made from another one,
 * see viewerUrl), else as kept for this tab. */
export function loadLibraryQuery(): LibraryQuery {
  const given = parseLibraryQuery(new URL(window.location.href).searchParams.get("library"));
  if (given) {
    saveLibraryQuery(given);
    return given;
  }
  try {
    return parseLibraryQuery(sessionStorage.getItem(KEY)) ?? NO_FILTERS;
  } catch {
    return NO_FILTERS;
  }
}

export function saveLibraryQuery(q: LibraryQuery): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(q));
  } catch {
    /* storage unavailable: the filters just aren't kept over a reload */
  }
}

/** Whether any filter narrows the list (the sort alone doesn't). */
export function hasFilters(q: LibraryQuery): boolean {
  return !!(q.folder || q.q || q.date || q.project || q.tags.length || q.users.length || q.starred || q.conflicts);
}
