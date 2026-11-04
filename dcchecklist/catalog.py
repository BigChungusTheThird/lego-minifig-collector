"""Collecting DC minifigures from BrickLink and deciding what goes on the list."""
from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable

from . import bricklink as bl
from . import config
from .net import CancelledError, Client
from .storage import cache_dir

ProgressFn = Callable[[float, str], None]   # (0..1, text)
LogFn = Callable[[str], None]


@dataclass
class Figure:
    item_id: str
    name: str = ""
    year: int | None = None
    category_path: list[str] = field(default_factory=list)
    category_id: str = ""
    thumb: str = ""
    dceu_sets: list[str] = field(default_factory=list)  # DCEU sets it appears in
    source: str = "promo"                                 # import | promo | category
    unsure: bool = False                                  # DC or Marvel? (mixed category)

    # -- derived -------------------------------------------------------
    @property
    def category_label(self) -> str:
        return " › ".join(self.category_path) if self.category_path else "Unbekannt"

    @property
    def section(self) -> str:
        """Heading used in the PDF (category without the generic parts)."""
        path = [p for p in self.category_path if p.lower() != "super heroes"]
        if path and path[0].lower() == "collectible minifigures":
            return "Sammelfiguren › " + (path[-1] if len(path) > 1 else "Sonstige")
        return " › ".join(path) if path else "Sonstige"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Figure":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


# ----------------------------------------------------------------- rules

def classify_group(path: Iterable[str], item_id: str = "") -> str:
    """Map a BrickLink category path to one of config.GROUPS."""
    p = [s.lower() for s in path]
    joined = " / ".join(p)
    iid = item_id.lower()
    root = p[0] if p else ""

    if root.startswith("duplo"):
        return "duplo"
    if root.startswith(("dimensions", "the lego movie")):
        return "other"
    if "super hero girls" in joined or iid.startswith("shg"):
        return "shg"
    if root.startswith("collectible minifigures") or iid.startswith("col"):
        if "batman movie" in joined or iid.startswith("coltlbm"):
            return "cmf_tlbm"
        return "cmf_dc"
    if root.startswith("batman i") and not root.startswith("batman ii"):
        return "batman1"
    if root in ("game", "games") or root.startswith("game") or "microfig" in joined:
        return "misc"
    if "batman movie" in joined:
        return "tlbm"
    if "mighty micros" in joined:
        return "mm"
    if "super heroes" in p or root.startswith("super heroes"):
        return "sh"
    if root.startswith("batman"):          # e.g. "Batman II" as its own root
        return "sh"
    if not p and iid.startswith("sh"):
        return "sh"
    return "other"


def is_marvel(fig: Figure) -> bool:
    hay = (" ".join(fig.category_path)).lower()
    return any(w in hay for w in config.MARVEL_WORDS)


def is_dceu(fig: Figure, active_sets: Iterable[str] | None = None) -> bool:
    """Figure from a DC Extended Universe film (Man of Steel ... WW84)?"""
    iid = fig.item_id.lower()
    if iid in config.DCEU_NOT_IDS:
        return False
    if iid in config.DCEU_EXTRA_IDS:
        return True
    if active_sets is None:
        if fig.dceu_sets:
            return True
    else:
        active = {s.strip().lower() if "-" in s else s.strip().lower() + "-1" for s in active_sets}
        if any(s.lower() in active for s in fig.dceu_sets):
            return True
    low = [p.lower() for p in fig.category_path]
    if "mighty micros" in low:
        return False
    last = low[-1] if low else ""
    if last in config.DCEU_CATEGORY_NAMES:
        return True
    # BrickLink files the 2017 Justice League film figures together with the
    # comic Justice League figures; all of its 2017 entries are the film.
    return last == "justice league" and fig.year == 2017


def is_dceu_exception(fig: Figure) -> bool:
    if fig.item_id.lower() in {i.lower() for i in config.DCEU_KEEP_IDS}:
        return True
    name = fig.name.lower()
    return any(w in name for w in config.DCEU_KEEP_NAME_WORDS)


@dataclass
class Decision:
    include: bool
    reason: str


def decide(fig: Figure, settings: dict, overrides: dict[str, bool] | None = None) -> Decision:
    """Should this figure be on the checklist with the current settings?"""
    overrides = overrides or {}
    group = classify_group(fig.category_path, fig.item_id)
    year_from = int(settings.get("year_from", config.FIRST_YEAR_DEFAULT))
    year_to = int(settings.get("year_to", config.CURRENT_YEAR))
    groups_on = set(settings.get("groups", [k for k, _l, _d, on in config.GROUPS if on]))

    if is_marvel(fig):
        auto = Decision(False, "Marvel")
    elif fig.unsure:
        auto = Decision(False, "unklar: DC oder Marvel?")
    elif fig.year is not None and fig.year < year_from:
        auto = Decision(False, f"vor {year_from}")
    elif fig.year is not None and fig.year > year_to:
        auto = Decision(False, f"nach {year_to}")
    elif settings.get("exclude_dceu", True) and is_dceu(fig, settings.get("dceu_sets")) and not (
            settings.get("keep_knightmare", True) and is_dceu_exception(fig)):
        auto = Decision(False, "DCEU-Film")
    elif group not in groups_on:
        auto = Decision(False, f"Thema aus: {config.GROUP_LABELS.get(group, group)}")
    else:
        why = "Knightmare-Ausnahme" if (settings.get("exclude_dceu", True) and is_dceu(
            fig, settings.get("dceu_sets"))) else ""
        auto = Decision(True, why)

    if fig.item_id in overrides:
        manual = overrides[fig.item_id]
        if manual != auto.include:
            return Decision(manual, "manuell " + ("hinzugefügt" if manual else "entfernt"))
    return auto


# --------------------------------------------------------------- sorting

def natural_key(item_id: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.findall(r"\d+|\D+", item_id)]


def sort_figures(figs: list[Figure], how: str = "year") -> list[Figure]:
    if how == "name":
        return sorted(figs, key=lambda f: (f.name.lower(), natural_key(f.item_id)))
    if how == "id":
        return sorted(figs, key=lambda f: natural_key(f.item_id))
    return sorted(figs, key=lambda f: (f.year or 9999, natural_key(f.item_id)))


def build_sections(figs: list[Figure], grouping: str = "category",
                   sort_by: str = "year") -> list[tuple[str, list[Figure]]]:
    """Split figures into PDF sections."""
    if grouping == "none":
        return [("Alle Figuren", sort_figures(figs, sort_by))]
    buckets: dict[str, list[Figure]] = {}
    for f in figs:
        if grouping == "year":
            key = str(f.year) if f.year else "Jahr unbekannt"
        elif grouping == "theme":
            key = config.GROUP_LABELS.get(classify_group(f.category_path, f.item_id), "Sonstige")
        else:
            key = f.section
        buckets.setdefault(key, []).append(f)

    def sect_order(item: tuple[str, list[Figure]]):
        name, members = item
        if grouping == "year":
            return (0, int(name)) if name.isdigit() else (1, 0)
        if grouping == "theme":
            gkeys = [k for k, lbl in config.GROUP_LABELS.items() if lbl == name]
            return (config.GROUP_ORDER.get(gkeys[0], 99) if gkeys else 99, name)
        first_group = min(config.GROUP_ORDER.get(classify_group(m.category_path, m.item_id), 99)
                          for m in members)
        first_year = min((m.year or 9999) for m in members)
        return (first_group, first_year, name.lower())

    return [(name, sort_figures(members, sort_by))
            for name, members in sorted(buckets.items(), key=sect_order)]


# ------------------------------------------------------------- scraping

class Scraper:
    def __init__(self, client: Client, log: LogFn, progress: ProgressFn,
                 cancel: threading.Event):
        self.client = client
        self.log = log
        self.progress = progress
        self.cancel = cancel

    # -- listing helpers --------------------------------------------------
    def _walk_list(self, label: str, url_for_page: Callable[[int], str]) -> list[bl.ListedItem]:
        items: list[bl.ListedItem] = []
        seen: set[str] = set()
        total_pages = None
        page = 1
        while page <= config.MAX_LIST_PAGES:
            html = self.client.get_page(url_for_page(page))
            parsed = bl.parse_list_page(html)
            new = [it for it in parsed.items if it.item_id.lower() not in seen]
            for it in new:
                seen.add(it.item_id.lower())
                items.append(it)
            if parsed.total_pages:
                total_pages = parsed.total_pages
            if page == 1 and parsed.total_items is not None:
                self.log(f"  {label}: {parsed.total_items} Einträge laut BrickLink")
            if not new or (total_pages and page >= total_pages) or (
                    total_pages is None and len(parsed.items) < 20):
                break
            page += 1
        return items

    # -- main steps --------------------------------------------------------
    def collect(self, year_from: int, year_to: int, cross_check: bool = True,
                dceu_sets: Iterable[str] = config.DCEU_SETS) -> list[Figure]:
        figs: dict[str, Figure] = {}
        years = list(range(year_from, year_to + 1))
        steps = len(years) + (1 if cross_check else 0) + 1
        done = 0

        self.log(f"Lade alle DC-Minifiguren von BrickLink ({year_from}–{year_to}) …")
        for y in years:
            self.progress(done / steps, f"BrickLink: DC-Figuren aus {y} …")
            listed = self._walk_list(str(y), lambda pg, y=y: bl.list_url(
                promo_cat_id=config.DC_PROMO_CAT_ID, year=y, page=pg))
            for it in listed:
                f = figs.get(it.item_id.lower())
                if f is None:
                    figs[it.item_id.lower()] = Figure(
                        item_id=it.item_id, name=it.name, year=y,
                        category_path=it.category_path, category_id=it.category_id,
                        thumb=it.thumb, source="promo")
            self.log(f"  {y}: {len(listed)} Figuren")
            done += 1

        if cross_check:
            self.progress(done / steps, "Gegenprüfung über die DC-Kategorien …")
            self._cross_check(figs, year_from, year_to)
            done += 1

        self.progress(done / steps, "DCEU-Sets prüfen …")
        self._mark_dceu(figs, dceu_sets)
        self.progress(1.0, f"{len(figs)} DC-Figuren gefunden")
        self.log(f"Fertig: {len(figs)} DC-Figuren im Zeitraum gefunden "
                 f"({self.client.page_requests} Seitenabrufe bei BrickLink).")
        return list(figs.values())

    def _cross_check(self, figs: dict[str, Figure], year_from: int, year_to: int) -> None:
        """Read whole DC-only categories to catch figures missing the DC tag."""
        cats: dict[str, str] = {}
        for f in figs.values():
            if f.category_id and self._dc_only_category(f.category_path):
                cats.setdefault(f.category_id, f.category_label)
        cats.setdefault(config.CAT_BATMAN_II, "Super Heroes › Batman II")
        added = 0
        for cat_id, label in sorted(cats.items()):
            listed: list[tuple[bl.ListedItem, int | None]] = []
            if cat_id == config.CAT_BATMAN_I:
                # Batman I ran 2006-2008: only ask for the years we want.
                for y in range(max(year_from, 2006), min(year_to, 2008) + 1):
                    listed += [(it, y) for it in self._walk_list(
                        f"{label} {y}", lambda pg, y=y: bl.list_url(
                            cat_string=config.CAT_BATMAN_I, year=y, page=pg))]
            else:
                listed = [(it, None) for it in self._walk_list(
                    label, lambda pg, c=cat_id: bl.list_url(cat_string=c, page=pg))]
            for it, year in listed:
                key = it.item_id.lower()
                if key in figs:
                    continue
                det = self._details(it.item_id) if year is None else bl.ItemDetails(it.item_id)
                year = year if year is not None else det.year
                if year is not None and not (year_from <= year <= year_to):
                    continue
                figs[key] = Figure(item_id=it.item_id, name=it.name or det.name, year=year,
                                   category_path=it.category_path or det.category_path,
                                   category_id=it.category_id or cat_id, thumb=it.thumb,
                                   source="category")
                added += 1
        self.log(f"  Gegenprüfung: {len(cats)} Kategorien gelesen, {added} zusätzliche Figuren")

    @staticmethod
    def _dc_only_category(path: list[str]) -> bool:
        p = [s.lower() for s in path]
        if not p or p[0].startswith(("duplo", "game")):
            return False
        last = p[-1]
        if "mighty micros" in last or "juniors" in last or "promotional" in last:
            return False
        return any(w in last for w in config.DC_CATEGORY_WORDS)

    def _details(self, item_id: str) -> bl.ItemDetails:
        html = self.client.get_page(bl.item_url(item_id), max_age_days=60)
        return bl.parse_item_page(html, item_id)

    def _mark_dceu(self, figs: dict[str, Figure], dceu_sets: Iterable[str]) -> None:
        marked = 0
        for set_no in dceu_sets:
            set_no = set_no.strip()
            if not set_no:
                continue
            if "-" not in set_no:
                set_no += "-1"
            html = self.client.get_page(bl.set_inventory_url(set_no), max_age_days=90)
            for iid in bl.parse_set_inventory(html):
                f = figs.get(iid.lower())
                if f is not None and set_no not in f.dceu_sets:
                    f.dceu_sets.append(set_no)
                    marked += 1
        self.log(f"  DCEU: {marked} Figuren-Zuordnungen zu DCEU-Sets gefunden")


# ---------------------------------------------------------------- images

def image_path(item_id: str):
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", item_id)
    return cache_dir("img") / f"{safe}.img"


def download_images(client: Client, figs: list[Figure], progress: ProgressFn,
                    log: LogFn, cancel: threading.Event) -> int:
    """Fetch pictures for all figures (cached). Returns number of misses."""
    import time
    from .net import NetworkError

    todo = [f for f in figs if not image_path(f.item_id).exists()]
    total = len(todo)
    if not total:
        progress(1.0, "Alle Bilder sind schon gespeichert")
        return 0
    log(f"Lade {total} Bilder von img.bricklink.com …")
    missing = 0
    done = 0
    lock = threading.Lock()
    state = {"net_errors": 0, "offline": False}

    def fetch(f: Figure) -> bool:
        if state["offline"]:
            return False
        for url in bl.image_urls(f.item_id, f.thumb):
            if cancel.is_set():
                raise CancelledError("Abgebrochen")
            try:
                data = client.get_binary(url)
            except NetworkError:
                with lock:
                    state["net_errors"] += 1
                    if state["net_errors"] >= 6:
                        state["offline"] = True
                return False
            with lock:
                state["net_errors"] = 0
            time.sleep(config.IMAGE_DELAY_SECONDS)
            if data and len(data) > 200:
                path = image_path(f.item_id)
                tmp = path.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(path)
                return True
        return False

    with ThreadPoolExecutor(max_workers=config.IMAGE_THREADS) as pool:
        futures = {pool.submit(fetch, f): f for f in todo}
        for fut in as_completed(futures):
            f = futures[fut]
            try:
                ok = fut.result()
            except CancelledError:
                for other in futures:
                    other.cancel()
                raise
            except Exception as exc:  # pragma: no cover - network dependent
                ok = False
                log(f"  Bild {f.item_id}: {exc}")
            with lock:
                done += 1
                if not ok:
                    missing += 1
                progress(done / total, f"Bilder {done}/{total}")
    if state["offline"]:
        log("  Keine Verbindung zu img.bricklink.com – die fehlenden Bilder werden beim "
            "nächsten Mal geladen (Knopf „Fehlende Bilder laden“ oder beim PDF).")
    elif missing:
        log(f"  {missing} Bilder nicht gefunden (Platzhalter im PDF)")
    return missing
