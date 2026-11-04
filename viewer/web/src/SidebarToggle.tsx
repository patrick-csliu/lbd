/**
 * The button that hides or shows a sidebar (the Library's folders, dates and labels; the Files
 * sidebar of Explore and Figure). It looks like a sidebar control, not like a filter: a window with
 * a panel on its left, and an arrow. While the sidebar is open the button is inside it (‹: hide
 * it); while it is closed, at the edge where it was (›: show it).
 */

export function SidebarIcon() {
  return (
    <svg className="sidebar-icon" width="14" height="12" viewBox="0 0 14 12" aria-hidden="true">
      <rect x="0.5" y="0.5" width="13" height="11" rx="1.5" fill="none" stroke="currentColor" />
      <rect x="0.5" y="0.5" width="4.5" height="11" rx="1.5" fill="currentColor" />
    </svg>
  );
}

export function SidebarToggle({
  open,
  onToggle,
  what,
  count,
  className = "",
}: {
  /** the sidebar is shown (the button hides it) */
  open: boolean;
  onToggle: () => void;
  /** what the sidebar holds, for the tooltip: "folders, dates, labels" */
  what: string;
  /** filters in use while it is hidden (a badge, so they aren't forgotten) */
  count?: number;
  className?: string;
}) {
  const label = open ? "Hide the sidebar" : "Show the sidebar";
  return (
    <button
      className={"sidebar-toggle " + (open ? "is-open " : "is-closed ") + className}
      aria-label={label}
      aria-expanded={open}
      title={`${label} (${what})`}
      onClick={onToggle}
    >
      <SidebarIcon />
      <span className="sidebar-arrow" aria-hidden="true">
        {open ? "‹" : "›"}
      </span>
      {!open && count ? <span className="count">{count}</span> : null}
    </button>
  );
}
