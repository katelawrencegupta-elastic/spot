"""Shared Elasticsearch helpers for Spot onboarding scripts."""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class WriteTarget:
    """Elasticsearch write destination for bulk ingest."""

    name: str
    kind: str  # "index" or "data_stream"
    pipeline_name: str
    artifact_prefix: str
    create_index: bool
    apply_mapping: bool
    set_default_pipeline: bool
    bulk_pipeline_in_action: bool

    def bulk_action(self) -> str:
        return "create" if self.kind == "data_stream" else "index"

    def bulk_index_meta(self) -> dict:
        meta: dict = {"_index": self.name}
        if self.bulk_pipeline_in_action:
            meta["pipeline"] = self.pipeline_name
        return meta

    def bulk_action_line(self) -> dict:
        return {self.bulk_action(): self.bulk_index_meta()}


def add_target_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-stream",
        help="Pre-created data stream name to ingest into (skips index creation).",
    )
    parser.add_argument(
        "--pipeline",
        help="Ingest pipeline name. Defaults to the write target name in index mode, "
        "or spot-pipeline-<index-base> in data stream mode.",
    )
    parser.add_argument(
        "--apply-mapping",
        action="store_true",
        help="Push generated mappings to the target. Default for indices; "
        "use this flag with --data-stream to apply additive mappings.",
    )
    parser.add_argument(
        "--skip-pipeline",
        action="store_true",
        help="Do not create or update the ingest pipeline (use a pre-created pipeline).",
    )


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


def resolve_write_target(
    elastic_url: str,
    api_key: str,
    index_base: str,
    data_stream: str | None,
    pipeline: str | None,
    apply_mapping: bool,
    skip_pipeline: bool,
) -> WriteTarget:
    if data_stream:
        pipeline_name = pipeline or f"spot-pipeline-{index_base}"
        return WriteTarget(
            name=data_stream,
            kind="data_stream",
            pipeline_name=pipeline_name,
            artifact_prefix=data_stream,
            create_index=False,
            apply_mapping=apply_mapping,
            set_default_pipeline=False,
            bulk_pipeline_in_action=not skip_pipeline,
        )

    index_name = next_index_name(elastic_url, api_key, index_base)
    pipeline_name = pipeline or index_name
    return WriteTarget(
        name=index_name,
        kind="index",
        pipeline_name=pipeline_name,
        artifact_prefix=index_name,
        create_index=True,
        apply_mapping=True,
        set_default_pipeline=not skip_pipeline,
        bulk_pipeline_in_action=False,
    )


def verify_data_stream(elastic_url: str, api_key: str, name: str) -> None:
    status, resp = request(elastic_url, api_key, "GET", f"/_data_stream/{name}")
    if status == 200:
        streams = resp.get("data_streams", [])
        if streams:
            print(f"data_stream_verified={name}")
            return
    raise SystemExit(f"data_stream_not_found name={name} status={status} resp={resp}")


def ensure_write_target(
    elastic_url: str,
    api_key: str,
    target: WriteTarget,
    mapping_payload: dict,
) -> None:
    if target.kind == "data_stream":
        verify_data_stream(elastic_url, api_key, target.name)
    else:
        status, create_resp = request(elastic_url, api_key, "PUT", f"/{target.name}", {})
        if status not in (200, 201):
            raise SystemExit(f"index_create_failed status={status} resp={create_resp}")
        print(f"index_create_ack={create_resp.get('acknowledged')}")

    if target.apply_mapping:
        status, map_resp = request(
            elastic_url, api_key, "PUT", f"/{target.name}/_mapping", mapping_payload
        )
        if status != 200:
            raise SystemExit(f"mapping_update_failed status={status} resp={map_resp}")
        print(f"mapping_update_ack={map_resp.get('acknowledged')}")
    elif target.kind == "data_stream":
        print("mapping_apply_skipped=precreated_data_stream")


def put_pipeline(
    elastic_url: str,
    api_key: str,
    target: WriteTarget,
    pipeline_payload: dict,
) -> None:
    if target.kind == "data_stream" and not target.bulk_pipeline_in_action:
        print(f"pipeline_update_skipped=using_precreated pipeline={target.pipeline_name}")
        return

    status, pipe_resp = request(
        elastic_url,
        api_key,
        "PUT",
        f"/_ingest/pipeline/{target.pipeline_name}",
        pipeline_payload,
    )
    if status != 200:
        raise SystemExit(f"pipeline_put_failed status={status} resp={pipe_resp}")
    print(f"pipeline_put_ack={pipe_resp.get('acknowledged')}")


def set_default_pipeline(elastic_url: str, api_key: str, target: WriteTarget) -> None:
    if not target.set_default_pipeline:
        print("default_pipeline_skipped=data_stream_mode")
        return

    status, set_resp = request(
        elastic_url,
        api_key,
        "PUT",
        f"/{target.name}/_settings",
        {"index": {"default_pipeline": target.pipeline_name}},
    )
    if status != 200:
        raise SystemExit(f"default_pipeline_set_failed status={status} resp={set_resp}")
    print(f"default_pipeline_set_ack={set_resp.get('acknowledged')}")
