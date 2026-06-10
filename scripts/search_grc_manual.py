"""Search GreenStar Rate Controller PDF (TM116619) for integration-relevant terms."""
import sys

try:
    import fitz
except ImportError:
    print("Install: pip install pymupdf")
    sys.exit(1)

PDF = r"C:\Projects\General_files\Repair Manuals\GreenStar Rate Controller.pdf"
TERMS = [
    "isobus", "iso 11783", "j1939", "can", "pgn", "ddi", "task controller",
    "section", "rate", "source address", "address", "process data",
    "greenstar", "grc", "gdc", "sbc", "spray", "valve", "pwm", "meter",
    "limb home", "limp home", "bypass", "terminator", "0x", "work state",
    "prescription", "setpoint", "flow",
]

doc = fitz.open(PDF)
print(f"Pages: {doc.page_count}\n")

# Print TOC-ish pages with theory/addresses
for target in [37, 46, 47, 311, 322, 383, 396, 422, 428, 432]:
    if 1 <= target <= doc.page_count:
        print(f"======== PAGE {target} ========")
        print(doc[target - 1].get_text()[:5000])
        print()

hits = []
for i in range(doc.page_count):
    t = doc[i].get_text()
    tl = t.lower()
    matched = [term for term in TERMS if term in tl]
    if matched:
        hits.append((i + 1, matched))

print(f"\nPages with hits: {len(hits)}")
for page, matched in hits:
    uniq = []
    for m in matched:
        if m not in uniq:
            uniq.append(m)
    print(f"  {page}: {', '.join(uniq[:8])}")
