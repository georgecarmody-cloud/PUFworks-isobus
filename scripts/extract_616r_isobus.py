"""Extract ISOBUS/network/addressing sections from 616R manual."""
import re
import fitz

PDF = r"C:\Projects\General_files\Repair Manuals\616R Diagnostic Manual.pdf"
doc = fitz.open(PDF)

# 1) Acronym table (doc page ~130 -> search)
for i in range(doc.page_count):
    t = doc[i].get_text()
    if re.search(r"^Acronym Table\s*$", t, re.M) or ("Acronym" in t and "GWC" in t and "Gateway" in t and len(t) > 2000):
        if "GWC" in t or "Gateway Network" in t:
            print(f"\n{'='*60}\nACRONYM / GLOSSARY CANDIDATE page {i+1}\n{'='*60}")
            print(t[:12000])
            break

# 2) Pages with ISOBUS or J1939 explicitly
print("\n\n=== EXPLICIT ISOBUS/J1939 PAGES ===")
for i in range(doc.page_count):
    t = doc[i].get_text()
    if "isobus" in t.lower() or "iso 11783" in t.lower() or "j1939" in t.lower():
        print(f"\n--- page {i+1} ---")
        for line in t.splitlines():
            ll = line.lower()
            if any(k in ll for k in ["isobus", "iso 11783", "j1939", "pgn", "source address", "address claim", "working set", "task controller", "virtual terminal"]):
                print(line.strip()[:220])

# 3) Source address listings (decimal SA references)
print("\n\n=== SOURCE ADDRESS REFERENCES ===")
sa_pages = {}
for i in range(doc.page_count):
    t = doc[i].get_text()
    for m in re.finditer(r"Source Address\s+(\d+)", t, re.I):
        sa = int(m.group(1))
        sa_pages.setdefault(sa, []).append(i+1)
for sa in sorted(sa_pages.keys()):
    print(f"SA {sa} (0x{sa:02X}): pages {sa_pages[sa][:8]}{'...' if len(sa_pages[sa])>8 else ''}")

# 4) Network / communication overview sections
print("\n\n=== NETWORK TOPOLOGY KEYWORDS ===")
keys = ["network interconnect", "gateway control", "exactapply subnet", "vision processing", "see & spray control", "communication system", "can subnet", "ethernet"]
for i in range(doc.page_count):
    t = doc[i].get_text().lower()
    score = sum(1 for k in keys if k in t)
    if score >= 3 and len(t) > 1500:
        print(f"page {i+1} score={score}")
        # first 80 lines
        lines = [l.strip() for l in doc[i].get_text().splitlines() if l.strip()][:40]
        for l in lines:
            print(" ", l[:180])

# 5) DTC detail pages for addressing faults
print("\n\n=== ADDRESSING FAULT DETAIL PAGES ===")
for i in range(doc.page_count):
    t = doc[i].get_text()
    if "Addressing Fault" in t and "GWC" in t and "Description" in t:
        print(f"\n--- page {i+1} ---")
        print(t[:5000])
