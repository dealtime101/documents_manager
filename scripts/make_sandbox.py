"""Creates sample PDFs in FOLDER/inbox so you can try `docflow --sandbox FOLDER scan`.
usage: PYTHONPATH=backend uv run python scripts/make_sandbox.py ~/docflow-sandbox"""
import argparse
import shutil
from pathlib import Path

# The text lines are French on purpose: they imitate real French-language documents.
SAMPLES = {
    "hydro_bill_oct.pdf": ["Hydro-Québec", "Facture d'électricité du 7 octobre 2025", "Numéro de facture : 123456789",
                           "Montant de la présente facture : 158,98 $"],
    "hydro_equal_payments.pdf": ["Hydro-Québec", "Facture d'électricité du 9 mars 2026", "Mode de versements égaux",
                                 "Numéro de facture : 555000111", "Montant de la présente facture : 119,40 $"],
    "blue_cross_card.pdf": ["Croix Bleue Medavie", "Carte d'identification", "Assurance santé collective"],
    "amazon_order.pdf": ["Amazon.com.ca ULC", "Invoice date / Date de facturation: 09 January 2026",
                         "Order date / Date de commande: 08 January 2026", "Description Quantity Unit price Discount GST QST Total",
                         "Friskies Chef's Blend Dry Cat Food 7.5kg 1 $22.99 $0.00 $1.15 $2.29 $26.43",
                         "Total $26.43"],
    "unknown_letter.pdf": ["Lettre de la tante Huguette", "Le 3 mai 2025", "Chère famille, tout va bien ici."],
}


def make(path: Path, lines: list[str]) -> None:
    """A one-page PDF with `lines` of text (Helvetica, Latin-1 letters kept). Written by hand, so no PDF library is needed."""
    def escape(text: str) -> bytes:
        return text.encode("cp1252", "replace").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    content = b"BT /F1 12 Tf 60 750 Td 22 TL " + b" ".join(b"(" + escape(t) + b") Tj T*" for t in lines) + b" ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(bytes(out))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create sample PDFs in FOLDER/inbox for `docflow --sandbox FOLDER scan`.")
    parser.add_argument("folder", metavar="FOLDER", help="sandbox folder (created if missing), e.g. ~/docflow-sandbox")
    inbox = Path(parser.parse_args().folder).expanduser() / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    for name, lines in SAMPLES.items():
        make(inbox / name, lines)
    shutil.copy(inbox / "hydro_bill_oct.pdf", inbox / "hydro_bill_oct_COPY.pdf")  # exact duplicate
    # what this run wrote (the samples and the duplicate), not whatever else the inbox already holds
    print(f"{len(SAMPLES) + 1} sample PDFs in {inbox}")
