---
name: elastic-index-ops
description: Manage Elasticsearch index operations with safe, repeatable steps using API key authentication. Use when creating indices, updating mappings/settings, managing templates and aliases, checking index health, or when the user asks for Elasticsearch index administration.
---

# Elasticsearch Index Operations

## Scope

Use this skill for Elasticsearch index administration tasks:
- Create/delete indices
- Update mappings and settings
- Manage aliases and index templates
- Validate health and index state
- Plan safe rollout for index schema changes

Default authentication: API key via `Authorization: ApiKey <base64(id:api_key)>`.

## Safety Rules

1. Never delete or close indices without explicit user confirmation.
2. Prefer additive mapping changes; do not suggest incompatible field type changes in place.
3. Before risky operations, gather evidence:
   - Cluster health
   - Current index settings/mappings
   - Existing aliases/templates
4. For mapping breaking changes, use reindex flow instead of force edits.
5. Use explicit index names and avoid wildcard writes unless user requests them.

## Required Inputs

Ask for these if missing:
- `ELASTIC_URL` (for example `https://cluster.region.gcp.elastic-cloud.com:9243`)
- `ELASTIC_API_KEY` (base64 encoded API key token)
- Target environment (`dev`, `staging`, `prod`)
- Target index/alias name

## Python Execution Rules

When transforming large payloads, parsing command output, or running bulk ingestion workflows, execute Python in terminal rather than only describing code.

Use:

```bash
python3 - <<'PY'
# python code
PY
```

Execution requirements:
1. Print concise status (`count`, `processed`, `failed`, output path).
2. Prefer chunked bulk operations for large datasets.
3. On timeout/network errors, retry with smaller batches.
4. If partial success occurs, report current index `_count` and remaining work.

## Command Patterns

Use these `curl` templates when the user wants executable commands.

### Health check

```bash
curl -sS \
  -H "Authorization: ApiKey $ELASTIC_API_KEY" \
  "$ELASTIC_URL/_cluster/health?pretty"
```

### Read index mapping

```bash
curl -sS \
  -H "Authorization: ApiKey $ELASTIC_API_KEY" \
  "$ELASTIC_URL/<index>/_mapping?pretty"
```

### Read index settings

```bash
curl -sS \
  -H "Authorization: ApiKey $ELASTIC_API_KEY" \
  "$ELASTIC_URL/<index>/_settings?pretty"
```

### Create index

```bash
curl -sS -X PUT \
  -H "Authorization: ApiKey $ELASTIC_API_KEY" \
  -H "Content-Type: application/json" \
  "$ELASTIC_URL/<index>" \
  -d '{
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 1
    },
    "mappings": {
      "properties": {
        "created_at": { "type": "date" }
      }
    }
  }'
```

### Update mapping (additive only)

```bash
curl -sS -X PUT \
  -H "Authorization: ApiKey $ELASTIC_API_KEY" \
  -H "Content-Type: application/json" \
  "$ELASTIC_URL/<index>/_mapping" \
  -d '{
    "properties": {
      "new_field": { "type": "keyword" }
    }
  }'
```

### Create or update alias

```bash
curl -sS -X POST \
  -H "Authorization: ApiKey $ELASTIC_API_KEY" \
  -H "Content-Type: application/json" \
  "$ELASTIC_URL/_aliases" \
  -d '{
    "actions": [
      { "add": { "index": "<index>", "alias": "<alias>" } }
    ]
  }'
```

### Bulk ingest (chunked recommended)

For large payloads, avoid a single huge `_bulk` request. Use chunked batches (for example 100-500 docs per request) and verify progress between batches.

## Standard Workflow

1. Confirm environment and target resource names.
2. Inspect current state (health, mapping, settings, aliases/templates).
3. Propose change plan:
   - Objective
   - Risk level
   - Rollback strategy
4. Execute minimal safe operations.
5. Verify with read-back checks and summarize outcomes.

## Breaking Mapping Change Workflow

When a field type must change:
1. Create new index `<name>-v2` with corrected mapping.
2. Reindex from source index.
3. Validate document counts and sample queries.
4. Atomically swap alias to new index.
5. Keep old index until user confirms cleanup.

## Response Format

When assisting the user, structure output as:

```markdown
## Plan
- Goal: ...
- Risk: low|medium|high
- Rollback: ...

## Commands
```bash
# commands here
```

## Verification
- Check 1 ...
- Check 2 ...

## Notes
- Any caveats
```

## Escalation Conditions

Pause and ask before proceeding if:
- Operation targets production and includes delete/close/shrink/force merge
- Request uses wildcard destructive operations
- Existing cluster health is red
- User asks to change existing field type in place
- Repeated bulk timeout occurs after reducing batch size
