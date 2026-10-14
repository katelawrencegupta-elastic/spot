#!/usr/bin/env python3
"""
Spot onboarding runner for JSON lines (one JSON object per line).

Wraps each line in a message field, parses via ingest pipeline, maps to ECS,
and bulk ingests with chunked retries.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Dict, List

from spot_elastic_common import (
    WriteTarget,
    add_target_arguments,
    ensure_write_target,
    put_pipeline,
    request,
    resolve_write_target,
    set_default_pipeline,
)


ECS_FIELDS = [
    "@timestamp",
    "event.action",
    "event.category",
    "event.dataset",
    "event.id",
    "event.original",
    "event.outcome",
    "source.ip",
    "source.geo.city_name",
    "source.geo.region_name",
    "source.geo.country_iso_code",
    "source.geo.location",
    "user.email",
    "user.id",
    "organization.id",
    "observer.vendor",
    "observer.product",
    "o365.audit",
    "o365.workload",
    "error.message",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Spot onboarding for JSONL logs.")
    parser.add_argument("--elastic-url", required=True)
    parser.add_argument("--elastic-api-key", required=True)
    parser.add_argument("--index-base", required=True, help="Base index name, e.g. o365")
    parser.add_argument("--source-file", required=True, help="JSONL source file path")
    parser.add_argument("--schema-csv", help="Optional custom schema CSV path")
    parser.add_argument("--dataset", default="o365.audit")
    parser.add_argument("--product", default="Office 365 Audit")
    parser.add_argument("--vendor", default="Microsoft")
    parser.add_argument(
        "--initial-batch-size",
        type=int,
        default=100,
        help="Starting bulk batch size (default: 100)",
    )
    add_target_arguments(parser)
    return parser.parse_args()


def resolve_properties(repo_root: Path, fields: List[str], schema_csv: str | None) -> Dict[str, dict]:
    fields_file = repo_root / ".spot-captured-fields.tmp.txt"
    fields_file.write_text("\n".join(fields) + "\n", encoding="utf-8")
    cmd = [
        "python3",
        "common-schema/resolve_mapping.py",
        "--fields-file",
        str(fields_file),
        "--include-missing",
    ]
    if schema_csv:
        cmd.extend(["--schema", schema_csv])
    run = subprocess.run(cmd, cwd=str(repo_root), check=True, capture_output=True, text=True)
    payload = json.loads(run.stdout)
    fields_file.unlink(missing_ok=True)
    return payload.get("properties", {})


def o365_pipeline(dataset: str, vendor: str, product: str) -> dict:
    return {
        "description": "Spot O365 unified audit JSONL onboarding",
        "processors": [
            {"set": {"field": "event.original", "copy_from": "message", "ignore_empty_value": True}},
            {
                "json": {
                    "field": "message",
                    "target_field": "o365.audit",
                    "add_to_root": False,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "@timestamp",
                    "copy_from": "o365.audit.CreationTime",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "date": {
                    "field": "@timestamp",
                    "formats": [
                        "ISO8601",
                        "yyyy-MM-dd'T'HH:mm:ss.SSSSSSS'Z'",
                        "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'",
                        "yyyy-MM-dd'T'HH:mm:ss'Z'",
                    ],
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "source.ip",
                    "copy_from": "o365.audit.ClientIP",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "user.email",
                    "copy_from": "o365.audit.UserId",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "user.id",
                    "copy_from": "o365.audit.UserKey",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "event.action",
                    "copy_from": "o365.audit.Operation",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "event.id",
                    "copy_from": "o365.audit.Id",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "organization.id",
                    "copy_from": "o365.audit.OrganizationId",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "o365.workload",
                    "copy_from": "o365.audit.Workload",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "source.geo.city_name",
                    "copy_from": "o365.audit.GeoLocation.city",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "source.geo.region_name",
                    "copy_from": "o365.audit.GeoLocation.state",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "source.geo.country_iso_code",
                    "copy_from": "o365.audit.GeoLocation.countryOrRegion",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "script": {
                    "lang": "painless",
                    "source": """
                        def geo = ctx?.o365?.audit?.GeoLocation;
                        if (geo != null && geo.latitude != null && geo.longitude != null) {
                            Map loc = new HashMap();
                            loc.put('lat', geo.latitude);
                            loc.put('lon', geo.longitude);
                            ctx.source = ctx.source != null ? ctx.source : new HashMap();
                            ctx.source.geo = ctx.source.geo != null ? ctx.source.geo : new HashMap();
                            ctx.source.geo.location = loc;
                        }
                    """,
                    "ignore_failure": True,
                }
            },
            {
                "script": {
                    "lang": "painless",
                    "source": """
                        def status = ctx?.o365?.audit?.ResultStatus;
                        if (status != null) {
                            String s = status.toString().toLowerCase();
                            if (s.equals('success')) {
                                ctx.event = ctx.event != null ? ctx.event : new HashMap();
                                ctx.event.outcome = 'success';
                            } else if (s.contains('fail')) {
                                ctx.event = ctx.event != null ? ctx.event : new HashMap();
                                ctx.event.outcome = 'failure';
                            } else {
                                ctx.event = ctx.event != null ? ctx.event : new HashMap();
                                ctx.event.outcome = 'unknown';
                            }
                        }
                        def op = ctx?.o365?.audit?.Operation;
                        if (op != null) {
                            String o = op.toString();
                            if (o.equals('UserLoggedIn') || o.equals('UserLoginFailed')) {
                                ctx.event = ctx.event != null ? ctx.event : new HashMap();
                                ctx.event.category = 'authentication';
                            }
                        }
                    """,
                    "ignore_failure": True,
                }
            },
            {"set": {"field": "event.dataset", "value": dataset}},
            {"set": {"field": "observer.vendor", "value": vendor}},
            {"set": {"field": "observer.product", "value": product}},
            {"remove": {"field": "message", "ignore_missing": True}},
        ],
        "on_failure": [{"set": {"field": "error.message", "value": "{{ _ingest.on_failure_message }}"}}],
    }


def bulk_ingest_lines(
    elastic_url: str,
    api_key: str,
    target: WriteTarget,
    lines: List[str],
    resume_from: int,
    initial_batch_size: int,
) -> int:
    remaining = lines[resume_from:]
    batch_sizes = [initial_batch_size, 50, 20, 10, 5, 1]
    batch_size = batch_sizes[0]
    pos = 0
    last_print = resume_from
    failed_items = 0
    bulk_meta = target.bulk_action_line()

    while pos < len(remaining):
        chunk = remaining[pos : pos + batch_size]
        success = False
        bulk_resp: dict = {}
        for attempt in range(1, 6):
            payload_lines = []
            for row in chunk:
                payload_lines.append(json.dumps(bulk_meta))
                payload_lines.append(json.dumps({"message": row.rstrip("\n")}))
            status, bulk_resp = request(
                elastic_url,
                api_key,
                "POST",
                "/_bulk",
                "\n".join(payload_lines) + "\n",
                ndjson=True,
                timeout=180,
            )
            if status == 200 and not bulk_resp.get("errors", False):
                pos += len(chunk)
                total = resume_from + pos
                success = True
                if total - last_print >= 500 or total == len(lines):
                    print(f"ingested={total}")
                    last_print = total
                break
            if status == 200 and bulk_resp.get("errors", False):
                failed_items += sum(
                    1 for item in bulk_resp.get("items", []) if item.get("index", {}).get("error")
                )
            retryable = status in (429, 502, 503, 504) or (status == 200 and bulk_resp.get("errors", False))
            if retryable and attempt < 5:
                time.sleep(2 ** (attempt - 1))
                continue
            break

        if success:
            continue

        try:
            idx = batch_sizes.index(batch_size)
        except ValueError:
            idx = len(batch_sizes) - 1
        if idx < len(batch_sizes) - 1:
            batch_size = batch_sizes[idx + 1]
            print(f"batch_reduce={batch_size} start={resume_from + pos}")
            continue
        print(f"failed_batch_start={resume_from + pos}")
        print(f"bulk_resp={json.dumps(bulk_resp)[:2000]}")
        raise SystemExit("Bulk ingest failed after retries and minimum batch size")

    return failed_items


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    source_file = Path(args.source_file).resolve()
    if not source_file.exists():
        raise SystemExit(f"Source file not found: {source_file}")

    target = resolve_write_target(
        args.elastic_url,
        args.elastic_api_key,
        args.index_base,
        args.data_stream,
        args.pipeline,
        args.apply_mapping,
        args.skip_pipeline,
    )
    print(f"write_target={target.name}")
    print(f"write_target_kind={target.kind}")
    print(f"pipeline_name={target.pipeline_name}")

    properties = resolve_properties(
        repo_root, ECS_FIELDS, str(Path(args.schema_csv).resolve()) if args.schema_csv else None
    )
    properties["o365.audit"] = {
        "type": "object",
        "enabled": True,
        "dynamic": True,
    }
    mapping_payload = {"properties": properties}

    prefix = target.artifact_prefix
    mapping_path = repo_root / f"{prefix}-mapping.json"
    mapping_path.write_text(json.dumps(mapping_payload, indent=2) + "\n", encoding="utf-8")
    print(f"written_file={mapping_path.name}")

    header_path = repo_root / f"{prefix}-spot_header.txt"
    header_path.write_text("json_per_line\n", encoding="utf-8")
    event_path = repo_root / f"{prefix}-spot_event.txt"
    event_path.write_text('json_parse_message\n%{GREEDYDATA:message_body}\n', encoding="utf-8")
    print(f"written_file={header_path.name}")
    print(f"written_file={event_path.name}")

    pipeline_payload = o365_pipeline(args.dataset, args.vendor, args.product)
    pipeline_path = repo_root / f"{prefix}-pipeline.json"
    pipeline_path.write_text(json.dumps(pipeline_payload, indent=2) + "\n", encoding="utf-8")
    print(f"written_file={pipeline_path.name}")

    ensure_write_target(args.elastic_url, args.elastic_api_key, target, mapping_payload)
    if not args.skip_pipeline:
        put_pipeline(args.elastic_url, args.elastic_api_key, target, pipeline_payload)
    set_default_pipeline(args.elastic_url, args.elastic_api_key, target)

    with source_file.open("r", encoding="utf-8", errors="replace") as handle:
        lines = [line for line in handle if line.strip()]
    expected_total = len(lines)
    print(f"count={expected_total}")

    status, count_resp = request(args.elastic_url, args.elastic_api_key, "GET", f"/{target.name}/_count")
    if status != 200:
        raise SystemExit(f"count_read_failed status={status} resp={count_resp}")
    resume_from = int(count_resp.get("count", 0))
    print(f"resume_from={resume_from}")

    failed_items = bulk_ingest_lines(
        args.elastic_url,
        args.elastic_api_key,
        target,
        lines,
        resume_from,
        args.initial_batch_size,
    )

    status, _ = request(args.elastic_url, args.elastic_api_key, "POST", f"/{target.name}/_refresh")
    if status != 200:
        raise SystemExit(f"refresh_failed status={status}")

    status, final_resp = request(args.elastic_url, args.elastic_api_key, "GET", f"/{target.name}/_count")
    if status != 200:
        raise SystemExit(f"final_count_failed status={status} resp={final_resp}")

    final_count = int(final_resp.get("count", 0))
    print(f"bulk_errors={failed_items > 0}")
    print(f"bulk_failed={failed_items}")
    print(f"bulk_items={expected_total - resume_from}")
    print(f"final_count={final_count}")
    print(f"write_target={target.name}")
    print(f"write_target_kind={target.kind}")
    print(f"pipeline_name={target.pipeline_name}")
    if final_count != expected_total:
        print(f"warning=expected_{expected_total}_got_{final_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
