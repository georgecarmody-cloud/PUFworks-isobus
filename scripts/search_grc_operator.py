"""Search the liquid GreenStar Rate Controller Operator's Manual (OMPFP10673)."""
import sys

try:
    import fitz
except ImportError:
    print("Install: pip install pymupdf")
    sys.exit(1)

PDF = r"C:\Users\georg\Downloads\GreenStar Rate Controller - StellarSupport - John Deere.pdf"
TERMS = [
    "greenseeker", "ndvi", "n-sens", "serial", "rs-232", "rs232", "com port",
    "prescription", "target rate", "sensor", "section", "flow control valve",
    "fast close", "pwm", "boom", "nh3", "chemical", "implement type",
    "controller address", "can", "j1939", "ddi", "pgn", "0xcc", "0xe1",
    "rate controller liquid", "third party", "raven", "task controller",
    "fertilizer", "valve", "as-applied", "vehicle bus", "implement bus",
]

doc = fitz.open(PDF)
print(f"Pages: {doc.page_count}\n")

hits = {}
for i in range(doc.page_count):
    t = doc[i].get_text().lower()
    for term in TERMS:
        if term in t:
            hits.setdefault(term, []).append(i + 1)

for term in TERMS:
    pages = hits.get(term, [])
    if pages:
        print(f"{term!r}: {len(pages)} pages -> {pages[:25]}")
    else:
        print(f"{term!r}: --none--")
