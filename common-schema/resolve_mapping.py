#!/usr/bin/env python3
"""
Resolve Elasticsearch mapping properties from common-schema/fields.csv.

Examples:
  python3 common-schema/resolve_mapping.py --fields source.ip,host.name,@timestamp
  python3 common-schema/resolve_mapping.py --fields-file extracted_fields.txt
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List


ECS_TO_ES_TYPE = {
    "date": "date",
    "keyword": "keyword",
    "match_only_text": "match_only_text",
    "text": "text",
    "object": "object",
    "flattened": "flattened",
    "ip": "ip",
    "geo_point": "geo_point",
    "geo_shape": "geo_shape",
    "boolean": "boolean",
    "long": "long",
    "integer": "integer",
    "short": "short",
    "byte": "byte",
    "double": "double",
    "float": "float",
    "half_float": "half_float",
    "scaled_float": "scaled_float",
    "unsigned_long": "unsigned_long",
    "wildcard": "wildcard",
    "constant_keyword": "constant_keyword",
    "version": "version",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve Elasticsearch mapping properties from fields.csv."
    )
    parser.add_argument(
        "--csv",
        default="common-schema/fields.csv",
        help="Path to schema CSV (default: common-schema/fields.csv)",
    )
    parser.add_argument(
        "--fields",
        help="Comma-separated field names to resolve (e.g. source.ip,host.name).",
    )
    parser.add_argument(
        "--fields-file",
        help="Path to a file with one field per line.",
    )
    parser.add_argument(
        "--include-missing",
        action="store_true",
        help="Include unresolved fields as keyword in output mappings.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    return parser.parse_args()


def load_schema(csv_path: Path) -> Dict[str, str]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Schema CSV not found: {csv_path}")

    resolved: Dict[str, str] = {}
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            field = (row.get("Field") or "").strip()
            ecs_type = (row.get("Type") or "").strip()
            if not field or not ecs_type:
                continue
            resolved[field] = ECS_TO_ES_TYPE.get(ecs_type, ecs_type)
    return resolved


def parse_input_fields(args: argparse.Namespace) -> List[str]:
    fields: List[str] = []
    if args.fields:
        fields.extend([item.strip() for item in args.fields.split(",") if item.strip()])
    if args.fields_file:
        with Path(args.fields_file).open("r", encoding="utf-8") as handle:
            fields.extend([line.strip() for line in handle if line.strip()])
    deduped: List[str] = []
    seen = set()
    for field in fields:
        if field not in seen:
            deduped.append(field)
            seen.add(field)
    return deduped


def build_properties(
    wanted_fields: Iterable[str],
    schema: Dict[str, str],
    include_missing: bool,
) -> Dict[str, Dict[str, str]]:
    properties: Dict[str, Dict[str, str]] = {}
    for field in wanted_fields:
        field_type = schema.get(field)
        if field_type:
            properties[field] = {"type": field_type}
        elif include_missing:
            properties[field] = {"type": "keyword"}
    return properties


def main() -> int:
    args = parse_args()
    csv_path = Path(args.csv)
    schema = load_schema(csv_path)
    fields = parse_input_fields(args)
    if not fields:
        raise SystemExit("No fields provided. Use --fields or --fields-file.")

    properties = build_properties(fields, schema, args.include_missing)
    unresolved = [field for field in fields if field not in schema]

    output = {
        "csv": str(csv_path),
        "requested_fields": len(fields),
        "resolved_fields": len(properties),
        "unresolved_fields": unresolved,
        "properties": properties,
    }

    if args.pretty:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(json.dumps(output, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
