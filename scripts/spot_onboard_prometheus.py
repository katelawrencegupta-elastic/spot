#!/usr/bin/env python3
"""
Spot onboarding runner for Prometheus text exposition format (.prom).

Parses metric samples into time-series documents (@timestamp, labels, metrics)
and bulk ingests into a pre-created metrics data stream.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional

from spot_elastic_common import (
    WriteTarget,
    add_target_arguments,
    ensure_write_target,
    request,
    resolve_write_target,
)

METRIC_RE = re.compile(
    r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+(\S+)(?:\s+(\d+))?$"
)
LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"\\])*)"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load Prometheus .prom samples into Elasticsearch.")
    parser.add_argument("--elastic-url", required=True)
    parser.add_argument("--elastic-api-key", required=True)
    parser.add_argument("--index-base", default="prometheus", help="Artifact/pipeline name base")
    parser.add_argument("--source-file", required=True, help="Prometheus exposition file (.prom)")
    parser.add_argument("--dataset", default="spot.prometheus.k8s")
    parser.add_argument(
        "--initial-batch-size",
        type=int,
        default=100,
        help="Starting bulk batch size (default: 100)",
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=0,
        help="Stop after N metric samples (0 = all)",
    )
    add_target_arguments(parser)
    return parser.parse_args()


def iter_metric_lines(path: Path) -> Iterator[str]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                yield stripped


def get_writable_range_ms(elastic_url: str, api_key: str, data_stream: str) -> tuple[int, int]:
    """Return (start_ms, end_ms) for the data stream's current writable time-series index."""
    status, resp = request(elastic_url, api_key, "GET", f"/{data_stream}/_settings")
    if status != 200:
        raise SystemExit(f"settings_read_failed status={status} resp={resp}")
    for _index, body in resp.items():
        ts = body.get("settings", {}).get("index", {}).get("time_series", {})
        start = ts.get("start_time")
        end = ts.get("end_time")
        if start and end:
            start_ms = int(datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp() * 1000)
            end_ms = int(datetime.fromisoformat(end.replace("Z", "+00:00")).timestamp() * 1000)
            # Leave margin so mapped samples are strictly inside the writable window.
            margin_ms = 1000
            return start_ms + margin_ms, end_ms - margin_ms
    raise SystemExit("writable_time_series_range_not_found")


def timestamp_for_doc_index(doc_index: int, total_docs: int, dst_min_ms: int, dst_max_ms: int) -> str:
    """Spread samples across the writable window so time-series _id values stay unique."""
    if total_docs <= 1:
        mapped_ms = dst_min_ms
    else:
        ratio = doc_index / (total_docs - 1)
        mapped_ms = int(dst_min_ms + ratio * (dst_max_ms - dst_min_ms))
    ts = datetime.fromtimestamp(mapped_ms / 1000, tz=timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_sample(
    line: str,
    *,
    doc_index: int,
    total_docs: int,
    dst_min_ms: int,
    dst_max_ms: int,
) -> Optional[dict]:
    match = METRIC_RE.match(line)
    if not match:
        return None
    name, labels_raw, value_raw, _ts_raw = match.groups()
    try:
        value = float(value_raw)
    except ValueError:
        return None
    labels = {key: val for key, val in LABEL_RE.findall(labels_raw or "")}
    timestamp = timestamp_for_doc_index(doc_index, total_docs, dst_min_ms, dst_max_ms)
    return {
        "@timestamp": timestamp,
        "labels": labels,
        "metrics": {name: value},
    }


def count_metric_lines(path: Path) -> int:
    return sum(1 for _ in iter_metric_lines(path))


def skip_metric_lines(path: Path, n: int) -> Iterator[str]:
    skipped = 0
    for line in iter_metric_lines(path):
        if skipped < n:
            skipped += 1
            continue
        yield line


def bulk_ingest_stream(
    elastic_url: str,
    api_key: str,
    target: WriteTarget,
    source_file: Path,
    resume_from: int,
    initial_batch_size: int,
    max_docs: int,
    total_docs: int,
    dst_min_ms: int,
    dst_max_ms: int,
) -> tuple[int, int]:
    batch_sizes = [initial_batch_size, 50, 20, 10, 5, 1]
    batch_size = batch_sizes[0]
    bulk_meta = target.bulk_action_line()
    lines_sent = 0
    failed = 0
    last_print = resume_from
    pending: List[str] = []

    def send_chunk(lines: List[str]) -> bool:
        nonlocal failed
        docs = []
        for doc_index, line in lines:
            doc = parse_sample(
                line,
                doc_index=doc_index,
                total_docs=total_docs,
                dst_min_ms=dst_min_ms,
                dst_max_ms=dst_max_ms,
            )
            if doc is None:
                failed += 1
                continue
            docs.append(doc)
        if not docs:
            return True

        for attempt in range(1, 6):
            payload = []
            for doc in docs:
                payload.append(json.dumps(bulk_meta))
                payload.append(json.dumps(doc))
            status, bulk_resp = request(
                elastic_url,
                api_key,
                "POST",
                "/_bulk",
                "\n".join(payload) + "\n",
                ndjson=True,
                timeout=300,
            )
            if status == 200 and not bulk_resp.get("errors", False):
                return True
            retryable = status in (429, 502, 503, 504) or (status == 200 and bulk_resp.get("errors", False))
            if retryable and attempt < 5:
                time.sleep(2 ** (attempt - 1))
                continue
            if status == 200 and bulk_resp.get("errors", False):
                failed += sum(
                    1
                    for item in bulk_resp.get("items", [])
                    if item.get(target.bulk_action(), {}).get("error")
                )
            print(f"bulk_error_sample={json.dumps(bulk_resp)[:1500]}")
            return False
        return False

    for line in skip_metric_lines(source_file, resume_from):
        doc_index = resume_from + lines_sent + len(pending)
        pending.append((doc_index, line))
        if max_docs and lines_sent + len(pending) >= max_docs:
            pending = pending[: max_docs - lines_sent]
        while len(pending) >= batch_size:
            chunk = pending[:batch_size]
            pending = pending[batch_size:]
            if not send_chunk(chunk):
                try:
                    idx = batch_sizes.index(batch_size)
                except ValueError:
                    idx = len(batch_sizes) - 1
                if idx < len(batch_sizes) - 1:
                    batch_size = batch_sizes[idx + 1]
                    pending = chunk + pending
                    print(f"batch_reduce={batch_size}")
                    continue
                raise SystemExit(f"Bulk ingest failed at offset={resume_from + lines_sent}")
            lines_sent += len(chunk)
            total = resume_from + lines_sent
            if total - last_print >= 5000 or (max_docs and total >= max_docs):
                print(f"ingested={total}")
                last_print = total
        if max_docs and lines_sent >= max_docs:
            break

    if pending and (not max_docs or lines_sent < max_docs):
        if max_docs:
            pending = pending[: max_docs - lines_sent]
        if pending and not send_chunk(pending):
            raise SystemExit(f"Bulk ingest failed at final chunk offset={resume_from + lines_sent}")
        lines_sent += len(pending)
        print(f"ingested={resume_from + lines_sent}")

    return lines_sent, failed


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    source_file = Path(args.source_file).resolve()
    if not source_file.exists():
        raise SystemExit(f"Source file not found: {source_file}")
    if not args.data_stream:
        raise SystemExit("--data-stream is required for Prometheus onboarding")

    target = resolve_write_target(
        args.elastic_url,
        args.elastic_api_key,
        args.index_base,
        args.data_stream,
        args.pipeline,
        args.apply_mapping,
        True,  # skip pipeline — metrics data stream uses passthrough mapping
    )
    print(f"write_target={target.name}")
    print(f"write_target_kind={target.kind}")

    mapping_payload = {
        "properties": {
            "@timestamp": {"type": "date"},
            "labels": {"type": "object", "dynamic": True},
            "metrics": {"type": "object", "dynamic": True},
        }
    }
    prefix = target.artifact_prefix.replace(".", "_")
    mapping_path = repo_root / f"{prefix}-mapping.json"
    mapping_path.write_text(json.dumps(mapping_payload, indent=2) + "\n", encoding="utf-8")
    print(f"written_file={mapping_path.name}")

    header_path = repo_root / f"{prefix}-spot_header.txt"
    header_path.write_text("prometheus_exposition\n", encoding="utf-8")
    event_path = repo_root / f"{prefix}-spot_event.txt"
    event_path.write_text(
        "%{DATA:metric_name}(\\{%{GREEDYDATA:labels}\\})?\\s+%{NUMBER:value}(%{SPACE}%{NUMBER:timestamp})?\n",
        encoding="utf-8",
    )
    print(f"written_file={header_path.name}")
    print(f"written_file={event_path.name}")

    ensure_write_target(args.elastic_url, args.elastic_api_key, target, mapping_payload)

    dst_min_ms, dst_max_ms = get_writable_range_ms(
        args.elastic_url, args.elastic_api_key, target.name
    )
    print(f"writable_ts_range_ms={dst_min_ms},{dst_max_ms}")

    print("counting_metric_lines...")
    expected_total = count_metric_lines(source_file)
    if args.max_docs:
        expected_total = min(expected_total, args.max_docs)
    print(f"count={expected_total}")

    status, count_resp = request(
        args.elastic_url, args.elastic_api_key, "GET", f"/{target.name}/_count"
    )
    if status != 200:
        raise SystemExit(f"count_read_failed status={status} resp={count_resp}")
    resume_from = int(count_resp.get("count", 0))
    if args.max_docs:
        resume_from = min(resume_from, args.max_docs)
    print(f"resume_from={resume_from}")

    if resume_from >= expected_total:
        print("already_complete=true")
        return 0

    t0 = time.perf_counter()
    ingested, failed = bulk_ingest_stream(
        args.elastic_url,
        args.elastic_api_key,
        target,
        source_file,
        resume_from,
        args.initial_batch_size,
        args.max_docs,
        expected_total,
        dst_min_ms,
        dst_max_ms,
    )
    elapsed = time.perf_counter() - t0

    status, _ = request(
        args.elastic_url,
        args.elastic_api_key,
        "POST",
        f"/{target.name}/_refresh",
    )
    if status != 200:
        raise SystemExit(f"refresh_failed status={status}")

    status, final_resp = request(
        args.elastic_url, args.elastic_api_key, "GET", f"/{target.name}/_count"
    )
    if status != 200:
        raise SystemExit(f"final_count_failed status={status} resp={final_resp}")

    final_count = int(final_resp.get("count", 0))
    print(f"bulk_failed={failed}")
    print(f"bulk_items={ingested}")
    print(f"final_count={final_count}")
    print(f"elapsed_sec={elapsed:.1f}")
    print(f"write_target={target.name}")
    if final_count < expected_total:
        print(f"warning=expected_{expected_total}_got_{final_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
