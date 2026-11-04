import re

from dcchecklist import prices


def test_oauth_signature_rfc5849_example():
    # RFC 5849, section 1.2 (photos.example.net)
    h = prices.oauth_header(
        "GET", "http://photos.example.net/photos", {"file": "vacation.jpg", "size": "original"},
        "dpf43f3p2l4k3l03", "kd94hf93k423kf44", "nnch734d00sl2jdk", "pfkkdhi9sl3r4s00",
        nonce="chapoH", timestamp="137131202", version=None)
    sig = re.search(r'oauth_signature="([^"]+)"', h).group(1)
    assert sig == "MdpQcU8iPSUjWoN%2FUDMsK2sui9I%3D"


def test_combine_weighted_by_quantity():
    de = {"qty_avg_price": "4.00", "avg_price": "4.50", "total_quantity": 30, "unit_quantity": 20,
          "min_price": "2.00", "max_price": "9.00"}
    at = {"qty_avg_price": "6.00", "total_quantity": 10, "unit_quantity": 5,
          "min_price": "5.00", "max_price": "7.00"}
    ch = {"total_quantity": 0}
    r = prices.combine([de, at, ch])
    assert r == {"avg": 4.5, "qty": 40, "lots": 25, "min": 2.0, "max": 9.0}
    assert prices.combine([ch])["avg"] is None


def test_stale_and_format():
    rec = {"date": "2000-01-01", "region": "dach", "currency": "EUR", "U": {"avg": 3.5}}
    assert prices.stale(rec, "dach", 14, ["U"], "EUR")
    assert prices.stale(None, "dach", 14, ["U"], "EUR")
    import datetime as dt
    rec["date"] = dt.date.today().isoformat()
    assert not prices.stale(rec, "dach", 14, ["U"], "EUR")
    assert prices.stale(rec, "eu", 14, ["U"], "EUR")
    assert prices.stale(rec, "dach", 14, ["U", "N"], "EUR")
    assert prices.money(1234.5) == "1.234,50 €"
    assert prices.main_price(rec) == 3.5
    assert prices.main_price({"N": {"avg": 7.0}, "U": {"avg": None}}) == 7.0
    assert prices.calls_per_figure("dach", ["U", "N"]) == 6
