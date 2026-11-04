import { formatBytes, LibraryColumn, LibraryRow } from "./api";

/**
 * The Library's columns, and how a row shows each: shared by the Library's list and the Files
 * sidebar's columns layout (and its two-line rows).
 */

// `min`: the column's smallest width (px). Fixed-format columns (dates, sizes) get the width
// their text needs; Name and the free-text columns share what is left.
export const COLUMNS: { id: LibraryColumn; title: string; width: string; min: number }[] = [
  { id: "name", title: "Name", width: "minmax(120px, 3fr)", min: 120 },
  { id: "date", title: "Date", width: "176px", min: 176 },
  { id: "sweep", title: "Sweep size", width: "96px", min: 96 },
  { id: "values", title: "Values", width: "minmax(90px, 1.5fr)", min: 90 },
  { id: "folder", title: "Folder", width: "minmax(90px, 1.5fr)", min: 90 },
  { id: "size", title: "File size", width: "76px", min: 76 },
  { id: "file", title: "File name", width: "minmax(100px, 1.5fr)", min: 100 },
  { id: "modified", title: "Modified", width: "128px", min: 128 },
  { id: "star", title: "★", width: "32px", min: 32 },
  { id: "project", title: "Project", width: "minmax(90px, 1.2fr)", min: 90 },
  { id: "users", title: "Users", width: "minmax(90px, 1.2fr)", min: 90 },
  { id: "tags", title: "Tags", width: "minmax(90px, 1.5fr)", min: 90 },
  { id: "comment", title: "Comment", width: "minmax(100px, 2fr)", min: 100 },
  { id: "copies", title: "Copies", width: "64px", min: 64 },
];
/** When the list is too narrow for the chosen columns, they are left out in this order (first
 * the ones least needed to tell files apart) instead of the list scrolling sideways. Name stays. */
const DROP_ORDER: LibraryColumn[] = ["modified", "file", "folder", "copies", "size", "comment", "users", "tags", "project", "values", "star", "sweep", "date"];

/** The chosen columns that fit in `width` px. */
export function fittingColumns(chosen: typeof COLUMNS, width: number): typeof COLUMNS {
  let shown = chosen;
  const need = (cols: typeof COLUMNS) => cols.reduce((n, c) => n + c.min, 0);
  for (const id of DROP_ORDER) {
    if (need(shown) <= width || shown.length <= 1) break;
    shown = shown.filter((c) => c.id !== id);
  }
  return shown;
}

/** "2026-03-14 23:30 +08": the date as written in the file, in its own time zone (shortened, see
 * shortZone; `fullZone`: "+08:00" as written). */
export function createdText(r: LibraryRow, fullZone = false): string {
  if (r.date_from_file || !r.created) return localTime(r.mtime);
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/i.exec(r.created);
  if (!m) return r.created;
  const zone = fullZone ? (m[3] === "Z" || m[3] === "z" ? "UTC" : m[3] ?? "") : shortZone(m[1], m[3]);
  return `${m[1]} ${m[2]} ${zone}`.trim();
}

/** "+08:00" → "+08" ("+05:30" stays), "Z" → "UTC"; nothing when it is this computer's own zone
 * on that day (the usual case), so the dates that differ stand out. */
export function shortZone(day: string, zone: string | undefined): string {
  if (!zone) return "";
  if (zone === "Z" || zone === "z") return new Date(`${day}T12:00:00Z`).getTimezoneOffset() === 0 ? "" : "UTC";
  const z = /^([+-])(\d{2}):?(\d{2})$/.exec(zone);
  if (!z) return zone;
  const minutes = (z[1] === "-" ? -1 : 1) * (Number(z[2]) * 60 + Number(z[3]));
  if (-new Date(`${day}T12:00:00`).getTimezoneOffset() === minutes) return "";
  return z[3] === "00" ? `${z[1]}${z[2]}` : `${z[1]}${z[2]}:${z[3]}`;
}

export function localTime(seconds: number): string {
  const d = new Date(seconds * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function cellText(r: LibraryRow, c: LibraryColumn): string {
  switch (c) {
    case "name":
      return r.title || r.name;
    case "date":
      return createdText(r);
    case "sweep":
      return r.sweep;
    case "values":
      return r.value_names;
    case "folder":
      return r.folder || "·";
    case "size":
      return formatBytes(r.size);
    case "file":
      return r.name;
    case "modified":
      return localTime(r.mtime);
    case "star":
      return r.star ? "★" : "";
    case "project":
      return r.project ?? "";
    case "users":
      return r.users.join(", ");
    case "tags":
      return r.tags.join(", ");
    case "comment":
      return r.comment.split("\n")[0];
    case "copies":
      return r.copies ? String(r.copies) : "";
  }
}
