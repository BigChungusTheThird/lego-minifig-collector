"""Persistent app state: settings, downloaded catalog, collection, overrides."""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, fields

from . import config
from .catalog import Decision, Figure, build_sections, decide
from .pdf import PdfOptions
from .storage import read_json, write_json


def default_settings() -> dict:
    return {
        "year_from": config.FIRST_YEAR_DEFAULT,
        "year_to": None,                      # None = up to the current year
        "groups": [k for k, _l, _d, on in config.GROUPS if on],
        "exclude_dceu": True,
        "keep_knightmare": True,
        "dceu_sets": list(config.DCEU_SETS),
        "cross_check": True,
        "use_cache": True,
        "grouping": "category",
        "sort_by": "year",
        "appearance": "System",
        "pdf": asdict(PdfOptions()),
    }


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
        self.catalog_meta: dict = {k: v for k, v in cat.items() if k != "figures"} \
            if isinstance(cat, dict) else {}
        self.figures: list[Figure] = [Figure.from_dict(d) for d in (cat.get("figures") or [])] \
            if isinstance(cat, dict) else []
        col = read_json("collection.json", {})
        self.owned: set[str] = set(col.get("owned", [])) if isinstance(col, dict) else set()
        self.overrides: dict[str, bool] = dict(col.get("overrides", {})) \
            if isinstance(col, dict) else {}

    # ------------------------------------------------------------ saving
    def save_settings(self) -> None:
        write_json("settings.json", self.settings)

    def save_collection(self) -> None:
        write_json("collection.json", {"owned": sorted(self.owned),
                                       "overrides": self.overrides})

    def set_catalog(self, figures: list[Figure], year_from: int, year_to: int) -> None:
        self.figures = figures
        self.catalog_meta = {"fetched": dt.datetime.now().isoformat(timespec="minutes"),
                             "year_from": year_from, "year_to": year_to,
                             "app_version": config.APP_VERSION}
        write_json("catalog.json", {**self.catalog_meta,
                                    "figures": [f.to_dict() for f in figures]})

    # ------------------------------------------------------------ helpers
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
        rs = self.rule_settings()
        return {f.item_id: decide(f, rs, self.overrides) for f in self.figures}

    def selected(self) -> list[Figure]:
        d = self.decisions()
        return [f for f in self.figures if d[f.item_id].include]

    def sections(self, figures: list[Figure] | None = None):
        figs = self.selected() if figures is None else figures
        return build_sections(figs, self.settings.get("grouping", "category"),
                              self.settings.get("sort_by", "year"))

    def pdf_options(self) -> PdfOptions:
        names = {f.name for f in fields(PdfOptions)}
        return PdfOptions(**{k: v for k, v in self.settings["pdf"].items() if k in names})

    def catalog_covers_settings(self) -> bool:
        if not self.figures:
            return False
        lo = self.catalog_meta.get("year_from", 0)
        hi = self.catalog_meta.get("year_to", 0)
        return lo <= self.year_from and hi >= min(self.year_to, config.CURRENT_YEAR)
