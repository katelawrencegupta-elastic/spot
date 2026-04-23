Common Spot schema files live here.

- `fields.csv` is the common schema definition used by Spot onboarding.
- Use the CSV `Field` and `Type` columns to drive Elasticsearch mapping decisions.
- `resolve_mapping.py` resolves Elasticsearch mapping `properties` for a list of fields.

Example:

```bash
python3 common-schema/resolve_mapping.py \
  --fields source.ip,host.name,@timestamp,event.dataset \
  --pretty
```

Use one field per line via `--fields-file` when the field list is generated from parsed GROK captures.
