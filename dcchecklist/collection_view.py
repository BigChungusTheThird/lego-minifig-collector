"""The collection: picture grid / list, filters and the detail panel."""
from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from tkinter import ttk

import customtkinter as ctk
from PIL import ImageTk

from . import bricklink as bl
from . import config
from .catalog import Figure, classify_group, natural_key
from . import thumbs
from .prices import CONDITIONS, REGIONS, money

IS_MAC = sys.platform == "darwin"

PALETTE = {
    "light": dict(bg="#F2F4F8", card="#FFFFFF", border="#DCE2EA", text="#1B2430", muted="#6B7785",
                  pic="#F4F6F9", sel="#0B5CAD", owned="#1E8E3E", owned_bg="#EEF8F0",
                  gold="#E2A800", head="#1B2430", bar="#DCE2EA", hidden="#9AA5B3"),
    "dark": dict(bg="#10161F", card="#1A2230", border="#2A3446", text="#E8EDF4", muted="#94A1B2",
                 pic="#FFFFFF", sel="#4A9BEA", owned="#5BC27A", owned_bg="#18301F",
                 gold="#F2C230", head="#E8EDF4", bar="#2A3446", hidden="#5D6878"),
}
CARD_W = {"S": 118, "M": 150, "L": 196}

STATUS_FILTERS = ["Alle", "Hab ich", "Fehlen mir", "Wunschliste", "Mit Notiz", "Ausgeblendet"]


def palette() -> dict:
    return PALETTE["dark" if ctk.get_appearance_mode() == "Dark" else "light"]


def _round_rect(cv: tk.Canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


# ======================================================================
class CardGrid(tk.Canvas):
    """Virtualised grid of figure cards on one canvas (fast for 1000+ cards)."""

    def __init__(self, master, page: "CollectionPage"):
        super().__init__(master, highlightthickness=0, bd=0, takefocus=1)
        self.page = page
        self.sections: list[tuple[str, list[Figure]]] = []
        self.cards: list[tuple[Figure, float, float, int]] = []     # fig, x, y, section idx
        self.heads: list[tuple[str, float, int]] = []                # title, y, section idx
        self.index: dict[str, int] = {}
        self.photos: dict[tuple[str, int], ImageTk.PhotoImage] = {}
        self.drawn_imgs: set[str] = set()
        self._img_queue: list[int] = []
        self._img_job = None
        self._anchor: int | None = None
        self.scale_ = 1.0
        self.bind("<Configure>", lambda e: self._relayout_later())
        self.bind("<Button-1>", self._click)
        self.bind("<Double-Button-1>", self._double)
        self.bind("<Button-3>" if not IS_MAC else "<Button-2>", self._context)
        if IS_MAC:
            self.bind("<Control-Button-1>", self._context)
        self.bind("<space>", lambda e: (self.page.toggle_owned(), "break")[1])
        for key, d in (("<Left>", -1), ("<Right>", 1), ("<Up>", "up"), ("<Down>", "down")):
            self.bind(key, lambda e, d=d: self._move(d))
        self.bind("<Enter>", lambda e: self._bind_wheel(True))
        self.bind("<Leave>", lambda e: self._bind_wheel(False))
        self._layout_job = None
        self._width = 0

    # --------------------------------------------------------- geometry
    def metrics(self):
        s = self.scale_
        w = CARD_W.get(self.page.app.state_.settings.get("card_size", "M"), 150) * s
        pad = 8 * s
        pic = w - 2 * pad
        h = pad + pic + 6 * s + 18 * s + 30 * s + pad
        if self.page.app.state_.settings.get("show_prices", True) and self.page.app.state_.prices:
            h += 16 * s
        gap = 12 * s
        head_h = 46 * s
        return w, h, pad, pic, gap, head_h

    def set_sections(self, sections) -> None:
        self.sections = sections
        self.relayout()

    def _relayout_later(self):
        if self.winfo_width() == self._width:
            return
        if self._layout_job:
            self.after_cancel(self._layout_job)
        self._layout_job = self.after(60, self.relayout)

    def relayout(self) -> None:
        self._layout_job = None
        self.scale_ = ctk.ScalingTracker.get_widget_scaling(self)
        self._width = self.winfo_width()
        p = palette()
        self.configure(bg=p["bg"])
        self.delete("all")
        self.drawn_imgs.clear()
        self.cards, self.heads, self.index = [], [], {}
        w, h, pad, pic, gap, head_h = self.metrics()
        avail = max(w + 2 * gap, self._width - 2 * gap)
        cols = max(1, int((avail + gap) // (w + gap)))
        x0 = gap + max(0, (avail - (cols * w + (cols - 1) * gap)) / 2)
        y = gap
        for si, (title, figs) in enumerate(self.sections):
            if not figs:
                continue
            if len(self.sections) > 1 or title:
                self.heads.append((title, y, si))
                y += head_h
            for i, f in enumerate(figs):
                c, r = i % cols, i // cols
                if c == 0 and r > 0:
                    y += h + gap
                self.index[f.item_id] = len(self.cards)
                self.cards.append((f, x0 + c * (w + gap), y, si))
            y += h + gap * 2
        self.total_h = y
        self.configure(scrollregion=(0, 0, self._width, max(y, self.winfo_height())))
        self.fonts()
        for hi in range(len(self.heads)):
            self.draw_head(hi)
        for ci in range(len(self.cards)):
            self.draw_card(ci)
        if not self.cards:
            self.create_text(self._width / 2, 80 * self.scale_, fill=p["muted"],
                             font=self.f_name, text=self.page.empty_text())
        self.queue_visible()

    def fonts(self):
        fam = tkfont.nametofont("TkDefaultFont").actual("family")
        s = self.scale_
        self.f_id = tkfont.Font(family=fam, size=-int(12 * s), weight="bold")
        self.f_name = tkfont.Font(family=fam, size=-int(11 * s))
        self.f_head = tkfont.Font(family=fam, size=-int(16 * s), weight="bold")
        self.f_small = tkfont.Font(family=fam, size=-int(11 * s))
        self.f_badge = tkfont.Font(family=fam, size=-int(14 * s), weight="bold")

    # ---------------------------------------------------------- drawing
    def draw_head(self, hi: int) -> None:
        title, y, si = self.heads[hi]
        p = palette()
        s = self.scale_
        tag = f"head{hi}"
        self.delete(tag)
        figs = self.sections[si][1]
        prog = self.page.app.state_.progress(figs)
        gap = 12 * s
        self.create_text(gap + 4 * s, y + 16 * s, anchor="w", text=title, font=self.f_head,
                         fill=p["head"], tags=tag)
        right = self._width - gap
        label = f"{prog.owned} / {prog.total}  ·  {prog.percent} %"
        self.create_text(right, y + 16 * s, anchor="e", text=label, font=self.f_small,
                         fill=p["muted"], tags=tag)
        bw = 160 * s
        bx = right - bw - self.f_small.measure(label) - 14 * s
        self.create_rectangle(bx, y + 13 * s, bx + bw, y + 19 * s, fill=p["bar"], width=0, tags=tag)
        if prog.total:
            self.create_rectangle(bx, y + 13 * s, bx + bw * prog.owned / prog.total, y + 19 * s,
                                  fill=p["owned"], width=0, tags=tag)
        self.create_line(gap, y + 34 * s, right, y + 34 * s, fill=p["border"], tags=tag)

    def _short(self, text: str, font, width: float, lines: int = 2) -> list[str]:
        words, out, cur = text.split(), [], ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if font.measure(trial) <= width:
                cur = trial
            else:
                if cur:
                    out.append(cur)
                cur = wd
                if len(out) == lines:
                    break
        if cur and len(out) < lines:
            out.append(cur)
        if len(out) == lines and " ".join(out) != " ".join(words):
            last = out[-1]
            while last and font.measure(last + "…") > width:
                last = last[:-1]
            out[-1] = last.rstrip(" ,-") + "…"
        return out

    def draw_card(self, ci: int) -> None:
        f, x, y, _si = self.cards[ci]
        st = self.page.app.state_
        p = palette()
        s = self.scale_
        w, h, pad, pic, _gap, _hh = self.metrics()
        tag = f"card{ci}"
        self.delete(tag)
        self.drawn_imgs.discard(f.item_id)
        owned = f.item_id in st.owned
        visible = st.is_visible(f.item_id)
        selected = f.item_id in self.page.selection
        border = p["sel"] if selected else (p["owned"] if owned else p["border"])
        _round_rect(self, x, y, x + w, y + h, 12 * s, fill=p["owned_bg"] if owned else p["card"],
                    outline=border, width=(3 if selected else (2 if owned else 1)) * s,
                    tags=(tag, "cardbg"))
        # picture area
        self.create_rectangle(x + pad, y + pad, x + pad + pic, y + pad + pic, fill=p["pic"],
                              width=0, tags=(tag, f"pic{ci}"))
        if visible:
            self.create_text(x + w / 2, y + pad + pic / 2, text="kein Bild", fill="#A9B3C0",
                             font=self.f_small, tags=(tag, f"nopic{ci}"))
        # badges
        if f.item_id in st.wishlist:
            self.create_text(x + w - pad - 4 * s, y + pad + 4 * s, anchor="ne", text="★",
                             fill=p["gold"], font=self.f_badge, tags=(tag, "badge"))
        if f.item_id in st.notes:
            self.create_text(x + pad + 4 * s, y + pad + 4 * s, anchor="nw", text="✎",
                             fill=p["muted"], font=self.f_badge, tags=(tag, "badge"))
        # tick box + number + year
        by = y + pad + pic + 6 * s
        bs = 16 * s
        self.create_rectangle(x + pad, by, x + pad + bs, by + bs, outline=p["owned"] if owned
                              else p["muted"], fill=p["owned"] if owned else p["card"],
                              width=max(1, 1.5 * s), tags=(tag, f"box{ci}"))
        if owned:
            self.create_line(x + pad + bs * .2, by + bs * .52, x + pad + bs * .42, by + bs * .75,
                             x + pad + bs * .82, by + bs * .25, fill="white", width=2 * s,
                             capstyle="round", joinstyle="round", tags=tag)
        self.create_text(x + pad + bs + 6 * s, by + bs / 2, anchor="w", text=f.item_id,
                         font=self.f_id, fill=p["text"], tags=tag)
        if f.year:
            self.create_text(x + w - pad, by + bs / 2, anchor="e", text=str(f.year),
                             font=self.f_small, fill=p["muted"], tags=tag)
        ny = by + bs + 4 * s
        for i, line in enumerate(self._short(f.name, self.f_name, w - 2 * pad)):
            self.create_text(x + pad, ny + i * 14 * s, anchor="nw", text=line, font=self.f_name,
                             fill=p["muted"] if not visible else p["text"], tags=tag)
        if st.settings.get("show_prices", True) and st.prices:
            price = st.price(f.item_id)
            self.create_text(x + pad, y + h - pad, anchor="sw", font=self.f_id,
                             text=("Ø " + money(price, st.currency)) if price is not None else "Ø –",
                             fill=p["sel"] if price is not None else p["muted"], tags=tag)
        if not visible:
            lw = self.f_small.measure("ausgeblendet") + 14 * s
            cx, cy = x + w / 2, y + pad + pic - 14 * s
            _round_rect(self, cx - lw / 2, cy - 10 * s, cx + lw / 2, cy + 10 * s, 8 * s,
                        fill=p["hidden"], outline="", tags=(tag, "veil"))
            self.create_text(cx, cy, text="ausgeblendet", fill="white", font=self.f_small,
                             tags=(tag, "veil"))

    def refresh_cards(self, ids) -> None:
        heads = set()
        for i in ids:
            ci = self.index.get(i)
            if ci is not None:
                self.draw_card(ci)
                heads.add(self.cards[ci][3])
        for hi, (_t, _y, si) in enumerate(self.heads):
            if si in heads:
                self.draw_head(hi)
        self.queue_visible()

    # ----------------------------------------------------------- images
    def visible_range(self) -> tuple[float, float]:
        top = self.canvasy(0)
        return top - 300 * self.scale_, top + self.winfo_height() + 300 * self.scale_

    def queue_visible(self) -> None:
        lo, hi = self.visible_range()
        _w, h, *_ = self.metrics()
        self._img_queue = [ci for ci, (f, _x, y, _s) in enumerate(self.cards)
                           if y + h >= lo and y <= hi and f.item_id not in self.drawn_imgs]
        if self._img_queue and self._img_job is None:
            self._img_job = self.after(1, self._load_some)

    def _load_some(self) -> None:
        self._img_job = None
        _w, _h, pad, pic, *_ = self.metrics()
        size = int(pic)
        for _ in range(10):
            if not self._img_queue:
                return
            ci = self._img_queue.pop(0)
            if ci >= len(self.cards):
                continue
            f, x, y, _si = self.cards[ci]
            faded = not self.page.app.state_.is_visible(f.item_id)
            key = (f.item_id, size, faded)
            photo = self.photos.get(key)
            if photo is None:
                im = thumbs.scaled(f.item_id, size)
                if im is None:
                    self.drawn_imgs.add(f.item_id)
                    continue
                if faded:
                    from PIL import Image
                    white = Image.new("RGBA", im.size, (255, 255, 255, 255))
                    im = Image.blend(im.convert("RGBA"), white, 0.6)
                photo = ImageTk.PhotoImage(im)
                self.photos[key] = photo
            self.delete(f"nopic{ci}")
            self.create_image(x + pad + pic / 2, y + pad + pic / 2, image=photo,
                              tags=(f"card{ci}", f"img{ci}"))
            self.tag_raise("badge")
            self.tag_raise("veil")
            self.drawn_imgs.add(f.item_id)
        if self._img_queue:
            self._img_job = self.after(5, self._load_some)

    def forget_photos(self) -> None:
        self.photos.clear()

    # ------------------------------------------------------------ input
    def _bind_wheel(self, on: bool) -> None:
        if on:
            self.bind_all("<MouseWheel>", self._wheel)
            self.bind_all("<Button-4>", lambda e: self._scroll(-3))
            self.bind_all("<Button-5>", lambda e: self._scroll(3))
        else:
            self.unbind_all("<MouseWheel>")
            self.unbind_all("<Button-4>")
            self.unbind_all("<Button-5>")

    def _wheel(self, e):
        if IS_MAC:
            self._scroll(-e.delta)
        else:
            self._scroll(-int(e.delta / 40) or (-1 if e.delta > 0 else 1))

    def _scroll(self, units: int) -> None:
        self.yview_scroll(units, "units")
        self.queue_visible()

    def yview(self, *args):  # called by the scrollbar
        r = super().yview(*args)
        if args:
            self.queue_visible()
        return r

    def card_at(self, ex, ey) -> int | None:
        x, y = self.canvasx(ex), self.canvasy(ey)
        w, h, *_ = self.metrics()
        for ci, (_f, cx, cy, _s) in enumerate(self.cards):
            if cx <= x <= cx + w and cy <= y <= cy + h:
                return ci
        return None

    def _in_box(self, ci, ex, ey) -> bool:
        _f, x, y, _s = self.cards[ci]
        _w, _h, pad, pic, *_ = self.metrics()
        cx, cy = self.canvasx(ex), self.canvasy(ey)
        by = y + pad + pic + 6 * self.scale_
        return x + pad - 4 <= cx <= x + pad + 22 * self.scale_ and by - 4 <= cy <= by + 22 * self.scale_

    def _click(self, e):
        self.focus_set()
        ci = self.card_at(e.x, e.y)
        if ci is None:
            return
        fid = self.cards[ci][0].item_id
        if self._in_box(ci, e.x, e.y):
            self.page.toggle_owned([fid])
            return
        multi = bool(e.state & (0x0008 if IS_MAC else 0x0004))      # Cmd / Ctrl
        shift = bool(e.state & 0x0001)
        if shift and self._anchor is not None:
            lo, hi = sorted((self._anchor, ci))
            ids = [self.cards[i][0].item_id for i in range(lo, hi + 1)]
            self.page.select(ids, add=multi)
        elif multi:
            self.page.select([fid], toggle=True)
            self._anchor = ci
        else:
            self.page.select([fid])
            self._anchor = ci

    def _double(self, e):
        ci = self.card_at(e.x, e.y)
        if ci is not None and not self._in_box(ci, e.x, e.y):
            self.page.toggle_owned([self.cards[ci][0].item_id])

    def _context(self, e):
        ci = self.card_at(e.x, e.y)
        if ci is None:
            return
        fid = self.cards[ci][0].item_id
        if fid not in self.page.selection:
            self.page.select([fid])
        self.page.context_menu(e.x_root, e.y_root)

    def _move(self, d):
        if not self.cards:
            return
        cur = self.index.get(next(iter(self.page.selection), ""), -1)
        w, _h, _p, _pic, gap, _hh = self.metrics()
        cols = max(1, int((self._width - gap) // (w + gap)))
        if d == "up":
            d = -cols
        elif d == "down":
            d = cols
        ni = min(len(self.cards) - 1, max(0, cur + d))
        self.page.select([self.cards[ni][0].item_id])
        self._anchor = ni
        self.see(ni)

    def see(self, ci: int) -> None:
        _f, _x, y, _s = self.cards[ci]
        _w, h, *_ = self.metrics()
        top, bottom = self.canvasy(0), self.canvasy(self.winfo_height())
        total = max(1, self.total_h)
        if y < top:
            self.yview_moveto(max(0, (y - 20) / total))
        elif y + h > bottom:
            self.yview_moveto(max(0, (y + h - self.winfo_height() + 20) / total))
        self.queue_visible()


# ======================================================================
class ListView(ttk.Treeview):
    COLS = ("own", "wish", "id", "name", "year", "price", "cat", "note")

    def __init__(self, master, page: "CollectionPage"):
        super().__init__(master, columns=self.COLS, show="headings", selectmode="extended",
                         style="DC.Treeview")
        self.page = page
        heads = {"own": ("Hab ich", 66), "wish": ("★", 30), "id": ("Nr.", 80),
                 "name": ("Name", 220), "year": ("Jahr", 50), "price": ("Ø Preis", 80),
                 "cat": ("Kategorie", 120),
                 "note": ("Notiz / Hinweis", 120)}
        for col, (label, width) in heads.items():
            self.heading(col, text=label)
            self.column(col, width=width, minwidth=30, stretch=col in ("name", "cat", "note"),
                        anchor="center" if col in ("own", "wish", "year") else
                        ("e" if col == "price" else "w"))
        self.bind("<<TreeviewSelect>>", lambda e: self.page.select(list(self.selection()),
                                                                   from_list=True))
        self.bind("<Double-1>", lambda e: self.page.toggle_owned())
        self.bind("<space>", lambda e: (self.page.toggle_owned(), "break")[1])
        self.bind("<Button-3>" if not IS_MAC else "<Button-2>", self._context)

    def _context(self, e):
        row = self.identify_row(e.y)
        if row and row not in self.selection():
            self.selection_set(row)
        self.page.context_menu(e.x_root, e.y_root)

    def values(self, f: Figure):
        st = self.page.app.state_
        note = st.notes.get(f.item_id, "")
        if not st.is_visible(f.item_id):
            note = "ausgeblendet: " + st.decisions()[f.item_id].reason + (f" · {note}" if note else "")
        price = st.price(f.item_id)
        return ("✔" if f.item_id in st.owned else "", "★" if f.item_id in st.wishlist else "",
                f.item_id, f.name, f.year or "?",
                money(price, st.currency) if price is not None else "", f.section, note)

    def tags_for(self, f: Figure):
        st = self.page.app.state_
        tags = []
        if f.item_id in st.owned:
            tags.append("own")
        if not st.is_visible(f.item_id):
            tags.append("hidden")
        return tags

    def fill(self, sections) -> None:
        self.delete(*self.get_children())
        for title, figs in sections:
            for f in figs:
                self.insert("", "end", iid=f.item_id, values=self.values(f), tags=self.tags_for(f))

    def refresh_rows(self, ids) -> None:
        for i in ids:
            f = self.page.app.state_.figure(i)
            if f is not None and self.exists(i):
                self.item(i, values=self.values(f), tags=self.tags_for(f))

    def style(self) -> None:
        dark = ctk.get_appearance_mode() == "Dark"
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        scale = ctk.ScalingTracker.get_widget_scaling(self)
        bg = "#1A2230" if dark else "#FFFFFF"
        fg = "#E8EDF4" if dark else "#1B2430"
        head = "#232D3E" if dark else "#EEF2F7"
        st.configure("DC.Treeview", background=bg, fieldbackground=bg, foreground=fg,
                     rowheight=int(26 * scale), borderwidth=0)
        st.map("DC.Treeview", background=[("selected", "#0B5CAD")],
               foreground=[("selected", "white")])
        st.configure("DC.Treeview.Heading", background=head, foreground=fg, relief="flat",
                     padding=(6, 6))
        st.map("DC.Treeview.Heading", background=[("active", head)])
        st.layout("DC.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        self.tag_configure("own", background="#18301F" if dark else "#EEF8F0")
        self.tag_configure("hidden", foreground="#6C7889" if dark else "#9AA5B3")


# ======================================================================
class DetailPanel(ctk.CTkFrame):
    def __init__(self, master, page: "CollectionPage", colors: dict):
        super().__init__(master, fg_color=colors["CARD"], corner_radius=14, border_width=1,
                         border_color=colors["CARD_BORDER"], width=290)
        self.page = page
        self.c = colors
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.pic = ctk.CTkLabel(self, text="", width=250, height=230, fg_color="#FFFFFF",
                                corner_radius=10, text_color="#A9B3C0")
        self.pic.grid(row=0, column=0, padx=18, pady=(18, 10), sticky="ew")
        self.title = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=16, weight="bold"),
                                  text_color=colors["TEXT"], anchor="w", justify="left",
                                  wraplength=250)
        self.title.grid(row=1, column=0, sticky="ew", padx=18)
        self.info = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12),
                                 text_color=colors["MUTED"], anchor="w", justify="left",
                                 wraplength=250)
        self.info.grid(row=2, column=0, sticky="ew", padx=18, pady=(4, 10))
        btn = dict(height=36, corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"))
        self.b_own = ctk.CTkButton(self, text="", command=lambda: self.page.toggle_owned(), **btn)
        self.b_own.grid(row=3, column=0, sticky="ew", padx=18, pady=3)
        self.b_wish = ctk.CTkButton(self, text="", command=lambda: self.page.toggle_wish(),
                                    fg_color=colors["GOLD"], hover_color=colors["GOLD_HOVER"],
                                    text_color=colors["NAVY"], **btn)
        self.b_wish.grid(row=4, column=0, sticky="ew", padx=18, pady=3)
        sec = dict(height=34, corner_radius=10, fg_color=("#E6EBF2", "#273246"),
                   hover_color=("#D6DDE8", "#323F57"), text_color=colors["TEXT"],
                   font=ctk.CTkFont(size=13))
        self.b_hide = ctk.CTkButton(self, text="", command=lambda: self.page.toggle_hidden(), **sec)
        self.b_hide.grid(row=5, column=0, sticky="ew", padx=18, pady=3)
        self.b_web = ctk.CTkButton(self, text="Auf BrickLink ansehen  ↗", command=self._web, **sec)
        self.b_web.grid(row=6, column=0, sticky="ew", padx=18, pady=3)
        self.note_label = ctk.CTkLabel(self, text="Notiz", text_color=colors["MUTED"], anchor="w")
        self.note_label.grid(row=7, column=0, sticky="ew", padx=18, pady=(10, 0))
        self.note = ctk.CTkTextbox(self, height=70, font=ctk.CTkFont(size=12), corner_radius=8,
                                   border_width=1, border_color=colors["CARD_BORDER"])
        self.note.grid(row=8, column=0, sticky="ew", padx=18, pady=(2, 16))
        self.note.bind("<KeyRelease>", lambda e: self._note_later())
        self.note.bind("<FocusOut>", lambda e: self._save_note())
        self._note_job = None
        self._note_for: str | None = None
        self._photo = None
        from PIL import Image
        # customtkinter cannot remove an image from a label: show a blank one instead
        self._blank = ctk.CTkImage(Image.new("RGBA", (1, 1), (0, 0, 0, 0)), size=(1, 1))
        self.show([])

    def _web(self):
        if self.page.selection:
            webbrowser.open(bl.item_url(next(iter(self.page.selection))))

    def _note_later(self):
        if self._note_job:
            self.after_cancel(self._note_job)
        self._note_job = self.after(700, self._save_note)

    def _save_note(self):
        self._note_job = None
        if self._note_for:
            text = self.note.get("1.0", "end")
            st = self.page.app.state_
            if text.strip() != st.notes.get(self._note_for, ""):
                st.set_note(self._note_for, text)
                self.page.refresh([self._note_for])

    def show(self, ids: list[str]) -> None:
        self._save_note()
        st = self.page.app.state_
        c = self.c
        if not ids:
            self._note_for = None
            self.pic.configure(image=self._blank, text="Figur anklicken")
            self.title.configure(text="")
            self.info.configure(text="Tipp: Kästchen oder Doppelklick = „Hab ich“.\n"
                                     "Strg/⌘-Klick oder Umschalt-Klick wählt mehrere aus.\n"
                                     "Rechtsklick öffnet das Menü.")
            for b in (self.b_own, self.b_wish, self.b_hide, self.b_web):
                b.configure(state="disabled")
            self.note.configure(state="normal")
            self.note.delete("1.0", "end")
            self.note.configure(state="disabled")
            self.b_own.configure(text="✓  Hab ich", fg_color=c["OK"], hover_color=c["OK_HOVER"])
            self.b_wish.configure(text="★  Auf die Wunschliste")
            self.b_hide.configure(text="Ausblenden")
            return
        for b in (self.b_own, self.b_wish, self.b_hide):
            b.configure(state="normal")
        owned = all(i in st.owned for i in ids)
        wish = all(i in st.wishlist for i in ids)
        visible = all(st.is_visible(i) for i in ids)
        self.b_own.configure(text="✓  Hab ich" if not owned else "Doch nicht gesammelt",
                             fg_color=c["OK"] if not owned else ("#E6EBF2", "#273246"),
                             hover_color=c["OK_HOVER"] if not owned else ("#D6DDE8", "#323F57"),
                             text_color="white" if not owned else c["TEXT"])
        self.b_wish.configure(text="★  Auf die Wunschliste" if not wish else "☆  Von der Wunschliste")
        self.b_hide.configure(text="Ausblenden" if visible else "Wieder einblenden")
        if len(ids) > 1:
            self._note_for = None
            self.b_web.configure(state="disabled")
            self.note.configure(state="normal")
            self.note.delete("1.0", "end")
            self.note.configure(state="disabled")
            self.pic.configure(image=self._blank, text=f"{len(ids)} Figuren")
            n_own = sum(1 for i in ids if i in st.owned)
            self.title.configure(text=f"{len(ids)} Figuren markiert")
            value, n_val = st.value([st.figure(i) for i in ids if st.figure(i)])
            extra = f"\nZusammen ca. {money(value, st.currency)} ({n_val} mit Preis)." if n_val else ""
            self.info.configure(text=f"{n_own} davon gesammelt.{extra}\n"
                                     "Die Knöpfe gelten für alle markierten.")
            return
        f = st.figure(ids[0])
        if f is None:
            return
        self.b_web.configure(state="normal")
        self.note.configure(state="normal")
        self._note_for = f.item_id
        self.note.delete("1.0", "end")
        self.note.insert("1.0", st.notes.get(f.item_id, ""))
        im = thumbs.thumbnail(f.item_id)
        if im is not None:
            im = im.copy()
            im.thumbnail((230, 230))
            self._photo = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
            self.pic.configure(image=self._photo, text="")
        else:
            self.pic.configure(image=self._blank, text="Noch kein Bild\n(Katalog & Daten → Bilder laden)")
        self.title.configure(text=f"{f.item_id}\n{f.name}")
        d = st.decisions()[f.item_id]
        lines = [f"Jahr: {f.year or 'unbekannt'}", f"Kategorie: {f.category_label}"]
        status = []
        if f.item_id in st.owned:
            status.append("✓ gesammelt")
        if f.item_id in st.wishlist:
            status.append("★ Wunschliste")
        if not d.include:
            status.append(f"ausgeblendet ({d.reason})")
        elif d.reason:
            status.append(d.reason)
        if status:
            lines.append(" · ".join(status))
        rec = st.prices.get(f.item_id)
        if rec:
            region = REGIONS.get(rec.get("region"), ("?",))[0].split(" (")[0]
            lines.append("")
            lines.append(f"Ø Verkaufspreis 6 Monate ({region}):")
            for cond in ("U", "N"):
                pr = rec.get(cond)
                if pr is None:
                    continue
                if pr.get("avg") is None:
                    lines.append(f"  {CONDITIONS[cond]}: keine Verkäufe")
                else:
                    rng = (f", {money(pr['min'], rec.get('currency', 'EUR'))}–"
                           f"{money(pr['max'], rec.get('currency', 'EUR'))}"
                           if pr.get("min") is not None and pr.get("max") is not None else "")
                    lines.append(f"  {CONDITIONS[cond]}: {money(pr['avg'], rec.get('currency', 'EUR'))}"
                                 f"  ({pr.get('qty', 0)} verkauft{rng})")
            try:
                import datetime as _dt
                lines.append("  Stand " + _dt.date.fromisoformat(rec["date"]).strftime("%d.%m.%Y"))
            except (KeyError, ValueError):
                pass
        elif st.prices:
            lines.append("\nNoch kein Preis – unter „Preise“ laden.")
        self.info.configure(text="\n".join(lines))


# ======================================================================
class CollectionPage(ctk.CTkFrame):
    """Main page: browse, tick off, hide and annotate figures – all offline."""

    def __init__(self, master, app, colors: dict):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.c = colors
        self.selection: list[str] = []
        self.dirty = True
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # ---- header with overall progress
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(head, text="Meine Sammlung", font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=colors["TEXT"]).grid(row=0, column=0, sticky="w")
        pbox = ctk.CTkFrame(head, fg_color="transparent")
        pbox.grid(row=0, column=1, sticky="e")
        self.p_label = ctk.CTkLabel(pbox, text="", font=ctk.CTkFont(size=13), text_color=colors["MUTED"])
        self.p_label.pack(side="left", padx=(0, 10))
        self.p_bar = ctk.CTkProgressBar(pbox, width=220, height=10, progress_color=colors["OK"])
        self.p_bar.pack(side="left")

        # ---- toolbar
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 10))
        self.search = ctk.StringVar()
        self.search.trace_add("write", lambda *_: self._filter_later())
        ctk.CTkEntry(bar, textvariable=self.search, width=220, height=32,
                     placeholder_text="Suchen: Name, Nummer …").pack(side="left")
        self.status = ctk.StringVar(value="Alle")
        ctk.CTkOptionMenu(bar, variable=self.status, values=STATUS_FILTERS, width=130, height=32,
                          command=lambda _v: self.populate()).pack(side="left", padx=(8, 0))
        self.category = ctk.StringVar(value="Alle Kategorien")
        self.cat_menu = ctk.CTkOptionMenu(bar, variable=self.category, values=["Alle Kategorien"],
                                          width=190, height=32, dynamic_resizing=False,
                                          command=lambda _v: self.populate())
        self.cat_menu.pack(side="left", padx=(8, 0))
        group_map = {"Nach Kategorie": "category", "Nach Thema": "theme", "Nach Jahr": "year",
                     "Ohne Gruppen": "none"}
        sort_map = {"Jahr": "year", "Nummer": "id", "Name": "name", "Preis ↑": "price",
                    "Preis ↓": "price_desc"}
        self.group_map, self.sort_map = group_map, sort_map
        inv_g = {v: k for k, v in group_map.items()}
        inv_s = {v: k for k, v in sort_map.items()}
        st = app.state_.settings
        self.grouping = ctk.StringVar(value=inv_g.get(st.get("grouping", "category"), "Nach Kategorie"))
        self.sorting = ctk.StringVar(value=inv_s.get(st.get("sort_by", "year"), "Jahr"))
        ctk.CTkOptionMenu(bar, variable=self.grouping, values=list(group_map), width=140, height=32,
                          command=lambda _v: self._save_view()).pack(side="left", padx=(8, 0))
        ctk.CTkOptionMenu(bar, variable=self.sorting, values=list(sort_map), width=100, height=32,
                          command=lambda _v: self._save_view()).pack(side="left", padx=(8, 0))
        self.view = ctk.StringVar(value="Raster" if st.get("view", "grid") == "grid" else "Liste")
        ctk.CTkSegmentedButton(bar, values=["Raster", "Liste"], variable=self.view, height=32,
                               command=lambda _v: self._switch_view(),
                               selected_color=colors["BLUE"],
                               selected_hover_color=colors["BLUE_HOVER"]).pack(side="right")
        self.size = ctk.StringVar(value=st.get("card_size", "M"))
        self.size_btn = ctk.CTkSegmentedButton(bar, values=["S", "M", "L"], variable=self.size,
                                               height=32, command=lambda _v: self._save_view(),
                                               selected_color=colors["BLUE"],
                                               selected_hover_color=colors["BLUE_HOVER"])
        self.size_btn.pack(side="right", padx=8)

        # ---- body: grid / list + detail panel
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=2, column=0, sticky="nsew")
        self.body.grid_rowconfigure(0, weight=1)
        self.body.grid_columnconfigure(0, weight=1)
        self.grid_holder = ctk.CTkFrame(self.body, fg_color="transparent")
        self.grid_holder.grid_rowconfigure(0, weight=1)
        self.grid_holder.grid_columnconfigure(0, weight=1)
        self.cards = CardGrid(self.grid_holder, self)
        self.cards.grid(row=0, column=0, sticky="nsew")
        sb = ctk.CTkScrollbar(self.grid_holder, command=self.cards.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.cards.configure(yscrollcommand=sb.set)
        self.list_holder = ctk.CTkFrame(self.body, fg_color=colors["CARD"], corner_radius=12,
                                        border_width=1, border_color=colors["CARD_BORDER"])
        self.list_holder.grid_rowconfigure(0, weight=1)
        self.list_holder.grid_columnconfigure(0, weight=1)
        self.listv = ListView(self.list_holder, self)
        self.listv.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        lsb = ctk.CTkScrollbar(self.list_holder, command=self.listv.yview)
        lsb.grid(row=0, column=1, sticky="ns", pady=8)
        self.listv.configure(yscrollcommand=lsb.set)
        self.detail = DetailPanel(self, self, colors)
        self.detail.grid(row=2, column=1, sticky="ns", padx=(14, 0))

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Hab ich / Doch nicht", command=lambda: self.toggle_owned())
        self.menu.add_command(label="Wunschliste an / aus", command=lambda: self.toggle_wish())
        self.menu.add_separator()
        self.menu.add_command(label="Ausblenden / Einblenden", command=lambda: self.toggle_hidden())
        self.menu.add_separator()
        self.menu.add_command(label="Alle angezeigten markieren", command=self.select_all)
        self.menu.add_command(label="Auf BrickLink ansehen", command=self.detail._web)

        self._filter_job = None
        self._sections = []
        self._switch_view(populate=False)
        app.bind("<Control-a>", lambda e: self._select_all_key(e), add="+")
        if IS_MAC:
            app.bind("<Command-a>", lambda e: self._select_all_key(e), add="+")

    # ------------------------------------------------------------ state
    def on_show(self) -> None:
        if self.dirty:
            self.populate()
        else:
            self.update_progress()

    def restyle(self) -> None:
        self.listv.style()
        self.cards.relayout()

    def empty_text(self) -> str:
        if not self.app.state_.figures:
            return "Noch kein Katalog – unter „Katalog & Daten“ importieren."
        return "Keine Figuren für diese Auswahl."

    def _filter_later(self):
        if self._filter_job:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(250, self.populate)

    def _save_view(self):
        st = self.app.state_.settings
        st["grouping"] = self.group_map[self.grouping.get()]
        st["sort_by"] = self.sort_map[self.sorting.get()]
        st["card_size"] = self.size.get()
        self.app.state_.save_settings()
        self.cards.forget_photos()
        self.populate()

    def _switch_view(self, populate=True):
        grid = self.view.get() == "Raster"
        self.app.state_.settings["view"] = "grid" if grid else "list"
        self.app.state_.save_settings()
        if grid:
            self.list_holder.grid_forget()
            self.grid_holder.grid(row=0, column=0, sticky="nsew")
            self.size_btn.pack(side="right", padx=8)
        else:
            self.grid_holder.grid_forget()
            self.list_holder.grid(row=0, column=0, sticky="nsew")
            self.size_btn.pack_forget()
        if populate:
            self.populate()

    def filtered(self) -> list[Figure]:
        st = self.app.state_
        status = self.status.get()
        figs = st.hidden() if status == "Ausgeblendet" else st.selected()
        q = self.search.get().strip().lower()
        cat = self.category.get()
        out = []
        for f in figs:
            if q and q not in f"{f.item_id} {f.name} {f.category_label} {st.notes.get(f.item_id, '')}".lower():
                continue
            if cat != "Alle Kategorien" and f.section != cat:
                continue
            if status == "Hab ich" and f.item_id not in st.owned:
                continue
            if status == "Fehlen mir" and f.item_id in st.owned:
                continue
            if status == "Wunschliste" and f.item_id not in st.wishlist:
                continue
            if status == "Mit Notiz" and f.item_id not in st.notes:
                continue
            out.append(f)
        return out

    def _update_categories(self):
        st = self.app.state_
        cats = []
        seen = set()
        for title, _figs in st.sections(grouping="category"):
            if title not in seen:
                seen.add(title)
                cats.append(title)
        values = ["Alle Kategorien"] + cats
        self.cat_menu.configure(values=values)
        if self.category.get() not in values:
            self.category.set("Alle Kategorien")

    def populate(self) -> None:
        self._filter_job = None
        self.dirty = False
        self._update_categories()
        st = self.app.state_
        self._sections = st.sections(self.filtered())
        self.selection = [i for i in self.selection if any(
            f.item_id == i for _t, fs in self._sections for f in fs)]
        if self.view.get() == "Raster":
            self.cards.set_sections(self._sections)
        else:
            self.listv.fill(self._sections)
            if self.selection:
                self.listv.selection_set(self.selection)
        self.detail.show(self.selection)
        self.update_progress()

    def update_progress(self) -> None:
        st = self.app.state_
        prog = st.progress()
        shown = sum(len(f) for _t, f in self._sections)
        text = f"{prog.owned} von {prog.total} gesammelt ({prog.percent} %)   ·   {shown} angezeigt"
        if st.prices:
            sel = st.selected()
            have, _n1 = st.value([f for f in sel if f.item_id in st.owned])
            miss, _n2 = st.value([f for f in sel if f.item_id not in st.owned])
            text += (f"\nSammlungswert ca. {money(have, st.currency)}   ·   "
                     f"fehlende Figuren ca. {money(miss, st.currency)}")
        self.p_label.configure(text=text, justify="right")
        self.p_bar.set(prog.owned / prog.total if prog.total else 0)
        self.app.refresh_summary()

    def refresh(self, ids) -> None:
        """Redraw some figures after a change (keeps scroll position)."""
        if self.view.get() == "Raster":
            self.cards.refresh_cards(ids)
        else:
            self.listv.refresh_rows(ids)
        self.detail.show(self.selection)
        self.update_progress()

    # -------------------------------------------------------- selection
    def select(self, ids, add=False, toggle=False, from_list=False) -> None:
        old = list(self.selection)
        if toggle:
            for i in ids:
                if i in self.selection:
                    self.selection.remove(i)
                else:
                    self.selection.append(i)
        elif add:
            self.selection += [i for i in ids if i not in self.selection]
        else:
            self.selection = list(ids)
        if self.view.get() == "Raster":
            self.cards.refresh_cards(set(old) | set(self.selection))
        self.detail.show(self.selection)

    def select_all(self) -> None:
        self.select([f.item_id for _t, fs in self._sections for f in fs])
        if self.view.get() == "Liste":
            self.listv.selection_set(self.selection)

    def _select_all_key(self, e):
        if self.winfo_ismapped() and not isinstance(e.widget, (tk.Entry, tk.Text)):
            self.select_all()
            return "break"

    def context_menu(self, x, y) -> None:
        try:
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()

    # ----------------------------------------------------------- actions
    def _targets(self, ids=None) -> list[str]:
        return list(ids) if ids else list(self.selection)

    def toggle_owned(self, ids=None) -> None:
        ids = self._targets(ids)
        if not ids:
            return
        st = self.app.state_
        st.set_owned(ids, not all(i in st.owned for i in ids))
        self.after_change(ids)

    def toggle_wish(self, ids=None) -> None:
        ids = self._targets(ids)
        if not ids:
            return
        st = self.app.state_
        st.set_wishlist(ids, not all(i in st.wishlist for i in ids))
        self.after_change(ids)

    def toggle_hidden(self, ids=None) -> None:
        ids = self._targets(ids)
        if not ids:
            return
        st = self.app.state_
        hide = all(st.is_visible(i) for i in ids)
        st.set_hidden(ids, hide)
        # the figures leave the current view (or come back): rebuild it
        self.selection = [] if hide != (self.status.get() == "Ausgeblendet") else self.selection
        self.populate()
        self.app.toast(f"{len(ids)} Figur{'en' if len(ids) != 1 else ''} "
                       f"{'ausgeblendet' if hide else 'wieder eingeblendet'}"
                       + (" – unter „Ausgeblendet“ wiederzufinden" if hide else ""))

    def after_change(self, ids) -> None:
        status = self.status.get()
        if status in ("Hab ich", "Fehlen mir", "Wunschliste"):
            self.populate()            # figures may drop out of this filter
        else:
            self.refresh(ids)
