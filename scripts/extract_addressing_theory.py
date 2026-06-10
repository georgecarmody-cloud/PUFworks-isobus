import fitz

PDF = r"C:\Projects\General_files\Repair Manuals\616R Diagnostic Manual.pdf"
doc = fitz.open(PDF)

# Find actual content pages (not TOC) by unique phrases
PHRASES = [
    "addressing procedure at start-up",
    "Gateway Network Interconnect",
    "Gateway Control Unit",
    "vision processing unit",
    "ExactApply subnet",
    "Boom CAN Bus",
    "CAN bus 1",
    "CAN bus 2",
    "CAN bus 3",
    "Indexed Boom Section",
    "corner post display",
    "Modular Telematics Gateway",
    "address claim",
    "source address 148",
    "source address 023",
    "source address 104",
]

seen = set()
for i in range(doc.page_count):
    t = doc[i].get_text()
    tl = t.lower()
    for p in PHRASES:
        if p.lower() in tl and len(t) > 800:
            key = (i+1, p)
            if key in seen:
                continue
            seen.add(key)
            print(f"\n{'='*70}\nPAGE {i+1} | phrase: {p}\n{'='*70}")
            print(t[:10000])
