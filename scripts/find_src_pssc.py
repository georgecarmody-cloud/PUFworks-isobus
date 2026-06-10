import fitz
PDF = r"C:\Projects\General_files\Repair Manuals\616R Diagnostic Manual.pdf"
doc = fitz.open(PDF)
for term in ["PSSC", "SSSC", "SRC", "Spray Rate", "Primary Solution", "SC1", "PDU — Electrical Theory", "VPU — Electrical Theory"]:
    for i in range(doc.page_count):
        t = doc[i].get_text()
        if term.lower() in t.lower() and "theory of operation" in t.lower() and len(t) > 800:
            print(f"\n=== {term} page {i+1} ===\n{t[:4000]}")
            break
