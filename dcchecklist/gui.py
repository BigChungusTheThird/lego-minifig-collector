"""Desktop app (customtkinter) – Windows, macOS and Linux.

The collection is the centre of the app and works offline; importing the
catalog, loading pictures and prices are the only steps that go online.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import ImageTk

from . import config
from . import prices as pr
from . import thumbs
from .catalog import download_images, image_path
from .collection_view import CollectionPage
from .icon import make_icon
from .importer import DOWNLOAD_PAGE, ImportError_, find_recent_download, import_catalog
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
OK = "#1E8E3E"
OK_HOVER = "#17732F"
COLORS = dict(NAVY=NAVY, BLUE=BLUE, BLUE_HOVER=BLUE_HOVER, GOLD=GOLD, GOLD_HOVER=GOLD_HOVER,
              CARD=CARD, CARD_BORDER=CARD_BORDER, TEXT=TEXT, MUTED=MUTED, OK=OK, OK_HOVER=OK_HOVER)


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
                         justify="left", wraplength=680).grid(
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
    if step:
        ctk.CTkLabel(f, text=step, font=_font(12, "bold"), text_color=BLUE, anchor="w").pack(anchor="w")
    ctk.CTkLabel(f, text=title, font=_font(24, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
    ctk.CTkLabel(f, text=text, font=_font(13), text_color=MUTED, anchor="w", justify="left",
                 wraplength=780).pack(anchor="w", pady=(2, 0))
    return f


def primary_button(master, text, command, **kw):
    return ctk.CTkButton(master, text=text, command=command, height=38, corner_radius=10,
                         fg_color=BLUE, hover_color=BLUE_HOVER, font=_font(14, "bold"), **kw)


def secondary_button(master, text, command, **kw):
    return ctk.CTkButton(master, text=text, command=command, height=34, corner_radius=10,
                         fg_color=("#E6EBF2", "#273246"), hover_color=("#D6DDE8", "#323F57"),
                         text_color=TEXT, font=_font(13), **kw)


class ScrollPage(ctk.CTkFrame):
    """A page whose content scrolls (CTkScrollableFrame cannot be raised directly)."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)
        self.body.grid_columnconfigure(0, weight=1)


# ======================================================================
class App(ctk.CTk):
    NAV = [("collection", "Sammlung"), ("themes", "Themen & Filter"),
           ("catalog", "Katalog & Daten"), ("prices", "Preise"), ("export", "PDF & Export")]

    def __init__(self) -> None:
        self.state_ = State()
        ctk.set_appearance_mode(self.state_.settings.get("appearance", "System"))
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.title(config.APP_NAME)
        self.geometry("1360x860")
        self.minsize(1080, 680)
        self.configure(fg_color=BG)
        try:
            self._icon = ImageTk.PhotoImage(make_icon(256))
            self.iconphoto(True, self._icon)
        except Exception:
            pass

        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel = threading.Event()
        self.current_task = ""

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=24, pady=20)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.pages = {
            "collection": CollectionPage(self.content, self, COLORS),
            "themes": ThemesPage(self.content, self),
            "catalog": CatalogPage(self.content, self),
            "prices": PricesPage(self.content, self),
            "export": ExportPage(self.content, self),
        }
        for p in self.pages.values():
            p.grid(row=0, column=0, sticky="nsew")
        self._toast = ctk.CTkLabel(self, text="", fg_color=NAVY, text_color="white",
                                   corner_radius=10, font=_font(13))
        self._toast_job = None
        self.show("collection" if self.state_.figures else "catalog")
        self.refresh_summary()
        self.after(120, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------- sidebar
    def _build_sidebar(self) -> None:
        sb = ctk.CTkFrame(self, fg_color=NAVY, corner_radius=0, width=240)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)

        logo = ctk.CTkImage(make_icon(128), size=(44, 44))
        head = ctk.CTkFrame(sb, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 14))
        ctk.CTkLabel(head, image=logo, text="").pack(side="left")
        tbox = ctk.CTkFrame(head, fg_color="transparent")
        tbox.pack(side="left", padx=10)
        ctk.CTkLabel(tbox, text="DC Minifiguren", font=_font(16, "bold"),
                     text_color="white", anchor="w").pack(anchor="w")
        ctk.CTkLabel(tbox, text="Sammlung", font=_font(13), text_color=GOLD,
                     anchor="w").pack(anchor="w")

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for i, (key, label) in enumerate(self.NAV):
            b = ctk.CTkButton(sb, text=label, anchor="w", height=40, corner_radius=10,
                              fg_color="transparent", hover_color=NAVY_2, text_color="#DCE6F2",
                              font=_font(14), command=lambda k=key: self.show(k))
            b.grid(row=1 + i, column=0, sticky="ew", padx=12, pady=2)
            self.nav_buttons[key] = b

        box = ctk.CTkFrame(sb, fg_color=NAVY_2, corner_radius=12)
        box.grid(row=7, column=0, sticky="ew", padx=14, pady=(22, 0))
        self.sum_title = ctk.CTkLabel(box, text="", font=_font(20, "bold"), text_color="white",
                                      anchor="w")
        self.sum_title.pack(anchor="w", padx=14, pady=(12, 0))
        self.sum_bar = ctk.CTkProgressBar(box, height=8, progress_color=GOLD, fg_color="#24456A")
        self.sum_bar.set(0)
        self.sum_bar.pack(fill="x", padx=14, pady=(6, 4))
        self.summary = ctk.CTkLabel(box, text="", font=_font(12), text_color="#AFC2D8",
                                    justify="left", anchor="w", wraplength=190)
        self.summary.pack(anchor="w", padx=14, pady=(0, 12))
        sb.grid_rowconfigure(8, weight=1)

        ctk.CTkLabel(sb, text="Darstellung", font=_font(11), text_color="#8EA3BC",
                     anchor="w").grid(row=9, column=0, sticky="ew", padx=20)
        mode_map = {"System": "System", "Hell": "Light", "Dunkel": "Dark"}
        inv = {v: k for k, v in mode_map.items()}
        self.mode_var = ctk.StringVar(value=inv.get(self.state_.settings.get("appearance", "System"),
                                                    "System"))

        def set_mode(v):
            ctk.set_appearance_mode(mode_map[v])
            self.state_.settings["appearance"] = mode_map[v]
            self.state_.save_settings()
            self.after(80, self.pages["collection"].restyle)

        ctk.CTkSegmentedButton(sb, values=list(mode_map), variable=self.mode_var,
                               command=set_mode, selected_color=BLUE,
                               selected_hover_color=BLUE_HOVER, unselected_color=NAVY_2,
                               unselected_hover_color="#1C4670", text_color="white").grid(
            row=10, column=0, sticky="ew", padx=18, pady=(4, 10))
        ctk.CTkLabel(sb, text=f"Version {config.APP_VERSION} · funktioniert offline\n"
                              "Daten & Bilder: BrickLink.com",
                     font=_font(10), text_color="#6F86A1", justify="left",
                     anchor="w").grid(row=11, column=0, sticky="ew", padx=20, pady=(0, 16))

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
            self.sum_title.configure(text="–")
            self.sum_bar.set(0)
            self.summary.configure(text="Noch kein Katalog.\nUnter „Katalog & Daten“ importieren.")
            return
        sel = st.selected()
        prog = st.progress(sel)
        self.sum_title.configure(text=f"{prog.owned} / {prog.total}")
        self.sum_bar.set(prog.owned / prog.total if prog.total else 0)
        ids = {f.item_id for f in sel}
        lines = [f"{prog.percent} % gesammelt", f"{len(st.wishlist & ids)} auf der Wunschliste"]
        if st.prices:
            have, _ = st.value([f for f in sel if f.item_id in st.owned])
            lines.append(f"Wert ca. {pr.money(have, st.currency)}")
        self.summary.configure(text="\n".join(lines))

    def toast(self, text: str, ms: int = 2600) -> None:
        self._toast.configure(text="  " + text + "  ")
        self._toast.place(relx=0.58, rely=0.975, anchor="s")
        self._toast.lift()
        if self._toast_job:
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(ms, self._toast.place_forget)

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
            except (BlockedError, ImportError_, pr.PriceError) as exc:
                self.events.put(("error", name, str(exc)))
            except Exception as exc:
                traceback.print_exc()
                self.events.put(("error", name, f"{type(exc).__name__}: {exc}"))

        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()
        return True

    def log(self, text: str) -> None:
        self.events.put(("log", self.current_task, text))

    def progress(self, frac: float, text: str) -> None:
        self.events.put(("progress", self.current_task, frac, text))

    def _poll_events(self) -> None:
        try:
            while True:
                ev = self.events.get_nowait()
                for page in self.pages.values():
                    handler = getattr(page, "on_event", None)
                    if handler:
                        handler(ev)
                if ev[0] in ("done", "error", "cancelled"):
                    self.refresh_summary()
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(config.APP_NAME, "Ein Vorgang läuft noch. Trotzdem beenden?"):
                return
            self.cancel.set()
        try:
            self.pages["collection"].detail._save_note()
        except Exception:
            pass
        self.destroy()

    def settings_changed(self) -> None:
        self.state_.settings_changed()
        self.refresh_summary()
        self.pages["collection"].dirty = True


# ======================================================================
class ThemesPage(ScrollPage):
    def __init__(self, master, app: App):
        super().__init__(master)
        self.app = app
        st = app.state_.settings
        body = self.body
        page_header(body, "", "Themen & Filter",
                    "Was gehört zu deiner Sammlung? Marvel, Figuren vor 2008 und DCEU-Filmfiguren "
                    "(außer Knightmare Batman) sind voreingestellt ausgeschlossen. Einzelne Figuren "
                    "kannst du in der Sammlung jederzeit aus- und wieder einblenden."
                    ).grid(row=0, column=0, sticky="ew", pady=(0, 14))

        years = [str(y) for y in range(2000, config.CURRENT_YEAR + 1)]
        c1 = Card(body, "Zeitraum", "Erscheinungsjahr der Figur laut BrickLink.")
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

        c2 = Card(body, "Themen")
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

        c3 = Card(body, "Ausschlüsse")
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
        row = ctk.CTkFrame(c3, fg_color="transparent")
        c3.add(row, pady=(14, 0))
        self.ov_label = ctk.CTkLabel(row, text="", text_color=MUTED)
        self.ov_label.pack(side="left")
        secondary_button(row, "Alle manuellen Ein-/Ausblendungen zurücksetzen", self._reset,
                         width=330).pack(side="left", padx=12)
        c3.end()

    def on_show(self):
        n = len(self.app.state_.overrides)
        self.ov_label.configure(text=f"{n} Figuren von Hand ein- oder ausgeblendet.")

    def _reset(self):
        st = self.app.state_
        if st.overrides and messagebox.askyesno(
                config.APP_NAME, f"{len(st.overrides)} Ein-/Ausblendungen von Hand zurücksetzen?"):
            st.reset_overrides()
            self.app.settings_changed()
            self.on_show()

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


# ======================================================================
class TaskArea:
    """Status line + progress bar + log used by pages that run background tasks."""

    def __init__(self, card: Card, task: str, log_height: int = 0):
        self.task = task
        self.status = ctk.CTkLabel(card, text="", font=_font(13), text_color=TEXT, anchor="w",
                                   justify="left", wraplength=700)
        card.add(self.status, pady=(12, 0))
        self.bar = ctk.CTkProgressBar(card, height=10, progress_color=BLUE)
        self.bar.set(0)
        card.add(self.bar, pady=(6, 0))
        self.logbox = None
        if log_height:
            self.logbox = ctk.CTkTextbox(card, height=log_height, font=_font(12), fg_color=BG,
                                         corner_radius=8, text_color=TEXT)
            card.add(self.logbox, pady=(10, 0))
            self.logbox.configure(state="disabled")

    def append(self, text: str) -> None:
        if self.logbox is None:
            return
        self.logbox.configure(state="normal")
        self.logbox.insert("end", text + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def handle(self, ev) -> str | None:
        """Returns 'done'/'error'/'cancelled' when the task finished."""
        kind = ev[0]
        if ev[1] != self.task:
            return None
        if kind == "log":
            self.append(ev[2])
        elif kind == "progress":
            self.bar.set(max(0.0, min(1.0, ev[2])))
            self.status.configure(text=ev[3])
        elif kind in ("done", "error", "cancelled"):
            if kind == "done":
                self.bar.set(1)
            elif kind == "error":
                self.status.configure(text="Fehler: " + str(ev[2]))
                self.append("FEHLER: " + str(ev[2]))
            else:
                self.status.configure(text="Abgebrochen.")
            return kind
        return None


class CatalogPage(ScrollPage):
    """Import BrickLink's catalog download, load pictures, back up the collection."""

    def __init__(self, master, app: App):
        super().__init__(master)
        self.app = app
        body = self.body
        page_header(body, "", "Katalog & Daten",
                    "Einmal den BrickLink-Katalog importieren und die Bilder laden – danach "
                    "funktioniert die Sammlung komplett offline. Den Katalog kannst du jederzeit "
                    "neu importieren (z. B. wenn neue Sets erscheinen); deine Markierungen bleiben.").grid(
            row=0, column=0, sticky="ew")

        steps = Card(body, "Katalog importieren")
        steps.grid(row=1, column=0, sticky="ew", pady=(14, 6))

        def step(num: str, text: str, widget=None):
            row = ctk.CTkFrame(steps, fg_color="transparent")
            steps.add(row, pady=(10, 0))
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=num, width=30, height=30, corner_radius=15, fg_color=BLUE,
                         text_color="white", font=_font(13, "bold")).grid(row=0, column=0, sticky="n")
            ctk.CTkLabel(row, text=text, font=_font(13), text_color=TEXT, anchor="w",
                         justify="left", wraplength=640).grid(row=0, column=1, sticky="w", padx=12)
            if widget:
                widget(row).grid(row=1, column=1, sticky="w", padx=12, pady=(6, 0))

        step("1", "Download-Seite von BrickLink öffnen und anmelden (kostenloses Konto).",
             lambda m: secondary_button(m, "BrickLink-Download-Seite öffnen  ↗",
                                        lambda: webbrowser.open(DOWNLOAD_PAGE), width=260))
        step("2", "Dort wählen:  What to download: „Catalog Items“  ·  Item Type: „Minifigures“  ·  "
                  "Category: „All“  ·  File Format: „Tab-Delimited File“  ·  falls angeboten: "
                  "„Year Released“ ankreuzen.  Dann „Download“ – es entsteht „Minifigures.txt“.")
        step("3", "Die Datei hier importieren:", self._import_buttons)
        self.found = ctk.CTkLabel(steps, text="", font=_font(12), text_color=MUTED, anchor="w",
                                  justify="left", wraplength=680)
        steps.add(self.found, pady=(8, 0), padx=(60, 18))
        self.result = ctk.CTkLabel(steps, text="", font=_font(13), text_color=TEXT, anchor="w",
                                   justify="left", wraplength=700)
        steps.add(self.result, pady=(12, 0))
        steps.end()

        imgs = Card(body, "Bilder (für den Offline-Betrieb)",
                    "Lädt die Bilder aller Figuren deiner Sammlung einmal von img.bricklink.com "
                    "und speichert sie. Fehlende Bilder werden nachgeladen.")
        imgs.grid(row=2, column=0, sticky="ew", pady=6)
        row = ctk.CTkFrame(imgs, fg_color="transparent")
        imgs.add(row, pady=(10, 0))
        self.img_btn = primary_button(row, "Fehlende Bilder laden", self.load_images, width=210)
        self.img_btn.pack(side="left")
        self.cancel_btn = secondary_button(row, "Abbrechen", lambda: app.cancel.set(), width=120,
                                           state="disabled")
        self.cancel_btn.pack(side="left", padx=10)
        self.offline = ctk.CTkLabel(imgs, text="", font=_font(12), text_color=MUTED, anchor="w")
        imgs.add(self.offline, pady=(8, 0))
        self.task = TaskArea(imgs, "load", log_height=130)
        imgs.end()

        data = Card(body, "Sicherung",
                    "Deine Sammlung (gesammelt, Wunschliste, Notizen, ausgeblendet) als Datei "
                    "sichern – z. B. um sie auf einen anderen Rechner mitzunehmen.")
        data.grid(row=3, column=0, sticky="ew", pady=6)
        row = ctk.CTkFrame(data, fg_color="transparent")
        data.add(row, pady=(10, 0))
        secondary_button(row, "Sammlung sichern …", self.backup, width=170).pack(side="left")
        secondary_button(row, "Sicherung laden …", self.restore, width=170).pack(side="left", padx=10)
        secondary_button(row, "Datenordner öffnen", lambda: open_path(data_dir()),
                         width=170).pack(side="left")
        row2 = ctk.CTkFrame(data, fg_color="transparent")
        data.add(row2, pady=(10, 0))
        secondary_button(row2, "Gespeicherte Bilder löschen", self.clear_images,
                         width=220).pack(side="left")
        data.end()
        self._found_path = None
        self.on_show()

    def _import_buttons(self, master):
        box = ctk.CTkFrame(master, fg_color="transparent")
        self.pick_btn = primary_button(box, "Datei auswählen …", self.pick_file, width=190)
        self.pick_btn.pack(side="left")
        self.quick_btn = secondary_button(box, "", self.import_found, width=10)
        return box

    def on_show(self) -> None:
        self._look_for_download()
        self._show_result()

    def _look_for_download(self) -> None:
        self._found_path = find_recent_download()
        last = self.app.state_.catalog_meta.get("file_mtime", 0)
        if self._found_path is not None:
            mtime = self._found_path.stat().st_mtime
            self.quick_btn.configure(
                text=f"„{self._found_path.name}“ vom {dt.datetime.fromtimestamp(mtime):%d.%m.%Y} importieren")
            self.quick_btn.pack(side="left", padx=10)
            self.found.configure(text=("Neue Datei im Download-Ordner: " if mtime > last + 1 else
                                       "Im Download-Ordner: ") + str(self._found_path))
        else:
            self.quick_btn.pack_forget()
            self.found.configure(text="")

    def _show_result(self) -> None:
        st = self.app.state_
        if not st.figures:
            self.result.configure(text="Noch kein Katalog importiert.")
            self.offline.configure(text="")
            return
        meta = st.catalog_meta
        when = meta.get("fetched", "")[:10]
        try:
            when = dt.date.fromisoformat(when).strftime("%d.%m.%Y")
        except ValueError:
            pass
        sel = st.selected()
        lines = [f"✔  Katalog „{meta.get('file_name') or 'BrickLink'}“ vom {when}: "
                 f"{len(st.figures)} DC-Figuren, {len(sel)} in deiner Sammlung, "
                 f"{len(st.figures) - len(sel)} ausgeblendet."]
        for w in meta.get("warnings", []):
            lines.append("⚠  " + w)
        self.result.configure(text="\n".join(lines))
        missing = sum(1 for f in sel if not image_path(f.item_id).exists())
        self.offline.configure(
            text="✔  Alle Bilder gespeichert – die Sammlung funktioniert offline." if not missing
            else f"Noch {missing} von {len(sel)} Bildern nicht gespeichert.")

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
            self.app.log(f"  {len(wanted)} Figuren in deiner Sammlung – lade fehlende Bilder …")
            client = Client(log=self.app.log, cancel=cancel)
            try:
                missing = download_images(client, wanted, lambda f, t: self.app.progress(
                    0.1 + 0.9 * f, t), self.app.log, cancel)
            finally:
                client.close()
            return len(res.figures), missing

        if self.app.run_task("load", task):
            self._busy(True)
            self.task.bar.set(0)
            self.task.append(f"— {dt.datetime.now():%d.%m.%Y %H:%M} —")

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
            self.task.bar.set(0)

    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for b in (self.pick_btn, self.quick_btn, self.img_btn):
            b.configure(state=state)
        self.cancel_btn.configure(state="normal" if busy else "disabled")

    def on_event(self, ev) -> None:
        kind = self.task.handle(ev)
        if not kind:
            return
        self._busy(False)
        if kind == "done":
            _n, missing = ev[2]
            self.task.status.configure(text="Fertig!" + (
                f" ({missing} Bilder fehlen noch – siehe Protokoll)" if missing else ""))
            thumbs.forget()
            col = self.app.pages["collection"]
            col.cards.forget_photos()
            col.dirty = True
        elif kind == "error":
            messagebox.showerror(config.APP_NAME, str(ev[2]))
        self._show_result()
        self._look_for_download()

    def backup(self) -> None:
        name = f"DC_Sammlung_Sicherung_{dt.date.today():%Y-%m-%d}.json"
        path = filedialog.asksaveasfilename(title="Sammlung sichern", defaultextension=".json",
                                            initialfile=name, initialdir=str(default_output_dir()),
                                            filetypes=[("Sicherung", "*.json")])
        if path:
            Path(path).write_text(json.dumps(self.app.state_.collection_data(), ensure_ascii=False,
                                             indent=1), encoding="utf-8")
            self.app.toast("Sammlung gesichert")

    def restore(self) -> None:
        path = filedialog.askopenfilename(title="Sicherung laden", filetypes=[("Sicherung", "*.json")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            n = len(data.get("owned", []))
            if not messagebox.askyesno(config.APP_NAME, f"Sicherung mit {n} gesammelten Figuren laden?\n"
                                       "Deine aktuelle Sammlung wird dabei ersetzt."):
                return
            self.app.state_.restore_collection(data)
        except (OSError, ValueError, AttributeError) as exc:
            messagebox.showerror(config.APP_NAME, f"Sicherung nicht lesbar:\n{exc}")
            return
        self.app.pages["collection"].dirty = True
        self.app.refresh_summary()
        self.app.toast("Sicherung geladen")

    def clear_images(self) -> None:
        if messagebox.askyesno(config.APP_NAME, "Gespeicherte Bilder löschen?\n"
                               "Ohne Bilder zeigt die Sammlung nur Platzhalter, bis du sie neu lädst."):
            n = clear_cache()
            thumbs.forget()
            self.app.pages["collection"].cards.forget_photos()
            self.app.pages["collection"].dirty = True
            self._show_result()
            messagebox.showinfo(config.APP_NAME, f"{n} Dateien gelöscht.")


# ======================================================================
class PricesPage(ScrollPage):
    """6-month average prices via the official BrickLink API."""

    def __init__(self, master, app: App):
        super().__init__(master)
        self.app = app
        body = self.body
        st = app.state_.settings
        page_header(body, "", "Preise",
                    "Durchschnittlicher Verkaufspreis der letzten 6 Monate pro Figur – aus BrickLinks "
                    "offizieller API, wahlweise für die DACH-Region (Deutschland, Österreich, "
                    "Schweiz), die EU oder Europa. Die Preise werden gespeichert und sind danach "
                    "auch offline sichtbar.").grid(row=0, column=0, sticky="ew")

        keys = Card(body, "BrickLink-API-Zugang",
                    "Einmalig nötig: eigene API-Schlüssel bei BrickLink anlegen (kostenlos). "
                    "1) Bei BrickLink anmelden und die API-Seite öffnen. 2) „Consumer Key“ "
                    "registrieren. 3) Einen „Access Token“ erstellen – als IP-Adresse 0.0.0.0 und "
                    "als Maske 0.0.0.0 eintragen, dann funktioniert er auch mit wechselnder "
                    "Internet-Adresse. 4) Die vier Werte hier eintragen. Hinweis: BrickLink kann für "
                    "den API-Zugang ein Verkäuferprofil verlangen.")
        keys.grid(row=1, column=0, sticky="ew", pady=(14, 6))
        keys.add(secondary_button(keys, "BrickLink-API-Seite öffnen  ↗",
                                  lambda: webbrowser.open(pr.REGISTER_PAGE), width=240),
                 sticky="w", pady=(10, 0))
        creds = pr.load_credentials()
        grid = ctk.CTkFrame(keys, fg_color="transparent")
        keys.add(grid, pady=(10, 0))
        grid.grid_columnconfigure(1, weight=1)
        self.entries: dict[str, ctk.CTkEntry] = {}
        for r, (k, label, secret) in enumerate([("consumer_key", "Consumer Key", False),
                                                ("consumer_secret", "Consumer Secret", True),
                                                ("token", "Token Value", False),
                                                ("token_secret", "Token Secret", True)]):
            ctk.CTkLabel(grid, text=label, text_color=MUTED, anchor="w", width=130).grid(
                row=r, column=0, sticky="w", pady=3)
            e = ctk.CTkEntry(grid, height=32, show="•" if secret else "")
            e.insert(0, getattr(creds, k))
            e.grid(row=r, column=1, sticky="ew", pady=3)
            self.entries[k] = e
        row = ctk.CTkFrame(keys, fg_color="transparent")
        keys.add(row, pady=(10, 0))
        secondary_button(row, "Speichern", self.save_keys, width=120).pack(side="left")
        secondary_button(row, "Verbindung testen", self.test, width=160).pack(side="left", padx=10)
        self.show_secret = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(row, text="Geheime Werte anzeigen", variable=self.show_secret,
                        command=self._toggle_secret, text_color=TEXT, fg_color=BLUE).pack(side="left")
        keys.add(ctk.CTkLabel(keys, text="Die Schlüssel werden nur lokal auf diesem Rechner "
                                         "gespeichert (Datenordner, Datei bricklink_api.json).",
                              font=_font(11), text_color=MUTED, anchor="w"), pady=(6, 0))
        keys.end()

        opts = Card(body, "Einstellungen")
        opts.grid(row=2, column=0, sticky="ew", pady=6)
        g = ctk.CTkFrame(opts, fg_color="transparent")
        opts.add(g, pady=(10, 0))
        region_names = {k: v[0] for k, v in pr.REGIONS.items()}
        self.region_map = {v: k for k, v in region_names.items()}
        self.region = ctk.StringVar(value=region_names.get(st.get("price_region", "dach"),
                                                           region_names["dach"]))
        cond_map = {"Gebraucht und neu": ["U", "N"], "Nur gebraucht": ["U"], "Nur neu": ["N"]}
        self.cond_map = cond_map
        inv_cond = {tuple(v): k for k, v in cond_map.items()}
        self.cond = ctk.StringVar(value=inv_cond.get(tuple(st.get("price_conditions", ["U", "N"])),
                                                     "Gebraucht und neu"))
        prefer_map = {"Gebraucht": "U", "Neu": "N"}
        self.prefer_map = prefer_map
        self.prefer = ctk.StringVar(value="Neu" if st.get("price_prefer") == "N" else "Gebraucht")
        self.currency = ctk.StringVar(value=st.get("price_currency", "EUR"))
        self.age = ctk.StringVar(value=str(st.get("price_max_age", 30)))

        def labeled(r, c, text, w):
            box = ctk.CTkFrame(g, fg_color="transparent")
            box.grid(row=r, column=c, sticky="w", padx=(0, 24), pady=6)
            ctk.CTkLabel(box, text=text, text_color=MUTED, anchor="w").pack(anchor="w")
            w(box).pack(anchor="w", pady=(2, 0))

        labeled(0, 0, "Region", lambda m: ctk.CTkOptionMenu(
            m, values=list(self.region_map), variable=self.region, width=300,
            command=lambda _v: self._save_opts()))
        labeled(0, 1, "Zustand", lambda m: ctk.CTkOptionMenu(
            m, values=list(cond_map), variable=self.cond, width=190, command=lambda _v: self._save_opts()))
        labeled(1, 0, "Auf den Karten anzeigen", lambda m: ctk.CTkSegmentedButton(
            m, values=list(prefer_map), variable=self.prefer, command=lambda _v: self._save_opts(),
            selected_color=BLUE, selected_hover_color=BLUE_HOVER))
        labeled(1, 1, "Währung", lambda m: ctk.CTkSegmentedButton(
            m, values=["EUR", "CHF"], variable=self.currency, command=lambda _v: self._save_opts(),
            selected_color=BLUE, selected_hover_color=BLUE_HOVER))
        labeled(2, 0, "Preise erneuern, wenn älter als (Tage)", lambda m: ctk.CTkOptionMenu(
            m, values=["7", "14", "30", "60", "90"], variable=self.age, width=100,
            command=lambda _v: self._save_opts()))
        self.show_prices = ctk.BooleanVar(value=st.get("show_prices", True))
        opts.add(ctk.CTkCheckBox(opts, text="Preise in der Sammlung anzeigen", variable=self.show_prices,
                                 command=self._save_opts, text_color=TEXT, fg_color=BLUE), pady=(8, 0))
        opts.end()

        run = Card(body, "Preise laden")
        run.grid(row=3, column=0, sticky="ew", pady=6)
        self.calls = ctk.CTkLabel(run, text="", font=_font(12), text_color=MUTED, anchor="w",
                                  justify="left", wraplength=700)
        run.add(self.calls, pady=(10, 0))
        row = ctk.CTkFrame(run, fg_color="transparent")
        run.add(row, pady=(10, 0))
        self.run_btn = primary_button(row, "Preise laden / aktualisieren", self.update_prices, width=250)
        self.run_btn.pack(side="left")
        self.stop_btn = secondary_button(row, "Abbrechen", lambda: app.cancel.set(), width=120,
                                         state="disabled")
        self.stop_btn.pack(side="left", padx=10)
        self.task = TaskArea(run, "prices", log_height=110)
        run.end()

    def _toggle_secret(self):
        for k in ("consumer_secret", "token_secret"):
            self.entries[k].configure(show="" if self.show_secret.get() else "•")

    def creds(self) -> pr.Credentials:
        return pr.Credentials(**{k: e.get().strip() for k, e in self.entries.items()})

    def save_keys(self) -> None:
        pr.save_credentials(self.creds())
        self.app.toast("API-Schlüssel gespeichert")

    def _save_opts(self) -> None:
        st = self.app.state_.settings
        st["price_region"] = self.region_map[self.region.get()]
        st["price_conditions"] = self.cond_map[self.cond.get()]
        st["price_prefer"] = self.prefer_map[self.prefer.get()]
        st["price_currency"] = self.currency.get()
        st["price_max_age"] = int(self.age.get())
        st["show_prices"] = bool(self.show_prices.get())
        self.app.state_.save_settings()
        self.app.pages["collection"].dirty = True
        self.on_show()

    def on_show(self) -> None:
        st = self.app.state_
        s = st.settings
        figs = st.selected()
        region, conds = s.get("price_region", "dach"), s.get("price_conditions", ["U", "N"])
        todo = [f for f in figs if pr.stale(st.prices.get(f.item_id), region,
                                            int(s.get("price_max_age", 30)), conds, st.currency)]
        per = pr.calls_per_figure(region, conds)
        have = sum(1 for f in figs if st.prices.get(f.item_id))
        self.calls.configure(text=(
            f"{have} von {len(figs)} Figuren deiner Sammlung haben einen Preis.  "
            f"{len(todo)} sind neu zu laden ({per} Abfragen pro Figur ≈ {len(todo) * per} Abfragen).\n"
            f"Heute schon genutzt: {pr.calls_today()} von {pr.DAILY_LIMIT} erlaubten API-Abfragen. "
            "Was heute nicht mehr passt, lädt der nächste Durchlauf."))

    def test(self) -> None:
        creds = self.creds()
        if not creds.complete():
            messagebox.showinfo(config.APP_NAME, "Bitte alle vier Werte eintragen.")
            return
        pr.save_credentials(creds)

        def task(cancel):
            return pr.PriceClient(creds, cancel=cancel).test()

        if self.app.run_task("prices-test", task):
            self.task.status.configure(text="Teste Verbindung …")

    def update_prices(self) -> None:
        st = self.app.state_
        creds = self.creds()
        if not creds.complete():
            messagebox.showinfo(config.APP_NAME, "Bitte zuerst die vier API-Werte eintragen.")
            return
        if not st.figures:
            messagebox.showinfo(config.APP_NAME, "Bitte zuerst den Katalog importieren.")
            return
        pr.save_credentials(creds)
        s = st.settings
        ids = [f.item_id for f in st.selected()]
        # wishlist first, then figures you still need, owned ones last
        ids.sort(key=lambda i: (i not in st.wishlist, i in st.owned))

        def task(cancel):
            return pr.update_prices(ids, creds, s.get("price_region", "dach"),
                                    s.get("price_conditions", ["U", "N"]), st.currency,
                                    int(s.get("price_max_age", 30)), self.app.progress,
                                    self.app.log, cancel)

        if self.app.run_task("prices", task):
            self.run_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
            self.task.bar.set(0)

    def on_event(self, ev) -> None:
        if ev[1] == "prices-test" and ev[0] in ("done", "error"):
            if ev[0] == "done":
                self.task.status.configure(text=f"✔  Verbindung klappt (Testfigur: {ev[2]}).")
            else:
                self.task.status.configure(text="✖  " + str(ev[2]))
            return
        kind = self.task.handle(ev)
        if not kind:
            return
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.app.state_.reload_prices()
        self.app.pages["collection"].dirty = True
        if kind == "done":
            done, left = ev[2]
            self.task.status.configure(text=f"Fertig: {done} Preise geladen" +
                                       (f", {left} folgen beim nächsten Mal." if left else "."))
        elif kind == "error":
            messagebox.showerror(config.APP_NAME, str(ev[2]))
        self.on_show()


# ======================================================================
class ExportPage(ScrollPage):
    SCOPES = {"Alle meiner Sammlung": "all", "Nur fehlende": "missing",
              "Nur gesammelte": "owned", "Nur Wunschliste": "wishlist"}
    SUBTITLES = {"all": "", "missing": "Fehlliste", "owned": "Meine Figuren", "wishlist": "Wunschliste"}

    def __init__(self, master, app: App):
        super().__init__(master)
        self.app = app
        self.last_file: Path | None = None
        p = app.state_.settings["pdf"]
        st = app.state_.settings
        body = self.body
        page_header(body, "", "PDF & Export",
                    "Deine Sammlung zum Ausdrucken oder Teilen: als Checkliste im Raster (PDF, mit "
                    "anklickbaren Kästchen) oder als Tabelle für Excel / Numbers (CSV). "
                    "Ausgeblendete Figuren kommen nicht mit.").grid(row=0, column=0, sticky="ew",
                                                                    pady=(0, 14))

        c0 = Card(body, "Was soll rein?")
        c0.grid(row=1, column=0, sticky="ew", pady=6)
        inv = {v: k for k, v in self.SCOPES.items()}
        self.scope = ctk.StringVar(value=inv.get(st.get("pdf_scope", "all"), list(self.SCOPES)[0]))
        c0.add(ctk.CTkSegmentedButton(c0, values=list(self.SCOPES), variable=self.scope,
                                      command=lambda _v: self._save(), selected_color=BLUE,
                                      selected_hover_color=BLUE_HOVER), sticky="w", pady=(10, 0))
        c0.end()

        c = Card(body, "PDF-Layout")
        c.grid(row=2, column=0, sticky="ew", pady=6)
        self.title_var = ctk.StringVar(value=p.get("title"))
        self.title_var.trace_add("write", lambda *_: self._save())
        c.add(ctk.CTkLabel(c, text="Titel", text_color=MUTED, anchor="w"))
        c.add(ctk.CTkEntry(c, textvariable=self.title_var, height=34), pady=(2, 0))
        grid = ctk.CTkFrame(c, fg_color="transparent")
        c.add(grid, pady=(12, 0))

        def labeled(r, col, text, widget):
            box = ctk.CTkFrame(grid, fg_color="transparent")
            box.grid(row=r, column=col, sticky="w", pady=6, padx=(0, 24))
            ctk.CTkLabel(box, text=text, text_color=MUTED, anchor="w").pack(anchor="w")
            widget(box).pack(anchor="w", pady=(2, 0))

        self.paper = ctk.StringVar(value=p.get("paper", "A4"))
        labeled(0, 0, "Papier", lambda m: ctk.CTkSegmentedButton(
            m, values=["A4", "Letter"], variable=self.paper, command=lambda _v: self._save(),
            selected_color=BLUE, selected_hover_color=BLUE_HOVER))
        self.orient_map = {"Hochformat": "portrait", "Querformat": "landscape"}
        self.orient = ctk.StringVar(value={v: k for k, v in self.orient_map.items()}.get(
            p.get("orientation", "portrait"), "Hochformat"))
        labeled(0, 1, "Ausrichtung", lambda m: ctk.CTkSegmentedButton(
            m, values=list(self.orient_map), variable=self.orient, command=lambda _v: self._save(),
            selected_color=BLUE, selected_hover_color=BLUE_HOVER))
        self.cols_label = ctk.CTkLabel(grid, text="", text_color=MUTED, anchor="w")
        self.cols_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.cols = ctk.CTkSlider(grid, from_=3, to=10, number_of_steps=7, width=260,
                                  command=lambda _v: self._save(), button_color=BLUE,
                                  progress_color=BLUE)
        self.cols.set(int(p.get("columns", 6)))
        self.cols.grid(row=2, column=0, sticky="w", pady=(2, 6))
        self.group_map = {"Nach Kategorie": "category", "Nach Thema": "theme",
                          "Nach Jahr": "year", "Ohne Gruppen": "none"}
        self.sort_map = {"Jahr": "year", "Nummer": "id", "Name": "name", "Preis ↑": "price",
                         "Preis ↓": "price_desc"}
        self.grouping = ctk.StringVar(value={v: k for k, v in self.group_map.items()}.get(
            st.get("grouping", "category"), "Nach Kategorie"))
        self.sorting = ctk.StringVar(value={v: k for k, v in self.sort_map.items()}.get(
            st.get("sort_by", "year"), "Jahr"))
        labeled(1, 1, "Gruppierung", lambda m: ctk.CTkOptionMenu(
            m, values=list(self.group_map), variable=self.grouping, command=lambda _v: self._save(),
            width=200))
        labeled(3, 1, "Sortierung", lambda m: ctk.CTkOptionMenu(
            m, values=list(self.sort_map), variable=self.sorting, command=lambda _v: self._save(),
            width=200))
        c.end()

        c2 = Card(body, "Pro Figur")
        c2.grid(row=3, column=0, sticky="ew", pady=6)
        self.flags: dict[str, ctk.BooleanVar] = {}
        for key, label in [("show_id", "BrickLink-Nummer"), ("show_name", "Name"),
                           ("show_year", "Jahr"), ("show_price", "Ø Preis (6 Monate)"),
                           ("fillable", "Kästchen im PDF anklickbar"),
                           ("precheck_owned", "Gesammelte Figuren vorab abhaken"),
                           ("new_page_per_section", "Jede Gruppe auf einer neuen Seite")]:
            var = ctk.BooleanVar(value=bool(p.get(key, False)))
            self.flags[key] = var
            c2.add(ctk.CTkCheckBox(c2, text=label, variable=var, text_color=TEXT, fg_color=BLUE,
                                   command=self._save), pady=(8, 0))
        c2.end()

        c3 = Card(body)
        c3.grid(row=4, column=0, sticky="ew", pady=6)
        self.summary = ctk.CTkLabel(c3, text="", font=_font(14), text_color=TEXT, anchor="w",
                                    justify="left")
        c3.add(self.summary, pady=(16, 0))
        row = ctk.CTkFrame(c3, fg_color="transparent")
        c3.add(row, pady=(12, 0))
        self.make_btn = primary_button(row, "PDF erstellen …", self.make_pdf, width=190)
        self.make_btn.pack(side="left")
        self.csv_btn = secondary_button(row, "Als CSV (Excel) exportieren …", self.make_csv, width=240)
        self.csv_btn.pack(side="left", padx=10)
        self.open_btn = secondary_button(row, "Letzte Datei öffnen", lambda: self.last_file and open_path(
            self.last_file), width=170, state="disabled")
        self.open_btn.pack(side="left")
        self.task = TaskArea(c3, "pdf")
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
        st["pdf_scope"] = self.SCOPES[self.scope.get()]
        self.app.state_.save_settings()
        self.app.pages["collection"].dirty = True
        self._update_summary()

    def _figures(self):
        st = self.app.state_
        return st.scope(st.settings.get("pdf_scope", "all"))

    def _opts(self):
        opts = self.app.state_.pdf_options()
        opts.subtitle = self.SUBTITLES.get(self.app.state_.settings.get("pdf_scope", "all"), "")
        return opts

    def _update_summary(self) -> None:
        self.cols_label.configure(text=f"Figuren pro Zeile: {int(round(self.cols.get()))}")
        st = self.app.state_
        if not st.figures:
            self.summary.configure(text="Noch kein Katalog – bitte unter „Katalog & Daten“ importieren.")
            self.make_btn.configure(state="disabled")
            self.csv_btn.configure(state="disabled")
            return
        self.make_btn.configure(state="normal")
        self.csv_btn.configure(state="normal")
        figs = self._figures()
        sections = st.sections(figs)
        pages = estimate_pages(sections, self._opts()) if figs else 0
        owned = sum(1 for f in figs if f.item_id in st.owned)
        text = (f"{len(figs)} Figuren in {len(sections)} Gruppen  ·  ca. {pages} PDF-Seiten  ·  "
                f"{owned} gesammelt")
        if st.prices:
            value, n = st.value(figs)
            text += f"\nWert ca. {pr.money(value, st.currency)} ({n} Figuren mit Preis)"
        self.summary.configure(text=text)

    def _ask_path(self, ext: str, label: str) -> Path | None:
        scope = self.app.state_.settings.get("pdf_scope", "all")
        kind = (self.SUBTITLES.get(scope) or ("Checkliste" if ext == "pdf" else "Sammlung"))
        name = f"DC_Minifiguren_{kind}_{dt.date.today():%Y-%m-%d}.{ext}".replace(" ", "_")
        path = filedialog.asksaveasfilename(title=f"{label} speichern unter", defaultextension=f".{ext}",
                                            initialfile=name, initialdir=str(default_output_dir()),
                                            filetypes=[(label, f"*.{ext}")])
        return Path(path) if path else None

    def make_pdf(self) -> None:
        st = self.app.state_
        figs = self._figures()
        if not figs:
            messagebox.showinfo(config.APP_NAME, "Für diese Auswahl gibt es keine Figuren.")
            return
        out = self._ask_path("pdf", "PDF")
        if out is None:
            return
        sections = st.sections(figs)
        opts = self._opts()
        owned = set(st.owned)
        cur = st.currency

        def price_text(item_id):
            p = st.price(item_id)
            return pr.money(p, cur) if p is not None else None

        def task(cancel):
            missing = [f for f in figs if not image_path(f.item_id).exists()]
            if missing:
                client = Client(log=self.app.log, cancel=cancel)
                try:
                    download_images(client, missing, lambda f, t: self.app.progress(f * 0.4, t),
                                    self.app.log, cancel)
                finally:
                    client.close()
            build_pdf(out, sections, opts, owned,
                      progress=lambda f, t: self.app.progress(0.4 + f * 0.6, t), price=price_text)
            return str(out)

        if self.app.run_task("pdf", task):
            self.make_btn.configure(state="disabled")
            self.task.status.configure(text="Erstelle PDF …")
            self.task.bar.set(0)

    def make_csv(self) -> None:
        st = self.app.state_
        figs = self._figures()
        out = self._ask_path("csv", "CSV (Excel)")
        if out is None:
            return
        write_csv(out, st, figs)
        self.last_file = out
        self.open_btn.configure(state="normal")
        self.app.toast(f"CSV mit {len(figs)} Figuren gespeichert")

    def on_event(self, ev) -> None:
        kind = self.task.handle(ev)
        if not kind:
            return
        self.make_btn.configure(state="normal")
        if kind == "done":
            self.last_file = Path(ev[2])
            self.task.status.configure(text=f"Gespeichert: {self.last_file}")
            self.open_btn.configure(state="normal")
            open_path(self.last_file)
        elif kind == "error":
            messagebox.showerror(config.APP_NAME, str(ev[2]))


def write_csv(path: Path, st: State, figs) -> None:
    """Spreadsheet export (semicolon separated, opens directly in German Excel)."""
    def num(v):
        return "" if v is None else f"{v:.2f}".replace(".", ",")

    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Nummer", "Name", "Jahr", "Kategorie", "Hab ich", "Wunschliste",
                    f"Ø gebraucht ({st.currency})", "Verkäufe gebraucht",
                    f"Ø neu ({st.currency})", "Verkäufe neu", "Preis-Region", "Preis-Stand",
                    "Notiz", "BrickLink"])
        for _t, fs in st.sections(figs):
            for f in fs:
                rec = st.prices.get(f.item_id) or {}
                u, n = rec.get("U") or {}, rec.get("N") or {}
                w.writerow([f.item_id, f.name, f.year or "", f.category_label,
                            "ja" if f.item_id in st.owned else "",
                            "ja" if f.item_id in st.wishlist else "",
                            num(u.get("avg")), u.get("qty", "") if u else "",
                            num(n.get("avg")), n.get("qty", "") if n else "",
                            pr.REGIONS.get(rec.get("region"), ("",))[0] if rec else "",
                            rec.get("date", ""), st.notes.get(f.item_id, ""),
                            f"https://www.bricklink.com/v2/catalog/catalogitem.page?M={f.item_id}"])


def main() -> None:
    app = App()
    app.mainloop()
