"""Import of BrickLink's catalog download (sample rows in BrickLink's format)."""
from pathlib import Path

import pytest

from dcchecklist.catalog import decide
from dcchecklist.importer import ImportError_, import_catalog, side_of
from dcchecklist.state import default_settings

FIX = Path(__file__).parent / "fixtures"


def settings(**kw):
    s = default_settings()
    s["year_to"] = 2026
    s.update(kw)
    return s


@pytest.fixture(scope="module")
def result():
    return import_catalog(FIX / "Minifigures_sample.txt")


def test_marvel_and_other_themes_dropped(result):
    ids = {f.item_id for f in result.figures}
    assert {"sh0027", "sh0362", "sh0360"}.isdisjoint(ids)       # Iron Man, Spider-Man
    assert {"sw0002", "tlm051", "tlm184"}.isdisjoint(ids)       # Star Wars, Gordon Zola, Vampire Bat
    assert {"sh0358", "sh0349", "tlm082", "dim002", "shg001"} <= ids
    assert result.marvel == 3


def test_names_are_unescaped(result):
    f = next(f for f in result.figures if f.item_id == "coltlbm01")
    assert f.name.startswith("Lobster Lovin' Batman")
    assert f.category_path[-1] == "The LEGO Batman Movie Series 1"


def test_rules(result):
    s = settings()
    d = {f.item_id: decide(f, s) for f in result.figures}
    on = {i for i, x in d.items() if x.include}
    # DC comic / TV / other films: on the list
    assert {"bat024", "bat026", "sh0003", "sh0151", "sh0458", "sh0473", "sh0533", "sh0001",
            "sh0358", "coltlbm01", "coltlbm21", "colsh01", "sh1152"} <= on
    # before 2008
    assert d["bat001"].reason == "vor 2008"
    # DCEU films
    for i in ("sh0429", "sh0435", "sh0438", "sh0217", "sh0219", "sh0075", "sh0393", "sh0634",
              "sh0524", "sh1122", "sh0586"):
        assert d[i].reason == "DCEU-Film", i
    # Knightmare Batman stays
    assert d["sh0532"].include and d["sh0532"].reason == "Knightmare-Ausnahme"
    # optional themes are off by default
    assert not d["tlm082"].include and not d["shg001"].include
    assert d["sh1152"].include and next(f for f in result.figures if f.item_id == "sh1152").year is None


def test_side_of():
    assert side_of(["Super Heroes", "Avengers"], "Thor") == "marvel"
    assert side_of(["Super Heroes", "The Batman"], "Riddler") == "dc"
    assert side_of(["Super Heroes", "Super Heroes Other"], "Shazam / Captain Marvel") == "dc"
    assert side_of(["Super Heroes", "Mighty Micros"], "Doomsday - Short Legs") == "dc"
    assert side_of(["Super Heroes", "Mighty Micros"], "Dr. Doom") == "marvel"
    assert side_of(["Super Heroes", "Super Heroes Other"], "Mystery Guy") == "unsure"
    assert side_of(["Star Wars"], "Batman") == ""


def test_headerless_and_xml(tmp_path):
    rows = (FIX / "Minifigures_sample.txt").read_text(encoding="utf-8").splitlines()[1:]
    p = tmp_path / "Minifigures.txt"
    p.write_text("\n".join(rows), encoding="cp1252", errors="replace")
    assert len(import_catalog(p).figures) == len(import_catalog(FIX / "Minifigures_sample.txt").figures)

    xml = tmp_path / "Minifigures.xml"
    xml.write_text("<CATALOG><ITEM><ITEMTYPE>M</ITEMTYPE><ITEMID>sh0458</ITEMID>"
                   "<ITEMNAME>Batman, Neck Bracket</ITEMNAME><CATEGORY>768</CATEGORY>"
                   "<ITEMYEAR>2018</ITEMYEAR></ITEM></CATALOG>", encoding="utf-8")
    cats = tmp_path / "categories.txt"
    cats.write_text("Category ID\tCategory Name\n768\tSuper Heroes / Justice League\n",
                    encoding="utf-8")
    res = import_catalog([xml, cats])
    assert [(f.item_id, f.year, f.category_path) for f in res.figures] == [
        ("sh0458", 2018, ["Super Heroes", "Justice League"])]
    with pytest.raises(ImportError_):
        import_catalog([xml])          # XML without category names


def test_not_a_catalog(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("Category ID\tCategory Name\tNumber\tName\n0\tStar Wars\tsw0002\tBoba\n")
    with pytest.raises(ImportError_):
        import_catalog(p)
