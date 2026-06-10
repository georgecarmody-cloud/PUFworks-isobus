"""Search 616R Diagnostic Manual PDF for ISOBUS/addressing terms."""
import re
import sys

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Install: pip install pymupdf")
    sys.exit(1)

PDF = r"C:\Projects\General_files\Repair Manuals\616R Diagnostic Manual.pdf"
TERMS = [
    "isobus", "iso 11783", "j1939", "source address", "address claim",
    "pgn", "working set", "task controller", "tc-sc", "ddi", "name field",
    "gwc", "src", "mnc", "nzc", "bhc", "bhs", "vpu", "exactapply",
    "see & spray", "network address", "can bus", "0x94", "0x17", "0x68",
    "spray rate", "section control", "greenstar", "commandcenter",
]

doc = fitz.open(PDF)
print(f"Pages: {doc.page_count}\n")

# TOC: find acronym table page
for i in range(min(200, doc.page_count)):
    t = doc[i].get_text()
    if "acronym table" in t.lower() and i < 20:
        print(f"=== Acronym Table area page {i+1} ===")
        print(t[:4000])
        print()

hits = []
for i in range(doc.page_count):
    t = doc[i].get_text()
    tl = t.lower()
    matched = [term for term in TERMS if term in tl]
    if matched:
        hits.append((i + 1, matched, t))

print(f"Pages with hits: {len(hits)}\n")
for page, matched, text in hits[:60]:
    print(f"--- Page {page} | {', '.join(matched[:5])} ---")
    # Print lines containing matches
    for line in text.splitlines():
        ll = line.lower()
        if any(term in ll for term in matched):
            print(line.strip()[:200])
    print()

# Deep extract: pages with multiple ISOBUS-related terms
priority = [p for p, m, _ in hits if sum(1 for t in ["isobus", "j1939", "pgn", "address", "gwc", "src", "task controller"] if any(t in x for x in m)) >= 2]
print(f"\nPriority pages: {priority[:30]}")
for page in priority[:8]:
    idx = page - 1
    print(f"\n======== FULL PAGE {page} ========")
    print(doc[idx].get_text()[:6000])
