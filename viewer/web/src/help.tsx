// Links into the documentation. The viewer serves the built docs site at /docs/ (offline).

/** URL of a documentation page, e.g. docsUrl("styles/settings.html", "frame"). */
export function docsUrl(page = "index.html", anchor?: string): string {
  return `/docs/${page}${anchor ? `#${anchor}` : ""}`;
}

/** A small "?" that opens a documentation page in a new tab. */
export function HelpLink({ page, anchor, topic }: { page: string; anchor?: string; topic: string }) {
  return (
    <a className="help-link" href={docsUrl(page, anchor)} target="_blank" rel="noopener" title={`Help: ${topic}`} aria-label={`Help: ${topic}`}>
      ?
    </a>
  );
}
