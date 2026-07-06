def normalize_llm_chunks(
    llm_chunks: list[dict[str, Any]],
    document_id: str,
    import_batch_id: str,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    normalized = []
    for index, chunk in enumerate(llm_chunks, start=1):
        content = str(chunk.get("content", "")).strip()
        if not content:
            continue
        raw_meta = chunk.get("metadata") or {}
        article_number = (
            optional_str(raw_meta.get("article_number"))
            or optional_str(raw_meta.get("article"))
            or str(index)
        )
        clause_number = optional_str(raw_meta.get("clause_number")) or optional_str(
            raw_meta.get("clause")
        )
        chunk_level = "clause" if clause_number else "article"
        normalized.append(
            build_chunk_record(
                content=content,
                document_id=document_id,
                import_batch_id=import_batch_id,
                metadata=metadata,
                article_number=article_number,
                clause_number=clause_number,
                chunk_level=chunk_level,
                ordinal=index,
            )
        )
    return normalized


_ARTICLE_HEADING_RE = re.compile(
    r"^\s*(?:\u0110i\u1ec1u|Dieu)\s+([0-9]+[a-zA-Z]?)\.?\s*(.*)$",
    re.IGNORECASE,
)
_CLAUSE_HEADING_RE = re.compile(r"^\s*(\d+)\.\s+")
_AMENDMENT_QUOTE_INTRO_RE = re.compile(
    r"(?:nh\u01b0|nhu)\s+sau\s*:\s*[\u201c\"]?\s*$",
    re.IGNORECASE,
)
_QUOTE_OPEN_CHARS = {"\u201c", "\u2018", "\u00ab"}
_QUOTE_CLOSE_CHARS = {"\u201d", "\u2019", "\u00bb"}
_QUOTE_START_CHARS = tuple(sorted([*_QUOTE_OPEN_CHARS, '"']))
EXTRACT_SEGMENTS_SEGMENT_PATTERN_1 = (
    r"(\n\s*[\u0110\u00d0]i\u1ec1u\s*\d+\s*\..*?|\n\s*[\u0110\u00d0]i\u1ec1u\s*\d+\s*:.*?|"
    r"\n\s*[\u0110\u00d0]i\u1ec1u\s*\d+\s*-\s*.*?|\n\s*[\u0110\u00d0]i\u1ec1u\s*\d+\s*:\s*.*?|"
    r"(?:^|\n)([\u0110\u00d0]i\u1ec1u\s*\d+\s*\n[\s\S]*?))"
    r"(?=(?:\n\s*[\u0110\u00d0]i\u1ec1u\s*\d+\s*[\.\-:]|$|"
    r"./\n|\./\.|\n\s*PH\u1ee4 L\u1ee4C [IVX]+|\n\s*PH\u1ee4 L\u1ee4C \d+|\n\s*PH\u1ee4 L\u1ee4C|"
    r"\n\s*Ph\u1ee5 l\u1ee5c [IVX]+|\n\s*Ph\u1ee5 l\u1ee5c \d+|\n\s*Ph\u1ee5 l\u1ee5c|"
    r"\nCh\u01b0\u01a1ng \d+|\nCH\u01af\u01a0NG \d+|\nCh\u01b0\u01a1ng [IVX]+|\nCH\u01af\u01a0NG [IVX]+|\nCH\u01af\u01a0NG TR\u00ccNH|"
    r"\nQUI CH\u1ebe|\nQUY \u0110\u1ecaNH\n|\nQUY CH\u1ebe\n|"
    r"\nC\u1ed8NG HO\u00c0 X\u00c3 H\u1ed8I CH\u1ee6 NGH\u0128A VI\u1ec6T NAM\n|\n\(\u0110\u00e3 k\u00fd\)|"
    r".\nM\u1ee5c \d+|.\nM\u1ee4C \d+|.\nTI\u1ec2U M\u1ee4C|.\nTi\u1ec3u m\u1ee5c|.\nTi\u1ec3u M\u1ee5c|\nM\u1ee5c [IVX]+|\nM\u1ee4C [IVX]+"
    r"\nN\u01a1i nh\u1eadn|\nKT\.|\nTM\.|\nTM/|\nT/M|\nM\u1ee4C L\u1ee4C|"
    r"\nCH\u1ee6 T\u1ecaCH N\u01af\u1edaC|\nTH\u1ee6 T\u01af\u1edaNG|\nPH\u00d3 TH\u1ee6 T\u01af\u1edaNG|\nB\u1ed8 TR\u01af\u1edeNG|\nTH\u1ee8 TR\u01af\u1edeNG|\nCH\u1ee6 T\u1ecaCH|\nPH\u00d3 CH\u1ee6 T\u1ecaCH|"
    r"\nTH\u1ed0NG \u0110\u1ed0C|\nPH\u00d3 TH\u1ed0NG \u0110\u1ed0C|\nT\u1ed4NG KI\u1ec2M TO\u00c1N NH\u00c0 N\u01af\u1edaC|\nPH\u00d3 T\u1ed4NG KI\u1ec2M TO\u00c1N NH\u00c0 N\u01af\u1edaC|"
    r"\nT\u1ed4NG THANH TRA|\nPH\u00d3 T\u1ed4NG THANH TRA|\nT\u1ed4NG KI\u1ec2M TO\u00c1N|\nPH\u00d3 T\u1ed4NG KI\u1ec2M TO\u00c1N|"
    r"\nCH\u1ee6 NHI\u1ec6M|\nPH\u00d3 CH\u1ee6 NHI\u1ec6M|\nCH\u00c1NH \u00c1N))"
)
_SEGMENT_ARTICLE_NUMBER_RE = re.compile(
    r"^\s*(?:\u0110i\u1ec1u|\u00d0i\u1ec1u)\s*(\d+[a-zA-Z]?)",
    re.IGNORECASE,
)


def regex_chunk_text(
    text: str,
    document_id: str,
    import_batch_id: str,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    article_segments = (
        _find_article_segments_with_segment_pattern(text)
        if True  # Toggle to False to compare with the legacy boundary splitter.
        else _find_article_segments_with_legacy_boundaries(text)
    )
    if not article_segments:
        article_segments = _find_article_segments_with_legacy_boundaries(text)

    if not article_segments:
        return [
            build_chunk_record(
                content=text.strip(),
                document_id=document_id,
                import_batch_id=import_batch_id,
                metadata=metadata,
                article_number="1",
                clause_number=None,
                chunk_level="article",
                ordinal=1,
            )
        ]

    chunks: list[dict[str, Any]] = []
    for article_number, article_text in article_segments:
        clause_chunks = split_article_clauses(article_text)
        if not clause_chunks:
            chunks.append(
                build_chunk_record(
                    content=article_text,
                    document_id=document_id,
                    import_batch_id=import_batch_id,
                    metadata=metadata,
                    article_number=article_number,
                    clause_number=None,
                    chunk_level="article",
                    ordinal=len(chunks) + 1,
                )
            )
            continue
        for clause_number, clause_text in clause_chunks:
            chunks.append(
                build_chunk_record(
                    content=clause_text,
                    document_id=document_id,
                    import_batch_id=import_batch_id,
                    metadata=metadata,
                    article_number=article_number,
                    clause_number=clause_number,
                    chunk_level="clause",
                    ordinal=len(chunks) + 1,
                )
            )
    return chunks


def _find_article_segments_with_segment_pattern(text: str) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    search_text = text if text.startswith("\n") else "\n" + text
    offset_adjust = 0 if search_text is text else -1
    for match in re.finditer(
        EXTRACT_SEGMENTS_SEGMENT_PATTERN_1,
        search_text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        raw_article_text = match.group(0)
        article_text_start = (
            match.start()
            + len(raw_article_text)
            - len(raw_article_text.lstrip())
            + offset_adjust
        )
        if _is_chunk_boundary_protected_at(text, article_text_start):
            continue
        article_text = raw_article_text.strip()
        number_match = _SEGMENT_ARTICLE_NUMBER_RE.match(article_text)
        if number_match:
            segments.append((number_match.group(1), article_text))
    return segments


def _find_article_segments_with_legacy_boundaries(text: str) -> list[tuple[str, str]]:
    article_matches = _find_article_boundaries(text)
    segments = []
    for article_index, (start, article_number) in enumerate(article_matches):
        end = (
            article_matches[article_index + 1][0]
            if article_index + 1 < len(article_matches)
            else len(text)
        )
        segments.append((article_number, text[start:end].strip()))
    return segments


def _is_chunk_boundary_protected_at(text: str, offset: int) -> bool:
    for line_start, line_end, _line_text, protected in _iter_chunk_boundary_lines(text):
        if line_start <= offset < line_end:
            return protected
    return False


def split_article_clauses(article_text: str) -> list[tuple[str, str]]:
    matches = _find_clause_boundaries(article_text)
    if len(matches) < 2:
        return []
    clauses = []
    for index, (start, clause_number) in enumerate(matches):
        end = matches[index + 1][0] if index + 1 < len(matches) else len(article_text)
        clauses.append((clause_number, article_text[start:end].strip()))
    return clauses


def _find_article_boundaries(text: str) -> list[tuple[int, str]]:
    matches = []
    for line_start, _line_end, line_text, protected in _iter_chunk_boundary_lines(text):
        if protected:
            continue
        match = _ARTICLE_HEADING_RE.match(line_text)
        if match:
            matches.append((line_start, match.group(1)))
    return matches


def _find_clause_boundaries(text: str) -> list[tuple[int, str]]:
    matches = []
    for line_start, _line_end, line_text, protected in _iter_chunk_boundary_lines(text):
        if protected:
            continue
        match = _CLAUSE_HEADING_RE.match(line_text)
        if match:
            matches.append((line_start, match.group(1)))
    return matches


def _iter_chunk_boundary_lines(text: str):
    offset = 0
    in_quote = False
    in_amendment_quote = False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        protected = (
            in_quote
            or in_amendment_quote
            or stripped.startswith(_QUOTE_START_CHARS)
        )
        line_start = offset
        offset += len(line)
        yield line_start, offset, line, protected

        begins_replacement_quote = bool(
            _AMENDMENT_QUOTE_INTRO_RE.search(line.strip())
        )
        quote_after_line = _update_quote_state(line, in_quote)
        closed_quote = _line_closes_quote(line, in_quote, quote_after_line)
        if begins_replacement_quote:
            in_amendment_quote = quote_after_line or not closed_quote
        elif in_amendment_quote and closed_quote and not quote_after_line:
            in_amendment_quote = False
        in_quote = quote_after_line


def _update_quote_state(line: str, in_quote: bool) -> bool:
    for char in line:
        if char == '"':
            in_quote = not in_quote
        elif char in _QUOTE_OPEN_CHARS:
            in_quote = True
        elif char in _QUOTE_CLOSE_CHARS:
            in_quote = False
    return in_quote


def _line_closes_quote(line: str, was_in_quote: bool, quote_after_line: bool) -> bool:
    return any(char in line for char in _QUOTE_CLOSE_CHARS) or (
        was_in_quote and '"' in line and not quote_after_line
    )


def build_chunk_record(
    content: str,
    document_id: str,
    import_batch_id: str,
    metadata: dict[str, Any],
    article_number: str,
    clause_number: str | None,
    chunk_level: str,
    ordinal: int,
) -> dict[str, Any]:
    chunk_id = make_chunk_id(document_id, article_number, clause_number, ordinal)
    citation_label = make_citation_label(
        metadata.get("document_number"),
        article_number,
        clause_number,
    )
    hierarchy_path = (
        f"Document/{metadata.get('document_number')}/Article/{article_number}"
        + (f"/Clause/{clause_number}" if clause_number else "")
    )
    content = format_clause_content(
        content=content,
        article_number=article_number,
        clause_number=clause_number,
        chunk_level=chunk_level,
    )
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "import_batch_id": import_batch_id,
        "document_number": metadata.get("document_number"),
        "document_title": metadata.get("document_title"),
        "document_type": metadata.get("document_type"),
        "source_system": "admin_upload",
        "source_url": metadata.get("source_url"),
        "content": content,
        "article_number": article_number,
        "article_title": None,
        "clause_number": clause_number,
        "citation_label": citation_label,
        "hierarchy_path": hierarchy_path,
        "chunk_level": chunk_level,
        "validity_status": metadata.get("validity_status", VALIDITY_UNKNOWN),
        "effective_date": metadata.get("effective_date"),
        "expiry_date": metadata.get("expiry_date"),
        "is_published": False,
        "published_version": metadata.get("published_version"),
        "ordinal": ordinal,
    }


def format_clause_content(
    content: str,
    article_number: str,
    clause_number: str | None,
    chunk_level: str,
) -> str:
    content = content.strip()
    if chunk_level != "clause" or not clause_number:
        return content

    prefix = f"Điều {article_number}.{clause_number}. "
    if content.startswith(prefix.rstrip()):
        return content
    already_contextualized_pattern = (
        rf"^\s*Điều\s+{re.escape(article_number)}\s*[,\.]\s*"
        rf"(?:khoản\s+)?{re.escape(clause_number)}\b"
    )
    if re.match(already_contextualized_pattern, content, re.IGNORECASE):
        return content
    if re.match(rf"^\s*{re.escape(clause_number)}\.\s+", content):
        return prefix + content.split(".", 1)[1].lstrip()
    return prefix + content


def make_chunk_id(
    document_id: str,
    article_number: str,
    clause_number: str | None,
    ordinal: int,
) -> str:
    raw = f"{document_id}:{article_number}:{clause_number or ''}:{ordinal}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


def make_citation_label(
    document_number: str | None,
    article_number: str,
    clause_number: str | None,
) -> str:
    label = f"{document_number or 'unknown'}, Điều {article_number}"
    if clause_number:
        label += f", khoản {clause_number}"
    return label


def validate_chunks(chunks: list[dict[str, Any]]) -> None:
    if not chunks:
        raise DocumentImportError(
            "CHUNK_VALIDATION_FAILED",
            "No valid chunks were produced from DOCX text.",
        )
    for index, chunk in enumerate(chunks, start=1):
        if not str(chunk.get("content", "")).strip():
            raise DocumentImportError(
                "CHUNK_VALIDATION_FAILED",
                f"Chunk #{index} has empty content.",
            )
        if not chunk.get("article_number"):
            raise DocumentImportError(
                "CHUNK_VALIDATION_FAILED",
                f"Chunk #{index} is missing article_number.",
            )
        if not chunk.get("hierarchy_path"):
            raise DocumentImportError(
                "CHUNK_VALIDATION_FAILED",
                f"Chunk #{index} is missing hierarchy_path.",
            )
        if chunk.get("chunk_level") == "clause" and not chunk.get("clause_number"):
            raise DocumentImportError(
                "CHUNK_VALIDATION_FAILED",
                f"Clause chunk #{index} is missing clause_number.",
            )


def load_chunk_preview(path: Path, limit: int) -> list[dict[str, Any]]:
    chunks = load_chunks(path)
    preview = []
    for chunk in chunks[:limit]:
        preview.append(
            {
                "chunk_id": chunk.get("chunk_id"),
                "citation_label": chunk.get("citation_label"),
                "chunk_level": chunk.get("chunk_level"),
                "content": str(chunk.get("content", ""))[:1000],
            }
        )
    return preview


def load_chunks(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        chunks = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return chunks if isinstance(chunks, list) else []


def count_chunks(path: Path) -> int:
    return len(load_chunks(path))






