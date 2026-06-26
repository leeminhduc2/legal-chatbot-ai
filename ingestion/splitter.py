import re
from pathlib import Path
from typing import Dict, Any, List

class VietnameseLegalSplitter:
    def __init__(self, doc_name: str):
        self.doc_name = doc_name
        
        # Regex patterns for matching legal hierarchical structures
        self.re_part = re.compile(r'^\s*#*\s*(Phần\s+[A-ZÀ-Ỹ0-9\-IVX]+|PHẦN\s+[A-ZÀ-Ỹ0-9\-IVX]+)(.*)', re.IGNORECASE)
        self.re_chapter = re.compile(r'^\s*#*\s*(Chương\s+[A-ZÀ-Ỹ0-9\-IVX]+|CHƯƠNG\s+[A-ZÀ-Ỹ0-9\-IVX]+)(.*)', re.IGNORECASE)
        self.re_section = re.compile(r'^\s*#*\s*(Mục\s+[0-9IVX]+)(.*)', re.IGNORECASE)
        self.re_subsection = re.compile(r'^\s*#*\s*(Tiểu\s*mục\s+[0-9IVX]+)(.*)', re.IGNORECASE)
        self.re_article = re.compile(r'^\s*#*\s*(Điều\s+\d+[\w]*)\.\s*(.*)', re.IGNORECASE)
        
        # Clause pattern: e.g. "1. " or "2. " at the start of a line
        self.re_clause = re.compile(r'^\s*(\d+)\.\s+(.*)')

    def normalize_text(self, text: str) -> str:
        # Insert newlines before headings if they are merged in a single line
        text = re.sub(r'(?<!\n)(Chương\s+[A-ZÀ-Ỹ0-9\-IVX]+|CHƯƠNG\s+[A-ZÀ-Ỹ0-9\-IVX]+)', r'\n\1', text)
        text = re.sub(r'(?<!\n)(Mục\s+[0-9IVX]+|MỤC\s+[0-9IVX]+)', r'\n\1', text)
        text = re.sub(r'(?<!\n)(Tiểu\s*mục\s+[0-9IVX]+|TIỂU\s*MỤC\s+[0-9IVX]+)', r'\n\1', text)
        text = re.sub(r'(?<!\n)(Điều\s+\d+[\w]*\.|ĐIỀU\s+\d+[\w]*\.)', r'\n\1', text)
        
        # Insert newlines before Clauses (e.g. " 2. Cơ quan" -> "\n2. Cơ quan")
        text = re.sub(r'(?<=\s)(\d+)\.\s+(?=[A-ZÀ-Ỹ])', r'\n\1. ', text)
        
        # Insert newlines before Points (e.g. "a) Người" -> "\na) Người")
        text = re.sub(r'(?<=\s)([a-zđ])\)\s+', r'\n\1) ', text)
        
        return text

    def split_text(self, text: str) -> List[Dict[str, Any]]:
        normalized_text = self.normalize_text(text)
        lines = normalized_text.split('\n')
        
        # State tracking
        current_part = None
        current_chapter = None
        current_section = None
        current_subsection = None
        current_article = None
        
        # Headers tracking to provide titles
        current_part_title = ""
        current_chapter_title = ""
        current_section_title = ""
        current_subsection_title = ""
        current_article_title = ""
        
        chunks = []
        
        # Temporary buffers for building chunks
        article_header_lines = []
        current_clause_num = None
        current_clause_lines = []
        
        def save_current_clause():
            nonlocal current_clause_num, current_clause_lines
            if not current_clause_lines:
                return
            
            # Construct hierarchy path and parents
            parents = []
            if current_part:
                parents.append(f"{current_part} {current_part_title}".strip())
            if current_chapter:
                parents.append(f"{current_chapter} {current_chapter_title}".strip())
            if current_section:
                parents.append(f"{current_section} {current_section_title}".strip())
            if current_subsection:
                parents.append(f"{current_subsection} {current_subsection_title}".strip())
            if current_article:
                parents.append(f"{current_article} {current_article_title}".strip())
                
            path_components = []
            if current_part: path_components.append(current_part)
            if current_chapter: path_components.append(current_chapter)
            if current_section: path_components.append(current_section)
            if current_subsection: path_components.append(current_subsection)
            if current_article: path_components.append(current_article)
            path_components.append(f"Khoản {current_clause_num}")
            
            hierarchy_path = " > ".join(path_components)
            prefix = f"[{self.doc_name} > {hierarchy_path}]\n"
            
            # Clean content and include Article header context
            article_header = "\n".join(article_header_lines).strip()
            # Remove markdown header syntax from article header when prepending for cleaner reading
            article_header_clean = re.sub(r'^#+\s*', '', article_header)
            
            clause_content = "\n".join(current_clause_lines).strip()
            
            if article_header_clean:
                full_content = f"{prefix}{article_header_clean}\n{clause_content}"
            else:
                full_content = f"{prefix}{clause_content}"
            
            chunk = {
                "chunk_id": f"{self.clean_id(self.doc_name)}_{self.clean_id(current_article or '')}_khoan_{current_clause_num}",
                "document_id": self.doc_name,
                "content": full_content,
                "metadata": {
                    "doc_name": self.doc_name,
                    "part": f"{current_part} {current_part_title}".strip() if current_part else None,
                    "chapter": f"{current_chapter} {current_chapter_title}".strip() if current_chapter else None,
                    "section": f"{current_section} {current_section_title}".strip() if current_section else None,
                    "subsection": f"{current_subsection} {current_subsection_title}".strip() if current_subsection else None,
                    "article": f"{current_article} {current_article_title}".strip() if current_article else None,
                    "clause": f"Khoản {current_clause_num}",
                    "hierarchy_path": hierarchy_path,
                    "parent_headers": parents,
                    "chunk_level": "clause"
                }
            }
            chunks.append(chunk)
            current_clause_lines = []
            current_clause_num = None

        def save_article_as_whole():
            """Called if an article contains text but no distinct clauses."""
            nonlocal article_header_lines
            if not article_header_lines:
                return
            
            parents = []
            if current_part:
                parents.append(f"{current_part} {current_part_title}".strip())
            if current_chapter:
                parents.append(f"{current_chapter} {current_chapter_title}".strip())
            if current_section:
                parents.append(f"{current_section} {current_section_title}".strip())
            if current_subsection:
                parents.append(f"{current_subsection} {current_subsection_title}".strip())
                
            path_components = []
            if current_part: path_components.append(current_part)
            if current_chapter: path_components.append(current_chapter)
            if current_section: path_components.append(current_section)
            if current_subsection: path_components.append(current_subsection)
            if current_article: path_components.append(current_article)
            
            hierarchy_path = " > ".join(path_components)
            prefix = f"[{self.doc_name} > {hierarchy_path}]\n"
            
            article_content = "\n".join(article_header_lines).strip()
            article_content_clean = re.sub(r'^#+\s*', '', article_content)
            
            chunk = {
                "chunk_id": f"{self.clean_id(self.doc_name)}_{self.clean_id(current_article or '')}",
                "document_id": self.doc_name,
                "content": f"{prefix}{article_content_clean}",
                "metadata": {
                    "doc_name": self.doc_name,
                    "part": f"{current_part} {current_part_title}".strip() if current_part else None,
                    "chapter": f"{current_chapter} {current_chapter_title}".strip() if current_chapter else None,
                    "section": f"{current_section} {current_section_title}".strip() if current_section else None,
                    "subsection": f"{current_subsection} {current_subsection_title}".strip() if current_subsection else None,
                    "article": f"{current_article} {current_article_title}".strip() if current_article else None,
                    "clause": None,
                    "hierarchy_path": hierarchy_path,
                    "parent_headers": parents,
                    "chunk_level": "article"
                }
            }
            chunks.append(chunk)
            article_header_lines = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_clause_num is not None:
                    current_clause_lines.append(line)
                elif current_article:
                    article_header_lines.append(line)
                continue
            
            # 1. Match Part
            m_part = self.re_part.match(line)
            if m_part:
                if current_clause_num is not None:
                    save_current_clause()
                elif article_header_lines:
                    save_article_as_whole()
                
                current_part = m_part.group(1).strip()
                current_part_title = m_part.group(2).strip().strip(':').strip()
                current_chapter = current_section = current_subsection = current_article = None
                continue
                
            # 2. Match Chapter
            m_chap = self.re_chapter.match(line)
            if m_chap:
                if current_clause_num is not None:
                    save_current_clause()
                elif article_header_lines:
                    save_article_as_whole()
                
                current_chapter = m_chap.group(1).strip()
                current_chapter_title = m_chap.group(2).strip().strip(':').strip()
                current_section = current_subsection = current_article = None
                continue
                
            # 3. Match Section
            m_sec = self.re_section.match(line)
            if m_sec:
                if current_clause_num is not None:
                    save_current_clause()
                elif article_header_lines:
                    save_article_as_whole()
                
                current_section = m_sec.group(1).strip()
                current_section_title = m_sec.group(2).strip().strip(':').strip()
                current_subsection = current_article = None
                continue
                
            # 4. Match Subsection
            m_subsec = self.re_subsection.match(line)
            if m_subsec:
                if current_clause_num is not None:
                    save_current_clause()
                elif article_header_lines:
                    save_article_as_whole()
                
                current_subsection = m_subsec.group(1).strip()
                current_subsection_title = m_subsec.group(2).strip().strip(':').strip()
                current_article = None
                continue
                
            # 5. Match Article
            m_art = self.re_article.match(line)
            if m_art:
                if current_clause_num is not None:
                    save_current_clause()
                elif article_header_lines:
                    save_article_as_whole()
                
                current_article = m_art.group(1).strip()
                current_article_title = m_art.group(2).strip()
                article_header_lines = [line]
                current_clause_num = None
                continue
                
            # 6. Match Clause (only valid if we are currently inside an Article)
            if current_article:
                m_clause = self.re_clause.match(line)
                if m_clause:
                    if current_clause_num is not None:
                        save_current_clause()
                    
                    current_clause_num = m_clause.group(1)
                    current_clause_lines = [line]
                    continue
            
            # Append content to the active block
            if current_clause_num is not None:
                current_clause_lines.append(line)
            elif current_article:
                article_header_lines.append(line)
                
        # End of document cleanup
        if current_clause_num is not None:
            save_current_clause()
        elif article_header_lines:
            save_article_as_whole()
            
        return chunks

    def clean_id(self, text: str) -> str:
        import unicodedata
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
        text = re.sub(r'[^a-zA-Z0-9_]', '_', text.lower())
        return re.sub(r'_+', '_', text).strip('_')
