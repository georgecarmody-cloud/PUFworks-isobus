import fitz

PDF = r"C:\Projects\General_files\Repair Manuals\616R Diagnostic Manual.pdf"
doc = fitz.open(PDF)

# Extract full diagnostic pages referenced in TOC for GWC addressing
for page_num in [1525, 1527, 1529, 1547, 1549, 1551, 1554, 4356, 4359, 4362, 5680, 5681, 5684, 5685, 5686, 5687]:
    if 1 <= page_num <= doc.page_count:
        t = doc[page_num-1].get_text()
        print(f"\n{'#'*70}\nPDF PAGE {page_num} (len={len(t)})\n{'#'*70}\n")
        print(t[:12000])
