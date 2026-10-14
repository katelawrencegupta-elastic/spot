#!/usr/bin/env python3
"""Spot onboarding for NetFlow v9 JSONL (one flow record per line)."""

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
    "event.category",
    "event.dataset",
    "event.original",
    "source.ip",
    "source.port",
    "source.as.number",
    "destination.ip",
    "destination.port",
    "destination.as.number",
    "network.transport",
    "network.protocol",
    "network.type",
    "network.direction",
    "network.bytes",
    "network.packets",
    "observer.hostname",
    "observer.ip",
    "observer.product",
    "observer.vendor",
    "netflow",
    "error.message",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Spot onboarding for NetFlow JSONL.")
    parser.add_argument("--elastic-url", required=True)
    parser.add_argument("--elastic-api-key", required=True)
    parser.add_argument("--index-base", default="netflow", help="Base index name")
    parser.add_argument("--source-file", required=True, help="NetFlow JSONL path")
    parser.add_argument("--schema-csv", help="Optional custom schema CSV")
    parser.add_argument("--dataset", default="netflow.v9")
    parser.add_argument("--product", default="NetFlow v9")
    parser.add_argument("--vendor", default="Spot")
    parser.add_argument("--initial-batch-size", type=int, default=100)
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


def netflow_pipeline(dataset: str, vendor: str, product: str) -> dict:
    return {
        "description": "Spot NetFlow v9 JSONL onboarding",
        "processors": [
            {"set": {"field": "event.original", "copy_from": "message", "ignore_empty_value": True}},
            {
                "json": {
                    "field": "message",
                    "target_field": "netflow",
                    "add_to_root": False,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "@timestamp",
                    "copy_from": "netflow.flow.flowEndMilliseconds",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "date": {
                    "field": "@timestamp",
                    "formats": [
                        "ISO8601",
                        "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'",
                        "yyyy-MM-dd'T'HH:mm:ss'Z'",
                    ],
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "source.ip",
                    "copy_from": "netflow.flow.sourceIPv4Address",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "destination.ip",
                    "copy_from": "netflow.flow.destinationIPv4Address",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "source.port",
                    "copy_from": "netflow.flow.sourceTransportPort",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "destination.port",
                    "copy_from": "netflow.flow.destinationTransportPort",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "network.bytes",
                    "copy_from": "netflow.flow.octetDeltaCount",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "network.packets",
                    "copy_from": "netflow.flow.packetDeltaCount",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "network.transport",
                    "copy_from": "netflow.flow.network.transport",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "network.protocol",
                    "copy_from": "netflow.flow.applicationName",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "network.type",
                    "value": "ipv4",
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "network.direction",
                    "copy_from": "netflow.flow.direction",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "source.as.number",
                    "copy_from": "netflow.flow.sourceAS",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "destination.as.number",
                    "copy_from": "netflow.flow.destinationAS",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "observer.hostname",
                    "copy_from": "netflow.export.host",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {
                "set": {
                    "field": "observer.ip",
                    "copy_from": "netflow.export.ip",
                    "ignore_empty_value": True,
                    "ignore_failure": True,
                }
            },
            {"set": {"field": "event.category", "value": "network"}},
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
    failed = 0
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
                if total - last_print >= 500 or total == resume_from + len(remaining):
                    print(f"ingested={total}")
                    last_print = total
                break
            if status == 200 and bulk_resp.get("errors", False):
                failed += sum(
                    1 for item in bulk_resp.get("items", []) if item.get(target.bulk_action(), {}).get("error")
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

    return failed


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
    properties["netflow"] = {"type": "object", "enabled": True, "dynamic": True}
    mapping_payload = {"properties": properties}

    prefix = target.artifact_prefix
    for name, content in [
        (f"{prefix}-mapping.json", json.dumps(mapping_payload, indent=2) + "\n"),
        (f"{prefix}-spot_header.txt", "netflow_v9_jsonl\n"),
        (f"{prefix}-spot_event.txt", "netflow_json_parse\n%{GREEDYDATA:message_body}\n"),
    ]:
        path = repo_root / name
        path.write_text(content, encoding="utf-8")
        print(f"written_file={path.name}")

    pipeline_payload = netflow_pipeline(args.dataset, args.vendor, args.product)
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

    failed = bulk_ingest_lines(
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
    print(f"bulk_errors={failed > 0}")
    print(f"bulk_failed={failed}")
    print(f"bulk_items={expected_total - resume_from}")
    print(f"final_count={final_count}")
    print(f"write_target={target.name}")
    print(f"pipeline_name={target.pipeline_name}")
    if final_count != expected_total:
        print(f"warning=expected_{expected_total}_got_{final_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
