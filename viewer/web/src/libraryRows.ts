import { useCallback, useEffect, useRef, useState } from "react";
import { api, LibraryQuery, LibraryRow, LibraryStatus } from "./api";
import { useToast } from "./toast";

/** Rows asked for at a time. */
export const PAGE = 100;

/**
 * The index's state, asked for every 2 s: `generation` changes when the listed files changed
 * (the lists then ask for their rows again, keeping the selection and the scroll position).
 * `notify`: show the index's notes about labels (once; only the Library page does).
 */
export function useLibraryStatus(notify: boolean): { status: LibraryStatus | null; generation: number; refresh: () => void } {
  const toast = useToast();
  const [status, setStatus] = useState<LibraryStatus | null>(null);
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    let live = true;
    const ask = () =>
      api
        .libraryStatus()
        .then((s) => {
          if (!live) return;
          setStatus(s);
          setGeneration(s.generation);
          if (notify) for (const n of s.notes ?? []) toast(n, "info"); // about labels: told once
        })
        .catch(() => undefined); // the next try reports nothing new; the list keeps what it shows
    ask();
    const id = window.setInterval(ask, 2000);
    return () => {
      live = false;
      window.clearInterval(id);
    };
  }, [toast, notify]);

  /** The index changed because of something done here: show it now, not at the next check. */
  const refresh = useCallback(
    () =>
      void api
        .libraryStatus()
        .then((s) => setGeneration(s.generation))
        .catch(() => undefined),
    [],
  );
  return { status, generation, refresh };
}

export interface LibraryRows {
  /** the number of files the query lists (null: not known yet) */
  total: number | null;
  /** row i, if its page is loaded */
  rowAt: (i: number) => LibraryRow | undefined;
  /** the index of a loaded row, or -1 */
  indexOf: (path: string | null) => number;
  /** the loaded rows, in order */
  loadedRows: () => LibraryRow[];
  /** why the last page couldn't be read */
  listError: string | null;
  /** changes whenever a page arrives (for effects that look at the rows) */
  pages: Map<number, LibraryRow[]>;
}

/**
 * The rows of a Library query, a page of PAGE rows at a time: the pages from `firstPage` to
 * `lastPage` (what is on screen, plus a margin) are asked for, again when the query or the
 * index's `generation` changes. A new query starts afresh.
 */
export function useLibraryRows(query: LibraryQuery, generation: number, firstPage: number, lastPage: number): LibraryRows {
  const queryKey = JSON.stringify(query);
  const [total, setTotal] = useState<number | null>(null);
  const [pages, setPages] = useState<Map<number, LibraryRow[]>>(new Map());
  const asked = useRef<Map<number, string>>(new Map()); // page -> the query+generation it was asked for
  const [listError, setListError] = useState<string | null>(null);

  useEffect(() => {
    setPages(new Map());
    asked.current = new Map();
    setTotal(null);
  }, [queryKey]);

  useEffect(() => {
    for (let p = firstPage; p <= lastPage; p++) {
      if (total !== null && p * PAGE >= total && p > 0) break;
      const key = `${queryKey}|${generation}`;
      if (asked.current.get(p) === key) continue;
      asked.current.set(p, key);
      api
        .libraryList(query, p * PAGE, PAGE)
        .then((r) => {
          if (asked.current.get(p) !== key) return; // a newer query or change was asked meanwhile
          setTotal(r.total);
          setListError(null);
          setPages((old) => new Map(old).set(p, r.rows));
        })
        .catch((e) => {
          asked.current.delete(p);
          setListError((e as Error).message);
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [firstPage, lastPage, queryKey, generation, total]);

  const rowAt = (i: number): LibraryRow | undefined => pages.get(Math.floor(i / PAGE))?.[i % PAGE];
  const indexOf = (path: string | null): number => {
    if (!path) return -1;
    for (const [p, rows] of pages) {
      const k = rows.findIndex((r) => r.path === path);
      if (k >= 0) return p * PAGE + k;
    }
    return -1;
  };
  const loadedRows = (): LibraryRow[] => [...pages.entries()].sort((a, b) => a[0] - b[0]).flatMap(([, rows]) => rows);
  return { total, rowAt, indexOf, loadedRows, listError, pages };
}
