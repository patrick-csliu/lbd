// The labels of one or several files (star, project, users, tags, comment), and the picker that
// chooses a label: the Library's details and Explore's Labels tab (16.31) use the same editor.

import { RefObject, useEffect, useLayoutEffect, useRef, useState } from "react";
import type React from "react";
import type { LabelChanges, LabelNode, LibraryFacets, LibraryRow } from "./api";
import { LabelChip } from "./LabelChip";
import { LabelPathInput, usedMost } from "./labelPath";
import { useOutsideClose } from "./menu";

/** The labels of one or several files. `compact` (the selected file, beside its preview): one row
 * per kind without a box, the star being in front of the title, the comment one line until it is
 * clicked. */
export function LabelsEditor({ rows, facets, login, onChange, compact = false }: { rows: LibraryRow[]; facets: LibraryFacets | null; login: string; onChange: (c: LabelChanges) => Promise<void> | void; compact?: boolean }) {
  const n = rows.length;
  const [picking, setPicking] = useState<"project" | "users" | "tags" | null>(null);
  const opener = useRef<HTMLElement | null>(null); // the Set / + Add button of the open picker
  const togglePicker = (which: "project" | "users" | "tags", e: React.MouseEvent<HTMLElement>) => {
    opener.current = e.currentTarget;
    setPicking(picking === which ? null : which);
  };
  const comments = [...new Set(rows.map((r) => r.comment))];
  const [comment, setComment] = useState(comments.length === 1 ? comments[0] : "");
  const key = rows.map((r) => r.path).join("|") + "|" + comments.join("|");
  useEffect(() => setComment(comments.length === 1 ? comments[0] : ""), [key]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!n) return null;
  const allStarred = rows.every((r) => r.star);
  const projects = [...new Set(rows.map((r) => r.project ?? ""))];
  const counts = (key: "users" | "tags") => {
    const m = new Map<string, number>();
    for (const r of rows) for (const l of r[key]) m.set(l, (m.get(l) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  };
  const saveComment = () => {
    if (comments.length === 1 ? comment !== comments[0] : comment.trim()) onChange({ comment });
  };
  const chips = (key: "users" | "tags") => (
    <div className="label-chips" aria-label={key === "users" ? "Users" : "Tags"}>
      {counts(key).map(([l, k]) => (
        <LabelChip
          key={l}
          label={l}
          extra={k < n ? `(${k} of ${n})` : undefined}
          removeLabel={`Remove ${key === "users" ? "user" : "tag"} ${l}`}
          onRemove={() => onChange(key === "users" ? { remove_users: [l] } : { remove_tags: [l] })}
        />
      ))}
      <button className="chip add-chip" onClick={(e) => togglePicker(key, e)} aria-expanded={picking === key} aria-label={key === "users" ? "Add a user" : "Add a tag"}>
        + Add
      </button>
      {picking === key && (
        <LabelPicker
          nodes={(key === "users" ? facets?.users : facets?.tags) ?? []}
          first={key === "users" ? login : undefined}
          placeholder={key === "users" ? "A user (group/sub-group/name), or pick one" : "A tag (nested with /), or pick one"}
          onPick={(l) => {
            setPicking(null);
            onChange(key === "users" ? { add_users: [l] } : { add_tags: [l] });
          }}
          onClose={() => setPicking(null)}
          opener={opener}
        />
      )}
    </div>
  );
  return (
    <div className={compact ? "library-labels-rows" : "library-labels-editor"} aria-label="Labels">
      {!compact && <h3>Labels{n > 1 ? ` of ${n} files` : ""}</h3>}
      {!compact && (
        <div className="label-row">
          <button className={"star-button" + (allStarred ? " on" : "")} aria-pressed={allStarred} onClick={() => onChange({ star: !allStarred })} title="Star (Space in the list)">
            {allStarred ? "★ Starred" : "☆ Star"}
          </button>
        </div>
      )}
      <div className="label-row">
        <span className="label-name">Project</span>
        <div className="label-chips" aria-label="Project">
          {projects.length === 1 && projects[0] ? (
            <LabelChip label={projects[0]} removeLabel="Remove the project" onRemove={() => onChange({ project: "" })} />
          ) : projects.length > 1 ? (
            <span className="muted small">several projects</span>
          ) : null}
          <button className="chip add-chip" onClick={(e) => togglePicker("project", e)} aria-expanded={picking === "project"} aria-label="Set the project">
            {projects.length === 1 && projects[0] ? "Change" : "Set"}
          </button>
          {picking === "project" && (
            <LabelPicker
              nodes={facets?.projects ?? []}
              placeholder="A project (nested with /), or pick one"
              onPick={(l) => {
                setPicking(null);
                onChange({ project: l });
              }}
              onClose={() => setPicking(null)}
              opener={opener}
            />
          )}
        </div>
      </div>
      <div className="label-row">
        <span className="label-name">Users</span>
        {chips("users")}
      </div>
      <div className="label-row">
        <span className="label-name">Tags</span>
        {chips("tags")}
      </div>
      <div className="label-row">
        <span className="label-name">Comment</span>
        <textarea
          aria-label="Comment"
          value={comment}
          placeholder={comments.length > 1 ? "(different comments; typing here replaces them all)" : compact ? "Add a comment…" : "Notes about this data (saved when you leave the box)"}
          title="Saved when you leave the box (Ctrl+Enter)"
          onChange={(e) => setComment(e.target.value)}
          onBlur={saveComment}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) (e.target as HTMLTextAreaElement).blur();
          }}
          rows={compact ? 1 : 3}
        />
      </div>
    </div>
  );
}

export function LabelPicker({ nodes, first, placeholder, onPick, onClose, opener }: { nodes: LabelNode[]; first?: string; placeholder: string; onPick: (label: string) => void; onClose: () => void; opener?: RefObject<HTMLElement | null> }) {
  const ref = useRef<HTMLDivElement>(null);
  const onKeyDown = useOutsideClose(ref, onClose, opener);
  const [text, setText] = useState("");
  const most = [...(first ? [{ label: first, note: "this computer's user" }] : []), ...usedMost(nodes).map((l) => ({ label: l }))];
  // Inside the pane: moved left until its right edge meets the pane's, however near the edge it opened.
  useLayoutEffect(() => {
    const fit = () => {
      const box = ref.current;
      if (!box) return;
      const pane = box.closest<HTMLElement>(".library-detail, .inspector-body");
      const limit = pane?.getBoundingClientRect() ?? { left: 0, right: window.innerWidth };
      const margin = 8;
      const room = Math.min(limit.right, window.innerWidth) - limit.left - 2 * margin;
      box.style.maxWidth = `${room}px`;
      box.style.left = "0px";
      if (pane) pane.scrollLeft = 0; // (the box's input took the focus: the pane may have scrolled to it)
      const at = box.getBoundingClientRect();
      const over = at.right - (Math.min(limit.right, window.innerWidth) - margin);
      const shift = Math.min(Math.max(over, 0), at.left - limit.left - margin);
      box.style.left = `${-Math.max(shift, 0)}px`;
      // up or down, by the room left in the window; the list scrolls inside it when it is short
      box.style.top = "";
      box.style.bottom = "";
      box.style.maxHeight = "";
      const parent = (box.offsetParent as HTMLElement | null)?.getBoundingClientRect() ?? at;
      const below = window.innerHeight - parent.bottom - margin, above = parent.top - margin;
      if (box.getBoundingClientRect().height > below && above > below) {
        box.style.top = "auto";
        box.style.bottom = "100%";
      }
      box.style.maxHeight = `${Math.max(Math.max(below, above), 120)}px`;
      box.style.overflow = "auto";
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);
  return (
    <div ref={ref} className="label-picker" role="dialog" aria-label="Pick a label" onKeyDown={onKeyDown}>
      <LabelPathInput nodes={nodes} value={text} onChange={setText} onPick={onPick} placeholder={placeholder} label="Label" first={most} />
      <div className="label-picker-foot">
        <span className="muted small">Type a path (Lab A/…); Tab goes into a group</span>
        <button className="link small" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}

