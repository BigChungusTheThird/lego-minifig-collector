from dcchecklist.catalog import Figure, build_sections, classify_group, decide
from dcchecklist.state import default_settings


def s(**kw):
    d = default_settings()
    d["year_to"] = 2026
    d.update(kw)
    return d


def test_groups():
    assert classify_group(["Batman I"]) == "batman1"
    assert classify_group(["Super Heroes", "Batman II"]) == "sh"
    assert classify_group(["Super Heroes", "The LEGO Batman Movie"]) == "tlbm"
    assert classify_group(["Collectible Minifigures", "The LEGO Batman Movie Series 2"]) == "cmf_tlbm"
    assert classify_group(["Collectible Minifigures", "DC Super Heroes"]) == "cmf_dc"
    assert classify_group(["Super Heroes", "Mighty Micros"]) == "mm"
    assert classify_group(["DUPLO", "Super Heroes", "Batman II"]) == "duplo"
    assert classify_group(["Game", "Super Heroes", "Batman II"]) == "misc"
    assert classify_group(["The LEGO Movie"]) == "other"


def test_year_and_marvel():
    old = Figure("bat001", "Batman", 2006, ["Batman I"])
    assert not decide(old, s()).include
    new = Figure("bat030", "Batman", 2008, ["Batman I"])
    assert decide(new, s()).include
    marvel = Figure("sh0100", "Iron Man", 2015, ["Super Heroes", "Avengers"])
    assert not decide(marvel, s()).include


def test_dceu_and_knightmare():
    sup = Figure("sh0219", "Superman", 2016, ["Super Heroes", "Justice League"], dceu_sets=["76087-1"])
    assert not decide(sup, s()).include
    assert decide(sup, s(exclude_dceu=False)).include
    # removing the set from the list makes the figure count as non-DCEU
    assert decide(sup, s(dceu_sets=["76044-1"])).include
    km = Figure("sh0532", "Batman - Knightmare Batman", 2018, ["Super Heroes", "Dawn of Justice"])
    assert decide(km, s()).include
    assert not decide(km, s(keep_knightmare=False)).include
    other = Figure("sh0217", "Batman - Armored", 2016, ["Super Heroes", "Dawn of Justice"])
    assert not decide(other, s()).include


def test_overrides_and_groups_off():
    f = Figure("sh0300", "Batman", 2017, ["Super Heroes", "Mighty Micros"])
    assert decide(f, s()).include
    assert not decide(f, s(groups=["sh"])).include
    assert decide(f, s(groups=["sh"]), {"sh0300": True}).include
    assert not decide(f, s(), {"sh0300": False}).include


def test_sections():
    figs = [Figure("sh0002", "B", 2013, ["Super Heroes", "Batman II"]),
            Figure("bat030", "A", 2008, ["Batman I"]),
            Figure("sh0001", "C", 2012, ["Super Heroes", "Batman II"])]
    secs = build_sections(figs, "category", "year")
    assert [t for t, _ in secs] == ["Batman I", "Batman II"]
    assert [f.item_id for f in secs[1][1]] == ["sh0001", "sh0002"]
    by_year = build_sections(figs, "year", "id")
    assert [t for t, _ in by_year] == ["2008", "2012", "2013"]
