"""Import BrickLink's official catalog download (Minifigures.txt / .xml).

BrickLink members can download the whole minifigure catalog at
https://www.bricklink.com/catalogDownload.asp ("Catalog Items" ->
"Minifigures" -> "Tab-Delimited File"). The file has one row per minifigure:

    Category ID  Category Name                    Number  Name              Year Released
    768          Super Heroes / Dawn of Justice   sh0532  Batman, Knightmare  2018

This module reads that file and keeps the DC figures.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import Figure

DOWNLOAD_PAGE = "https://www.bricklink.com/catalogDownload.asp"


class ImportError_(ValueError):
    """The file is not a BrickLink minifigure catalog."""


# ----------------------------------------------------------- DC or Marvel?

# Sub-categories of "Super Heroes" (and of Collectible Minifigures / DUPLO /
# Games ... / Super Heroes) that belong to DC.
_DC_CAT = re.compile(
    r"batman|superman|justice league|wonder woman|aquaman|dawn of justice|man of steel|"
    r"dark knight|legends of tomorrow|\bdc\b|the flash|shazam|suicide squad|teen titans|"
    r"gotham|green lantern|super hero girls|harley quinn|joker", re.I)
_MARVEL_CAT = re.compile(
    r"marvel|avengers|spider|spidey|x-men|infinity saga|guardians|iron man|thor\b|captain america|"
    r"captain marvel|black panther|eternals|shang-chi|doctor strange|ant-man|black widow|"
    r"what if|fantastic four|ghost rider|the marvels|venom|deadpool|wolverine|hulk|loki|"
    r"daredevil|moon knight|ms\. marvel|she-hulk|hawkeye|wandavision|thunderbolts", re.I)
# Sub-categories that mix DC and Marvel: decide per figure by its name.
_MIXED_CAT = re.compile(r"mighty micros|super heroes other|juniors|4\+|promotional|^$", re.I)

_DC_NAME = re.compile(r"\b(" + "|".join([
    r"bat(man|girl|woman|zarro|cow)", r"robin", r"nightwing", r"red hood", r"joker", r"harley",
    r"catwoman", r"penguin", r"riddler", r"two-face", r"bane", r"poison ivy", r"scarecrow",
    r"mr\.? freeze", r"killer croc", r"killer moth", r"man-bat", r"clayface", r"alfred",
    r"(commissioner|jim|james|barbara) gordon", r"super(man|girl|boy)", r"krypto", r"lex luthor", r"lois lane",
    r"jimmy olsen", r"bizarro", r"brainiac", r"doomsday", r"general zod", r"zod", r"jor-el",
    r"wonder woman", r"cheetah", r"steve trevor", r"etta candy", r"aquaman", r"black manta",
    r"mera", r"(reverse )?flash", r"captain cold", r"cyborg", r"green lantern", r"sinestro",
    r"green arrow", r"arsenal", r"martian manhunter", r"hawk(man|girl)", r"darkseid",
    r"steppenwolf", r"parademon", r"shazam", r"black adam", r"lobo", r"firestorm",
    r"killer frost", r"plastic man", r"gorilla grodd", r"trickster", r"deathstroke",
    r"black lightning", r"lightning lad", r"cosmic boy", r"saturn girl", r"atom", r"vixen",
    r"starfire", r"raven", r"beast boy", r"blue beetle", r"booster gold", r"zatanna",
    r"swamp thing", r"constantine", r"deadshot", r"captain boomerang", r"katana",
    r"bronze tiger", r"black canary", r"huntress", r"metallo", r"parasite", r"toyman",
    r"mxyzptlk", r"val-zod", r"calendar man", r"egghead", r"mad hatter", r"hush",
    r"talia", r"ra'?s al ghul", r"deadman", r"kite man", r"condiment king",
]) + r")\b", re.I)
_MARVEL_NAME = re.compile(r"\b(" + "|".join([
    r"iron man", r"spider", r"captain america", r"hulk", r"thor", r"loki", r"thanos",
    r"black widow", r"hawkeye", r"deadpool", r"venom", r"carnage", r"wolverine", r"groot",
    r"rocket", r"star-lord", r"gamora", r"drax", r"nebula", r"ant-man", r"wasp",
    r"doctor strange", r"dr\.? strange", r"dr\.? doom", r"doom", r"black panther",
    r"captain marvel", r"scorpion", r"electro", r"falcon", r"war machine", r"vision",
    r"ultron", r"nick fury", r"magneto", r"cyclops", r"ghost rider", r"green goblin",
    r"doctor octopus", r"doc ock", r"mysterio", r"sandman", r"vulture", r"rhino",
    r"winter soldier", r"bucky", r"shuri", r"okoye", r"killmonger", r"mantis", r"yondu",
    r"silver surfer", r"galactus", r"dormammu", r"wong", r"kang", r"sam wilson",
    r"steve rogers", r"tony stark", r"peter parker", r"miles morales", r"gwen",
]) + r")\b", re.I)


def side_of(category_path: list[str], name: str) -> str:
    """'dc', 'marvel', 'unsure' or '' (not a super hero figure at all)."""
    segs = [s.strip() for s in category_path]
    low = [s.lower() for s in segs]
    root = low[0] if low else ""

    if root == "batman i" or root.startswith("dc super hero girls"):
        return "dc"
    if "super heroes" in low:
        sub = segs[low.index("super heroes") + 1:]
        sub_txt = " / ".join(sub)
        if sub and not _MIXED_CAT.search(sub[0]):
            if _DC_CAT.search(sub_txt):
                return "dc"
            if _MARVEL_CAT.search(sub_txt):
                return "marvel"
        # mixed or unknown sub-category -> use sub-sub-category, then the name
        if len(sub) > 1:
            rest = " / ".join(sub[1:])
            if _DC_CAT.search(rest):
                return "dc"
            if _MARVEL_CAT.search(rest):
                return "marvel"
        return _side_by_name(name) or "unsure"
    if root in ("the lego movie", "the lego movie 2", "dimensions") or root.startswith(
            ("the lego movie", "dimensions")):
        return _side_by_name(name) if _DC_NAME.search(name) else ""
    return ""


def _side_by_name(name: str) -> str:
    n = name.replace("Shazam / Captain Marvel", "Shazam")
    dc = _DC_NAME.search(n)
    mv = _MARVEL_NAME.search(n)
    if dc and not mv:
        return "dc"
    if mv and not dc:
        return "marvel"
    if dc and mv:
        return "dc" if dc.start() < mv.start() else "marvel"
    return ""


# ------------------------------------------------------------------ parsing

@dataclass
class ImportResult:
    figures: list[Figure]
    total_rows: int
    marvel: int = 0
    unsure: int = 0
    has_year: bool = True
    file_name: str = ""
    warnings: list[str] = field(default_factory=list)


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


_ID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


def _rows_from_tsv(text: str) -> tuple[list[dict], bool]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ImportError_("Die Datei ist leer.")
    head = [h.strip().lower() for h in lines[0].split("\t")]

    def col(*patterns: str) -> int:
        for i, h in enumerate(head):
            if any(re.fullmatch(p, h) for p in patterns):
                return i
        return -1

    i_num = col(r"number", r"item ?no\.?", r"item ?number", r"item ?id")
    i_name = col(r"name", r"item ?name", r"description")
    i_cat = col(r"category ?name", r"category")
    i_cid = col(r"category ?id")
    i_year = next((i for i, h in enumerate(head) if "year" in h), -1)
    start = 1
    if i_num < 0 or i_name < 0:
        # no header: BrickLink's usual column order
        i_cid, i_cat, i_num, i_name, i_year, start = 0, 1, 2, 3, 4, 0
    rows = []
    for ln in lines[start:]:
        c = ln.split("\t")

        def get(i: int) -> str:
            return c[i].strip() if 0 <= i < len(c) else ""
        rows.append({"id": get(i_num), "name": get(i_name), "cat": get(i_cat),
                     "cat_id": get(i_cid), "year": get(i_year)})
    has_year = i_year >= 0 and any(re.fullmatch(r"\d{4}", r["year"]) for r in rows[:2000])
    return rows, has_year


def _rows_from_xml(text: str, categories: dict[str, str]) -> tuple[list[dict], bool]:
    try:
        root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    except ET.ParseError as exc:
        raise ImportError_(f"XML-Datei nicht lesbar: {exc}") from exc

    def pick(el, *names):
        for n in names:
            v = el.findtext(n)
            if v is not None:
                return v.strip()
        return ""
    rows = []
    for item in root.iter("ITEM"):
        cat_id = pick(item, "CATEGORY", "CATEGORYID")
        rows.append({"id": pick(item, "ITEMID", "ITEMNO", "NUMBER"),
                     "name": pick(item, "ITEMNAME", "NAME"),
                     "cat": pick(item, "CATEGORYNAME") or categories.get(cat_id, ""),
                     "cat_id": cat_id,
                     "year": pick(item, "ITEMYEAR", "YEAR", "YEARRELEASED")})
    has_year = any(re.fullmatch(r"\d{4}", r["year"]) for r in rows[:2000])
    return rows, has_year


def read_categories(path: Path) -> dict[str, str]:
    """BrickLink's 'Categories' download (id -> 'Parent / Child' name)."""
    text = _read_text(path)
    out: dict[str, str] = {}
    if text.lstrip().startswith("<"):
        try:
            root = ET.fromstring(text.encode("utf-8"))
        except ET.ParseError:
            return out
        for c in root.iter("CATEGORY"):
            cid = (c.findtext("CATEGORY") or "").strip()
            name = (c.findtext("CATEGORYNAME") or "").strip()
            if cid and name:
                out[cid] = _clean(name)
        return out
    for ln in text.splitlines()[1:]:
        parts = ln.split("\t")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            out[parts[0].strip()] = _clean(parts[1])
    return out


def is_categories_file(path: Path) -> bool:
    try:
        head = _read_text(path)[:400].lower()
    except OSError:
        return False
    first = head.splitlines()[0] if head.splitlines() else ""
    if "<catalog" in head and "<categoryname>" in head and "<itemid>" not in head:
        return True
    return first.startswith("category id") and "number" not in first and "name" in first \
        and first.count("\t") <= 2


def import_catalog(paths: list[Path] | Path) -> ImportResult:
    """Read one items file (plus an optional categories file) and keep DC figures."""
    if isinstance(paths, (str, Path)):
        paths = [Path(paths)]
    paths = [Path(p) for p in paths]
    cat_files = [p for p in paths if is_categories_file(p)]
    item_files = [p for p in paths if p not in cat_files]
    if not item_files:
        raise ImportError_("Bitte die Minifiguren-Datei (Minifigures.txt) auswählen.")
    categories: dict[str, str] = {}
    for p in cat_files:
        categories.update(read_categories(p))

    path = item_files[0]
    text = _read_text(path)
    if text.lstrip().startswith("<"):
        rows, has_year = _rows_from_xml(text, categories)
    else:
        rows, has_year = _rows_from_tsv(text)
    if not rows:
        raise ImportError_("In der Datei wurden keine Einträge gefunden.")

    rows = [r for r in rows if _ID_OK.match(r["id"] or "")]
    if not any(r["cat"] for r in rows):
        raise ImportError_(
            "Die Datei enthält keine Kategorienamen. Bitte bei BrickLink das Format "
            "„Tab-Delimited File“ wählen (oder zusätzlich die Kategorien-Datei auswählen).")
    if not any(r["id"].lower().startswith(("sh", "bat")) for r in rows):
        raise ImportError_(
            "In der Datei sind keine Super-Heroes-Figuren. Bitte bei BrickLink "
            "„Catalog Items“ → „Minifigures“ mit Category „All“ herunterladen.")

    res = ImportResult(figures=[], total_rows=len(rows), has_year=has_year, file_name=path.name)
    seen: set[str] = set()
    for r in rows:
        name = _clean(r["name"])
        cat_path = [s.strip() for s in _clean(r["cat"]).split(" / ") if s.strip()]
        side = side_of(cat_path, name)
        if side == "marvel":
            res.marvel += 1
            continue
        if side not in ("dc", "unsure"):
            continue
        key = r["id"].lower()
        if key in seen:
            continue
        seen.add(key)
        year = int(r["year"]) if re.fullmatch(r"\d{4}", r["year"] or "") else None
        f = Figure(item_id=r["id"], name=name, year=year, category_path=cat_path,
                   category_id=r["cat_id"], source="import", unsure=(side == "unsure"))
        if side == "unsure":
            res.unsure += 1
        res.figures.append(f)
    if len(rows) < 5000:
        res.warnings.append(
            f"Die Datei enthält nur {len(rows)} Minifiguren – ist es der komplette Katalog "
            "(Category „All“)?")
    if not has_year:
        res.warnings.append(
            "Die Datei enthält kein Erscheinungsjahr – Figuren vor 2008 können so nicht "
            "aussortiert werden. Beim Download bitte das Jahr („Year“) mit auswählen.")
    return res


def find_recent_download() -> Path | None:
    """Newest Minifigures*.txt/.xml in the usual download folders."""
    candidates = []
    for d in (Path.home() / "Downloads", Path.home() / "Download", Path.home() / "Desktop",
              Path.home() / "Schreibtisch"):
        if d.is_dir():
            for p in list(d.glob("Minifigures*.txt")) + list(d.glob("Minifigures*.xml")):
                try:
                    candidates.append((p.stat().st_mtime, p))
                except OSError:
                    pass
    return max(candidates)[1] if candidates else None
