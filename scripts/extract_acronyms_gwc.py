import fitz
import re

PDF = r"C:\Projects\General_files\Repair Manuals\616R Diagnostic Manual.pdf"
doc = fitz.open(PDF)

# Full acronym table spans multiple pages after page 130
for i in range(129, 160):
    t = doc[i].get_text()
    if "Acronym" in t or any(k in t for k in ["GWC", "SRC", "MNC", "NZC", "VPU", "MNA", "SR1", "PDU", "ISOBUS", "GS4", "GS5"]):
        print(f"\n=== PAGE {i+1} ===\n{t}")

# GWC addressing fault full procedure
for i in range(doc.page_count):
    t = doc[i].get_text()
    if "GWC 001235.11" in t or "GWC 001672.11" in t:
        print(f"\n=== ADDRESSING FAULT PAGE {i+1} ===\n{t[:7000]}")
        break

# Theory of operation for See & Spray / GWC
for i in range(doc.page_count):
    t = doc[i].get_text().lower()
    if "theory of operation" in t and ("see & spray" in t or "gateway" in t or "gwc" in t):
        print(f"\n=== THEORY PAGE {i+1} ===\n{doc[i].get_text()[:5000]}")
