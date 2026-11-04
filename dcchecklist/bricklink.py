"""BrickLink URL builders and HTML parsers.

The parsers deliberately avoid depending on exact CSS classes: BrickLink's
classic catalog pages are old table layouts that change now and then. Items
are found through their catalog links (``...catalogitem.page?M=sh0532``), and
everything else (name, category, picture) is read from the smallest page
element that belongs to exactly one item.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .config import BL_BASE, BL_IMG

# --------------------------------------------------------------------- URLs

def list_url(*, promo_cat_id: int | None = None, cat_string: str | None = None,
             year: int | None = None, page: int = 1, cat_type: str = "M") -> str:
    params: list[tuple[str, str | int]] = [("catType", cat_type)]
    if cat_string:
        params.append(("catString", cat_string))
    if promo_cat_id:
        params.append(("promoCatID", promo_cat_id))
    if year:
        params.append(("itemYear", year))
    if page > 1:
        params.append(("pg", page))
    params.append(("v", 1))  # list view: one row per item incl. category
    return f"{BL_BASE}/catalogList.asp?{urlencode(params)}"


def item_url(item_id: str, item_type: str = "M") -> str:
    return f"{BL_BASE}/v2/catalog/catalogitem.page?{item_type}={item_id}"


def set_inventory_url(set_no: str) -> str:
    return f"{BL_BASE}/catalogItemInv.asp?S={set_no}"


def image_urls(item_id: str, thumb: str | None = None) -> list[str]:
    """Candidate picture URLs, best first."""
    urls = [
        f"{BL_IMG}/ItemImage/MN/0/{item_id}.png",
        f"{BL_IMG}/ItemImage/ML/{item_id}.png",
        f"{BL_IMG}/M/{item_id}.jpg",
        f"{BL_IMG}/M/{item_id}.gif",
    ]
    if thumb:
        t = urljoin(BL_BASE + "/", thumb)
        # list thumbnails look like .../ItemImage/MT/0/sh0532.t1.png
        bigger = re.sub(r"/ItemImage/MT/", "/ItemImage/MN/", t)
        bigger = re.sub(r"\.t\d+\.(png|jpg|gif)$", r".\1", bigger)
        for u in (bigger, t):
            if u not in urls:
                urls.append(u)
    return urls


# ------------------------------------------------------------------ parsing

_ITEM_HREF = re.compile(r"(?:catalogitem\.page|catalogItem\.asp)\?(?:[^\"'#]*&)?M=([^&\"'#\s]+)", re.I)
_CAT_HREF = re.compile(r"catString=([0-9.]+)", re.I)
_WS = re.compile(r"\s+")


@dataclass
class ListedItem:
    item_id: str
    name: str = ""
    category_path: list[str] = field(default_factory=list)
    category_id: str = ""
    thumb: str = ""


@dataclass
class ListPage:
    items: list[ListedItem]
    total_items: int | None
    total_pages: int | None
    no_results: bool


def _clean(text: str) -> str:
    return _WS.sub(" ", text.replace("\xa0", " ")).strip()


def item_id_from_href(href: str) -> str | None:
    m = _ITEM_HREF.search(href or "")
    if not m:
        return None
    return unquote(m.group(1)).strip()


def _item_ids_under(tag: Tag) -> set[str]:
    ids = set()
    for a in tag.find_all("a", href=True):
        iid = item_id_from_href(a["href"])
        if iid:
            ids.add(iid.lower())
    return ids


def _container_for(anchor: Tag, item_id: str) -> Tag:
    """Largest ancestor of ``anchor`` that contains links to this item only."""
    best: Tag = anchor
    node = anchor.parent
    key = item_id.lower()
    while isinstance(node, Tag) and node.name not in ("body", "html", "[document]"):
        ids = _item_ids_under(node)
        if ids and ids != {key}:
            break
        best = node
        if node.name == "tr":
            # a table row per item is exactly what we want
            break
        node = node.parent
    return best


def _category_from(container: Tag) -> tuple[list[str], str]:
    names: list[str] = []
    cat_id = ""
    for a in container.find_all("a", href=True):
        m = _CAT_HREF.search(a["href"])
        if not m:
            continue
        label = _clean(a.get_text(" "))
        if label and label.lower() not in ("minifigures", "minifigs", "minifig"):
            names.append(label)
            cat_id = m.group(1)
    if names:
        return names, cat_id
    # text fallback: "Cat: Minifigures: Super Heroes: Batman II"
    text = _clean(container.get_text(" "))
    m = re.search(r"Cat(?:egory)?\s*:\s*(.+)$", text)
    if m:
        parts = [_clean(p) for p in m.group(1).split(":")]
        parts = [p for p in parts if p and p.lower() not in ("minifigures", "minifigs")]
        return parts, ""
    return [], ""


def _name_from(container: Tag, item_id: str) -> str:
    key = item_id.lower()
    for tag_name in ("strong", "b"):
        for el in container.find_all(tag_name):
            t = _clean(el.get_text(" "))
            if t and t.lower() != key and len(t) > 2 and not t.lower().startswith("cat:"):
                return t
    best = ""
    for a in container.find_all("a", href=True):
        if item_id_from_href(a["href"]):
            t = _clean(a.get_text(" "))
            if t.lower() != key and len(t) > len(best):
                best = t
    if best:
        return best
    for img in container.find_all("img"):
        for attr in ("alt", "title"):
            t = _clean(img.get(attr, ""))
            if t and t.lower() != key and len(t) > 2:
                return re.sub(rf"^{re.escape(item_id)}\s*[:\-]?\s*", "", t, flags=re.I)
    return ""


def _thumb_from(container: Tag) -> str:
    for img in container.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if "ItemImage" in src or "/M/" in src:
            return src
    return ""


def _page_numbers(soup: BeautifulSoup) -> tuple[int | None, int | None]:
    text = _clean(soup.get_text(" "))
    total_items = None
    m = (re.search(r"(\d[\d,.]*)\s+Items?\s+Found", text, re.I)
         or re.search(r"Items?\s+Found\s*:?\s*(\d[\d,.]*)", text, re.I))
    if m:
        try:
            total_items = int(re.sub(r"[,.]", "", m.group(1)))
        except ValueError:
            pass
    total_pages = None
    m = re.search(r"Page\s+\d+\s+of\s+(\d+)", text, re.I)
    if m:
        total_pages = int(m.group(1))
    else:
        pages = [int(p) for p in re.findall(r"[?&]pg=(\d+)", str(soup))]
        if pages:
            total_pages = max(pages)
    return total_items, total_pages


def parse_list_page(html: str) -> ListPage:
    soup = BeautifulSoup(html or "", "html.parser")
    seen: dict[str, ListedItem] = {}
    order: list[str] = []
    for a in soup.find_all("a", href=True):
        iid = item_id_from_href(a["href"])
        if not iid:
            continue
        key = iid.lower()
        if key in seen:
            continue
        box = _container_for(a, iid)
        cat_path, cat_id = _category_from(box)
        item = ListedItem(item_id=iid, name=_name_from(box, iid),
                          category_path=cat_path, category_id=cat_id,
                          thumb=_thumb_from(box))
        seen[key] = item
        order.append(key)
    total_items, total_pages = _page_numbers(soup)
    lower = (html or "").lower()
    no_results = not order and ("no item" in lower and "found" in lower)
    return ListPage([seen[k] for k in order], total_items, total_pages, no_results)


@dataclass
class ItemDetails:
    item_id: str
    name: str = ""
    year: int | None = None
    category_path: list[str] = field(default_factory=list)


def parse_item_page(html: str, item_id: str) -> ItemDetails:
    soup = BeautifulSoup(html or "", "html.parser")
    det = ItemDetails(item_id=item_id)
    el = soup.find(id="item-name-title")
    if el:
        det.name = _clean(el.get_text(" "))
    title = _clean(soup.title.get_text(" ")) if soup.title else ""
    # "Catalog: Minifigures: Super Heroes: Dawn of Justice: sh0532"
    if title.lower().startswith("catalog:"):
        parts = [_clean(p) for p in title.split(":")[1:]]
        parts = [p for p in parts if p]
        if parts and parts[-1].lower() == item_id.lower():
            parts = parts[:-1]
        if parts and parts[0].lower() in ("minifigures", "minifigs"):
            parts = parts[1:]
        det.category_path = parts
    text = str(soup)
    m = re.search(r"Year\s+Released\s*:?\s*(?:</?[^>]+>\s*)*(\d{4})", text, re.I)
    if not m:
        m = re.search(r"itemYear=(\d{4})", text)
    if m:
        det.year = int(m.group(1))
    return det


def parse_set_inventory(html: str) -> set[str]:
    """Minifigure ids contained in a set inventory page."""
    soup = BeautifulSoup(html or "", "html.parser")
    ids: set[str] = set()
    for a in soup.find_all("a", href=True):
        iid = item_id_from_href(a["href"])
        if iid:
            ids.add(iid)
    return ids


def query_value(url: str, key: str) -> str | None:
    vals = parse_qs(urlparse(url).query).get(key)
    return vals[0] if vals else None
