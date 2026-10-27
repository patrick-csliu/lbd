import { useEffect, useState } from "react";
import { api, baseName, StyleFileInfo } from "./api";
import { useToast } from "./toast";
import { useDiskVersion, useLatestVersion } from "./watch";

interface Props {
  path: string;
  previewPath: string | null;
  onImported: () => void | Promise<void>;
  onError: (msg: string) => void;
}

/** A .lbd.json style file from a folder: preview it on an open data file, or import it as a preset. */
export default function StyleFileView({ path, previewPath, onImported, onError }: Props) {
  const toast = useToast();
  const [info, setInfo] = useState<StyleFileInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [showJson, setShowJson] = useState(false);
  // Read again when the style file changes on disk (while it is gone, the last one stays).
  const disk = useDiskVersion("file", path);
  const version = useLatestVersion(disk.version);

  useEffect(() => {
    api
      .styleFile(path)
      .then((i) => (setInfo(i), setError(null)))
      .catch((e) => setError((e as Error).message));
  }, [path, version]);

  useEffect(() => {
    if (!previewPath) return;
    let cancelled = false;
    let made: string | null = null;
    api
      .render(previewPath, null, null, null, path)
      .then((r) => {
        made = URL.createObjectURL(new Blob([r.svg], { type: "image/svg+xml" }));
        if (!cancelled) (setPreview(made), setPreviewError(null));
      })
      .catch((e) => !cancelled && setPreviewError((e as Error).message));
    return () => {
      cancelled = true;
      if (made) URL.revokeObjectURL(made);
    };
  }, [path, previewPath, version]);

  const importIt = async () => {
    if (!info) return;
    const name = window.prompt("Import as a style preset named:", info.name)?.trim();
    if (!name) return;
    try {
      await api.importStyle(name, info.resolved);
      toast(`Imported "${name}". It is now on the Styles page and in every Preset list.`);
      await onImported();
    } catch (e) {
      onError((e as Error).message);
    }
  };

  if (error) {
    return (
      <div className="file-view">
        <div className="error-box">
          <strong>Can't read this style file.</strong> {error}
        </div>
      </div>
    );
  }
  if (!info) return <div className="file-view muted pad">Loading…</div>;
  const fig = info.resolved.figure as { width_mm: number; height_mm: number; dpi: number; font: { family: string; size_pt: number } };

  return (
    <div className="file-view">
      <div className="file-head">
        <div>
          <h1>Style: {info.name}</h1>
          <div className="muted small path" title={info.path}>
            {info.path}
          </div>
        </div>
        <div className="actions">
          <button className="primary" onClick={importIt}>
            Import as preset
          </button>
          <button onClick={() => api.reveal(path).catch((e) => onError(e.message))}>Show in folder</button>
        </div>
      </div>
      {info.description && <p>{info.description}</p>}
      {info.warnings.length > 0 && (
        <ul className="warn-box" aria-label="Notes about this style file">
          {info.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      <dl className="props">
        <dt>Figure</dt>
        <dd>
          {fig.width_mm} × {fig.height_mm} mm, {fig.dpi} dpi
        </dd>
        <dt>Font</dt>
        <dd>
          {fig.font.family}, {fig.font.size_pt} pt
        </dd>
      </dl>

      <h3>Preview</h3>
      {!previewPath && <p className="muted small">Open a data file in another tab to preview this style with it.</p>}
      {previewPath && <p className="muted small">With {baseName(previewPath)}</p>}
      {previewError && <div className="error-box">{previewError}</div>}
      {preview && (
        <div className="figure fit">
          <img src={preview} alt={`Preview of the style ${info.name}`} />
        </div>
      )}

      <div className="info-toggle">
        <button className="link" onClick={() => setShowJson((s) => !s)} aria-expanded={showJson}>
          {showJson ? "▾" : "▸"} All settings
        </button>
      </div>
      {showJson && <pre className="code-block">{JSON.stringify(info.resolved, null, 2)}</pre>}
    </div>
  );
}
