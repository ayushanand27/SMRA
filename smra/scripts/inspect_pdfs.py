import sys
from pathlib import Path

smra_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(smra_root))

from dotenv import load_dotenv
load_dotenv()

PDF_DIR = smra_root / "pdfs"
if not PDF_DIR.exists():
    print("No pdfs/ folder found at", PDF_DIR)
    raise SystemExit(1)

print("Inspecting PDFs in:", PDF_DIR)

# Try langchain loader first, then pdfplumber
try:
    from langchain_community.document_loaders import PyPDFLoader
    HAS_LOADER = True
except Exception:
    HAS_LOADER = False

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except Exception:
    HAS_PDFPLUMBER = False

for p in sorted(PDF_DIR.glob("*.pdf")):
    print("\n===", p.name)
    extracted = ""
    if HAS_LOADER:
        try:
            loader = PyPDFLoader(str(p))
            docs = loader.load()
            extracted = "\n".join([getattr(d, "page_content", "") or "" for d in docs])
            print(f"PyPDFLoader extracted {len(extracted)} chars")
            print(extracted[:1000])
            continue
        except Exception as e:
            print("PyPDFLoader failed:", e)
    if HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(p) as pdf:
                full = []
                for i, page in enumerate(pdf.pages):
                    t = page.extract_text()
                    if t:
                        full.append(t)
                    else:
                        # show if page contains images
                        imgs = getattr(page, "images", None)
                        if imgs:
                            print(f" page {i}: no text, {len(imgs)} images present")
                extracted = "\n".join(full)
                print(f"pdfplumber extracted {len(extracted)} chars")
                print(extracted[:1000])
                continue
        except Exception as e:
            print("pdfplumber failed:", e)
    print("No text-extraction tool available or extraction failed. Install 'langchain_community' or 'pdfplumber'.")
    print("If the PDF is scanned (images only), run an OCR pass (e.g., ocrmypdf) to produce a searchable PDF.")
