// Copy picture (plan 5, E2): canvases on the page put together into one picture, as laid out on
// screen, and that picture put on the clipboard as PNG (or saved, where the browser can't).

/** Canvases drawn into one picture at their places on the page (`frame`: the area taken), at
 *  the screen's pixel density, on `background`. */
export function compose(canvases: HTMLCanvasElement[], frame: DOMRect, background: string): HTMLCanvasElement {
  const dpr = window.devicePixelRatio || 1;
  const out = document.createElement("canvas");
  out.width = Math.max(1, Math.round(frame.width * dpr));
  out.height = Math.max(1, Math.round(frame.height * dpr));
  const g = out.getContext("2d")!;
  g.fillStyle = background;
  g.fillRect(0, 0, out.width, out.height);
  for (const c of canvases) {
    const r = c.getBoundingClientRect();
    if (!c.width || !c.height || !r.width || !r.height) continue;
    g.drawImage(c, (r.left - frame.left) * dpr, (r.top - frame.top) * dpr, r.width * dpr, r.height * dpr);
  }
  return out;
}

/** The page's background colour (what is behind a picture with transparent parts). */
export function pageBackground(el: Element): string {
  for (let e: Element | null = el; e; e = e.parentElement) {
    const c = getComputedStyle(e).backgroundColor;
    if (c && c !== "transparent" && !/rgba\(.*,\s*0\)$/.test(c)) return c;
  }
  return "#ffffff";
}

/** The smallest box around these elements' boxes. */
export function around(els: Element[]): DOMRect {
  const rs = els.map((e) => e.getBoundingClientRect()).filter((r) => r.width && r.height);
  const left = Math.min(...rs.map((r) => r.left)), top = Math.min(...rs.map((r) => r.top));
  const right = Math.max(...rs.map((r) => r.right)), bottom = Math.max(...rs.map((r) => r.bottom));
  return new DOMRect(left, top, right - left, bottom - top);
}

function blob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((ok, fail) => canvas.toBlob((b) => (b ? ok(b) : fail(new Error("the picture couldn't be made"))), "image/png"));
}

/** Put the picture (a canvas, or PNG bytes on their way) on the clipboard. Throws with a
 *  message saying why it couldn't. */
export async function copyPng(picture: HTMLCanvasElement | Promise<Blob>): Promise<void> {
  if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
    throw new Error("this browser can't put pictures on the clipboard; save the picture as PNG instead");
  }
  try {
    // the bytes are passed as a promise: the clipboard is asked for at once, while the click still counts
    const png = picture instanceof HTMLCanvasElement ? blob(picture) : picture;
    await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
  } catch (e) {
    throw new Error(`the picture couldn't be put on the clipboard (${e instanceof Error ? e.message : String(e)}); save it as PNG instead`);
  }
}

/** Save the picture as a PNG file (the browser's download). */
export async function downloadPng(canvas: HTMLCanvasElement, name: string): Promise<void> {
  const url = URL.createObjectURL(await blob(canvas));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export type PictureWhat = "screen" | "plot";
export interface PictureChoice {
  what: PictureWhat;
  all: boolean;
}

const PICTURE_KEY = "lbd.pictureChoice";

/** The picture choices this browser used last (cursors and cuts as on screen, this panel). */
export function pictureChoice(): PictureChoice {
  try {
    return { what: "screen", all: false, ...JSON.parse(localStorage.getItem(PICTURE_KEY) ?? "{}") };
  } catch {
    return { what: "screen", all: false };
  }
}

export function rememberPictureChoice(c: PictureChoice): void {
  try {
    localStorage.setItem(PICTURE_KEY, JSON.stringify(c));
  } catch {
    // only a convenience
  }
}
