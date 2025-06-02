import logging
import re
from pathlib import Path
from typing import List
from PyPDF2 import PdfReader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("pdf-scraper")

# Configurable paths
PDF_DIR = Path(__file__).parent / "raw_data_rag"
OUTPUT_FILE = Path(__file__).parent / "data/raw_data.txt"

class PDFScraper:
    def __init__(self):
        self.content: List[str] = []

    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extracts text from PDF while preserving structure"""
        text = ""
        try:
            with open(pdf_path, "rb") as f:
                reader = PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            return text
        except Exception as e:
            logger.error(f"Error reading PDF {pdf_path.name}: {e}")
            return ""

    def format_faq_content(self, text: str) -> List[str]:
        """Formats FAQ content with proper spacing between questions"""
        # Normalize line endings and clean up whitespace
        text = re.sub(r'\r\n', '\n', text)
        text = re.sub(r' +', ' ', text)  # Fix multiple spaces
        text = re.sub(r'\n+', '\n', text).strip()
        
        # Split into lines and process
        lines = []
        
        # Process each line
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # Detect FAQ sections (like "General Services")
            if re.match(r'^[A-Z][a-z]+(\s[A-Z][a-z]+)*$', line) and not re.search(r'[.?]', line):
                lines.append("")
                lines.append(line + ":")
                lines.append("")
                continue
                
            # Detect numbered questions
            if re.match(r'^\d+\.', line):
                lines.append("")
                lines.append(line)
            else:
                # This is part of an answer
                if lines:  # Append to last line if it exists
                    lines[-1] = lines[-1] + " " + line if lines[-1] else line
        
        # Remove first empty line if exists
        if lines and not lines[0]:
            lines = lines[1:]
            
        return lines

    def scrape(self):
        if not PDF_DIR.exists():
            logger.error(f"PDF directory not found: {PDF_DIR}")
            return False

        pdf_files = list(PDF_DIR.glob("*.pdf"))
        if not pdf_files:
            logger.error(f"No PDF files found in {PDF_DIR}")
            return False

        logger.info(f"Found {len(pdf_files)} PDFs to process")
        
        for pdf_file in pdf_files:
            logger.info(f"Processing PDF: {pdf_file.name}")
            text = self.extract_text_from_pdf(pdf_file)
            if text:
                formatted_content = self.format_faq_content(text)
                self.content.append(f"Content from PDF {pdf_file.name}:")
                self.content.append("")  # Empty line before content
                self.content.extend(formatted_content)
                self.content.append("")  # Empty line after content
        
        return True

    def save_content(self):
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                # Write with proper spacing
                f.write("\n".join(self.content))
            logger.info(f"Saved content to {OUTPUT_FILE}")
            return True
        except Exception as e:
            logger.error(f"Failed to save content: {e}")
            return False

def main():
    scraper = PDFScraper()
    if scraper.scrape():
        scraper.save_content()

if __name__ == "__main__":
    main()