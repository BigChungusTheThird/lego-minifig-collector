"""Collection management: owned, wishlist, notes, hide/show, backup."""
from dcchecklist.catalog import Figure
from dcchecklist.state import State


def make_state():
    st = State()
    figs = [Figure("sh0001", "Batman", 2012, ["Super Heroes", "Batman II"]),
            Figure("sh0002", "Robin", 2013, ["Super Heroes", "Batman II"]),
            Figure("bat001", "Old Batman", 2006, ["Batman I"]),               # hidden by rule
            Figure("sh0219", "Superman", 2016, ["Super Heroes", "Dawn of Justice"])]  # DCEU
    st.set_catalog(figs, 0, 9999, source="import")
    st.owned, st.wishlist, st.notes, st.overrides = set(), set(), {}, {}
    st.save_collection()
    return st


def test_hide_and_show():
    st = make_state()
    assert [f.item_id for f in st.selected()] == ["sh0001", "sh0002"]
    st.set_hidden(["sh0002"], True)
    assert [f.item_id for f in st.selected()] == ["sh0001"]
    assert st.overrides == {"sh0002": False}
    # show a figure the rules hide (pre-2008)
    st.set_hidden(["bat001"], False)
    assert st.is_visible("bat001") and st.overrides["bat001"] is True
    # hiding it again just drops the manual choice
    st.set_hidden(["bat001"], True)
    assert not st.is_visible("bat001") and "bat001" not in st.overrides
    assert {f.item_id for f in st.hidden()} == {"sh0002", "bat001", "sh0219"}


def test_owned_wishlist_notes_progress_and_persistence():
    st = make_state()
    st.set_owned(["sh0001"], True)
    st.set_wishlist(["sh0002"], True)
    st.set_note("sh0001", "  doppelt  ")
    st.set_note("sh0002", "   ")
    assert st.notes == {"sh0001": "doppelt"}
    prog = st.progress()
    assert (prog.owned, prog.total, prog.percent) == (1, 2, 50)
    assert [f.item_id for f in st.scope("missing")] == ["sh0002"]
    assert [f.item_id for f in st.scope("wishlist")] == ["sh0002"]
    again = State()                       # reload from disk
    assert again.owned == {"sh0001"} and again.wishlist == {"sh0002"}
    assert again.notes == {"sh0001": "doppelt"}


def test_backup_restore():
    st = make_state()
    st.set_owned(["sh0001", "sh0002"], True)
    data = st.collection_data()
    st.set_owned(["sh0001", "sh0002"], False)
    st.restore_collection(data)
    assert st.owned == {"sh0001", "sh0002"}
    import pytest
    with pytest.raises(ValueError):
        st.restore_collection({"foo": 1})


def test_prices_value_and_sorting(tmp_path):
    st = make_state()
    st.prices = {"sh0001": {"U": {"avg": 4.0}, "N": {"avg": 9.0}}, "sh0002": {"U": {"avg": 2.5}}}
    st.set_owned(["sh0001"], True)
    assert st.price("sh0001") == 4.0
    st.settings["price_prefer"] = "N"
    assert st.price("sh0001") == 9.0 and st.price("sh0002") == 2.5
    st.settings["price_prefer"] = "U"
    assert st.value(st.selected()) == (6.5, 2)
    (_t, figs), = st.sections(grouping="none", sort_by="price_desc")
    assert [f.item_id for f in figs] == ["sh0001", "sh0002"]


def test_csv_export(tmp_path):
    from dcchecklist.gui import write_csv
    st = make_state()
    st.set_owned(["sh0001"], True)
    st.prices = {"sh0001": {"region": "dach", "date": "2026-11-01", "U": {"avg": 4.5, "qty": 12}}}
    out = tmp_path / "x.csv"
    write_csv(out, st, st.selected())
    text = out.read_text(encoding="utf-8-sig").splitlines()
    assert text[0].startswith("Nummer;Name;Jahr;Kategorie;Hab ich")
    assert text[1].startswith("sh0001;Batman;2012;Super Heroes › Batman II;ja;;4,50;12")
