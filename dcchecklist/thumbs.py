"""Small, cached preview pictures for the collection grid (works offline)."""
from __future__ import annotations

import re
from functools import lru_cache

from PIL import Image

from .catalog import image_path
from .storage import cache_dir

THUMB_PX = 220          # stored size; the grid scales down from this


def _thumb_path(item_id: str):
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", item_id)
    return cache_dir("thumb") / f"{safe}.png"


def _make(item_id: str) -> Image.Image | None:
    src = image_path(item_id)
    if not src.exists():
        return None
    try:
        with Image.open(src) as im:
            im.load()
            im = im.convert("RGBA")
            # trim the white / transparent frame BrickLink pictures have
            rgb = Image.new("RGB", im.size, (255, 255, 255))
            rgb.paste(im, mask=im.split()[-1])
            box = rgb.convert("L").point(lambda v: 255 if v < 246 else 0).getbbox()
            if box:
                im = im.crop(box)
            im.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
            # white background so the picture looks the same in dark mode
            out = Image.new("RGBA", im.size, (255, 255, 255, 255))
            out.alpha_composite(im)
            return out
    except Exception:
        return None


def thumbnail(item_id: str) -> Image.Image | None:
    """PIL image (max THUMB_PX), created once and kept on disk."""
    tp = _thumb_path(item_id)
    src = image_path(item_id)
    if tp.exists() and (not src.exists() or tp.stat().st_mtime >= src.stat().st_mtime):
        try:
            with Image.open(tp) as im:
                im.load()
                return im.convert("RGBA")
        except Exception:
            pass
    im = _make(item_id)
    if im is not None:
        try:
            im.save(tp, "PNG", optimize=True)
        except OSError:
            pass
    return im


@lru_cache(maxsize=2048)
def scaled(item_id: str, size: int, _stamp: float = 0.0) -> Image.Image | None:
    """Thumbnail fitted into size x size (memory cached)."""
    im = thumbnail(item_id)
    if im is None:
        return None
    im = im.copy()
    im.thumbnail((size, size), Image.LANCZOS)
    return im


def forget(item_id: str | None = None) -> None:
    scaled.cache_clear()
    if item_id:
        try:
            _thumb_path(item_id).unlink()
        except OSError:
            pass
