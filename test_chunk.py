import re
from backend.services.document_import_service import regex_chunk_text,_find_article_segments_with_legacy_boundaries,_find_article_segments_with_segment_pattern,_iter_chunk_boundary_lines,_find_article_boundaries
# Read data in a file
data = '' 
with open("data\preprocessed\9faa951c-17b9-46a8-8865-8a61d5031c86\8b77aa6f-bb6d-4918-ab00-d453a344e0b5.txt","r", encoding = "utf-8") as file:
    data = file.read()
# print(data)
_ARTICLE_HEADING_RE = re.compile(
    r"^\s*(?:\u0110i\u1ec1u|Dieu)\s+([0-9]+[a-zA-Z]?)\.?\s*(.*)$",
    re.IGNORECASE,
)
foo = []

for line_start, _line_end, line_text, protected in _iter_chunk_boundary_lines(data):
    print(line_start, _line_end, line_text, protected)
    if protected:
        continue
    match = _ARTICLE_HEADING_RE.match(line_text)
    if match:
        foo.append((line_start, match.group(1)))


for bar in foo:
    print(bar)
print(len(foo))
