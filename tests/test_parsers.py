from pathlib import Path

from dcchecklist import bricklink as bl

FIX = Path(__file__).parent / "fixtures"


def test_list_page():
    page = bl.parse_list_page((FIX / "list_page.html").read_text())
    ids = [i.item_id for i in page.items]
    assert ids == ["sh0532", "sh0458", "coltlbm01"]
    first = page.items[0]
    assert first.name == "Batman - Knightmare Batman"
    assert first.category_path == ["Super Heroes", "Dawn of Justice"]
    assert first.category_id == "768.1056"
    assert first.thumb.endswith("sh0532.t1.png")
    assert page.items[2].category_path[0] == "Collectible Minifigures"
    assert page.total_items == 3
    assert page.total_pages == 2


def test_item_page():
    det = bl.parse_item_page((FIX / "item_page.html").read_text(), "sh0532")
    assert det.year == 2018
    assert det.name == "Batman - Knightmare Batman"
    assert det.category_path == ["Super Heroes", "Dawn of Justice"]


def test_set_inventory():
    ids = bl.parse_set_inventory((FIX / "set_inventory.html").read_text())
    assert ids == {"sh0219", "sh0427"}


def test_urls():
    u = bl.list_url(promo_cat_id=247, year=2018, page=2)
    assert "promoCatID=247" in u and "itemYear=2018" in u and "pg=2" in u
    imgs = bl.image_urls("sh0532", "//img.bricklink.com/ItemImage/MT/0/sh0532.t1.png")
    assert imgs[0] == "https://img.bricklink.com/ItemImage/MN/0/sh0532.png"


def test_grid_layout_items():
    html = """<table><tr>
      <td><a href="catalogitem.page?M=sh0001"><img src="x/ItemImage/MT/0/sh0001.t1.png"></a>
          <br><a href="catalogitem.page?M=sh0001">Batman</a></td>
      <td><a href="catalogitem.page?M=sh0002"><img src="x/ItemImage/MT/0/sh0002.t1.png"></a>
          <br><a href="catalogitem.page?M=sh0002">Robin</a></td></tr></table>"""
    page = bl.parse_list_page(html)
    assert [(i.item_id, i.name) for i in page.items] == [("sh0001", "Batman"), ("sh0002", "Robin")]


def test_challenge_detection():
    from dcchecklist.net import is_challenge, looks_blocked
    assert is_challenge(202, "<html></html>")
    assert is_challenge(200, "<script>window.gokuProps = {}</script>")
    assert is_challenge(200, "x", {"x-amzn-waf-action": "challenge"})
    assert not is_challenge(200, "<html>" + "x" * 40000 + "</html>")
    assert looks_blocked(429, "")
