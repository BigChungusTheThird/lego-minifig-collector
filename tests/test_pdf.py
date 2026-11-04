from PIL import Image

from dcchecklist.catalog import Figure, build_sections, image_path
from dcchecklist.pdf import PdfOptions, build_pdf, estimate_pages


def test_pdf(tmp_path):
    figs = []
    for i in range(30):
        f = Figure(f"sh{i:04d}", "Testfigur mit einem sehr langen Namen – Variante ÄÖÜ ß ★",
                   2010 + i % 10, ["Super Heroes", "Batman II" if i % 2 else "Justice League"])
        figs.append(f)
        if i % 3:
            Image.new("RGBA", (50, 80), (200, 30, 30, 255)).save(image_path(f.item_id), "PNG")
    secs = build_sections(figs)
    for opts in (PdfOptions(), PdfOptions(fillable=False, columns=4, orientation="landscape",
                                          paper="Letter", new_page_per_section=True)):
        out = build_pdf(tmp_path / "x.pdf", secs, opts, owned={"sh0001"})
        data = out.read_bytes()
        assert data.startswith(b"%PDF") and len(data) > 5000
        assert estimate_pages(secs, opts) >= 1
