---
name: elastic-log-onboarding
description: Build and validate Elasticsearch log onboarding end-to-end. Use when generating sample logs, deriving GROK header and event patterns, creating an index and ingest pipeline, applying mappings, and bulk ingesting data.
---

# Elastic Log Onboarding

## Purpose

Run a repeatable workflow for onboarding a new log source into Elasticsearch:
1. Generate or read source logs
2. Derive header GROK pattern
3. Derive unique event GROK patterns
4. Create index and mappings
5. Create ingest pipeline
6. Assign default pipeline
7. Bulk ingest and verify

## Required Inputs

- `ELASTIC_URL`
- `ELASTIC_API_KEY`
- `INDEX_NAME` (base name only, example: `cloudtrail` or `apache`)
- `SOURCE_LOG_FILE` (absolute path)

Spot must generate the concrete index/pipeline name each run as:
`spot-logs-<INDEX_NAME>-<N>`

Where `<N>` is the next sequential number for that base name (zero-padded, starting at `0001`).
Example sequence for `INDEX_NAME=cloudtrail`:
- `spot-logs-cloudtrail-0001`
- `spot-logs-cloudtrail-0002`
- `spot-logs-cloudtrail-0003`

Never reuse an existing numbered index/pipeline unless explicitly requested.

## Output Files

- `<index>-spot_header.txt`: one header GROK line
- `<index>-spot_event.txt`: unique event GROK patterns, one per line
- `<index>-pipeline.json`: ingest pipeline payload
- `<index>-bulk.ndjson`: bulk payload

## Python Execution Rules

When parsing logs, generating artifacts, or building ingest payloads, execute Python in the terminal instead of only proposing code.

Use:

```bash
python3 - <<'PY'
# python code
PY
```

Execution requirements:
1. Print concise status output (`count`, `written_file`, `ingested`).
2. Write generated artifacts to workspace files.
3. For ingest operations, prefer chunked batches over a single huge request.
4. On timeout/network errors, retry with smaller batch size before giving up.
5. If partial ingest occurred, report current `_count` and what remains.

## Workflow

### 1) Extract header and event GROK patterns

Run Python to derive patterns from representative lines.
- Header pattern in `<index>-spot_header.txt`
- Unique per-event patterns in `<index>-spot_event.txt`
- Include fallback `%{GREEDYDATA:message_body}` as the final event pattern

### 2) Create index mappings from header fields

At minimum, map fields from header captures:
- IP-like fields -> `ip`
- timestamp fields -> `date` with expected format(s)
- identity/auth/facility/host-like fields -> `keyword`
- numeric fields -> `integer`/`long`

Only apply additive mappings.

### 3) Create ingest pipeline (one GROK processor per event line)

Build processors by iterating each line in `<index>-spot_event.txt`:

```json
{
  "grok": {
    "field": "message",
    "patterns": ["<line_pattern>"],
    "ignore_missing": true,
    "ignore_failure": true
  }
}
```

Append metadata processors:
- `event.dataset`
- `observer.vendor`
- `observer.product`

Add `on_failure` with `error.message`.

### 4) Assign pipeline and ingest data

- Set `index.default_pipeline` to pipeline name
- Always use the generated run-specific index/pipeline name by default
- Resolve the next sequential number by listing existing indices/pipelines matching `spot-logs-<INDEX_NAME>-*`
- For ingestion reliability, apply the `elastic-bulk-ingest` skill when available.
- Execute Python to convert source file into bulk NDJSON:
  - action line: `{"index":{"_index":"<index>"}}`
  - source line: `{"message":"<raw line>"}`
- Ingest using chunked `_bulk` requests (recommended starting size: 100-500 docs/batch).
- Refresh index after final successful batch.

When delegating to `elastic-bulk-ingest`, pass:
- `INDEX_NAME=<index>`
- `SOURCE_FILE=<source log path>`
- Current expected document total

### 5) Verify

Always return:
- Index creation/mapping acknowledgment
- Pipeline creation acknowledgment
- Bulk summary (`errors`, `failed`, `items`)
- Final `_count`

## Command Templates

```bash
# Create/Update pipeline
curl -sS -X PUT \
  -H "Authorization: ApiKey $ELASTIC_API_KEY" \
  -H "Content-Type: application/json" \
  "$ELASTIC_URL/_ingest/pipeline/$INDEX_NAME" \
  --data-binary @"$PIPELINE_JSON"
```

```bash
# Set default pipeline
curl -sS -X PUT \
  -H "Authorization: ApiKey $ELASTIC_API_KEY" \
  -H "Content-Type: application/json" \
  "$ELASTIC_URL/$INDEX_NAME/_settings" \
  -d "{\"index\":{\"default_pipeline\":\"$INDEX_NAME\"}}"
```

```bash
# Bulk ingest
curl -sS -X POST \
  -H "Authorization: ApiKey $ELASTIC_API_KEY" \
  -H "Content-Type: application/x-ndjson" \
  "$ELASTIC_URL/_bulk?refresh=true" \
  --data-binary @"$BULK_FILE"
```

## Guardrails

1. Never delete indices or pipelines unless the user explicitly asks.
2. If credentials are missing, stop and request them.
3. If bulk returns `errors=true`, summarize failed items and stop for confirmation.
4. Do not assume timestamp format; align date mapping with observed log format.
5. Do not rely on one-shot huge bulk requests for large files; chunk and retry.
6. Default behavior is create-only per run: generate `spot-logs-<INDEX_NAME>-<N>` and do not update existing numbered indices/pipelines unless explicitly requested.

## Interactive Prompt: Spot

Use the standalone prompt in `spot-prompt.md`.

## How to use Spot

Copy the prompt from `spot-prompt.md`, then start by providing:
- `ELASTIC_URL`
- `ELASTIC_API_KEY`
- `SOURCE_LOG_FILE` (absolute path)

Spot will ask for anything missing, generate the next `spot-logs-<INDEX_NAME>-<N>` index/pipeline name, and execute the workflow step by step.
