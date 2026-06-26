import re
import json
from pathlib import Path

input_path = Path(r"D:\legal-chatbot-ai\data\document_segment.json")
output_path = Path(r"D:\legal-chatbot-ai\data\document_segment_fixed.json")

text = input_path.read_text(encoding="utf-8")

# Chuyển ObjectId("...") thành Extended JSON: {"$oid": "..."}
text = re.sub(
    r'ObjectId\("([0-9a-fA-F]{24})"\)',
    r'{"$oid": "\1"}',
    text
)

docs = []
depth = 0
start = None
in_string = False
escape = False

for i, ch in enumerate(text):
    if in_string:
        if escape:
            escape = False
        elif ch == "\\":
            escape = True
        elif ch == '"':
            in_string = False
    else:
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                raw_doc = text[start:i + 1]
                docs.append(json.loads(raw_doc))
                start = None

print(f"Found {len(docs)} documents")

output_path.write_text(
    json.dumps(docs, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(f"Saved fixed JSON to: {output_path}")