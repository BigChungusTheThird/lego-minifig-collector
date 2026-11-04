"""Persistent app state: settings, catalog and the user's collection.

Everything lives in JSON files in the data folder, so the app works offline
once the catalog has been imported and the pictures are downloaded.

Collection data (keyed by BrickLink number, survives catalog re-imports):
  owned      – figures the user has
  wishlist   – figures the user wants next
  notes      – free text per figure
  overrides  – manual show (True) / hide (False) that beats the theme rules
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, fields

from . import config
from .catalog import Decision, Figure, build_sections, decide
from .pdf import PdfOptions
from .prices import load_prices, main_price
from .storage import read_json, write_json


def default_settings() -> dict:
    return {
        "year_from": config.FIRST_YEAR_DEFAULT,
        "year_to": None,                      # None = up to the current year
        "groups": [k for k, _l, _d, on in config.GROUPS if on],
        "exclude_dceu": True,
        "keep_knightmare": True,
        "dceu_sets": list(config.DCEU_SETS),
        "grouping": "category",
        "sort_by": "year",
        "appearance": "System",
        "view": "grid",                       # grid | list
        "card_size": "M",                     # S | M | L
        "pdf": asdict(PdfOptions()),
        "pdf_scope": "all",                   # all | missing | owned | wishlist
        # prices (BrickLink API, 6-month sales)
        "price_region": "dach",               # dach | eu | europe | de | world
        "price_conditions": ["U", "N"],
        "price_prefer": "U",                  # condition shown on the cards
        "price_currency": "EUR",
        "price_max_age": 30,                  # days before a price is refreshed
        "show_prices": True,
    }


@dataclass
class Progress:
    total: int = 0
    owned: int = 0

    @property
    def percent(self) -> int:
        return round(100 * self.owned / self.total) if self.total else 0


class State:
    def __init__(self) -> None:
        self.settings = default_settings()
        stored = read_json("settings.json", {})
        if isinstance(stored, dict):
            for k, v in stored.items():
                if k == "pdf" and isinstance(v, dict):
                    self.settings["pdf"].update(v)
                elif k in self.settings:
                    self.settings[k] = v
        cat = read_json("catalog.json", {})
        if not isinstance(cat, dict):
            cat = {}
        self.catalog_meta: dict = {k: v for k, v in cat.items() if k != "figures"}
        self.figures: list[Figure] = [Figure.from_dict(d) for d in (cat.get("figures") or [])]
        self._by_id = {f.item_id: f for f in self.figures}
        self._load_collection(read_json("collection.json", {}))
        self._decisions: dict[str, Decision] | None = None
        self.prices: dict = load_prices()

    def _load_collection(self, col) -> None:
        col = col if isinstance(col, dict) else {}
        self.owned: set[str] = set(col.get("owned", []))
        self.wishlist: set[str] = set(col.get("wishlist", []))
        self.notes: dict[str, str] = {k: v for k, v in dict(col.get("notes", {})).items() if v}
        self.overrides: dict[str, bool] = dict(col.get("overrides", {}))

    # ------------------------------------------------------------ saving
    def save_settings(self) -> None:
        write_json("settings.json", self.settings)

    def collection_data(self) -> dict:
        return {"owned": sorted(self.owned), "wishlist": sorted(self.wishlist),
                "notes": dict(sorted(self.notes.items())), "overrides": self.overrides,
                "saved": dt.datetime.now().isoformat(timespec="seconds"),
                "app_version": config.APP_VERSION}

    def save_collection(self) -> None:
        self._decisions = None
        write_json("collection.json", self.collection_data())

    def restore_collection(self, data: dict) -> None:
        """Replace the collection with a backup (see collection_data)."""
        if not isinstance(data, dict) or not any(k in data for k in ("owned", "overrides")):
            raise ValueError("Das ist keine Sicherung dieser App.")
        self._load_collection(data)
        self.save_collection()

    def set_catalog(self, figures: list[Figure], year_from: int, year_to: int,
                    **meta) -> None:
        self.figures = figures
        self._by_id = {f.item_id: f for f in figures}
        self._decisions = None
        self.catalog_meta = {"fetched": dt.datetime.now().isoformat(timespec="minutes"),
                             "year_from": year_from, "year_to": year_to,
                             "app_version": config.APP_VERSION, **meta}
        write_json("catalog.json", {**self.catalog_meta,
                                    "figures": [f.to_dict() for f in figures]})

    def settings_changed(self) -> None:
        self._decisions = None
        self.save_settings()

    # ------------------------------------------------------------ lookups
    def figure(self, item_id: str) -> Figure | None:
        return self._by_id.get(item_id)

    @property
    def year_from(self) -> int:
        return int(self.settings.get("year_from") or config.FIRST_YEAR_DEFAULT)

    @property
    def year_to(self) -> int:
        return int(self.settings.get("year_to") or config.CURRENT_YEAR)

    def rule_settings(self) -> dict:
        s = dict(self.settings)
        s["year_to"] = self.year_to
        return s

    def decisions(self) -> dict[str, Decision]:
        if self._decisions is None:
            rs = self.rule_settings()
            self._decisions = {f.item_id: decide(f, rs, self.overrides) for f in self.figures}
        return self._decisions

    def is_visible(self, item_id: str) -> bool:
        d = self.decisions().get(item_id)
        return bool(d and d.include)

    def selected(self) -> list[Figure]:
        """All figures that belong to the collection (not hidden)."""
        d = self.decisions()
        return [f for f in self.figures if d[f.item_id].include]

    def hidden(self) -> list[Figure]:
        d = self.decisions()
        return [f for f in self.figures if not d[f.item_id].include]

    # ------------------------------------------------------------ editing
    def set_owned(self, ids, value: bool) -> None:
        for i in ids:
            (self.owned.add if value else self.owned.discard)(i)
        self.save_collection()

    def set_wishlist(self, ids, value: bool) -> None:
        for i in ids:
            (self.wishlist.add if value else self.wishlist.discard)(i)
        self.save_collection()

    def set_note(self, item_id: str, text: str) -> None:
        text = text.strip()
        if text:
            self.notes[item_id] = text
        else:
            self.notes.pop(item_id, None)
        self.save_collection()

    def set_hidden(self, ids, hidden: bool) -> None:
        """Hide figures from the collection, or show them again."""
        rs = self.rule_settings()
        for i in ids:
            f = self._by_id.get(i)
            if f is None:
                continue
            self.overrides.pop(i, None)
            by_rule = decide(f, rs, {}).include
            if by_rule == hidden:              # rule says the opposite -> remember choice
                self.overrides[i] = not hidden
        self.save_collection()

    def reset_overrides(self) -> int:
        n = len(self.overrides)
        self.overrides.clear()
        self.save_collection()
        return n

    # ------------------------------------------------------------ views
    def sections(self, figures: list[Figure] | None = None, grouping: str | None = None,
                 sort_by: str | None = None):
        figs = self.selected() if figures is None else figures
        return build_sections(figs, grouping or self.settings.get("grouping", "category"),
                              sort_by or self.settings.get("sort_by", "year"), self.price)

    def scope(self, scope: str) -> list[Figure]:
        figs = self.selected()
        if scope == "missing":
            return [f for f in figs if f.item_id not in self.owned]
        if scope == "owned":
            return [f for f in figs if f.item_id in self.owned]
        if scope == "wishlist":
            return [f for f in figs if f.item_id in self.wishlist]
        return figs

    def progress(self, figures: list[Figure] | None = None) -> Progress:
        figs = self.selected() if figures is None else figures
        return Progress(total=len(figs), owned=sum(1 for f in figs if f.item_id in self.owned))

    # ------------------------------------------------------------ prices
    def reload_prices(self) -> None:
        self.prices = load_prices()

    def price(self, item_id: str) -> float | None:
        return main_price(self.prices.get(item_id), self.settings.get("price_prefer", "U"))

    def value(self, figures) -> tuple[float, int]:
        """Sum of the shown prices and how many figures have a price."""
        total, n = 0.0, 0
        for f in figures:
            p = self.price(f.item_id)
            if p is not None:
                total += p
                n += 1
        return total, n

    @property
    def currency(self) -> str:
        return self.settings.get("price_currency", "EUR")

    def pdf_options(self) -> PdfOptions:
        names = {f.name for f in fields(PdfOptions)}
        return PdfOptions(**{k: v for k, v in self.settings["pdf"].items() if k in names})

    def catalog_covers_settings(self) -> bool:
        if not self.figures:
            return False
        if self.catalog_meta.get("source") == "import":
            return True          # the official download covers every year
        lo = self.catalog_meta.get("year_from", 0)
        hi = self.catalog_meta.get("year_to", 0)
        return lo <= self.year_from and hi >= min(self.year_to, config.CURRENT_YEAR)
