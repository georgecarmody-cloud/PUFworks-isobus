"""Dump selected pages of the liquid GRC Operator's Manual to a UTF-8 text file."""
import fitz

PDF = r"C:\Users\georg\Downloads\GreenStar Rate Controller - StellarSupport - John Deere.pdf"
OUT = r"C:\Projects\PUFVision\scripts\grc_operator_pages.txt"

PAGES = [21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 37,
         38, 40, 54, 61, 62, 63, 64, 66, 69, 71, 81, 86, 90, 102, 104, 105]

doc = fitz.open(PDF)
with open(OUT, "w", encoding="utf-8") as f:
    for p in PAGES:
        if 1 <= p <= doc.page_count:
            f.write(f"\n======== PAGE {p} ========\n")
            f.write(doc[p - 1].get_text())
print(f"Wrote {OUT}")
