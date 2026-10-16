"""Images in the folder panel: metadata and display (view only, never modified)."""

from __future__ import annotations

import datetime as _dt
import io
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".svg"}
BROWSER_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
                 ".webp": "image/webp", ".svg": "image/svg+xml"}
CONVERTED = {".bmp", ".tif", ".tiff"}      # browsers can't show these; sent as PNG
SVG_MAX_BYTES = 20_000_000
_BIT_DEPTH = {"1": 1, "L": 8, "P": 8, "RGB": 8, "RGBA": 8, "CMYK": 8, "YCbCr": 8, "LA": 8, "PA": 8,
              "I;16": 16, "I;16B": 16, "I;16L": 16, "I": 32, "F": 32}
_EXIF_TAGS = {271: "Make", 272: "Model", 305: "Software", 306: "DateTime", 270: "ImageDescription", 315: "Artist"}


class ImageError(Exception):
    """The file can't be shown as an image (unreadable, corrupt, unsupported or too large)."""


def _add_note(out: Dict[str, Any], text: str) -> None:
    out["note"] = f"{out['note']} {text}" if out.get("note") else text


def is_image(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_SUFFIXES


def info(path: Path) -> Dict[str, Any]:
    st = path.stat()
    out: Dict[str, Any] = {
        "path": str(path), "name": path.name, "file_size": st.st_size,
        "modified": _dt.datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds"),
        "format": None, "width": None, "height": None, "mode": None, "bit_depth": None, "frames": 1,
        "dpi": None, "size_mm": None, "text": {}, "note": None,
    }
    if path.suffix.lower() == ".svg":
        out.update(_svg_info(path))
        return out
    from PIL import Image

    try:
        with Image.open(path) as img:
            out["format"] = img.format
            out["width"], out["height"] = img.size
            out["mode"] = img.mode
            out["bit_depth"] = _BIT_DEPTH.get(img.mode)
            out["frames"] = int(getattr(img, "n_frames", 1))
            if out["frames"] > 1:
                _add_note(out, f"{out['frames']} frames; the first one is shown.")
            dpi = img.info.get("dpi")
            if dpi:
                try:
                    dx, dy = float(dpi[0]), float(dpi[1])
                except (TypeError, ValueError, IndexError):
                    dx = dy = 0.0
                if dx > 0 and dy > 0:
                    out["dpi"] = [round(dx, 2), round(dy, 2)]
                    out["size_mm"] = [round(img.size[0] / dx * 25.4, 2), round(img.size[1] / dy * 25.4, 2)]
                else:
                    _add_note(out, f"The stored resolution {dpi!r} is invalid, so the printed size is unknown.")
            text = {}
            for k, v in (getattr(img, "text", None) or {}).items():   # PNG text chunks
                text[str(k)] = str(v)[:2000]
            try:
                exif = img.getexif()
                for tag, name in _EXIF_TAGS.items():
                    if tag in exif:
                        text[name] = str(exif[tag])[:2000]
            except Exception:  # noqa: BLE001 - broken EXIF must not hide the image
                _add_note(out, "The EXIF data (camera/software tags) is damaged and was not read.")
            out["text"] = text
            if img.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
                _add_note(out, "High bit-depth image: shown with its contrast stretched to the full range.")
    except Image.DecompressionBombError:
        raise ImageError(f"{path.name} is too large to open safely") from None
    except OSError as e:
        raise ImageError(f"{path.name} can't be read as an image: {e}") from None
    return out


def _svg_info(path: Path) -> Dict[str, Any]:
    if path.stat().st_size > SVG_MAX_BYTES:
        raise ImageError(f"{path.name} is too large to inspect")
    out: Dict[str, Any] = {"format": "SVG", "note": None}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise ImageError(f"{path.name} is not a valid SVG: {e}") from None
    w, h, vb = root.get("width"), root.get("height"), root.get("viewBox")
    out["text"] = {k: v for k, v in (("width", w), ("height", h), ("viewBox", vb)) if v}
    mm_w, mm_h = _svg_length_mm(w), _svg_length_mm(h)
    if mm_w and mm_h:
        out["size_mm"] = [round(mm_w, 2), round(mm_h, 2)]
    elif (w and mm_w is None) or (h and mm_h is None):
        _add_note(out, f"The size {w!r} x {h!r} uses units LBD can't convert (e.g. % or em), so the printed "
                       "size is unknown.")
    if vb:
        parts = vb.replace(",", " ").split()
        try:
            if len(parts) != 4:
                raise ValueError
            out["width"], out["height"] = round(float(parts[2]), 2), round(float(parts[3]), 2)
        except ValueError:
            _add_note(out, f"The viewBox {vb!r} is malformed.")
    # matplotlib writes the creator/title into <metadata> (RDF/Dublin Core)
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag in ("title", "creator", "date", "description") and el.text and el.text.strip():
            out["text"].setdefault(tag.capitalize(), el.text.strip()[:2000])
        if tag == "creator":
            for sub in el.iter():
                if sub.tag.split("}")[-1] == "title" and sub.text:
                    out["text"]["Creator"] = sub.text.strip()[:2000]
    return out


def _svg_length_mm(v: Optional[str]) -> Optional[float]:
    if not v:
        return None
    units = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72, "pc": 25.4 / 6, "px": 25.4 / 96, "": 25.4 / 96}
    v = v.strip()
    for u in ("mm", "cm", "in", "pt", "pc", "px", ""):
        if v.endswith(u):
            try:
                return float(v[: len(v) - len(u)] if u else v) * units[u]
            except ValueError:
                return None
    return None


def browser_bytes(path: Path) -> Tuple[bytes, str]:
    """Bytes a browser can show, and their media type. TIFF/BMP are converted to PNG."""
    suffix = path.suffix.lower()
    if suffix in BROWSER_TYPES:
        return path.read_bytes(), BROWSER_TYPES[suffix]
    if suffix not in CONVERTED:
        raise ImageError(f"{path.name}: not a supported image type")
    from PIL import Image

    try:
        with Image.open(path) as img:
            img.seek(0)
            if img.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
                arr = np.asarray(img, dtype=float)
                finite = arr[np.isfinite(arr)]
                lo, hi = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 0.0)
                arr = np.nan_to_num((arr - lo) / (hi - lo) * 255 if hi > lo else np.zeros_like(arr))
                img = Image.fromarray(arr.astype(np.uint8))
            elif img.mode not in ("RGB", "RGBA", "L", "LA"):
                img = img.convert("RGBA")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
    except Image.DecompressionBombError:
        raise ImageError(f"{path.name} is too large to open safely") from None
    except OSError as e:
        raise ImageError(f"{path.name} can't be read as an image: {e}") from None
    return buf.getvalue(), "image/png"
