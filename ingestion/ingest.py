import json
from pathlib import Path
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from splitter import VietnameseLegalSplitter

def process_legal_documents():
    # Setup directories
    raw_dir = Path("data/raw")
    preprocessed_dir = Path("data/preprocessed")
    chunked_dir = Path("data/chunked")
    
    preprocessed_dir.mkdir(parents=True, exist_ok=True)
    chunked_dir.mkdir(parents=True, exist_ok=True)
    
    # Docling pipeline options
    opts = PdfPipelineOptions(do_ocr=False)  # PDFs have a text layer
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=opts),
        }
    )
    
    pdf_files = list(raw_dir.glob("*.pdf"))
    print(f"Found {len(pdf_files)} PDF files in {raw_dir}")
    
    for pdf_path in pdf_files:
        doc_name = pdf_path.stem
        print(f"Processing: {pdf_path.name}")
        
        try:
            # 1. Convert PDF to Markdown using Docling
            conversion_res = converter.convert(pdf_path)
            doc = conversion_res.document
            markdown_content = doc.export_to_markdown()
            
            # 2. Save raw Markdown to data/preprocessed/
            md_path = preprocessed_dir / f"{doc_name}.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)
            print(f"  - Saved preprocessed markdown to: {md_path}")
            
            # 3. Chunk the document at the Khoản level
            splitter = VietnameseLegalSplitter(doc_name=doc_name)
            chunks = splitter.split_text(markdown_content)
            
            # 4. Save chunked JSON to data/chunked/
            json_path = chunked_dir / f"{doc_name}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(chunks, f, ensure_ascii=False, indent=2)
            print(f"  - Saved {len(chunks)} chunks to: {json_path}")
            
        except Exception as e:
            print(f"  - [ERROR] Failed to process {pdf_path.name}: {e}")

if __name__ == "__main__":
    process_legal_documents()