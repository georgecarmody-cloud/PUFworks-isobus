"""Extract key pages from 616R manual for system overview."""
import fitz

PDF = r"C:\Projects\General_files\Repair Manuals\616R Diagnostic Manual.pdf"
doc = fitz.open(PDF)

PAGES = [
    130,  # acronym table (doc ref)
    26, 27, 28, 29, 30,  # SA index pages
    136, 137,  # machine specs
    170, 173,  # diagnostic philosophy
    1483, 1484,  # addressing fault detail if exists
    2385, 2407, 2484, 2494, 2532, 2543, 2607, 2620,  # sample SA detail pages
    5605, 5624,  # J1939 pages
]

for p in PAGES:
    if p < 1 or p > doc.page_count:
        continue
    t = doc[p-1].get_text()
    print(f"\n{'#'*70}\nPAGE {p}\n{'#'*70}\n")
    print(t[:8000])
