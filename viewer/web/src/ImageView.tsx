import { useEffect, useState } from "react";
import { api, formatBytes, ImageInfo } from "./api";

const MM_TO_PX = 96 / 25.4;

/** View-only display of an image file with its metadata. */
export default function ImageView({ path, onError }: { path: string; onError: (msg: string) => void }) {
  const [info, setInfo] = useState<ImageInfo | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState("fit");

  useEffect(() => {
    let cancelled = false;
    let made: string | null = null;
    api
      .imageInfo(path)
      .then((i) => !cancelled && setInfo(i))
      .catch((e) => !cancelled && setError((e as Error).message));
    api
      .imageUrl(path)
      .then((u) => {
        made = u;
        if (!cancelled) setUrl(u);
      })
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => {
      cancelled = true;
      if (made) URL.revokeObjectURL(made);
    };
  }, [path]);

  if (error) {
    return (
      <div className="file-view">
        <div className="error-box">
          <strong>Can't show this image.</strong> {error}
        </div>
      </div>
    );
  }

  // 100 % = printed size when the image stores its dpi, else one image pixel per screen pixel
  const naturalWidth = info?.size_mm ? info.size_mm[0] * MM_TO_PX : info?.width ?? undefined;
  const style = zoom === "fit" || !naturalWidth ? undefined : { width: naturalWidth * Number(zoom), maxWidth: "none" };

  return (
    <div className="file-view">
      <div className="file-head">
        <div>
          <h1>{info?.name ?? ""}</h1>
          <div className="muted small path" title={path}>
            {path}
          </div>
        </div>
        <div className="actions">
          <label>
            Zoom{" "}
            <select value={zoom} onChange={(e) => setZoom(e.target.value)}>
              <option value="fit">Fit</option>
              <option value="1">{info?.size_mm ? "100% (print size)" : "100%"}</option>
              <option value="2">200%</option>
            </select>
          </label>
          <button onClick={() => api.reveal(path).catch((e) => onError(e.message))}>Show in folder</button>
        </div>
      </div>

      <div className={"figure image" + (zoom === "fit" ? " fit" : "")}>
        {url ? <img src={url} alt={info?.name ?? "image"} style={style} /> : <span className="muted small">Loading…</span>}
      </div>
      <p className="muted small">View only. Images are never changed by LBD Viewer.</p>

      {info && (
        <div className="details">
          {info.note && <p className="note">{info.note}</p>}
          <dl className="props">
            <dt>Format</dt>
            <dd>{info.format ?? "—"}</dd>
            <dt>Pixels</dt>
            <dd>{info.width && info.height ? `${info.width} × ${info.height}` : "—"}</dd>
            <dt>Printed size</dt>
            <dd>{info.size_mm ? `${info.size_mm[0]} × ${info.size_mm[1]} mm` : "not stored in the file"}</dd>
            <dt>Resolution</dt>
            <dd>{info.dpi ? `${info.dpi[0]} × ${info.dpi[1]} dpi` : "—"}</dd>
            <dt>Colour</dt>
            <dd>{info.mode ? `${info.mode}${info.bit_depth ? `, ${info.bit_depth} bit` : ""}` : "—"}</dd>
            {info.frames > 1 && (
              <>
                <dt>Frames</dt>
                <dd>{info.frames} (the first is shown)</dd>
              </>
            )}
            <dt>File size</dt>
            <dd>{formatBytes(info.file_size)}</dd>
            <dt>Modified</dt>
            <dd>{info.modified}</dd>
          </dl>
          {Object.keys(info.text).length > 0 && (
            <>
              <h3>Embedded information</h3>
              <dl className="props">
                {Object.entries(info.text).map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt>{k}</dt>
                    <dd className="meta-val">{v}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
        </div>
      )}
    </div>
  );
}
