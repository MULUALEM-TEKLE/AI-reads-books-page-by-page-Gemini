from pathlib import Path
from typing import Dict, Any, Optional
import json
import json5
from google.generativeai import GenerativeModel, configure
import google.generativeai as genai
import fitz  # PyMuPDF
from termcolor import colored
from datetime import datetime
import shutil

# source for the infinite descent book: https://infinitedescent.xyz/dl/infdesc.pdf

# Configuration Constants
PDF_NAME = None
BASE_DIR = Path("book_analysis")
PDF_DIR = BASE_DIR / "pdfs"
INPUT_BOOKS_DIR = Path("input_books")
KNOWLEDGE_DIR = BASE_DIR / "knowledge_bases"
SUMMARIES_DIR = BASE_DIR / "summaries"

ANALYSIS_INTERVAL = 20  # Set to None to skip interval analyses, or a number for analysis every N pages
MODEL = "gemini-2.0-flash-001"
TEST_PAGES = None  # Set to None to process entire book




def load_or_create_knowledge_base(pdf_name: str) -> Dict[str, Any]:
    output_path = KNOWLEDGE_DIR / f"{pdf_name.replace('.pdf', '')}_knowledge.json"
    if Path(output_path).exists():
        with open(output_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_knowledge_base(knowledge_base: list[str], pdf_name: str):
    output_path = KNOWLEDGE_DIR / f"{pdf_name.replace('.pdf', '')}_knowledge.json"
    print(colored(f"💾 Saving knowledge base ({len(knowledge_base)} items)...", "blue"))
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({"knowledge": knowledge_base}, f, indent=2)

def process_page(model: GenerativeModel, page_text: str, current_knowledge: list[str], page_num: int, pdf_name: str) -> list[str]:
    print(colored(f"\n📖 Processing page {page_num + 1}...", "yellow"))

    prompt = f"""Analyze this page as if you're studying from a book.

        SKIP content if the page contains:
        - Table of contents
        - Chapter listings
        - Index pages
        - Blank pages
        - Copyright information
        - Publishing details
        - References or bibliography
        - Acknowledgments

        DO extract knowledge if the page contains:
        - Preface content that explains important concepts
        - Actual educational content
        - Key definitions and concepts
        - Important arguments or theories
        - Examples and case studies
        - Significant findings or conclusions
        - Methodologies or frameworks
        - Critical analyses or interpretations

        For valid content:
        - Set has_content to true
        - Extract detailed, learnable knowledge points
        - Include important quotes or key statements
        - Capture examples with their context
        - Preserve technical terms and definitions

        For pages to skip:
        - Set has_content to false
        - Return empty knowledge list

        Page text: {page_text}

        Return a valid JSON object with the following keys:
        - has_content (boolean): true if the page contains relevant content, false otherwise.
        - knowledge (list): A list of knowledge points extracted from the page. The list should be empty if has_content is false.
        Ensure the JSON is valid and can be parsed by Python's json.loads function.
        """

    response = model.generate_content(prompt)
    print(colored(f"Gemini Response: {response.text}", "magenta"))

    updated_knowledge = current_knowledge
    try:
        text = response.text.replace("```json", "").replace("```", "")
        result = json5.loads(text)
        has_content = result.get("has_content", False, )
        knowledge = result.get("knowledge", [], )

        if has_content:
            print(colored(f"✅ Found {len(knowledge)} new knowledge points", "green"))
            updated_knowledge = current_knowledge + knowledge
        else:
            print(colored("⏭️  Skipping page (no relevant content)", "yellow"))

    except json.JSONDecodeError:
        print(colored("❌ Error decoding JSON response from Gemini", "red"))

    # Update single knowledge base file
    save_knowledge_base(updated_knowledge, pdf_name)

    return updated_knowledge

def load_existing_knowledge(pdf_name: str) -> list[str]:
    knowledge_file = KNOWLEDGE_DIR / f"{pdf_name.replace('.pdf', '')}_knowledge.json"
    if knowledge_file.exists():
        print(colored("📚 Loading existing knowledge base...", "cyan"))
        with open(knowledge_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            print(colored(f"✅ Loaded {len(data['knowledge'])} existing knowledge points", "green"))
            return data['knowledge']
    print(colored("🆕 Starting with fresh knowledge base", "cyan"))
    return []

def analyze_knowledge_base(model: GenerativeModel, knowledge_base: list[Any], pdf_name: str) -> str:
    if not knowledge_base:
        print(colored("\n⚠️  Skipping analysis: No knowledge points collected", "yellow"))
        return ""

    knowledge_base_str = [str(item) for item in knowledge_base]

    print(colored("\n🤔 Generating final book analysis for {pdf_name}...", "cyan"))
    prompt = f"""Create a comprehensive summary of the provided content in a concise but detailed way, using markdown format.

        Use markdown formatting:
        - ## for main sections
        - ### for subsections
        - Bullet points for lists
        - `code blocks` for any code or formulas
        - **bold** for emphasis
        - *italic* for terminology
        - > blockquotes for important notes

        Return only the markdown summary, nothing else. Do not say 'here is the summary' or anything like that before or after

        Analyze this content:\n""" + "\n".join(knowledge_base_str) + """

        Return only the markdown summary, nothing else. Do not include any JSON.
        """

    try:
        response = model.generate_content(prompt)
        print(colored("✨ Analysis generated successfully!", "green"))
        return response.text
    except ValueError as e:
        print(colored(f"❌ Error generating analysis: {e}", "red"))
        return ""

def setup_directories():
    # Clear all previously generated files
    for directory in [KNOWLEDGE_DIR, SUMMARIES_DIR]:
        if directory.exists():
            # Only delete files, not the directories themselves
            for file in directory.glob("*"):
                if file.is_file():
                    file.unlink()

    # Create all necessary directories
    for directory in [PDF_DIR, KNOWLEDGE_DIR, SUMMARIES_DIR, INPUT_BOOKS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)

def save_summary(summary: str, is_final: bool, pdf_name: str):
    if not summary:
        print(colored("⏭️  Skipping summary save: No content to save", "yellow"))
        return

    # Create markdown file with proper naming
    if is_final:
        existing_summaries = list(SUMMARIES_DIR.glob(f"{pdf_name.replace('.pdf', '')}_final_*.md"))
        next_number = len(existing_summaries) + 1
        summary_path = SUMMARIES_DIR / f"{pdf_name.replace('.pdf', '')}_final_{next_number:03d}.md"
    else:
        existing_summaries = list(SUMMARIES_DIR.glob(f"{pdf_name.replace('.pdf', '')}_interval_*.md"))
        next_number = len(existing_summaries) + 1
        summary_path = SUMMARIES_DIR / f"{pdf_name.replace('.pdf', '')}_interval_{next_number:03d}.md"

    # Create markdown content with metadata
    markdown_content = f"""# Book Analysis: {pdf_name}
Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

{summary}

---
*Analysis generated using AI Book Analysis Tool*
"""

    print(colored(f"\n📝 Saving {'final' if is_final else 'interval'} analysis to markdown...", "cyan"))
    with open(summary_path, 'w', encoding='utf-8') as f:  # Added encoding='utf-8'
        f.write(markdown_content)
    print(colored(f"✅ Analysis saved to: {summary_path}", "green"))

def print_instructions():
    print(colored("""
📚 PDF Book Analysis Tool 📚
---------------------------
1. Place your PDF files in the input_books directory
2. Run the script. It will:
   - Process each book page by page
   - Extract and save knowledge points
   - Generate interval summaries (if enabled)
   - Create a final comprehensive analysis

Configuration options:
- ANALYSIS_INTERVAL: Set to None to skip interval analyses, or a number for analysis every N pages
- TEST_PAGES: Set to None to process entire book, or a number for partial processing

Press Enter to continue or Ctrl+C to exit...
""", "cyan"))

def get_pdf_files(directory: Path) -> list[Path]:
    pdf_files = list(Path(directory).resolve().glob("*.pdf"))
    print(colored(f"get_pdf_files: directory = {directory}, pdf_files = {pdf_files}", "magenta"))
    return pdf_files

def main():
    try:
        print_instructions()
        input()
    except KeyboardInterrupt:
        print(colored("\n❌ Process cancelled by user", "red"))
        return

    print(colored(f"main: INPUT_BOOKS_DIR = {INPUT_BOOKS_DIR}", "magenta"))

    setup_directories()

    from api_key import API_KEY
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel(MODEL)

    pdf_files = get_pdf_files(INPUT_BOOKS_DIR)
    if not pdf_files:
        print(colored("\n⚠️  No PDF files found in input_books directory", "yellow"))
        return

    for pdf_path in pdf_files:
        pdf_name = pdf_path.name
        print(colored(f"\n📚 Processing book: {pdf_name}...", "cyan"))

        # Load or initialize knowledge base
        knowledge_base = load_existing_knowledge(pdf_name)

        try:
            pdf_document = fitz.open(str(pdf_path))
            pages_to_process = TEST_PAGES if TEST_PAGES is not None else pdf_document.page_count

            print(colored(f"\n📚 Processing {pages_to_process} pages...", "cyan"))
            for page_num in range(min(pages_to_process, pdf_document.page_count)):
                page = pdf_document[page_num]
                page_text = page.get_text()

                knowledge_base = process_page(model, page_text, knowledge_base, page_num, pdf_name)

                # Generate interval analysis if ANALYSIS_INTERVAL is set
                if ANALYSIS_INTERVAL:
                    is_interval = (page_num + 1) % ANALYSIS_INTERVAL == 0
                    is_final_page = page_num + 1 == pages_to_process

                    if is_interval and not is_final_page:
                        print(colored(f"\n📊 Progress: {page_num + 1}/{pages_to_process} pages processed", "cyan"))
                        filtered_knowledge_base = [item for item in knowledge_base if (isinstance(item, dict) and len(item.get("point", "").split()) <= 50) or (isinstance(item, str) and len(item.split()) <= 50)]
                        interval_summary = analyze_knowledge_base(model, filtered_knowledge_base, pdf_name)
                        save_summary(interval_summary, is_final=False, pdf_name=pdf_name)

                # Always generate final analysis on last page
                if page_num + 1 == pages_to_process:
                    print(colored(f"\n📊 Final page ({page_num + 1}/{pages_to_process} pages processed", "cyan"))
                    filtered_knowledge_base = [item for item in knowledge_base if (isinstance(item, dict) and len(item.get("point", "").split()) <= 50) or (isinstance(item, str) and len(item.split()) <= 50)]
                    final_summary = analyze_knowledge_base(model, filtered_knowledge_base, pdf_name)
                    save_summary(final_summary, is_final=True, pdf_name=pdf_name)

            print(colored(f"\n✨ Processing of {pdf_name} complete! ✨", "green", attrs=['bold']))

        except Exception as e:
            print(colored(f"\n❌ Error processing {pdf_name}: {e}", "red"))
            continue

    print(colored("\n✨ Processing complete! ✨", "green", attrs=['bold']))

if __name__ == "__main__":
    main()
