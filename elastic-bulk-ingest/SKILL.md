---
name: elastic-bulk-ingest
description: Perform reliable Elasticsearch bulk ingestion with chunking, retries, backoff, and resume behavior. Use when ingesting large log files, handling bulk timeouts, or recovering from partial ingest.
---

# Elastic Bulk Ingest

## Purpose

Ingest large files into Elasticsearch reliably without one-shot bulk failures.

## Required Inputs

- `ELASTIC_URL`
- `ELASTIC_API_KEY`
- `INDEX_NAME`
- `SOURCE_FILE` (absolute path)

## Python Execution Requirement

Always execute Python for payload construction and ingestion orchestration:

```bash
python3 - <<'PY'
# python code
PY
```

## Ingest Rules

1. Never send one huge `_bulk` request.
2. Start with chunked batches (`20` docs per batch), then reduce (`10`, `5`, `1`) on repeated failures.
3. Retry each failed batch up to 5 times.
4. For `429` or timeout/network errors, use exponential backoff (1s, 2s, 4s, 8s, 16s).
5. Resume from current index `_count` when re-running.
6. Refresh index after final successful batch.

## Expected Output During Run

Print concise progress:
- `resume_from=<count>`
- `ingested=<count>` every 100-200 docs
- `final_ingested=<count>`
- `failed_batch_start=<offset>` if unrecoverable

## Workflow

1. Read current `_count` from target index.
2. Read source file lines and skip already-ingested rows based on `_count`.
3. Build per-doc NDJSON pairs:
   - `{"index":{"_index":"<index>"}}`
   - `{"message":"<raw_line>"}`
4. Send chunked `_bulk` requests with retries/backoff.
5. Call `/<index>/_refresh`.
6. Verify final `_count`.

## Verification Checklist

- Bulk loop completed without unrecoverable batch errors.
- Final `_count` matches expected source-line total.
- Report any gap between expected vs indexed.

## Guardrails

1. Do not delete or recreate index unless explicitly requested.
2. Stop and ask if credentials are missing.
3. If retries are exhausted for a batch, stop and report exact offset.
4. Keep terminology consistent: use `batch`, `retry`, `backoff`, `resume`.
