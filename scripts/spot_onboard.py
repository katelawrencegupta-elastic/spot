#!/usr/bin/env python3
"""
Spot onboarding runner (CSV-focused).

This script centralizes onboarding runtime behavior and always resolves mappings
through common-schema/resolve_mapping.py so schema fallback behavior is not
duplicated.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Spot onboarding for CSV data.")
    parser.add_argument("--elastic-url", required=True, help="Elasticsearch URL")
    parser.add_argument("--elastic-api-key", required=True, help="Elasticsearch API key")
    parser.add_argument("--index-base", required=True, help="Base index name, e.g. allstate")
    parser.add_argument("--source-file", required=True, help="CSV source file path")
    parser.add_argument(
        "--schema-csv",
        help="Optional custom schema CSV; falls back to ECS default when omitted.",
    )
    parser.add_argument(
        "--dataset",
        default="spot.custom",
        help="event.dataset value to set in pipeline",
    )
    parser.add_argument(
        "--product",
        default="Spot Records",
        help="observer.product value to set in pipeline",
    )
    parser.add_argument(
        "--skip-header",
        action="store_true",
        help="Skip first line from source CSV during ingest.",
    )
    return parser.parse_args()


def request(
    elastic_url: str,
    api_key: str,
    method: str,
    path: str,
    body: object | None = None,
    ndjson: bool = False,
    timeout: int = 90,
) -> Tuple[int, dict]:
    url = f"{elastic_url.rstrip('/')}{path}"
    headers = {
        "Authorization": f"ApiKey {api_key}",
        "Content-Type": "application/x-ndjson" if ndjson else "application/json",
    }
    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = body
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {"error": raw}
        except Exception:
            payload = {"error": raw}
        return exc.code, payload


def next_index_name(elastic_url: str, api_key: str, index_base: str) -> str:
    pattern = f"spot-logs-{index_base}-"
    status, resp = request(
        elastic_url,
        api_key,
        "GET",
        f"/_cat/indices/{pattern}*?h=index&format=json",
    )
    if status not in (200, 404):
        raise SystemExit(f"Failed listing indices: status={status}, response={resp}")
    indices = [item.get("index", "") for item in resp] if status == 200 else []
    regex = re.compile(rf"^{re.escape(pattern)}(\d{{4}})$")
    max_n = 0
    for index in indices:
        match = regex.match(index)
        if match:
            max_n = max(max_n, int(match.group(1)))
    return f"{pattern}{max_n + 1:04d}"


def read_schema_fields(schema_csv: Path) -> List[str]:
    rows = list(csv.DictReader(schema_csv.open("r", encoding="utf-8", newline="")))
    fields = [row["Field"].strip() for row in rows if row.get("Field")]
    if not fields:
        raise SystemExit(f"No Field entries found in schema CSV: {schema_csv}")
    return fields


def resolve_properties(repo_root: Path, fields: List[str], schema_csv: str | None) -> Dict[str, dict]:
    fields_file = repo_root / ".spot-captured-fields.tmp.txt"
    fields_file.write_text("\n".join(fields) + "\n", encoding="utf-8")
    cmd = [
        "python3",
        "common-schema/resolve_mapping.py",
        "--fields-file",
        str(fields_file),
    ]
    if schema_csv:
        cmd.extend(["--schema", schema_csv])
    run = subprocess.run(
        cmd,
        cwd=str(repo_root),
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(run.stdout)
    fields_file.unlink(missing_ok=True)
    return payload.get("properties", {})


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    source_file = Path(args.source_file).resolve()
    schema_csv = Path(args.schema_csv).resolve() if args.schema_csv else None
    if not source_file.exists():
        raise SystemExit(f"Source file not found: {source_file}")
    if schema_csv and not schema_csv.exists():
        raise SystemExit(f"Schema CSV not found: {schema_csv}")

    index_name = next_index_name(args.elastic_url, args.elastic_api_key, args.index_base)
    pipeline_name = index_name
    print(f"generated_index={index_name}")

    selected_schema = schema_csv if schema_csv else (repo_root / "common-schema/fields.csv")
    fields = read_schema_fields(selected_schema)
    properties = resolve_properties(repo_root, fields, str(schema_csv) if schema_csv else None)
    properties["event.original"] = {"type": "match_only_text"}
    properties["event.dataset"] = {"type": "keyword"}
    properties["observer.vendor"] = {"type": "keyword"}
    properties["observer.product"] = {"type": "keyword"}
    mapping_payload = {"properties": properties}

    mapping_path = repo_root / f"{index_name}-mapping.json"
    mapping_path.write_text(json.dumps(mapping_payload, indent=2) + "\n", encoding="utf-8")
    print(f"written_file={mapping_path.name}")

    header_path = repo_root / f"{index_name}-spot_header.txt"
    header_path.write_text(",".join(fields) + "\n", encoding="utf-8")
    event_path = repo_root / f"{index_name}-spot_event.txt"
    event_path.write_text("csv_row_to_fields\n", encoding="utf-8")
    print(f"written_file={header_path.name}")
    print(f"written_file={event_path.name}")

    pipeline_payload = {
        "description": f"Spot onboarding pipeline for {args.index_base}",
        "processors": [
            {"set": {"field": "event.original", "copy_from": "message", "ignore_empty_value": True}},
            {
                "csv": {
                    "field": "message",
                    "target_fields": fields,
                    "separator": ",",
                    "trim": True,
                    "ignore_missing": True,
                    "ignore_failure": True,
                }
            },
            {"set": {"field": "event.dataset", "value": args.dataset}},
            {"set": {"field": "observer.vendor", "value": "Spot"}},
            {"set": {"field": "observer.product", "value": args.product}},
        ],
        "on_failure": [{"set": {"field": "error.message", "value": "{{ _ingest.on_failure_message }}"}}],
    }
    pipeline_path = repo_root / f"{index_name}-pipeline.json"
    pipeline_path.write_text(json.dumps(pipeline_payload, indent=2) + "\n", encoding="utf-8")
    print(f"written_file={pipeline_path.name}")

    status, create_resp = request(args.elastic_url, args.elastic_api_key, "PUT", f"/{index_name}", {})
    if status not in (200, 201):
        raise SystemExit(f"index_create_failed status={status} resp={create_resp}")
    print(f"index_create_ack={create_resp.get('acknowledged')}")

    status, map_resp = request(
        args.elastic_url, args.elastic_api_key, "PUT", f"/{index_name}/_mapping", mapping_payload
    )
    if status != 200:
        raise SystemExit(f"mapping_update_failed status={status} resp={map_resp}")
    print(f"mapping_update_ack={map_resp.get('acknowledged')}")

    status, pipe_resp = request(
        args.elastic_url, args.elastic_api_key, "PUT", f"/_ingest/pipeline/{pipeline_name}", pipeline_payload
    )
    if status != 200:
        raise SystemExit(f"pipeline_put_failed status={status} resp={pipe_resp}")
    print(f"pipeline_put_ack={pipe_resp.get('acknowledged')}")

    status, set_resp = request(
        args.elastic_url,
        args.elastic_api_key,
        "PUT",
        f"/{index_name}/_settings",
        {"index": {"default_pipeline": pipeline_name}},
    )
    if status != 200:
        raise SystemExit(f"default_pipeline_set_failed status={status} resp={set_resp}")
    print(f"default_pipeline_set_ack={set_resp.get('acknowledged')}")

    lines = source_file.read_text(encoding="utf-8", errors="replace").splitlines()
    if args.skip_header and lines:
        lines = lines[1:]
    expected_total = len(lines)
    print(f"count={expected_total}")

    bulk_path = repo_root / f"{index_name}-bulk.ndjson"
    with bulk_path.open("w", encoding="utf-8") as out:
        for line in lines:
            out.write(json.dumps({"index": {"_index": index_name}}) + "\n")
            out.write(json.dumps({"message": line}) + "\n")
    print(f"written_file={bulk_path.name}")

    status, count_resp = request(args.elastic_url, args.elastic_api_key, "GET", f"/{index_name}/_count")
    if status != 200:
        raise SystemExit(f"count_read_failed status={status} resp={count_resp}")
    resume_from = int(count_resp.get("count", 0))
    print(f"resume_from={resume_from}")
    remaining = lines[resume_from:]

    batch_sizes = [20, 10, 5, 1]
    batch_size = 20
    pos = 0
    last_print = resume_from
    while pos < len(remaining):
        chunk = remaining[pos : pos + batch_size]
        success = False
        for attempt in range(1, 6):
            payload = []
            for row in chunk:
                payload.append(json.dumps({"index": {"_index": index_name}}))
                payload.append(json.dumps({"message": row}))
            status, bulk_resp = request(
                args.elastic_url,
                args.elastic_api_key,
                "POST",
                "/_bulk",
                "\n".join(payload) + "\n",
                ndjson=True,
                timeout=120,
            )
            if status == 200 and not bulk_resp.get("errors", False):
                pos += len(chunk)
                total = resume_from + pos
                success = True
                if total - last_print >= 200 or total == expected_total:
                    print(f"ingested={total}")
                    last_print = total
                break
            retryable = status in (429, 502, 503, 504) or (status == 200 and bulk_resp.get("errors", False))
            if retryable and attempt < 5:
                time.sleep(2 ** (attempt - 1))
                continue
            break

        if success:
            continue

        idx = batch_sizes.index(batch_size)
        if idx < len(batch_sizes) - 1:
            batch_size = batch_sizes[idx + 1]
            print(f"batch_reduce={batch_size} start={resume_from + pos}")
            continue
        print(f"failed_batch_start={resume_from + pos}")
        raise SystemExit("Bulk ingest failed after retries and minimum batch size")

    status, _ = request(args.elastic_url, args.elastic_api_key, "POST", f"/{index_name}/_refresh")
    if status != 200:
        raise SystemExit(f"refresh_failed status={status}")
    status, final_resp = request(args.elastic_url, args.elastic_api_key, "GET", f"/{index_name}/_count")
    if status != 200:
        raise SystemExit(f"final_count_failed status={status} resp={final_resp}")

    print("bulk_errors=false")
    print("bulk_failed=0")
    print(f"bulk_items={len(remaining)}")
    print(f"final_count={final_resp.get('count')}")
    print(f"index_name={index_name}")
    print(f"pipeline_name={pipeline_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
