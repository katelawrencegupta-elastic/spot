Spot - a Cursor agent to load sample data into Elastic(search) for testing/evaluation

Spot will parse the sample data with Grok & extract the header structure & per-event patterns, auto-generated an index with mappings along with an ingest pipeline of the same name for processing. Spot will upload the sample data to Elastic via bulk ingest & make it available for search with the fields now made available by the ingest pipeline.

## Common schema definition

Spot uses a schema-selection flow when creating/validating mappings:
- If a custom schema CSV is supplied, Spot uses it as the source of truth.
- If no custom schema is supplied, Spot defaults to `common-schema/fields.csv` (ECS field reference).
- Mapping resolution should be executed through `common-schema/resolve_mapping.py` so fallback behavior is centralized.

Elastic Common Schema Field Reference: [https://www.elastic.co/docs/reference/ecs/ecs-field-reference](https://www.elastic.co/docs/reference/ecs/ecs-field-reference)

## Runtime onboarding script

Use `scripts/spot_onboard.py` to run CSV onboarding end-to-end with centralized mapping resolution.

Example (custom schema):

```bash
python3 scripts/spot_onboard.py \
  --elastic-url "$ELASTIC_URL" \
  --elastic-api-key "$ELASTIC_API_KEY" \
  --index-base allstate \
  --source-file /absolute/path/to/structured_records.csv \
  --schema-csv /absolute/path/to/structured_schema.csv \
  --dataset spot.allstate \
  --product "Structured Records" \
  --skip-header
```

If `--schema-csv` is omitted, the script falls back to `common-schema/fields.csv` via `common-schema/resolve_mapping.py`.

Skills:

- elastic-bulk-ingest
- elastic-log-onboarding
- elastic-index-ops

This Skill will do the following

- Prompt for the URL & API key to connect to the Elastic(search) cluster 
- Prompt for the base index-name
- Prompt for a source file of sample data for ingest to Elastic(search)

The elastic-index-ops Skill will

- Create a new index & ingest pipeline named with the pattern spot-logs-index-name-sequential number

The elastic-log-onboarding Skill will

- Read the source file & parse out the GROK header structure; this will be applied as index mappings
- Read the source file & parse out the per-event GROK patterns and apply to the Ingest Pipeline
- Spot will recognize if the source file is JSON or CSV and parse accordingly 
- If Spot encounters parsing errors it will attempt to correct before proceeding with ingest

The elastic-bulk-ingest Skill will use Python is the default interperter for the bulk ingest and will follow these rules:

- Never send one huge `_bulk` request.
- Start with chunked batches (`20` docs per batch), then reduce (`10`, `5`, `1`) on repeated failures.
- Retry each failed batch up to 5 times.
- For `429` or timeout/network errors, use exponential backoff (1s, 2s, 4s, 8s, 16s).
- Resume from current index `_count` when re-running.
- Refresh index after final successful batch.

---

**Sample Summary Output**

Onboarding completed with Spot for ../spot_sshd_sample.log.

**Inputs summary**

- INDEX_NAME base: sshd
- Generated index/pipeline: spot-logs-sshd-0001
- Source file: /Users/klg/Documents/GItHub/spot/spot_sshd_sample.log

**Actions taken**

- Detected SSH syslog format and derived header/event GROK patterns.
- Created new index and additive mappings.
- Created ingest pipeline with multi-pattern SSH parsing + timestamp derivation.
- Set index.default_pipeline.
- Bulk ingested in chunks (300/300/300/100) with retry logic.
- Refreshed and verified final count.

**Artifacts generated**

- spot-logs-sshd-0001-spot_header.txt
- spot-logs-sshd-0001-spot_event.txt
- spot-logs-sshd-0001-pipeline.json
- spot-logs-sshd-0001-mapping.json
- spot-logs-sshd-0001-bulk.ndjson

**Verification results**

- index/mapping ack
  - index create: acknowledged=true
  - mapping update: acknowledged=true
- pipeline ack
  - pipeline create/update: acknowledged=true
  - default pipeline set: acknowledged=true
- bulk summary
  - errors=false
  - failed=0
  - items=1000
  - final _count 1000

