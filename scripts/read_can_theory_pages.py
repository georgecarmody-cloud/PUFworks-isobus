import fitz
PDF = r"C:\Projects\General_files\Repair Manuals\616R Diagnostic Manual.pdf"
doc = fitz.open(PDF)
for p in range(4238, 4260):
    t = doc[p-1].get_text()
    if "Theory of Operation" in t or "Component Information" in t:
        print(f"\n{'#'*70}\nPDF PAGE {p} (len={len(t)})\n{'#'*70}\n{t[:10000]}")
