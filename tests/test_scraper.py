"""Scraper orchestration against a fake BrickLink (synthetic HTML)."""
import threading
from urllib.parse import parse_qs, urlparse

from dcchecklist.catalog import Scraper


def row(iid, name, cats):
    links = "".join(f':&nbsp;<a href="catalogList.asp?catType=M&catString={cid}">{label}</a>'
                    for cid, label in cats)
    return (f'<tr><td><a href="/v2/catalog/catalogitem.page?M={iid}">{iid}</a></td>'
            f'<td><strong>{name}</strong><br><font>Cat: <a href="catalog.asp">Minifigures</a>'
            f'{links}</font></td></tr>')


SH = ("768", "Super Heroes")
B2 = ("768.769", "Batman II")
JL = ("768.900", "Justice League")
B1 = ("570", "Batman I")

BY_YEAR = {
    2008: [row("bat030", "Batman - Black Suit", [B1])],
    2016: [row("sh0219", "Superman - Dark Blue Suit", [SH, JL])],
    2017: [row(f"sh{400 + i:04d}", f"Figur {i}", [SH, B2]) for i in range(60)],
}


class FakeClient:
    def __init__(self):
        self.page_requests = 0
        self.urls = []

    def get_page(self, url, max_age_days=7):
        self.page_requests += 1
        self.urls.append(url)
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        if "catalogItemInv" in url:
            if q.get("S") == "76087-1":
                return '<a href="/v2/catalog/catalogitem.page?M=sh0219">sh0219</a>'
            return "<html></html>"
        if "catalogitem.page" in url:
            return ('<title>Catalog: Minifigures: Super Heroes: Batman II: sh9999</title>'
                    '<td>Year Released: <a href="x?itemYear=2019">2019</a></td>')
        rows = []
        if "promoCatID" in q:
            rows = BY_YEAR.get(int(q.get("itemYear", 0)), [])
        elif q.get("catString") == "768.769":
            rows = BY_YEAR[2017] + [row("sh9999", "Hidden Batman", [SH, B2])]
        elif q.get("catString") == "570":
            rows = BY_YEAR[2008] if q.get("itemYear") == "2008" else []
        page = int(q.get("pg", 1))
        chunk = rows[(page - 1) * 50: page * 50]
        pages = max(1, (len(rows) + 49) // 50)
        return (f"<p>{len(rows)} Items Found. Page {page} of {pages}</p><table>"
                + "".join(chunk) + "</table>")


def test_collect():
    client = FakeClient()
    logs = []
    sc = Scraper(client, logs.append, lambda f, t: None, threading.Event())
    figs = {f.item_id: f for f in sc.collect(2008, 2018)}
    assert len([i for i in figs if i.startswith("sh04")]) == 60      # 2 pages read
    assert figs["bat030"].year == 2008
    assert figs["sh0219"].dceu_sets == ["76087-1"]
    assert "sh9999" not in figs           # only in the category, released 2019 > 2018
    assert figs["sh0400"].category_path == ["Super Heroes", "Batman II"]


def test_cross_check_adds_untagged_figures():
    sc = Scraper(FakeClient(), lambda m: None, lambda f, t: None, threading.Event())
    figs = {f.item_id: f for f in sc.collect(2008, 2020)}
    assert figs["sh9999"].source == "category"
    assert figs["sh9999"].year == 2019
