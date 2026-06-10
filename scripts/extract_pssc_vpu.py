import fitz
PDF = r"C:\Projects\General_files\Repair Manuals\616R Diagnostic Manual.pdf"
doc = fitz.open(PDF)

for p in [5692, 5693, 5694, 5695, 5690, 5691, 4150, 4151, 4152, 4153, 4154, 4155, 4156, 4157]:
    if 1 <= p <= doc.page_count:
        t = doc[p-1].get_text()
        if len(t) > 300:
            print(f"\n{'#'*70}\nPAGE {p}\n{'#'*70}\n{t[:9000]}")

for i in range(doc.page_count):
    t = doc[i].get_text()
    if t.startswith("415") or "[TOC-ANCHOR" in t[:50]:
        if "implement can bus" in t.lower() and "component information" in t.lower() and "vehicle can bus" in t.lower():
            print(f"\n{'#'*70}\nIMPLEMENT CAN THEORY PAGE {i+1}\n{'#'*70}\n{t[:8000]}")
            break
