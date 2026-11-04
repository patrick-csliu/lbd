import { KeyboardEvent, Ref, useId, useMemo, useState } from "react";
import type { LabelNode } from "./api";
import { labelPath, shortLabel } from "./labelText";

/** At most this many suggestions under the box; then "and N more: keep typing". */
const MAX = 8;

type Suggestion = { label: string; count: number; children: number; note?: string };

function flat(nodes: LabelNode[]): LabelNode[] {
  return nodes.flatMap((n) => [n, ...flat(n.children)]);
}

/** The labels to suggest for `text`: with a "/", the next level under what is typed ("Lab A/" →
 * Lab A's teams); without one, every label containing the text, those starting with it first. */
export function suggestLabels(nodes: LabelNode[], text: string): { list: Suggestion[]; more: number } {
  const t = text.toLowerCase();
  const all = flat(nodes);
  let found: LabelNode[];
  const cut = t.lastIndexOf("/");
  if (cut >= 0) {
    const parent = t.slice(0, cut);
    const rest = t.slice(cut + 1);
    const under = all.find((n) => n.label.toLowerCase() === parent);
    found = (under?.children ?? []).filter((n) => n.name.toLowerCase().includes(rest));
    found.sort((a, b) => Number(!a.name.toLowerCase().startsWith(rest)) - Number(!b.name.toLowerCase().startsWith(rest)) || a.name.localeCompare(b.name));
  } else if (!t) {
    found = [...nodes];
  } else {
    found = all.filter((n) => n.label.toLowerCase().includes(t));
    const rank = (n: LabelNode) => (n.name.toLowerCase().startsWith(t) ? 0 : n.label.toLowerCase().startsWith(t) ? 1 : 2);
    found.sort((a, b) => rank(a) - rank(b) || b.count - a.count || a.label.localeCompare(b.label));
  }
  return { list: found.slice(0, MAX).map((n) => ({ label: n.label, count: n.count, children: n.children.length })), more: Math.max(0, found.length - MAX) };
}

/** The labels used most (the "Used most" list of a picker). */
export function usedMost(nodes: LabelNode[], n = 5): string[] {
  return flat(nodes)
    .filter((x) => x.count > 0)
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
    .slice(0, n)
    .map((x) => x.label);
}

/** Where a new label goes: "under Lab A › Qubit team", or "at the top level". */
export function whereItGoes(label: string): string {
  const cut = label.lastIndexOf("/");
  return cut > 0 ? `under ${labelPath(label.slice(0, cut))}` : "at the top level";
}

/**
 * A text box for a label's whole path ("Lab A/Qubit team/Alice") with suggestions under it, never
 * a long list: the next level of what is typed, at most 8. ↑/↓ choose a suggestion, Tab or →
 * (at the end) go into it ("Lab A/"), Enter takes it.
 *
 * `onPick` (a picker): Enter or a click takes the chosen label, or the typed one (a new label).
 * Without `onPick` (a dialog's name box): taking a suggestion types it in, to go on from there;
 * Enter with no suggestion chosen submits the form.
 */
export function LabelPathInput({
  nodes,
  value,
  onChange,
  onPick,
  placeholder,
  label,
  first,
  autoFocus = true,
  inputRef,
}: {
  nodes: LabelNode[];
  value: string;
  onChange: (v: string) => void;
  onPick?: (label: string) => void;
  placeholder?: string;
  label: string;
  /** shown first while nothing is typed (a picker's "Used most", the computer's user) */
  first?: { label: string; note?: string }[];
  autoFocus?: boolean;
  inputRef?: Ref<HTMLInputElement>;
}) {
  const id = useId();
  const [active, setActive] = useState(-1);
  const { list, more } = useMemo(() => suggestLabels(nodes, value.trimStart()), [nodes, value]);
  const known = useMemo(() => new Set(flat(nodes).map((n) => n.label)), [nodes]);
  const typed = value.trim().replace(/\/+$/, "");
  const firstShown = !value && first?.length ? first.filter((f, i, a) => a.findIndex((x) => x.label === f.label) === i) : [];
  const all: Suggestion[] = [
    ...firstShown.map((f) => ({ label: f.label, count: -1, children: 0, note: f.note })),
    ...list.filter((s) => !firstShown.some((f) => f.label === s.label)),
  ];
  const options = all.slice(0, MAX);
  const hiddenMore = more + all.length - options.length;
  const isNew = !!onPick && !!typed && !known.has(typed) && !/(^\/|\/\/)/.test(typed);
  const count = options.length + (isNew ? 1 : 0);
  const take = (s: Suggestion | "new") => {
    if (s === "new") onPick?.(typed);
    else if (onPick) onPick(s.label);
    else onChange(s.label + "/");
    setActive(-1);
  };
  const deeper = (s: Suggestion) => {
    onChange(s.label + "/");
    setActive(-1);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" && count) setActive((a) => (a + 1) % count);
    else if (e.key === "ArrowUp" && count) setActive((a) => (a <= 0 ? count - 1 : a - 1));
    else if ((e.key === "Tab" && !e.shiftKey) || (e.key === "ArrowRight" && e.currentTarget.selectionStart === value.length)) {
      const s = options[active >= 0 ? active : 0];
      if (!s || active >= options.length || (e.key === "Tab" && !value && active < 0)) return;
      deeper(s);
    } else if (e.key === "Enter") {
      if (active >= 0 && active < options.length) take(options[active]);
      else if (active === options.length && isNew) take("new");
      else if (onPick) {
        e.preventDefault(); // no keypress: it would click the button the focus goes back to
        if (typed) onPick(typed);
        return;
      } else return; // the dialog's form submits
    } else return;
    e.preventDefault();
  };
  const optionId = (i: number) => `${id}-${i}`;
  return (
    <div className="label-path">
      <input
        ref={inputRef}
        autoFocus={autoFocus}
        value={value}
        placeholder={placeholder}
        aria-label={label}
        role="combobox"
        aria-expanded={count > 0}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? optionId(active) : undefined}
        onChange={(e) => {
          onChange(e.target.value);
          setActive(-1);
        }}
        onKeyDown={onKeyDown}
      />
      {count > 0 && (
        <ul className="label-path-list" id={`${id}-list`} role="listbox" aria-label={`${label}: suggestions`}>
          {firstShown.length > 0 && (
            <li className="label-path-heading muted small" role="presentation">
              Used most
            </li>
          )}
          {options.map((s, i) => (
            <li
              key={s.label}
              id={optionId(i)}
              role="option"
              aria-selected={i === active}
              className={(i === active ? "active" : "") + (i === firstShown.length && firstShown.length ? " after-first" : "")}
              onMouseDown={(e) => e.preventDefault()} // keep the focus in the box
              onClick={() => take(s)}
              title={labelPath(s.label)}
            >
              <span className="label-path-name">
                {s.label.includes("/") && <span className="muted">{labelPath(shortLabel(s.label.slice(0, s.label.lastIndexOf("/")), 36))} › </span>}
                {shortLabel(s.label.slice(s.label.lastIndexOf("/") + 1), 48)}
                {s.note && <span className="muted small"> ({s.note})</span>}
              </span>
              {s.count >= 0 && <span className="count">{s.count}</span>}
              {s.children > 0 && (
                <button
                  type="button"
                  tabIndex={-1}
                  className="link label-path-in"
                  aria-label={`Into ${s.label}`}
                  title={`The labels in ${labelPath(s.label)} (Tab)`}
                  onClick={(e) => {
                    e.stopPropagation();
                    deeper(s);
                  }}
                >
                  ›
                </button>
              )}
            </li>
          ))}
          {isNew && (
            <li id={optionId(options.length)} role="option" aria-selected={active === options.length} className={"label-path-new" + (active === options.length ? " active" : "")} onMouseDown={(e) => e.preventDefault()} onClick={() => take("new")}>
              New: <strong>{shortLabel(typed, 60)}</strong> <span className="muted small">({whereItGoes(typed)})</span>
            </li>
          )}
          {hiddenMore > 0 && (
            <li className="label-path-more muted small" role="presentation">
              and {hiddenMore} more: keep typing
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
