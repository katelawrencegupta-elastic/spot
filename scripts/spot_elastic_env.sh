#!/usr/bin/env bash
# Source this file to configure Elastic Cloud credentials for Spot:
#   source scripts/spot_elastic_env.sh
#
# Optional: create repo-root .elastic.env (gitignored) with exports to skip the prompt.

_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${_repo_root}/.elastic.env" ]]; then
  # shellcheck source=/dev/null
  source "${_repo_root}/.elastic.env"
fi

# Normalize ELASTICSEARCH_* (common in Elastic tooling) to Spot's ELASTIC_* names
if [[ -n "${ELASTICSEARCH_HOSTS:-}" && -z "${ELASTIC_URL:-}" ]]; then
  export ELASTIC_URL="${ELASTICSEARCH_HOSTS%% *}"
fi
if [[ -n "${ELASTICSEARCH_API_KEY:-}" && -z "${ELASTIC_API_KEY:-}" ]]; then
  export ELASTIC_API_KEY="${ELASTICSEARCH_API_KEY}"
fi

export ELASTIC_URL="${ELASTIC_URL:-https://8951990f71754a818e768e655ff2789d.us-central1.gcp.cloud.es.io:443}"

if [[ -n "${ELASTIC_API_KEY:-}" ]]; then
  echo "ELASTICSEARCH_HOSTS=${ELASTIC_URL}"
  echo "ELASTIC_URL=${ELASTIC_URL}"
  echo "ELASTICSEARCH_API_KEY is set (length ${#ELASTIC_API_KEY})."
  return 0 2>/dev/null || exit 0
fi

echo "Elastic Cloud cluster: ${ELASTIC_URL}" >&2
echo "Paste an API key from Kibana → Stack Management → API keys (or Deployment → API keys)." >&2

_tty="/dev/tty"
if [[ -r "${_tty}" ]]; then
  printf "Elasticsearch API key: " >"${_tty}"
  read -rsp "" ELASTIC_API_KEY <"${_tty}"
  printf "\n" >"${_tty}"
else
  printf "Elasticsearch API key: " >&2
  read -rsp "" ELASTIC_API_KEY
  printf "\n" >&2
fi

if [[ -z "${ELASTIC_API_KEY}" ]]; then
  echo "No API key entered." >&2
  unset ELASTIC_API_KEY
  return 1 2>/dev/null || exit 1
fi

export ELASTIC_API_KEY
export ELASTICSEARCH_API_KEY="${ELASTIC_API_KEY}"
export ELASTICSEARCH_HOSTS="${ELASTIC_URL}"
echo "ELASTICSEARCH_HOSTS=${ELASTIC_URL}"
echo "ELASTIC_URL=${ELASTIC_URL}"
echo "ELASTICSEARCH_API_KEY set (length ${#ELASTIC_API_KEY})."
