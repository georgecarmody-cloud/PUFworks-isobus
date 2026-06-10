import fitz
PDF = r"C:\Projects\General_files\Repair Manuals\616R Diagnostic Manual.pdf"
doc = fitz.open(PDF)
for i in range(doc.page_count):
    t = doc[i].get_text()
    tl = t.lower()
    if "overview: can bus and lin bus" in tl or ("vehicle can bus 1 (vb1)" in tl and "implement can bus 2" in tl):
        print(f"\n{'#'*70}\nPAGE {i+1}\n{'#'*70}\n{t[:12000]}")
