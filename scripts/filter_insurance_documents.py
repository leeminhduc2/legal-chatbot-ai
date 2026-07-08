from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable


OBJECT_ID_PATTERN = re.compile(r'ObjectId\("([^"]+)"\)')
INSURANCE_KEYWORD = "bao hiem"
PROPERTY_SECTOR_KEYS = {
    "linh vuc/nganh",
    "linh vuc",
    "nganh",
    "linh_vuc",
    "linh_vuc_con",
    "sector",
    "domain",
    "industry_sector",
    "industry_sector_name",
}
TOP_LEVEL_SECTOR_FIELDS = {
    "sector",
    "domain",
    "industry_sector",
    "industry_sectors",
    "industry_sector_name",
    "industry_sector_names",
    "linh_vuc",
    "linh_vuc_con",
    "nganh",
}


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    without_marks = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return without_marks.replace("\u0111", "d").replace("\u0110", "D").lower()


def value_contains_insurance(value: Any) -> bool:
    if isinstance(value, str):
        return INSURANCE_KEYWORD in normalize_text(value)
    if isinstance(value, list):
        return any(value_contains_insurance(item) for item in value)
    if isinstance(value, dict):
        return any(value_contains_insurance(item) for item in value.values())
    return False


def is_sector_key(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return normalize_text(value).strip() in PROPERTY_SECTOR_KEYS


def has_insurance_sector(record: dict[str, Any]) -> bool:
    properties = record.get("properties")
    if isinstance(properties, list):
        for item in properties:
            if not isinstance(item, dict):
                continue
            if is_sector_key(item.get("key")) and value_contains_insurance(
                item.get("value")
            ):
                return True

    for field_name in TOP_LEVEL_SECTOR_FIELDS:
        if value_contains_insurance(record.get(field_name)):
            return True

    return False


def replace_mongo_literals(raw_object: str) -> str:
    return OBJECT_ID_PATTERN.sub(lambda match: json.dumps(match.group(1)), raw_object)


def iter_mongo_objects(input_path: Path, chunk_size: int) -> Iterable[str]:
    buffer: list[str] = []
    depth = 0
    in_string = False
    escaped = False
    started = False

    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break

            for char in chunk:
                if not started:
                    if char.isspace():
                        continue
                    if char != "{":
                        raise ValueError(
                            f"Unexpected character before object start: {char!r}"
                        )
                    started = True
                    depth = 1
                    in_string = False
                    escaped = False
                    buffer = [char]
                    continue

                buffer.append(char)

                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue

                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        yield "".join(buffer)
                        buffer = []
                        started = False

    if started:
        raise ValueError("Input ended before the current object was closed.")


def filter_documents(input_path: Path, output_path: Path, chunk_size: int) -> int:
    total_count = 0
    kept_count = 0
    parse_errors = 0
    parse_error_log_limit = 20

    with output_path.open("w", encoding="utf-8", newline="\n") as output_file:
        output_file.write("[")
        first_record = True

        for raw_object in iter_mongo_objects(input_path, chunk_size):
            total_count += 1
            try:
                record = json.loads(replace_mongo_literals(raw_object))
            except json.JSONDecodeError as exc:
                parse_errors += 1
                if parse_errors <= parse_error_log_limit:
                    print(
                        f"Skipping object #{total_count}: JSON parse error at "
                        f"line {exc.lineno}, column {exc.colno}: {exc.msg}",
                        file=sys.stderr,
                    )
                continue

            if not isinstance(record, dict) or not has_insurance_sector(record):
                continue

            if not first_record:
                output_file.write(",")
            output_file.write("\n")
            json.dump(record, output_file, ensure_ascii=False, separators=(",", ":"))
            first_record = False
            kept_count += 1

        if not first_record:
            output_file.write("\n")
        output_file.write("]\n")

    print(f"Total objects read: {total_count}")
    print(f"Objects kept: {kept_count}")
    print(f"Parse errors: {parse_errors}")
    print(f"Output: {output_path}")

    return 0 if parse_errors == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Filter Mongo-style legal document metadata to insurance-sector "
            "documents and write valid JSON."
        )
    )
    parser.add_argument(
        "--input",
        default="document_segment.json",
        type=Path,
        help="Path to the large Mongo-style source file.",
    )
    parser.add_argument(
        "--output",
        default="document_filtered.json",
        type=Path,
        help="Path for the filtered JSON array output.",
    )
    parser.add_argument(
        "--chunk-size",
        default=1024 * 1024,
        type=int,
        help="Read buffer size in characters.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return filter_documents(
        input_path=args.input,
        output_path=args.output,
        chunk_size=args.chunk_size,
    )


if __name__ == "__main__":
    raise SystemExit(main())
