import fitz

PDF = r"C:\Projects\General_files\Repair Manuals\616R Diagnostic Manual.pdf"
doc = fitz.open(PDF)

PAGES = [
    4357, 4358, 4360, 4361, 4363, 4364, 4365, 4366,  # addressing/can continuation
    4320, 4321, 4322,  # Basic CAN / Implement CAN TOC refs - search by anchor
]

for p in PAGES:
    if 1 <= p <= doc.page_count:
        t = doc[p-1].get_text()
        if len(t) > 200:
            print(f"\n{'#'*70}\nPAGE {p}\n{'#'*70}\n{t[:8000]}")

# Search implement CAN and PDU theory content pages
for i in range(doc.page_count):
    t = doc[i].get_text()
    tl = t.lower()
    if "implement can bus" in tl and "theory of operation" in tl and "component information" in tl and len(t) > 1500:
        print(f"\n{'#'*70}\nIMPLEMENT CAN PAGE {i+1}\n{'#'*70}\n{t[:6000]}")
        break

for i in range(doc.page_count):
    t = doc[i].get_text()
    if t.startswith("4320") or "[TOC-ANCHOR" in t and "Basic Controller Area Network" in t:
        if "basic controller area network" in t.lower() and len(t) > 1000:
            print(f"\n{'#'*70}\nBASIC CAN PAGE {i+1}\n{'#'*70}\n{t[:6000]}")

# MNC NZC VPU SRC SR1 acronym search in pages 131-145
for i in range(130, 150):
    t = doc[i].get_text()
    if any(x in t for x in ["GWC", "SRC", "MNC", "NZC", "VPU", "SR1", "PSSC", "SSSC", "SC1", "PDU"]):
        print(f"\n--- acronym page {i+1} ---\n{t}")
