Common Spot schema files live here.

- `fields.csv` is the default ECS field reference used by Spot onboarding.
- Use the CSV `Field` and `Type` columns to drive Elasticsearch mapping decisions.
- `resolve_mapping.py` resolves Elasticsearch mapping `properties` for a list of fields.

Example:

```bash
python3 common-schema/resolve_mapping.py \
  --fields source.ip,host.name,@timestamp,event.dataset \
  --pretty
```

Custom schema override:

```bash
python3 common-schema/resolve_mapping.py \
  --schema /absolute/path/to/custom_schema.csv \
  --fields-file captured_fields.txt \
  --pretty
```

If `--schema` is not supplied, Spot falls back to:
1. `SPOT_SCHEMA_CSV` (if set)
2. `common-schema/fields.csv` (default ECS reference)

Use one field per line via `--fields-file` when the field list is generated from parsed GROK captures.
