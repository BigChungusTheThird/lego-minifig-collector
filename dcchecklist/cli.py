"""Command line: headless fetch / PDF build and a live smoke test (used by CI)."""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

from . import bricklink as bl
from . import config
from .catalog import Figure, Scraper, decide, download_images
from .net import Client
from .pdf import build_pdf
from .state import State


def _log(msg: str) -> None:
    print(msg, flush=True)


def _progress(_f: float, _t: str) -> None:
    pass


def cmd_fetch(args) -> int:
    st = State()
    if args.year_from:
        st.settings["year_from"] = args.year_from
    if args.year_to:
        st.settings["year_to"] = args.year_to
    cancel = threading.Event()
    client = Client(log=_log, cancel=cancel, use_cache=not args.no_cache)
    scraper = Scraper(client, _log, _progress, cancel)
    try:
        figs = scraper.collect(st.year_from, st.year_to, cross_check=not args.no_cross_check,
                               dceu_sets=st.settings["dceu_sets"])
        st.set_catalog(figs, st.year_from, st.year_to)
        sel = st.selected()
        _log(f"{len(figs)} Figuren im Katalog, {len(sel)} auf der Liste")
        if not args.no_images:
            download_images(client, sel, _progress, _log, cancel)
    finally:
        client.close()
    return 0 if figs else 1


def cmd_pdf(args) -> int:
    st = State()
    if not st.figures:
        _log("Kein Katalog vorhanden – zuerst 'fetch' ausführen.")
        return 1
    opts = st.pdf_options()
    if args.columns:
        opts.columns = args.columns
    sections = st.sections()
    n = sum(len(f) for _s, f in sections)
    if not args.no_images:
        client = Client(log=_log)
        try:
            download_images(client, [f for _s, fs in sections for f in fs], _progress, _log,
                            threading.Event())
        finally:
            client.close()
    out = build_pdf(args.output, sections, opts, st.owned)
    _log(f"PDF mit {n} Figuren geschrieben: {out}")
    return 0


def cmd_list(args) -> int:
    st = State()
    rs = st.rule_settings()
    for f in sorted(st.figures, key=lambda f: (f.category_label, f.year or 0, f.item_id)):
        d = decide(f, rs, st.overrides)
        if args.all or d.include:
            print(f"{'+' if d.include else '-'} {f.item_id:<12} {f.year or '????'}  "
                  f"{f.category_label:<45.45}  {f.name[:70]}  {d.reason}")
    return 0


def cmd_smoke(args) -> int:
    """Talk to the real BrickLink and print what the parsers see."""
    ok = True
    client = Client(log=_log, use_cache=False, page_delay=(1.0, 1.5))
    try:
        return _smoke(client, args)
    finally:
        client.close()


def _smoke(client: Client, args) -> int:
    ok = True

    def show(label, html, n=1500):
        _log(f"\n===== {label}: {len(html)} bytes =====")
        idx = html.find("catalogitem.page?M=")
        if idx < 0:
            idx = html.find("M=")
        start = max(0, idx - n // 2)
        _log(html[start:start + n] if args.dump else "(dump off)")

    url = bl.list_url(promo_cat_id=config.DC_PROMO_CAT_ID, year=2018)
    html = client.get_page(url)
    show(url, html)
    page = bl.parse_list_page(html)
    _log(f"parsed: {len(page.items)} items, total_items={page.total_items}, "
         f"total_pages={page.total_pages}")
    for it in page.items[:12]:
        _log(f"  {it.item_id:<10} | {it.name[:60]:<60} | {' > '.join(it.category_path)} "
             f"| cat={it.category_id} | thumb={it.thumb[:60]}")
    ok &= len(page.items) > 0 and all(it.category_path for it in page.items[:5])

    if page.total_pages and page.total_pages > 1:
        html2 = client.get_page(bl.list_url(promo_cat_id=config.DC_PROMO_CAT_ID, year=2018, page=2))
        p2 = bl.parse_list_page(html2)
        overlap = {i.item_id for i in p2.items} & {i.item_id for i in page.items}
        _log(f"page 2: {len(p2.items)} items, overlap with page 1: {len(overlap)}")
        ok &= len(p2.items) > 0 and not overlap

    html = client.get_page(bl.list_url(promo_cat_id=config.DC_PROMO_CAT_ID, year=2009))
    p09 = bl.parse_list_page(html)
    _log(f"year 2009: {len(p09.items)} items (should differ from 2018)")
    for it in p09.items[:5]:
        _log(f"  {it.item_id:<10} | {it.name[:60]} | {' > '.join(it.category_path)}")

    html = client.get_page(bl.list_url(cat_string=config.CAT_BATMAN_II))
    pb = bl.parse_list_page(html)
    _log(f"category Batman II (no DC filter): {len(pb.items)} items on page 1, "
         f"total_items={pb.total_items}, pages={pb.total_pages}")
    html = client.get_page(bl.list_url(cat_string=config.CAT_BATMAN_II,
                                       promo_cat_id=config.DC_PROMO_CAT_ID))
    pbp = bl.parse_list_page(html)
    _log(f"category Batman II + DC filter: total_items={pbp.total_items}")

    html = client.get_page(bl.item_url("sh0532"))
    show("item sh0532", html, 800)
    det = bl.parse_item_page(html, "sh0532")
    _log(f"item sh0532: name={det.name!r} year={det.year} path={det.category_path}")
    ok &= det.year == 2018

    html = client.get_page(bl.set_inventory_url("76087-1"))
    ids = bl.parse_set_inventory(html)
    _log(f"set 76087-1 minifigs: {sorted(ids)}")
    ok &= len(ids) > 0

    for u in bl.image_urls("sh0532"):
        data = client.get_binary(u)
        _log(f"image {u}: {len(data) if data else None} bytes")
        if data:
            break
    else:
        ok = False

    _log(f"\npage requests: {client.page_requests}")
    _log("\nSMOKE " + ("OK" if ok else "FAILED"))
    return 0 if ok else 2


def cmd_diag(args) -> int:
    """One plain request per URL; print status, interesting headers and a body snippet."""
    import requests
    urls = [
        "https://www.bricklink.com/",
        bl.list_url(promo_cat_id=config.DC_PROMO_CAT_ID, year=2018),
        bl.item_url("sh0532"),
        "https://img.bricklink.com/ItemImage/MN/0/sh0532.png",
        "https://img.bricklink.com/ItemImage/MT/0/sh0532.t1.png",
        "https://api.bricklink.com/api/store/v1/items/MINIFIG/sh0532",
    ]
    s = requests.Session()
    s.headers.update({"User-Agent": config.USER_AGENT, "Accept-Language": "en-US,en;q=0.9",
                      "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    for u in urls:
        try:
            r = s.get(u, timeout=30)
        except Exception as exc:
            _log(f"{u}\n  ERROR {exc}")
            continue
        hdr = {k: v for k, v in r.headers.items() if k.lower() in (
            "server", "content-type", "content-length", "x-amzn-waf-action", "x-cache",
            "via", "cf-ray", "set-cookie", "x-amz-cf-id", "location")}
        _log(f"{u}\n  status={r.status_code} len={len(r.content)} headers={hdr}")
        if "text" in r.headers.get("Content-Type", "") or "json" in r.headers.get("Content-Type", ""):
            _log("  body: " + r.text[:700].replace("\n", " "))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dc-checklist", description=config.APP_NAME)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="Katalog von BrickLink laden")
    f.add_argument("--from", dest="year_from", type=int)
    f.add_argument("--to", dest="year_to", type=int)
    f.add_argument("--no-cross-check", action="store_true")
    f.add_argument("--no-cache", action="store_true")
    f.add_argument("--no-images", action="store_true")
    p = sub.add_parser("pdf", help="PDF erstellen")
    p.add_argument("output", type=Path)
    p.add_argument("--columns", type=int)
    p.add_argument("--no-images", action="store_true")
    ls = sub.add_parser("list", help="Figuren auflisten")
    ls.add_argument("--all", action="store_true", help="auch ausgeschlossene zeigen")
    sub.add_parser("diag", help="Einzelne Testanfragen an BrickLink")
    s = sub.add_parser("smoke", help="Live-Test gegen BrickLink")
    s.add_argument("--dump", action="store_true", help="HTML-Ausschnitte ausgeben")
    args = ap.parse_args(argv)
    return {"fetch": cmd_fetch, "pdf": cmd_pdf, "list": cmd_list, "smoke": cmd_smoke,
            "diag": cmd_diag}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
