#!/usr/bin/env bash
# Onboard NetFlow sample — prompts for API key if not set.
# Usage: ./scripts/onboard_netflow.sh

set -euo pipefail
_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${_repo_root}"

export ELASTIC_URL="${ELASTIC_URL:-https://8951990f71754a818e768e655ff2789d.us-central1.gcp.cloud.es.io:443}"
export ELASTICSEARCH_HOSTS="${ELASTICSEARCH_HOSTS:-$ELASTIC_URL}"

# Load saved URL from .elastic.env (API key intentionally omitted until prompt)
if [[ -f "${_repo_root}/.elastic.env" ]]; then
  # shellcheck source=/dev/null
  source "${_repo_root}/.elastic.env"
fi

# shellcheck source=/dev/null
source "${_repo_root}/scripts/spot_elastic_env.sh"

exec python3 "${_repo_root}/scripts/spot_onboard_netflow.py" \
  --elastic-url "${ELASTIC_URL}" \
  --elastic-api-key "${ELASTIC_API_KEY}" \
  --index-base netflow \
  --source-file "${_repo_root}/sample-data/spot_netflow_sample.log" \
  --initial-batch-size 100
