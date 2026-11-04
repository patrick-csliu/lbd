import type { ReactNode } from "react";
import { labelParts, labelPath, shortLabel } from "./labelText";

/** One label as a pill: its groups muted and "›" between levels, on one line (a long label is
 * shortened in the middle; the whole label is in the tooltip), and its × inside the pill.
 * `prefix`: a word in front ("tag"); `extra`: e.g. "(2 of 3)". */
export function LabelChip({
  label,
  max = 40,
  prefix,
  extra,
  onRemove,
  removeLabel,
  small = false,
}: {
  label: string;
  max?: number;
  prefix?: string;
  extra?: ReactNode;
  onRemove?: () => void;
  removeLabel?: string;
  small?: boolean;
}) {
  const { groups, name } = labelParts(shortLabel(label, max));
  return (
    <span className={"chip label-chip" + (small ? " small-chip" : "")} title={labelPath(label)}>
      <span className="chip-text">
        {prefix && <span className="chip-prefix">{prefix} </span>}
        {groups.map((g, i) => (
          <span key={i} className="chip-group">
            {g}
            <span className="chip-sep" aria-hidden="true">
              {" › "}
            </span>
          </span>
        ))}
        <span className="chip-name">{name}</span>
        {extra && <span className="chip-extra"> {extra}</span>}
      </span>
      {onRemove && (
        <button className="chip-x" aria-label={removeLabel ?? `Remove ${label}`} title={removeLabel ?? `Remove ${label}`} onClick={onRemove}>
          ×
        </button>
      )}
    </span>
  );
}

/** A plain chip (a filter like "Date: 2026-03"), with the same look and × as a label chip. */
export function Chip({ children, onRemove, removeLabel }: { children: ReactNode; onRemove: () => void; removeLabel: string }) {
  return (
    <span className="chip label-chip">
      <span className="chip-text">{children}</span>
      <button className="chip-x" aria-label={removeLabel} title={removeLabel} onClick={onRemove}>
        ×
      </button>
    </span>
  );
}
