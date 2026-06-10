import fitz
PDF = r"C:\Projects\General_files\Repair Manuals\616R Diagnostic Manual.pdf"
doc = fitz.open(PDF)
targets = [
    "Overview: CAN Bus and LIN Bus",
    "Implement CAN Bus",
    "Boom CAN Bus",
    "ExactApply CAN Bus",
    "Vehicle CAN Bus",
    "Basic Controller Area Network (CAN) Theory",
]
found = set()
for i in range(doc.page_count):
    t = doc[i].get_text()
    for target in targets:
        if target in t and "Component Information" in t and target not in found:
            found.add(target)
            print(f"\n{'#'*70}\n{target} — PDF PAGE {i+1}\n{'#'*70}\n{t[:11000]}")
