"""Constants: BrickLink endpoints, theme rules and the DCEU set list."""
from __future__ import annotations

import datetime as _dt

APP_NAME = "DC Minifiguren-Checkliste"
APP_SLUG = "DC-Minifig-Checkliste"
APP_VERSION = "1.0.0"

BL_BASE = "https://www.bricklink.com"
BL_IMG = "https://img.bricklink.com"

# BrickLink "DC Comics Co-Branded Items" - every minifigure BrickLink tags as
# a licensed DC product, across all themes (Super Heroes, Batman I,
# Collectible Minifigures, The LEGO Movie, ...). Marvel has its own tag, so
# this list contains no Marvel figures.
DC_PROMO_CAT_ID = 247

# A few known BrickLink category ids (used for the cross-check pass).
CAT_SUPER_HEROES = "768"
CAT_BATMAN_I = "570"
CAT_BATMAN_II = "768.769"

FIRST_YEAR_DEFAULT = 2008
CURRENT_YEAR = _dt.date.today().year

# Polite crawling: BrickLink blocks clients that hammer the site.
PAGE_DELAY_SECONDS = (1.3, 2.3)   # random pause between catalog pages
IMAGE_DELAY_SECONDS = 0.15        # pause per image request (per thread)
IMAGE_THREADS = 3
HTML_CACHE_DAYS = 7
MAX_LIST_PAGES = 80

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# --------------------------------------------------------------------------
# DCEU (Snyder-verse and the other DC Extended Universe films).
# Minifigures that appear in these sets are flagged as "DCEU" and are left out
# by default. The list is editable in the app.
# --------------------------------------------------------------------------
DCEU_SETS: dict[str, str] = {
    "76002-1": "Superman: Metropolis Showdown (Man of Steel, 2013)",
    "76003-1": "Superman: Battle of Smallville (Man of Steel, 2013)",
    "76009-1": "Superman: Black Zero Escape (Man of Steel, 2013)",
    "76044-1": "Clash of the Heroes (Batman v Superman, 2016)",
    "76045-1": "Kryptonite Interception (Batman v Superman, 2016)",
    "76046-1": "Heroes of Justice: Sky High Battle (Batman v Superman, 2016)",
    "30446-1": "The Batmobile (Batman v Superman Polybag, 2016)",
    "76075-1": "Wonder Woman Warrior Battle (Wonder Woman, 2017)",
    "76085-1": "Battle of Atlantis (Justice League, 2017)",
    "76086-1": "Knightcrawler Tunnel Attack (Justice League, 2017)",
    "76087-1": "Flying Fox: Batmobile Airlift Attack (Justice League, 2017)",
    "853744-1": "Knightmare Batman Accessory Set (2018)",
    "76095-1": "Aquaman: Black Manta Strike (Aquaman, 2018)",
    "30623-1": "SHAZAM! (Polybag, 2019)",
    "76157-1": "Wonder Woman vs Cheetah (Wonder Woman 1984, 2020)",
}

# BrickLink sub-categories that only contain DCEU film figures.
DCEU_CATEGORY_NAMES = ("man of steel", "dawn of justice")

# Figures that stay in even though they are DCEU: Knightmare Batman
# (Batman v Superman / Zack Snyder's Justice League), BrickLink sh0532.
DCEU_KEEP_IDS = {"sh0532"}
DCEU_KEEP_NAME_WORDS = ("knightmare",)

# Safety net against Marvel (should never appear in the DC list anyway).
MARVEL_WORDS = (
    "marvel", "avengers", "spider-man", "spider man", "spidey", "x-men",
    "iron man", "captain america", "hulk", "thor:", "guardians of the galaxy",
    "ant-man", "black panther", "doctor strange", "eternals", "shang-chi",
    "fantastic four", "venom", "deadpool", "wolverine", "captain marvel",
    "black widow", "loki", "thanos", "what if",
)

# --------------------------------------------------------------------------
# Groups shown in the app ("Themen"). Each BrickLink category path is mapped
# to exactly one group (see catalog.classify_group).
# --------------------------------------------------------------------------
GROUPS: list[tuple[str, str, str, bool]] = [
    # key, label, description, enabled by default
    ("batman1", "Batman I (nur 2008)",
     "Die klassische Batman-Reihe – Figuren ab 2008", True),
    ("sh", "DC Super Heroes",
     "Batman II, Justice League, Superman, Wonder Woman, Aquaman … "
     "(Comic-, Serien- und Nicht-DCEU-Film-Figuren)", True),
    ("tlbm", "The LEGO Batman Movie (Sets)",
     "Figuren aus den Sets zum LEGO Batman Movie", True),
    ("cmf_tlbm", "Sammelfiguren: LEGO Batman Movie Serie 1 & 2",
     "Collectible Minifigures 71017 & 71020", True),
    ("cmf_dc", "Sammelfiguren: DC Super Heroes Serie",
     "Collectible Minifigures 71026 und andere DC-Sammelserien", True),
    ("mm", "Mighty Micros",
     "DC-Figuren mit kurzen Beinen aus den Mighty-Micros-Sets", True),
    ("other", "DC in anderen Themen",
     "z. B. The LEGO Movie, LEGO Dimensions, Promo-Figuren anderer Themen",
     False),
    ("shg", "DC Super Hero Girls",
     "Mini-Puppen (keine klassischen Minifiguren)", False),
    ("duplo", "DUPLO",
     "DUPLO-Figuren (keine Minifiguren)", False),
    ("misc", "Spiele & Mikrofiguren",
     "Videospiel-/Brettspiel-Mikrofiguren und Sonstiges", False),
]
GROUP_LABELS = {k: label for k, label, _d, _e in GROUPS}
GROUP_ORDER = {k: i for i, (k, *_rest) in enumerate(GROUPS)}

# Words that mark a BrickLink category (or sub-category) as DC-only, used by
# the cross-check pass that re-reads whole categories.
DC_CATEGORY_WORDS = (
    "batman", "justice league", "superman", "wonder woman", "aquaman",
    "dawn of justice", "man of steel", "dc ", "dc comics", "dc super",
    "the flash", "shazam", "suicide squad", "gotham", "teen titans",
    "green lantern", "super hero girls",
)
