// Small inline icons (16 px, drawn with currentColor so they follow the theme), for the icon
// buttons of Explore and other compact toolbars. Every icon button also has an aria-label and a
// tooltip with its name (and key), so the icon is never the only way to know what it does.

import type { ReactNode } from "react";

export type IconName =
  | "reset" | "limits" | "cuts" | "download" | "folder" | "info" | "more" | "link" | "side" | "stacked"
  | "gear" | "copy" | "help" | "swap" | "close" | "files";

const PATHS: Record<IconName, ReactNode> = {
  reset: (
    <>
      <path d="M3 8a5 5 0 1 0 1.5-3.6" />
      <path d="M3 2.5v2.5h2.5" />
    </>
  ),
  limits: <path d="M2 8h12M2 8l2.5-2.5M2 8l2.5 2.5M14 8l-2.5-2.5M14 8l-2.5 2.5" />,
  cuts: (
    <>
      <rect x="2" y="5" width="8.5" height="9" />
      <path d="M2 2.8h8.5M13 5v9" />
    </>
  ),
  download: <path d="M8 2v8M4.5 7 8 10.5 11.5 7M2.5 13.5h11" />,
  folder: <path d="M1.8 3.5h4l1.5 1.5h6.9v8H1.8z" />,
  info: (
    <>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M8 7v4.2M8 4.7v.1" strokeLinecap="round" />
    </>
  ),
  more: (
    <>
      <circle cx="3" cy="8" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="8" cy="8" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="13" cy="8" r="1.3" fill="currentColor" stroke="none" />
    </>
  ),
  link: (
    <>
      <path d="M6.5 9.5a2.5 2.5 0 0 0 3.5 0l2.5-2.5a2.5 2.5 0 0 0-3.5-3.5l-.8.8" />
      <path d="M9.5 6.5a2.5 2.5 0 0 0-3.5 0L3.5 9a2.5 2.5 0 0 0 3.5 3.5l.8-.8" />
    </>
  ),
  side: (
    <>
      <rect x="1.5" y="2.5" width="5.5" height="11" rx="1" />
      <rect x="9" y="2.5" width="5.5" height="11" rx="1" />
    </>
  ),
  stacked: (
    <>
      <rect x="2" y="1.5" width="12" height="5.5" rx="1" />
      <rect x="2" y="9" width="12" height="5.5" rx="1" />
    </>
  ),
  gear: (
    <>
      <circle cx="8" cy="8" r="2.3" />
      <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4" />
    </>
  ),
  copy: (
    <>
      <rect x="5" y="5" width="8" height="9" rx="1.5" />
      <path d="M3 11V3.5A1.5 1.5 0 0 1 4.5 2H10" />
    </>
  ),
  help: (
    <>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M6.2 6.3a1.9 1.9 0 1 1 2.6 1.8c-.6.3-.8.7-.8 1.3M8 11.6v.1" strokeLinecap="round" />
    </>
  ),
  swap: <path d="M3 5h9.5M10 2.5 12.5 5 10 7.5M13 11H3.5M6 8.5 3.5 11 6 13.5" />,
  close: <path d="M4 4l8 8M12 4l-8 8" />,
  files: (
    <>
      <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" />
      <path d="M5.5 2.5v11" />
    </>
  ),
};

export function Icon({ name }: { name: IconName }) {
  return (
    <svg className="icon-svg" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" aria-hidden="true">
      {PATHS[name]}
    </svg>
  );
}
