"""Desktop app (customtkinter) – Windows, macOS and Linux."""
from __future__ import annotations

import datetime as dt
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageTk

from . import bricklink as bl
from . import config
from .catalog import Figure, classify_group, download_images, image_path
from .importer import DOWNLOAD_PAGE, ImportError_, find_recent_download, import_catalog
from .icon import make_icon
from .net import BlockedError, CancelledError, Client
from .pdf import build_pdf, estimate_pages
from .state import State
from .storage import clear_cache, data_dir, default_output_dir

# ------------------------------------------------------------------ colours
NAVY = "#0A2540"
NAVY_2 = "#123456"
BLUE = "#0B5CAD"
BLUE_HOVER = "#094C8F"
GOLD = "#F2C230"
GOLD_HOVER = "#D9AC22"
BG = ("#F2F4F8", "#10161F")
CARD = ("#FFFFFF", "#1A2230")
CARD_BORDER = ("#E1E6EE", "#263042")
TEXT = ("#1B2430", "#E8EDF4")
MUTED = ("#6B7785", "#94A1B2")
OK = ("#1E8E3E", "#5BC27A")
BAD = ("#C5221F", "#F28B82")


def _font(size=13, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def open_path(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:  # pragma: no cover - platform dependent
        messagebox.showerror(config.APP_NAME, f"Konnte nicht öffnen:\n{path}\n\n{exc}")


class Card(ctk.CTkFrame):
    def __init__(self, master, title: str | None = None, subtitle: str | None = None, **kw):
        super().__init__(master, fg_color=CARD, corner_radius=14, border_width=1,
                         border_color=CARD_BORDER, **kw)
        self.grid_columnconfigure(0, weight=1)
        self._row = 0
        if title:
            ctk.CTkLabel(self, text=title, font=_font(15, "bold"), text_color=TEXT,
                         anchor="w").grid(row=self._next(), column=0, sticky="ew",
                                          padx=18, pady=(14, 0))
        if subtitle:
            ctk.CTkLabel(self, text=subtitle, font=_font(12), text_color=MUTED, anchor="w",
                         justify="left", wraplength=640).grid(
                row=self._next(), column=0, sticky="ew", padx=18, pady=(2, 0))

    def _next(self) -> int:
        r = self._row
        self._row += 1
        return r

    def add(self, widget, pady=(8, 0), padx=18, sticky="ew"):
        widget.grid(row=self._next(), column=0, sticky=sticky, padx=padx, pady=pady)
        return widget

    def end(self):
        ctk.CTkFrame(self, height=10, fg_color="transparent").grid(row=self._next(), column=0)


def page_header(master, step: str, title: str, text: str) -> ctk.CTkFrame:
    f = ctk.CTkFrame(master, fg_color="transparent")
    ctk.CTkLabel(f, text=step, font=_font(12, "bold"), text_color=BLUE, anchor="w").pack(anchor="w")
    ctk.CTkLabel(f, text=title, font=_font(24, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
    ctk.CTkLabel(f, text=text, font=_font(13), text_color=MUTED, anchor="w", justify="left",
                 wraplength=760).pack(anchor="w", pady=(2, 0))
    return f


def primary_button(master, text, command, **kw):
    return ctk.CTkButton(master, text=text, command=command, height=40, corner_radius=10,
                         fg_color=BLUE, hover_color=BLUE_HOVER, font=_font(14, "bold"), **kw)


def secondary_button(master, text, command, **kw):
    return ctk.CTkButton(master, text=text, command=command, height=36, corner_radius=10,
                         fg_color=("#E6EBF2", "#273246"), hover_color=("#D6DDE8", "#323F57"),
                         text_color=TEXT, font=_font(13), **kw)


# ======================================================================
class App(ctk.CTk):
    def __init__(self) -> None:
        self.state_ = State()
        ctk.set_appearance_mode(self.state_.settings.get("appearance", "System"))
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.title(config.APP_NAME)
        self.geometry("1280x800")
        self.minsize(980, 640)
        self.configure(fg_color=BG)
        try:
            self._icon = ImageTk.PhotoImage(make_icon(256))
            self.iconphoto(True, self._icon)
        except Exception:
            pass

        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel = threading.Event()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=26, pady=22)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.pages = {
            "themes": ThemesPage(self.content, self),
            "load": LoadPage(self.content, self),
            "review": ReviewPage(self.content, self),
            "pdf": PdfPage(self.content, self),
        }
        for p in self.pages.values():
            p.grid(row=0, column=0, sticky="nsew")
        self.show("load" if not self.state_.figures else "pdf")
        self.refresh_summary()
        self.after(120, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------- sidebar
    def _build_sidebar(self) -> None:
        sb = ctk.CTkFrame(self, fg_color=NAVY, corner_radius=0, width=250)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)

        logo = ctk.CTkImage(make_icon(128), size=(46, 46))
        head = ctk.CTkFrame(sb, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 6))
        ctk.CTkLabel(head, image=logo, text="").pack(side="left")
        tbox = ctk.CTkFrame(head, fg_color="transparent")
        tbox.pack(side="left", padx=10)
        ctk.CTkLabel(tbox, text="DC Minifiguren", font=_font(16, "bold"),
                     text_color="white", anchor="w").pack(anchor="w")
        ctk.CTkLabel(tbox, text="Checkliste", font=_font(13), text_color=GOLD,
                     anchor="w").pack(anchor="w")

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        items = [("themes", "1   Themen & Filter"), ("load", "2   Katalog importieren"),
                 ("review", "3   Auswahl prüfen"), ("pdf", "4   PDF erstellen")]
        for i, (key, label) in enumerate(items):
            b = ctk.CTkButton(sb, text=label, anchor="w", height=42, corner_radius=10,
                              fg_color="transparent", hover_color=NAVY_2, text_color="#DCE6F2",
                              font=_font(14), command=lambda k=key: self.show(k))
            b.grid(row=1 + i, column=0, sticky="ew", padx=12, pady=3)
            self.nav_buttons[key] = b

        self.summary = ctk.CTkLabel(sb, text="", font=_font(12), text_color="#AFC2D8",
                                    justify="left", anchor="w", wraplength=210)
        self.summary.grid(row=6, column=0, sticky="ew", padx=20, pady=(26, 0))
        sb.grid_rowconfigure(7, weight=1)

        ctk.CTkLabel(sb, text="Darstellung", font=_font(11), text_color="#8EA3BC",
                     anchor="w").grid(row=8, column=0, sticky="ew", padx=20)
        mode_map = {"System": "System", "Hell": "Light", "Dunkel": "Dark"}
        inv = {v: k for k, v in mode_map.items()}
        self.mode_var = ctk.StringVar(value=inv.get(self.state_.settings.get("appearance", "System"),
                                                    "System"))

        def set_mode(v):
            mode = mode_map[v]
            ctk.set_appearance_mode(mode)
            self.state_.settings["appearance"] = mode
            self.state_.save_settings()
            self.after(50, self.pages["review"].style_tree)

        ctk.CTkSegmentedButton(sb, values=list(mode_map), variable=self.mode_var,
                               command=set_mode, selected_color=BLUE,
                               selected_hover_color=BLUE_HOVER, unselected_color=NAVY_2,
                               unselected_hover_color="#1C4670", text_color="white").grid(
            row=9, column=0, sticky="ew", padx=18, pady=(4, 10))
        ctk.CTkLabel(sb, text=f"Version {config.APP_VERSION} · Daten & Bilder: BrickLink.com",
                     font=_font(10), text_color="#6F86A1", wraplength=210, justify="left",
                     anchor="w").grid(row=10, column=0, sticky="ew", padx=20, pady=(0, 16))

    def show(self, key: str) -> None:
        for k, b in self.nav_buttons.items():
            b.configure(fg_color=BLUE if k == key else "transparent",
                        text_color="white" if k == key else "#DCE6F2")
        page = self.pages[key]
        page.tkraise()
        if hasattr(page, "on_show"):
            page.on_show()

    def refresh_summary(self) -> None:
        st = self.state_
        if not st.figures:
            self.summary.configure(text="Noch kein Katalog geladen.\nStarte mit Schritt 2.")
            return
        sel = len(st.selected())
        fetched = st.catalog_meta.get("fetched", "")[:10]
        try:
            fetched = dt.date.fromisoformat(fetched).strftime("%d.%m.%Y")
        except ValueError:
            pass
        owned = len([f for f in st.figures if f.item_id in st.owned])
        self.summary.configure(
            text=f"Katalog vom {fetched}\n{len(st.figures)} DC-Figuren geladen\n"
                 f"{sel} auf deiner Liste\n{owned} schon gesammelt")

    # ------------------------------------------------------------- workers
    def run_task(self, name: str, fn) -> bool:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(config.APP_NAME, "Es läuft gerade schon ein Vorgang.")
            return False
        self.cancel = threading.Event()
        self.current_task = name

        def runner():
            try:
                result = fn(self.cancel)
                self.events.put(("done", name, result))
            except CancelledError:
                self.events.put(("cancelled", name, None))
            except (BlockedError, ImportError_) as exc:
                self.events.put(("error", name, str(exc)))
            except Exception as exc:
                traceback.print_exc()
                self.events.put(("error", name, f"{type(exc).__name__}: {exc}"))

        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()
        return True

    def log(self, text: str) -> None:
        self.events.put(("log", text))

    def progress(self, frac: float, text: str) -> None:
        self.events.put(("progress", getattr(self, "current_task", ""), frac, text))

    def _poll_events(self) -> None:
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                for page in self.pages.values():
                    handler = getattr(page, "on_event", None)
                    if handler:
                        handler(ev)
                if kind in ("done", "error", "cancelled"):
                    self.refresh_summary()
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(config.APP_NAME, "Ein Vorgang läuft noch. Trotzdem beenden?"):
                return
            self.cancel.set()
        self.destroy()

    def settings_changed(self) -> None:
        self.state_.save_settings()
        self.refresh_summary()
        self.pages["review"].dirty = True


# ======================================================================
class ScrollPage(ctk.CTkFrame):
    """A page whose content scrolls (CTkScrollableFrame cannot be raised directly)."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)
        self.body.grid_columnconfigure(0, weight=1)


class ThemesPage(ScrollPage):
    def __init__(self, master, app: App):
        super().__init__(master)
        self.app = app
        st = app.state_.settings
        page_header(self.body, "SCHRITT 1", "Themen & Filter",
                    "Lege fest, welche DC-Figuren auf deine Checkliste kommen. Marvel, Figuren vor "
                    "2008 und DCEU-Filmfiguren (außer Knightmare Batman) sind schon ausgeschlossen."
                    ).grid(row=0, column=0, sticky="ew", pady=(0, 14))

        # --- years
        years = [str(y) for y in range(2000, config.CURRENT_YEAR + 1)]
        c1 = Card(self.body, "Zeitraum", "Erscheinungsjahr der Figur laut BrickLink.")
        c1.grid(row=1, column=0, sticky="ew", pady=6)
        row = ctk.CTkFrame(c1, fg_color="transparent")
        c1.add(row)
        self.year_from = ctk.StringVar(value=str(app.state_.year_from))
        self.year_to = ctk.StringVar(value="heute" if not st.get("year_to") else str(st["year_to"]))
        ctk.CTkLabel(row, text="von", text_color=TEXT).pack(side="left")
        ctk.CTkOptionMenu(row, values=years, variable=self.year_from, width=100,
                          command=lambda _v: self._save()).pack(side="left", padx=8)
        ctk.CTkLabel(row, text="bis", text_color=TEXT).pack(side="left", padx=(10, 0))
        ctk.CTkOptionMenu(row, values=["heute"] + years[::-1], variable=self.year_to, width=100,
                          command=lambda _v: self._save()).pack(side="left", padx=8)
        c1.end()

        # --- groups
        c2 = Card(self.body, "Themen", "Was gehört zu deiner Sammlung?")
        c2.grid(row=2, column=0, sticky="ew", pady=6)
        self.group_vars: dict[str, ctk.BooleanVar] = {}
        on = set(st.get("groups", []))
        for key, label, desc, _default in config.GROUPS:
            var = ctk.BooleanVar(value=key in on)
            self.group_vars[key] = var
            box = ctk.CTkFrame(c2, fg_color="transparent")
            c2.add(box, pady=(6, 0))
            ctk.CTkCheckBox(box, text=label, variable=var, font=_font(13, "bold"),
                            text_color=TEXT, command=self._save, fg_color=BLUE,
                            hover_color=BLUE_HOVER).pack(anchor="w")
            ctk.CTkLabel(box, text=desc, font=_font(12), text_color=MUTED, anchor="w",
                         justify="left", wraplength=640).pack(anchor="w", padx=(30, 0))
        c2.end()

        # --- exclusions
        c3 = Card(self.body, "Ausschlüsse")
        c3.grid(row=3, column=0, sticky="ew", pady=6)
        marvel = ctk.CTkCheckBox(c3, text="Marvel immer ausschließen", font=_font(13, "bold"),
                                 text_color=TEXT, fg_color=BLUE)
        marvel.select()
        marvel.configure(state="disabled")
        c3.add(marvel)
        self.dceu = ctk.BooleanVar(value=st.get("exclude_dceu", True))
        self.knight = ctk.BooleanVar(value=st.get("keep_knightmare", True))
        c3.add(ctk.CTkCheckBox(c3, text="DCEU-Filmfiguren ausschließen", variable=self.dceu,
                               font=_font(13, "bold"), text_color=TEXT, fg_color=BLUE,
                               command=self._save))
        c3.add(ctk.CTkLabel(c3, text="Man of Steel, Batman v Superman / Dawn of Justice, Wonder Woman "
                                     "(2017 & 1984), Justice League (2017), Aquaman (2018), Shazam!",
                            font=_font(12), text_color=MUTED, anchor="w", justify="left",
                            wraplength=640), pady=(0, 0), padx=(48, 18))
        c3.add(ctk.CTkCheckBox(c3, text="… aber Knightmare Batman behalten (sh0532)",
                               variable=self.knight, font=_font(13), text_color=TEXT,
                               fg_color=BLUE, command=self._save), padx=(48, 18))
        c3.add(ctk.CTkLabel(c3, text="Einzelne Figuren kannst du in Schritt 3 jederzeit von Hand "
                                     "auf die Liste nehmen oder herunternehmen.",
                            font=_font(12), text_color=MUTED, anchor="w", justify="left",
                            wraplength=640), pady=(10, 0))
        c3.end()

        # --- data
        c4 = Card(self.body, "Daten")
        c4.grid(row=4, column=0, sticky="ew", pady=6)
        row = ctk.CTkFrame(c4, fg_color="transparent")
        c4.add(row, pady=(12, 0))
        secondary_button(row, "Gespeicherte Bilder löschen", self._clear_cache, width=220).pack(
            side="left")
        secondary_button(row, "Datenordner öffnen", lambda: open_path(data_dir()),
                         width=180).pack(side="left", padx=10)
        c4.end()

        primary_button(self.body, "Weiter: Katalog importieren  →", lambda: app.show("load"),
                       width=260).grid(row=5, column=0, sticky="e", pady=(14, 6))

    def _save(self) -> None:
        st = self.app.state_.settings
        st["year_from"] = int(self.year_from.get())
        yt = self.year_to.get()
        st["year_to"] = None if yt == "heute" else int(yt)
        if st["year_to"] and st["year_to"] < st["year_from"]:
            st["year_to"] = st["year_from"]
            self.year_to.set(str(st["year_from"]))
        st["groups"] = [k for k, v in self.group_vars.items() if v.get()]
        st["exclude_dceu"] = bool(self.dceu.get())
        st["keep_knightmare"] = bool(self.knight.get())
        self.app.settings_changed()

    def _clear_cache(self) -> None:
        if messagebox.askyesno(config.APP_NAME, "Gespeicherte Figurenbilder löschen?\n"
                               "(Sie werden beim nächsten PDF neu geladen.)"):
            n = clear_cache()
            messagebox.showinfo(config.APP_NAME, f"{n} Dateien gelöscht.")


# ======================================================================
class LoadPage(ScrollPage):
    """Step 2: import BrickLink's official catalog download."""

    def __init__(self, master, app: App):
        super().__init__(master)
        self.app = app
        body = self.body
        page_header(body, "SCHRITT 2", "BrickLink-Katalog importieren",
                    "BrickLink bietet angemeldeten Mitgliedern den kompletten Minifiguren-Katalog "
                    "als Datei an. Die App liest daraus alle DC-Figuren und lädt danach die Bilder. "
                    "Ein kostenloses BrickLink-Konto reicht.").grid(row=0, column=0, sticky="ew")

        steps = Card(body, "So geht's")
        steps.grid(row=1, column=0, sticky="ew", pady=(16, 6))

        def step(num: str, text: str, widget=None):
            row = ctk.CTkFrame(steps, fg_color="transparent")
            steps.add(row, pady=(10, 0))
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=num, width=30, height=30, corner_radius=15, fg_color=BLUE,
                         text_color="white", font=_font(13, "bold")).grid(row=0, column=0, sticky="n")
            ctk.CTkLabel(row, text=text, font=_font(13), text_color=TEXT, anchor="w",
                         justify="left", wraplength=620).grid(row=0, column=1, sticky="w", padx=12)
            if widget:
                widget(row).grid(row=1, column=1, sticky="w", padx=12, pady=(6, 0))

        step("1", "Download-Seite von BrickLink öffnen und anmelden.",
             lambda m: secondary_button(m, "BrickLink-Download-Seite öffnen  ↗",
                                        lambda: webbrowser.open(DOWNLOAD_PAGE), width=260))
        step("2", "Dort wählen:  What to download: „Catalog Items“  ·  Item Type: „Minifigures“  ·  "
                  "Category: „All“  ·  File Format: „Tab-Delimited File“  ·  falls angeboten: "
                  "„Year Released“ ankreuzen.  Dann „Download“ – es entsteht die Datei "
                  "„Minifigures.txt“.")
        step("3", "Die Datei hier importieren:",
             lambda m: self._import_buttons(m))
        self.found = ctk.CTkLabel(steps, text="", font=_font(12), text_color=MUTED, anchor="w",
                                  justify="left", wraplength=660)
        steps.add(self.found, pady=(8, 0), padx=(60, 18))
        steps.end()

        prog = Card(body)
        prog.grid(row=2, column=0, sticky="ew", pady=6)
        self.status = ctk.CTkLabel(prog, text="Bereit.", font=_font(13), text_color=TEXT, anchor="w")
        prog.add(self.status, pady=(14, 0))
        self.bar = ctk.CTkProgressBar(prog, height=12, corner_radius=6, progress_color=BLUE)
        self.bar.set(0)
        prog.add(self.bar, pady=(6, 0))
        row = ctk.CTkFrame(prog, fg_color="transparent")
        prog.add(row, pady=(10, 0))
        self.img_btn = secondary_button(row, "Fehlende Bilder laden", self.load_images, width=190)
        self.img_btn.pack(side="left")
        self.cancel_btn = secondary_button(row, "Abbrechen", self.stop, width=120, state="disabled")
        self.cancel_btn.pack(side="left", padx=10)
        prog.end()

        self.result = Card(body)
        self.result_label = ctk.CTkLabel(self.result, text="", font=_font(14), text_color=TEXT,
                                         justify="left", anchor="w")
        self.result.add(self.result_label, pady=(14, 0))
        rrow = ctk.CTkFrame(self.result, fg_color="transparent")
        self.result.add(rrow, pady=(10, 0))
        primary_button(rrow, "Weiter: Auswahl prüfen  →", lambda: app.show("review"),
                       width=230).pack(side="left")
        secondary_button(rrow, "Direkt zum PDF", lambda: app.show("pdf"), width=150).pack(
            side="left", padx=10)
        self.result.end()

        self.logbox = ctk.CTkTextbox(body, height=170, font=ctk.CTkFont(size=12), fg_color=CARD,
                                     border_width=1, border_color=CARD_BORDER, corner_radius=12,
                                     text_color=TEXT)
        self.logbox.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.logbox.configure(state="disabled")
        self._show_result()
        self._look_for_download()

    def _import_buttons(self, master):
        box = ctk.CTkFrame(master, fg_color="transparent")
        self.pick_btn = primary_button(box, "Datei auswählen …", self.pick_file, width=190)
        self.pick_btn.pack(side="left")
        self.quick_btn = secondary_button(box, "", self.import_found, width=10)
        return box

    def on_show(self) -> None:
        self._show_result()
        self._look_for_download()

    def _look_for_download(self) -> None:
        self._found_path = find_recent_download()
        last = self.app.state_.catalog_meta.get("file_mtime", 0)
        if self._found_path is not None:
            when = dt.datetime.fromtimestamp(self._found_path.stat().st_mtime)
            newer = self._found_path.stat().st_mtime > last + 1
            self.quick_btn.configure(text=f"„{self._found_path.name}“ vom {when:%d.%m.%Y} importieren")
            self.quick_btn.pack(side="left", padx=10)
            self.found.configure(text=("Neue Datei im Download-Ordner gefunden: " if newer else
                                       "Im Download-Ordner: ") + str(self._found_path))
        else:
            self.quick_btn.pack_forget()
            self.found.configure(text="")

    def _show_result(self) -> None:
        st = self.app.state_
        if not st.figures:
            self.result.grid_forget()
            return
        dec = st.decisions()
        sel = sum(1 for d in dec.values() if d.include)
        reasons: dict[str, int] = {}
        for d in dec.values():
            if not d.include:
                reasons[d.reason] = reasons.get(d.reason, 0) + 1
        meta = st.catalog_meta
        src = meta.get("file_name") or "BrickLink"
        lines = [f"✔  {len(st.figures)} DC-Figuren aus „{src}“ – {sel} davon kommen auf deine Liste."]
        if reasons:
            lines.append("Nicht auf der Liste: " + ", ".join(
                f"{n}× {r}" for r, n in sorted(reasons.items(), key=lambda x: -x[1])))
        for w in meta.get("warnings", []):
            lines.append("⚠  " + w)
        missing = sum(1 for f in st.selected() if not image_path(f.item_id).exists())
        if missing:
            lines.append(f"Noch {missing} Bilder nicht geladen – das passiert beim PDF automatisch.")
        self.result_label.configure(text="\n".join(lines), wraplength=760)
        self.result.grid(row=3, column=0, sticky="ew", pady=6)

    def _append(self, text: str) -> None:
        self.logbox.configure(state="normal")
        self.logbox.insert("end", text + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    # ------------------------------------------------------------ actions
    def pick_file(self) -> None:
        start = self._found_path.parent if self._found_path else Path.home() / "Downloads"
        paths = filedialog.askopenfilenames(
            title="BrickLink-Katalog auswählen (Minifigures.txt)",
            initialdir=str(start if start.is_dir() else Path.home()),
            filetypes=[("BrickLink-Katalog", "*.txt *.xml *.tsv"), ("Alle Dateien", "*")])
        if paths:
            self.start_import([Path(p) for p in paths])

    def import_found(self) -> None:
        if self._found_path:
            self.start_import([self._found_path])

    def start_import(self, paths: list[Path]) -> None:
        st = self.app.state_

        def task(cancel):
            self.app.log(f"Lese {', '.join(p.name for p in paths)} …")
            self.app.progress(0.05, "Lese Katalog …")
            res = import_catalog(paths)
            self.app.log(f"  {res.total_rows} Minifiguren in der Datei, davon {len(res.figures)} DC, "
                         f"{res.marvel} Marvel aussortiert")
            for w in res.warnings:
                self.app.log("  Hinweis: " + w)
            main = next((p for p in paths if p.name == res.file_name), paths[0])
            st.set_catalog(res.figures, 0, 9999, source="import", file_name=res.file_name,
                           file_mtime=main.stat().st_mtime, warnings=res.warnings)
            wanted = st.selected()
            self.app.log(f"  {len(wanted)} Figuren auf deiner Liste – lade die Bilder …")
            client = Client(log=self.app.log, cancel=cancel)
            try:
                missing = download_images(client, wanted, lambda f, t: self.app.progress(
                    0.1 + 0.9 * f, t), self.app.log, cancel)
            finally:
                client.close()
            return len(res.figures), missing

        if self.app.run_task("load", task):
            self._busy(True)
            self.bar.set(0)
            self.status.configure(text="Importiere …")
            self._append(f"— {dt.datetime.now():%d.%m.%Y %H:%M} —")

    def load_images(self) -> None:
        st = self.app.state_
        if not st.figures:
            messagebox.showinfo(config.APP_NAME, "Bitte zuerst den Katalog importieren.")
            return
        wanted = st.selected()

        def task(cancel):
            client = Client(log=self.app.log, cancel=cancel)
            try:
                return len(wanted), download_images(client, wanted, self.app.progress,
                                                    self.app.log, cancel)
            finally:
                client.close()

        if self.app.run_task("load", task):
            self._busy(True)
            self.bar.set(0)

    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.pick_btn.configure(state=state)
        self.quick_btn.configure(state=state)
        self.img_btn.configure(state=state)
        self.cancel_btn.configure(state="normal" if busy else "disabled")

    def stop(self) -> None:
        self.app.cancel.set()
        self.status.configure(text="Breche ab …")

    def on_event(self, ev) -> None:
        kind = ev[0]
        if kind == "log":
            self._append(ev[1])
        elif kind == "progress" and ev[1] == "load":
            self.bar.set(max(0.0, min(1.0, ev[2])))
            self.status.configure(text=ev[3])
        elif kind in ("done", "error", "cancelled") and ev[1] == "load":
            self._busy(False)
            if kind == "done":
                self.bar.set(1)
                _n, missing = ev[2]
                self.status.configure(text="Fertig!" + (
                    f" ({missing} Bilder fehlen noch – siehe Protokoll)" if missing else ""))
                self.app.pages["review"].dirty = True
                self._show_result()
                self._look_for_download()
            elif kind == "cancelled":
                self.status.configure(text="Abgebrochen. Schon geladene Bilder bleiben gespeichert.")
                self._show_result()
            else:
                self.status.configure(text="Fehler – siehe Protokoll.")
                self._append("FEHLER: " + str(ev[2]))
                messagebox.showerror(config.APP_NAME, str(ev[2]))


# ======================================================================
class ReviewPage(ctk.CTkFrame):
    COLS = ("list", "own", "id", "name", "year", "cat", "note")

    def __init__(self, master, app: App):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.dirty = True
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        page_header(self, "SCHRITT 3", "Auswahl prüfen",
                    "Doppelklick oder Leertaste: Figur auf die Liste / von der Liste. Taste H oder "
                    "der Stern-Knopf: „hab ich schon“ – diese Figuren werden im PDF vorab abgehakt."
                    ).grid(row=0, column=0, columnspan=2, sticky="ew")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 8))
        self.search = ctk.StringVar()
        self.search.trace_add("write", lambda *_: self.populate())
        ctk.CTkEntry(bar, textvariable=self.search, placeholder_text="Suchen (Name, Nummer, Kategorie) …",
                     width=260, height=34).pack(side="left")
        self.filter = ctk.StringVar(value="Alle")
        ctk.CTkOptionMenu(bar, variable=self.filter, width=190, height=34,
                          values=["Alle", "Auf der Liste", "Nicht auf der Liste", "Hab ich schon",
                                  "Fehlen mir noch", "Manuell geändert"],
                          command=lambda _v: self.populate()).pack(side="left", padx=8)
        self.count = ctk.CTkLabel(bar, text="", text_color=MUTED)
        self.count.pack(side="left", padx=8)
        secondary_button(bar, "Änderungen zurücksetzen", self._reset_overrides,
                         width=180).pack(side="right")

        # tree
        tree_frame = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12, border_width=1,
                                  border_color=CARD_BORDER)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_frame, columns=self.COLS, show="headings",
                                 selectmode="extended", style="DC.Treeview")
        heads = {"list": ("Liste", 52), "own": ("Hab ich", 74), "id": ("Nr.", 78),
                 "name": ("Name", 220), "year": ("Jahr", 48), "cat": ("Kategorie", 110),
                 "note": ("Hinweis", 90)}
        for col, (label, width) in heads.items():
            self.tree.heading(col, text=label, command=lambda c=col: self._sort_by(c))
            self.tree.column(col, width=width, minwidth=40,
                             anchor="center" if col in ("list", "own", "year") else "w",
                             stretch=col in ("name", "cat"))
        vsb = ctk.CTkScrollbar(tree_frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        vsb.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        self.tree.bind("<Double-1>", lambda _e: self.toggle_list())
        self.tree.bind("<space>", lambda _e: self.toggle_list())
        self.tree.bind("<KeyPress-h>", lambda _e: self.toggle_owned())
        self.tree.bind("<KeyPress-H>", lambda _e: self.toggle_owned())

        # detail panel
        side = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12, border_width=1,
                            border_color=CARD_BORDER, width=270)
        side.grid(row=2, column=1, sticky="ns", padx=(12, 0))
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        self.pic = ctk.CTkLabel(side, text="Figur auswählen", text_color=MUTED, width=230, height=230)
        self.pic.grid(row=0, column=0, padx=18, pady=(18, 6))
        self.d_title = ctk.CTkLabel(side, text="", font=_font(14, "bold"), text_color=TEXT,
                                    wraplength=230, justify="left", anchor="w")
        self.d_title.grid(row=1, column=0, sticky="ew", padx=18)
        self.d_info = ctk.CTkLabel(side, text="", font=_font(12), text_color=MUTED,
                                   wraplength=230, justify="left", anchor="w")
        self.d_info.grid(row=2, column=0, sticky="ew", padx=18, pady=(4, 10))
        self.b_list = primary_button(side, "Auf die Liste", self.toggle_list)
        self.b_list.grid(row=3, column=0, sticky="ew", padx=18, pady=4)
        self.b_own = ctk.CTkButton(side, text="★  Hab ich schon", command=self.toggle_owned,
                                   height=38, corner_radius=10, fg_color=GOLD, hover_color=GOLD_HOVER,
                                   text_color=NAVY, font=_font(13, "bold"))
        self.b_own.grid(row=4, column=0, sticky="ew", padx=18, pady=4)
        secondary_button(side, "Auf BrickLink ansehen", self._open_bl).grid(
            row=5, column=0, sticky="ew", padx=18, pady=4)

        self._sort = ("default", False)
        self._photo = None
        self._decisions = {}
        self.style_tree()

    # ----------------------------------------------------------- styling
    def style_tree(self) -> None:
        dark = ctk.get_appearance_mode() == "Dark"
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        scale = ctk.ScalingTracker.get_widget_scaling(self)
        bg = "#1A2230" if dark else "#FFFFFF"
        fg = "#E8EDF4" if dark else "#1B2430"
        head_bg = "#232D3E" if dark else "#EEF2F7"
        sel = "#0B5CAD"
        style.configure("DC.Treeview", background=bg, fieldbackground=bg, foreground=fg,
                        rowheight=int(26 * scale), borderwidth=0, font=("TkDefaultFont", 11))
        style.map("DC.Treeview", background=[("selected", sel)], foreground=[("selected", "white")])
        style.configure("DC.Treeview.Heading", background=head_bg, foreground=fg, relief="flat",
                        font=("TkDefaultFont", 11, "bold"), padding=(6, 6))
        style.map("DC.Treeview.Heading", background=[("active", head_bg)])
        style.layout("DC.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        self.tree.tag_configure("out", foreground="#8A96A6" if not dark else "#6C7889")
        self.tree.tag_configure("own", background="#EAF4EA" if not dark else "#1E3527")

    # ------------------------------------------------------------ data
    def on_show(self) -> None:
        if self.dirty:
            self.populate()

    def _rows(self) -> list[Figure]:
        st = self.app.state_
        self._decisions = st.decisions()
        q = self.search.get().strip().lower()
        flt = self.filter.get()
        rows = []
        for f in st.figures:
            d = self._decisions[f.item_id]
            if q and q not in f"{f.item_id} {f.name} {f.category_label}".lower():
                continue
            if flt == "Auf der Liste" and not d.include:
                continue
            if flt == "Nicht auf der Liste" and d.include:
                continue
            if flt == "Hab ich schon" and f.item_id not in st.owned:
                continue
            if flt == "Fehlen mir noch" and (f.item_id in st.owned or not d.include):
                continue
            if flt == "Manuell geändert" and f.item_id not in st.overrides:
                continue
            rows.append(f)
        key, rev = self._sort
        if key == "id":
            from .catalog import natural_key
            rows.sort(key=lambda f: natural_key(f.item_id), reverse=rev)
        elif key == "name":
            rows.sort(key=lambda f: f.name.lower(), reverse=rev)
        elif key == "year":
            rows.sort(key=lambda f: (f.year or 0), reverse=rev)
        elif key == "cat":
            rows.sort(key=lambda f: f.category_label.lower(), reverse=rev)
        elif key == "list":
            rows.sort(key=lambda f: self._decisions[f.item_id].include, reverse=not rev)
        elif key == "own":
            rows.sort(key=lambda f: f.item_id in st.owned, reverse=not rev)
        else:
            from .catalog import natural_key
            rows.sort(key=lambda f: (not self._decisions[f.item_id].include,
                                     config.GROUP_ORDER.get(classify_group(
                                         f.category_path, f.item_id), 99),
                                     f.category_label, f.year or 0, natural_key(f.item_id)))
        return rows

    def _values(self, f: Figure):
        d = self._decisions[f.item_id]
        own = f.item_id in self.app.state_.owned
        return ("✔" if d.include else "–", "★" if own else "", f.item_id, f.name,
                f.year or "?", f.section, d.reason)

    def _tags(self, f: Figure):
        tags = []
        if not self._decisions[f.item_id].include:
            tags.append("out")
        if f.item_id in self.app.state_.owned:
            tags.append("own")
        return tags

    def populate(self) -> None:
        self.dirty = False
        sel = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        rows = self._rows()
        for f in rows:
            self.tree.insert("", "end", iid=f.item_id, values=self._values(f), tags=self._tags(f))
        keep = [i for i in sel if self.tree.exists(i)]
        if keep:
            self.tree.selection_set(keep)
        st = self.app.state_
        total_sel = sum(1 for d in self._decisions.values() if d.include)
        self.count.configure(text=f"{len(rows)} angezeigt · {total_sel} auf der Liste")
        if not st.figures:
            self.count.configure(text="Noch kein Katalog – bitte zuerst Schritt 2.")

    def _refresh_rows(self, ids) -> None:
        self._decisions = self.app.state_.decisions()
        for iid in ids:
            if self.tree.exists(iid):
                f = self._fig(iid)
                self.tree.item(iid, values=self._values(f), tags=self._tags(f))
        total_sel = sum(1 for d in self._decisions.values() if d.include)
        self.count.configure(text=f"{len(self.tree.get_children())} angezeigt · {total_sel} auf der Liste")
        self._on_select()
        self.app.refresh_summary()

    def _fig(self, iid: str) -> Figure:
        for f in self.app.state_.figures:
            if f.item_id == iid:
                return f
        raise KeyError(iid)

    def _sort_by(self, col: str) -> None:
        key, rev = self._sort
        self._sort = (col, not rev if key == col else False)
        self.populate()

    # ---------------------------------------------------------- actions
    def toggle_list(self) -> None:
        ids = list(self.tree.selection())
        if not ids:
            return
        st = self.app.state_
        auto = st.decisions()
        target = not all(auto[i].include for i in ids)
        for iid in ids:
            st.overrides.pop(iid, None)
            base = st.decisions()[iid].include
            if base != target:
                st.overrides[iid] = target
        st.save_collection()
        self._refresh_rows(ids)

    def toggle_owned(self) -> None:
        ids = list(self.tree.selection())
        if not ids:
            return
        st = self.app.state_
        target = not all(i in st.owned for i in ids)
        for iid in ids:
            if target:
                st.owned.add(iid)
            else:
                st.owned.discard(iid)
        st.save_collection()
        self._refresh_rows(ids)

    def _reset_overrides(self) -> None:
        st = self.app.state_
        if st.overrides and messagebox.askyesno(config.APP_NAME,
                                                f"{len(st.overrides)} manuelle Änderungen zurücksetzen?"):
            st.overrides.clear()
            st.save_collection()
            self.populate()
            self.app.refresh_summary()

    def _open_bl(self) -> None:
        ids = self.tree.selection()
        if ids:
            webbrowser.open(bl.item_url(ids[0]))

    def _on_select(self) -> None:
        ids = self.tree.selection()
        if not ids:
            return
        f = self._fig(ids[0])
        d = self._decisions.get(f.item_id) or self.app.state_.decisions()[f.item_id]
        own = f.item_id in self.app.state_.owned
        self.d_title.configure(text=f"{f.item_id}\n{f.name}")
        info = [f"Jahr: {f.year or 'unbekannt'}", f"Kategorie: {f.category_label}"]
        if f.dceu_sets:
            info.append("In DCEU-Sets: " + ", ".join(f.dceu_sets))
        info.append(("Auf der Liste" if d.include else "Nicht auf der Liste")
                    + (f" ({d.reason})" if d.reason else ""))
        if len(ids) > 1:
            info.append(f"\n{len(ids)} Figuren markiert – die Knöpfe gelten für alle.")
        self.d_info.configure(text="\n".join(info))
        self.b_list.configure(text="Von der Liste nehmen" if d.include else "Auf die Liste")
        self.b_own.configure(text="☆  Doch nicht gesammelt" if own else "★  Hab ich schon")
        self._show_picture(f)

    def _show_picture(self, f: Figure) -> None:
        path = image_path(f.item_id)
        if path.exists():
            try:
                with Image.open(path) as im:
                    im = im.convert("RGBA")
                    im.thumbnail((230, 230))
                    self._photo = ctk.CTkImage(light_image=im.copy(), size=im.size)
                self.pic.configure(image=self._photo, text="")
                return
            except Exception:
                pass
        self.pic.configure(image=None, text="Bild wird geladen …")
        item_id = f.item_id

        def fetch():
            client = Client()
            for url in bl.image_urls(f.item_id, f.thumb):
                data = client.get_binary(url)
                if data and len(data) > 200:
                    path.write_bytes(data)
                    break
            self.after(0, lambda: self._after_fetch(item_id))

        threading.Thread(target=fetch, daemon=True).start()

    def _after_fetch(self, item_id: str) -> None:
        ids = self.tree.selection()
        if ids and ids[0] == item_id:
            if image_path(item_id).exists():
                self._show_picture(self._fig(item_id))
            else:
                self.pic.configure(image=None, text="Kein Bild gefunden")

    def on_event(self, ev) -> None:
        if ev[0] == "done" and ev[1] == "load":
            self.dirty = True


# ======================================================================
class PdfPage(ScrollPage):
    def __init__(self, master, app: App):
        super().__init__(master)
        self.app = app
        self.last_pdf: Path | None = None
        p = app.state_.settings["pdf"]
        st = app.state_.settings
        page_header(self.body, "SCHRITT 4", "PDF erstellen",
                    "Alle Figuren deiner Liste im Raster – mit Kästchen zum Abhaken. Die Kästchen "
                    "kann man im PDF anklicken oder ausgedruckt mit dem Stift ankreuzen."
                    ).grid(row=0, column=0, sticky="ew", pady=(0, 14))

        c = Card(self.body, "Layout")
        c.grid(row=1, column=0, sticky="ew", pady=6)
        self.title_var = ctk.StringVar(value=p.get("title"))
        self.title_var.trace_add("write", lambda *_: self._save())
        c.add(ctk.CTkLabel(c, text="Titel", text_color=MUTED, anchor="w"))
        c.add(ctk.CTkEntry(c, textvariable=self.title_var, height=34), pady=(2, 0))

        grid = ctk.CTkFrame(c, fg_color="transparent")
        c.add(grid, pady=(12, 0))
        for i in range(2):
            grid.grid_columnconfigure(i, weight=1)

        def labeled(r, col, text, widget):
            box = ctk.CTkFrame(grid, fg_color="transparent")
            box.grid(row=r, column=col, sticky="w", pady=6, padx=(0, 20))
            ctk.CTkLabel(box, text=text, text_color=MUTED, anchor="w").pack(anchor="w")
            widget(box).pack(anchor="w", pady=(2, 0))

        self.paper = ctk.StringVar(value=p.get("paper", "A4"))
        labeled(0, 0, "Papier", lambda m: ctk.CTkSegmentedButton(
            m, values=["A4", "Letter"], variable=self.paper, command=lambda _v: self._save(),
            selected_color=BLUE, selected_hover_color=BLUE_HOVER))
        orient_map = {"Hochformat": "portrait", "Querformat": "landscape"}
        self.orient_map = orient_map
        self.orient = ctk.StringVar(value={v: k for k, v in orient_map.items()}.get(
            p.get("orientation", "portrait"), "Hochformat"))
        labeled(0, 1, "Ausrichtung", lambda m: ctk.CTkSegmentedButton(
            m, values=list(orient_map), variable=self.orient, command=lambda _v: self._save(),
            selected_color=BLUE, selected_hover_color=BLUE_HOVER))

        self.cols_label = ctk.CTkLabel(grid, text="", text_color=MUTED, anchor="w")
        self.cols_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.cols = ctk.CTkSlider(grid, from_=3, to=10, number_of_steps=7, width=260,
                                  command=lambda _v: self._save(), button_color=BLUE,
                                  progress_color=BLUE)
        self.cols.set(int(p.get("columns", 6)))
        self.cols.grid(row=2, column=0, sticky="w", pady=(2, 6))

        group_map = {"Nach BrickLink-Kategorie": "category", "Nach Thema": "theme",
                     "Nach Jahr": "year", "Keine Gruppen": "none"}
        sort_map = {"Nach Jahr": "year", "Nach Nummer": "id", "Nach Name": "name"}
        self.group_map, self.sort_map = group_map, sort_map
        self.grouping = ctk.StringVar(value={v: k for k, v in group_map.items()}.get(
            st.get("grouping", "category"), "Nach BrickLink-Kategorie"))
        self.sorting = ctk.StringVar(value={v: k for k, v in sort_map.items()}.get(
            st.get("sort_by", "year"), "Nach Jahr"))
        labeled(1, 1, "Gruppierung", lambda m: ctk.CTkOptionMenu(
            m, values=list(group_map), variable=self.grouping, command=lambda _v: self._save(),
            width=230))
        labeled(3, 1, "Sortierung innerhalb der Gruppe", lambda m: ctk.CTkOptionMenu(
            m, values=list(sort_map), variable=self.sorting, command=lambda _v: self._save(),
            width=230))
        c.end()

        c2 = Card(self.body, "Anzeige pro Figur")
        c2.grid(row=2, column=0, sticky="ew", pady=6)
        self.flags: dict[str, ctk.BooleanVar] = {}
        for key, label in [("show_id", "BrickLink-Nummer"), ("show_name", "Name"),
                           ("show_year", "Jahr"),
                           ("fillable", "Kästchen im PDF anklickbar"),
                           ("precheck_owned", "„Hab ich schon“-Figuren vorab abhaken"),
                           ("new_page_per_section", "Jede Gruppe auf einer neuen Seite")]:
            var = ctk.BooleanVar(value=bool(p.get(key, True)))
            self.flags[key] = var
            c2.add(ctk.CTkCheckBox(c2, text=label, variable=var, text_color=TEXT, fg_color=BLUE,
                                   command=self._save), pady=(8, 0))
        c2.end()

        c3 = Card(self.body)
        c3.grid(row=3, column=0, sticky="ew", pady=6)
        self.summary = ctk.CTkLabel(c3, text="", font=_font(14), text_color=TEXT, anchor="w",
                                    justify="left")
        c3.add(self.summary, pady=(16, 0))
        row = ctk.CTkFrame(c3, fg_color="transparent")
        c3.add(row, pady=(12, 0))
        self.make_btn = primary_button(row, "PDF erstellen …", self.make_pdf, width=200)
        self.make_btn.pack(side="left")
        self.open_btn = secondary_button(row, "PDF öffnen", lambda: self.last_pdf and open_path(
            self.last_pdf), width=130, state="disabled")
        self.open_btn.pack(side="left", padx=10)
        self.folder_btn = secondary_button(row, "Ordner öffnen", lambda: self.last_pdf and open_path(
            self.last_pdf.parent), width=130, state="disabled")
        self.folder_btn.pack(side="left")
        self.status = ctk.CTkLabel(c3, text="", text_color=MUTED, anchor="w")
        c3.add(self.status, pady=(10, 0))
        self.bar = ctk.CTkProgressBar(c3, height=10, progress_color=BLUE)
        self.bar.set(0)
        c3.add(self.bar, pady=(4, 0))
        c3.end()
        self._update_summary()

    def on_show(self) -> None:
        self._update_summary()

    def _save(self) -> None:
        p = self.app.state_.settings["pdf"]
        p["title"] = self.title_var.get()
        p["paper"] = self.paper.get()
        p["orientation"] = self.orient_map[self.orient.get()]
        p["columns"] = int(round(self.cols.get()))
        for k, v in self.flags.items():
            p[k] = bool(v.get())
        st = self.app.state_.settings
        st["grouping"] = self.group_map[self.grouping.get()]
        st["sort_by"] = self.sort_map[self.sorting.get()]
        self.app.state_.save_settings()
        self._update_summary()

    def _update_summary(self) -> None:
        self.cols_label.configure(text=f"Figuren pro Zeile: {int(round(self.cols.get()))}")
        st = self.app.state_
        if not st.figures:
            self.summary.configure(text="Noch kein Katalog geladen – bitte zuerst Schritt 2.")
            self.make_btn.configure(state="disabled")
            return
        self.make_btn.configure(state="normal")
        sections = st.sections()
        n = sum(len(f) for _s, f in sections)
        pages = estimate_pages(sections, st.pdf_options()) if n else 0
        owned = sum(1 for _s, figs in sections for f in figs if f.item_id in st.owned)
        self.summary.configure(text=f"{n} Figuren in {len(sections)} Gruppen  ·  ca. {pages} Seiten"
                                    f"  ·  {owned} schon gesammelt")

    def make_pdf(self) -> None:
        st = self.app.state_
        if not st.catalog_covers_settings():
            if not messagebox.askyesno(config.APP_NAME, "Der Zeitraum passt nicht mehr zum geladenen "
                                       "Katalog. Trotzdem mit dem alten Katalog fortfahren?"):
                return
        name = f"DC_Minifiguren_Checkliste_{dt.date.today():%Y-%m-%d}.pdf"
        path = filedialog.asksaveasfilename(
            title="PDF speichern unter", defaultextension=".pdf", initialfile=name,
            initialdir=str(default_output_dir()), filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        figs = st.selected()
        sections = st.sections(figs)
        opts = st.pdf_options()
        owned = set(st.owned)
        out = Path(path)

        def task(cancel):
            client = Client(log=self.app.log, cancel=cancel)
            try:
                download_images(client, figs, lambda f, t: self.app.progress(f * 0.5, t),
                                self.app.log, cancel)
            finally:
                client.close()
            build_pdf(out, sections, opts, owned,
                      progress=lambda f, t: self.app.progress(0.5 + f * 0.5, t))
            return str(out)

        if self.app.run_task("pdf", task):
            self.make_btn.configure(state="disabled")
            self.status.configure(text="Erstelle PDF …")
            self.bar.set(0)

    def on_event(self, ev) -> None:
        kind = ev[0]
        if kind == "progress" and ev[1] == "pdf":
            self.bar.set(max(0.0, min(1.0, ev[2])))
            self.status.configure(text=ev[3])
        elif kind in ("done", "error", "cancelled") and ev[1] == "pdf":
            self.make_btn.configure(state="normal")
            if kind == "done":
                self.last_pdf = Path(ev[2])
                self.bar.set(1)
                self.status.configure(text=f"Gespeichert: {self.last_pdf}")
                self.open_btn.configure(state="normal")
                self.folder_btn.configure(state="normal")
                open_path(self.last_pdf)
            elif kind == "error":
                self.status.configure(text="Fehler beim Erstellen.")
                messagebox.showerror(config.APP_NAME, str(ev[2]))
            else:
                self.status.configure(text="Abgebrochen.")
        elif kind == "done" and ev[1] == "load":
            self._update_summary()


def main() -> None:
    app = App()
    app.mainloop()
