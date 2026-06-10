import fitz

PDF = r"C:\Projects\General_files\Repair Manuals\616R Diagnostic Manual.pdf"
doc = fitz.open(PDF)

TARGETS = [
    "See & Spray Addressing",
    "See & Spray CAN Bus",
    "See & Spray Ethernet",
    "GWC Electrical Theory of Operation",
    "GWC — Electrical Theory of Operation",
    "GWC ù Electrical Theory of Operation",
    "MNC ù Electrical Theory of Operation",
    "NZC ù Electrical Theory of Operation",
    "VPU ù Electrical Theory of Operation",
    "PDU ù Electrical Theory of Operation",
    "GWC 001235.11",
    "GWC 001672.11",
    "Addressing Fault with Gateway",
    "Addressing procedure",
]

for i in range(doc.page_count):
    t = doc[i].get_text()
    for target in TARGETS:
        if target.lower() in t.lower():
            print(f"\n{'='*70}\nMATCH '{target}' on PDF page {i+1}\n{'='*70}")
            print(t[:9000])
            break
