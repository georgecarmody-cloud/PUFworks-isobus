import fitz
PDF = r"C:\Projects\General_files\Repair Manuals\616R Diagnostic Manual.pdf"
doc = fitz.open(PDF)
for i in range(doc.page_count):
    t = doc[i].get_text()
    if "implement can bus" in t.lower() and "binary unit system" in t.lower():
        if "vehicle can bus 1" in t.lower() or "ib1" in t.lower() or "implement can bus 2" in t.lower():
            if len(t) > 1200 and "theory of operation" in t.lower():
                print(f"\n{'#'*70}\nPAGE {i+1}\n{'#'*70}\n{t[:10000]}")
