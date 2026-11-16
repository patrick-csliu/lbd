/** Labels (projects, users, tags) as text: nested with "/", shown with "›" between levels. */

const ELL = "…";

/** Shorten `text` in the middle to at most `max` characters: "a rather long…chips cope". */
export function middle(text: string, max: number): string {
  if (text.length <= max) return text;
  if (max <= 1) return ELL;
  const head = Math.ceil((max - 1) / 2);
  const tail = max - 1 - head;
  return text.slice(0, head).trimEnd() + ELL + (tail ? text.slice(text.length - tail).trimStart() : "");
}

/** A label at most `max` characters long, keeping where it starts and its last part:
 * "Resonator chip 3/Wafer 12/Die 4" → "Resonator chip 3/…/Die 4" → "Reson…/…/Die 4". One part is
 * shortened in the middle. The levels stay separated by "/". */
export function shortLabel(label: string, max: number): string {
  if (label.length <= max) return label;
  const parts = label.split("/");
  if (parts.length === 1) return middle(label, max);
  const first = parts[0];
  const last = parts[parts.length - 1];
  const sep = parts.length > 2 ? `/${ELL}/` : "/";
  // the last part gets up to 60% of the room; the first part what is left
  const lastRoom = Math.max(4, Math.min(last.length, Math.floor(max * 0.6)));
  const shownLast = middle(last, lastRoom);
  const firstRoom = max - shownLast.length - sep.length;
  if (firstRoom >= 2) return middle(first, firstRoom) + sep + shownLast;
  return middle(last, max);
}

/** The parts of a label to show: the groups (muted) and the last part. */
export function labelParts(label: string): { groups: string[]; name: string } {
  const parts = label.split("/");
  return { groups: parts.slice(0, -1), name: parts[parts.length - 1] };
}

/** "Lab A › Qubit team › Alice": a label as read aloud and in plain text. */
export function labelPath(label: string): string {
  return label.split("/").join(" › ");
}
