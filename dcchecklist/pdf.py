"""Checklist PDF: all figures in a grid, each with a tick box."""
from __future__ import annotations

import datetime as dt
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, letter
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .catalog import Figure, image_path

ACCENT = colors.HexColor("#0B5CAD")      # DC-ish blue
ACCENT_DARK = colors.HexColor("#0A2540")
GOLD = colors.HexColor("#F2C230")
GRID = colors.HexColor("#C9D1DB")
MUTED = colors.HexColor("#6B7785")
TEXT = colors.HexColor("#1B2430")
OWNED_FILL = colors.HexColor("#EAF4EA")


@dataclass
class PdfOptions:
    title: str = "LEGO DC Super Heroes – Minifiguren-Checkliste"
    paper: str = "A4"                 # "A4" | "Letter"
    orientation: str = "portrait"     # "portrait" | "landscape"
    columns: int = 6
    show_id: bool = True
    show_name: bool = True
    show_year: bool = True
    fillable: bool = True             # clickable AcroForm tick boxes
    precheck_owned: bool = True
    new_page_per_section: bool = False


def _pagesize(opts: PdfOptions):
    size = A4 if opts.paper.upper() == "A4" else letter
    return landscape(size) if opts.orientation == "landscape" else size


def _safe(text: str) -> str:
    """The built-in PDF fonts only know the Windows-1252 characters."""
    return (text or "").encode("cp1252", "replace").decode("cp1252")


def _wrap(text: str, font: str, size: float, width: float, max_lines: int) -> list[str]:
    words = _safe(text).split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if stringWidth(trial, font, size) <= width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        cur = w
        while stringWidth(cur, font, size) > width and len(cur) > 1:
            # very long single word: hard cut
            cut = len(cur)
            while cut > 1 and stringWidth(cur[:cut], font, size) > width:
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]
        if len(lines) >= max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    used = " ".join(lines)
    if len(used) < len(" ".join(words)) and lines:
        last = lines[-1]
        while last and stringWidth(last + "…", font, size) > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _prepared_image(item_id: str, max_px: int = 360) -> ImageReader | None:
    path = image_path(item_id)
    if not path.exists():
        return None
    try:
        with Image.open(path) as im:
            im.load()
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            # trim white border so figures fill their cell
            gray = im.convert("L").point(lambda v: 255 if v < 248 else 0)
            box = gray.getbbox()
            if box:
                im = im.crop(box)
            im.thumbnail((max_px, max_px), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85, optimize=True)
            buf.seek(0)
            return ImageReader(buf)
    except Exception:
        return None


def _field_name(item_id: str, used: set[str]) -> str:
    base = "fig_" + re.sub(r"[^A-Za-z0-9_]", "_", item_id)
    name, n = base, 2
    while name in used:
        name, n = f"{base}_{n}", n + 1
    used.add(name)
    return name


@dataclass
class _Layout:
    page_w: float
    page_h: float
    margin: float
    usable_w: float
    cell_w: float
    cell_h: float
    pad: float
    img_h: float
    box: float
    id_size: float
    name_size: float
    text_lines: int
    section_h: float
    pages: list


def _compute_layout(sections: list[tuple[str, list[Figure]]], opts: PdfOptions) -> _Layout:
    page_w, page_h = _pagesize(opts)
    margin = 11 * mm
    gap = 2.2 * mm
    cols = max(2, min(10, int(opts.columns)))
    usable_w = page_w - 2 * margin
    cell_w = (usable_w - (cols - 1) * gap) / cols
    pad = max(3.0, cell_w * 0.05)

    # font sizes scale with the cell
    id_size = max(6.0, min(9.0, cell_w / 11))
    name_size = max(5.0, min(7.5, cell_w / 13.5))
    box = max(7.0, min(11.0, cell_w / 7.5))
    text_lines = 0
    text_h = max(box, id_size) + 2          # tick box row (always shown)
    if opts.show_name:
        text_lines = 2
        text_h += text_lines * (name_size + 1.4) + 1
    img_h = cell_w - 2 * pad
    cell_h = pad + img_h + 3 + text_h + pad

    header_first = 30 * mm
    header_other = 11 * mm
    footer_h = 9 * mm
    section_h = 9.5 * mm

    pages: list[list[tuple]] = [[]]
    y = page_h - margin - header_first

    def new_page() -> float:
        pages.append([])
        return page_h - margin - header_other

    bottom = margin + footer_h
    first = True
    for title, figs in sections:
        if not figs:
            continue
        if opts.new_page_per_section and not first and pages[-1]:
            y = new_page()
        first = False
        if y - section_h - cell_h < bottom:
            y = new_page()
        pages[-1].append(("section", title, len(figs), y))
        y -= section_h
        for i in range(0, len(figs), cols):
            if y - cell_h < bottom:
                y = new_page()
                pages[-1].append(("section-cont", title, len(figs), y))
                y -= section_h * 0.75
            for col, fig in enumerate(figs[i:i + cols]):
                x = margin + col * (cell_w + gap)
                pages[-1].append(("cell", fig, x, y - cell_h))
            y -= cell_h + gap
        y -= 2 * mm
    return _Layout(page_w, page_h, margin, usable_w, cell_w, cell_h, pad, img_h, box,
                   id_size, name_size, text_lines, section_h, pages)


def estimate_pages(sections: list[tuple[str, list[Figure]]], opts: PdfOptions) -> int:
    return len(_compute_layout(sections, opts).pages)


def build_pdf(out_path: str | Path, sections: list[tuple[str, list[Figure]]],
              opts: PdfOptions, owned: set[str] | None = None,
              progress: Callable[[float, str], None] | None = None) -> Path:
    owned = owned or set()
    progress = progress or (lambda _f, _t: None)
    out_path = Path(out_path)
    sections = [(t, f) for t, f in sections if f]
    lay = _compute_layout(sections, opts)
    page_w, page_h, margin = lay.page_w, lay.page_h, lay.margin
    pages = lay.pages
    n_pages = len(pages)
    total = sum(len(f) for _s, f in sections)
    when = dt.date.today().strftime("%d.%m.%Y")

    # ---------- drawing pass ----------
    c = canvas.Canvas(str(out_path), pagesize=(page_w, page_h))
    c.setTitle(_safe(opts.title))
    c.setAuthor("DC Minifiguren-Checkliste")
    c.setSubject("Checkliste – Bilder und Daten: BrickLink.com")
    used_names: set[str] = set()
    drawn = 0

    for p_idx, items in enumerate(pages):
        if p_idx == 0:
            _draw_first_header(c, opts, page_w, page_h, margin, total, len(sections), when)
        else:
            _draw_small_header(c, opts, page_w, page_h, margin)
        _draw_footer(c, page_w, margin, p_idx + 1, n_pages, when)

        for it in items:
            kind = it[0]
            if kind in ("section", "section-cont"):
                _, title, count, top = it
                _draw_section(c, title, count, margin, top, lay.usable_w, lay.section_h,
                              cont=(kind == "section-cont"))
                if kind == "section":
                    key = f"s{p_idx}_{int(top)}"
                    c.bookmarkPage(key, fit="XYZ", top=top + 4)
                    c.addOutlineEntry(f"{_safe(title)} ({count})", key, level=0)
            else:
                _, fig, x, y0 = it
                _draw_cell(c, fig, x, y0, lay.cell_w, lay.cell_h, lay.pad, lay.img_h, lay.box,
                           lay.id_size, lay.name_size, lay.text_lines, opts,
                           fig.item_id in owned, used_names)
                drawn += 1
                if drawn % 25 == 0:
                    progress(drawn / max(1, total), f"PDF: {drawn}/{total} Figuren")
        c.showPage()
    c.save()
    progress(1.0, "PDF fertig")
    return out_path


def _draw_first_header(c, opts, page_w, page_h, margin, total, n_sections, when):
    top = page_h - margin
    band_h = 19 * mm
    c.setFillColor(ACCENT_DARK)
    c.roundRect(margin, top - band_h, page_w - 2 * margin, band_h, 4 * mm, fill=1, stroke=0)
    c.setFillColor(GOLD)
    c.rect(margin + 6 * mm, top - band_h + 4.5 * mm, 2.2 * mm, band_h - 9 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(margin + 12 * mm, top - 9.5 * mm, _safe(opts.title))
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#C9D8EA"))
    c.drawString(margin + 12 * mm, top - 15 * mm,
                 _safe(f"{total} Figuren in {n_sections} Kategorien  ·  Stand {when}  ·  "
                       "Bilder & Daten: BrickLink.com"))
    # tally field
    c.setFillColor(TEXT)
    c.setFont("Helvetica", 9)
    c.drawRightString(page_w - margin, top - band_h - 6 * mm,
                      _safe(f"Gesammelt:  ________  von {total}"))
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    c.drawString(margin, top - band_h - 6 * mm,
                 "Kästchen abhaken – am Bildschirm anklicken oder ausdrucken und ankreuzen.")


def _draw_small_header(c, opts, page_w, page_h, margin):
    top = page_h - margin
    c.setStrokeColor(GRID)
    c.setLineWidth(0.6)
    c.line(margin, top - 5.5 * mm, page_w - margin, top - 5.5 * mm)
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(margin, top - 3.6 * mm, _safe(opts.title))


def _draw_footer(c, page_w, margin, page_no, n_pages, when):
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7)
    c.drawString(margin, margin, _safe(f"Stand {when} · Bilder: BrickLink.com · nur für den privaten Gebrauch"))
    c.drawRightString(page_w - margin, margin, f"Seite {page_no} von {n_pages}")


def _draw_section(c, title, count, x, top, width, h, cont=False):
    c.setFillColor(ACCENT)
    c.roundRect(x, top - h + 1.5 * mm, 1.6 * mm, h - 3 * mm, 0.8 * mm, fill=1, stroke=0)
    c.setFillColor(TEXT)
    c.setFont("Helvetica-Bold", 11.5 if not cont else 9.5)
    label = _safe(title + (" (Fortsetzung)" if cont else ""))
    c.drawString(x + 4 * mm, top - h + 3.2 * mm, label)
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    tally = f"{count} Figuren   ·   gesammelt: ____ / {count}" if not cont else f"{count} Figuren"
    c.drawRightString(x + width, top - h + 3.2 * mm, tally)


def _draw_cell(c, fig: Figure, x, y, w, h, pad, img_h, box, id_size, name_size,
               text_lines, opts: PdfOptions, owned: bool, used_names: set[str]):
    c.setLineWidth(0.6)
    c.setStrokeColor(GRID)
    c.setFillColor(OWNED_FILL if (owned and opts.precheck_owned) else colors.white)
    c.roundRect(x, y, w, h, 2.2 * mm, fill=1, stroke=1)

    # picture
    img_box_w = w - 2 * pad
    img_top = y + h - pad
    reader = _prepared_image(fig.item_id)
    if reader is not None:
        iw, ih = reader.getSize()
        scale = min(img_box_w / iw, img_h / ih)
        dw, dh = iw * scale, ih * scale
        c.drawImage(reader, x + pad + (img_box_w - dw) / 2, img_top - img_h + (img_h - dh) / 2,
                    dw, dh, mask=None)
    else:
        c.setFillColor(colors.HexColor("#F1F3F6"))
        c.roundRect(x + pad, img_top - img_h, img_box_w, img_h, 1.5 * mm, fill=1, stroke=0)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 6.5)
        c.drawCentredString(x + w / 2, img_top - img_h / 2, "kein Bild")

    # tick box + id + year
    row_y = img_top - img_h - 3 - max(box, id_size)
    bx, by = x + pad, row_y
    checked = owned and opts.precheck_owned
    if opts.fillable:
        c.acroForm.checkbox(
            name=_field_name(fig.item_id, used_names), tooltip=_safe(f"{fig.item_id} {fig.name}"),
            x=bx, y=by, size=box, checked=checked, buttonStyle="check",
            borderStyle="solid", borderWidth=0.8, borderColor=ACCENT_DARK,
            fillColor=colors.white, textColor=ACCENT_DARK, forceBorder=True)
    else:
        c.setStrokeColor(ACCENT_DARK)
        c.setLineWidth(0.8)
        c.setFillColor(colors.white)
        c.rect(bx, by, box, box, fill=1, stroke=1)
        if checked:
            c.setLineWidth(1.4)
            p = c.beginPath()
            p.moveTo(bx + box * 0.18, by + box * 0.52)
            p.lineTo(bx + box * 0.42, by + box * 0.24)
            p.lineTo(bx + box * 0.85, by + box * 0.82)
            c.drawPath(p, stroke=1, fill=0)

    tx = bx + box + 2.2
    text_baseline = by + (box - id_size) / 2 + 1
    right = x + w - pad
    if opts.show_year and fig.year:
        c.setFont("Helvetica", id_size * 0.88)
        c.setFillColor(MUTED)
        c.drawRightString(right, text_baseline, str(fig.year))
        right -= stringWidth(str(fig.year), "Helvetica", id_size * 0.88) + 2
    if opts.show_id:
        c.setFont("Helvetica-Bold", id_size)
        c.setFillColor(TEXT)
        label = _safe(fig.item_id)
        while label and stringWidth(label, "Helvetica-Bold", id_size) > right - tx:
            label = label[:-1]
        c.drawString(tx, text_baseline, label)

    if opts.show_name and text_lines:
        c.setFont("Helvetica", name_size)
        c.setFillColor(TEXT)
        ny = by - 1.5 - name_size
        for line in _wrap(fig.name or "", "Helvetica", name_size, w - 2 * pad, text_lines):
            c.drawString(x + pad, ny, line)
            ny -= name_size + 1.4
