#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
BACKEND_DIR="${REPO_DIR}/backend"
DATA_DIR="${REPO_DIR}/data"
WEBHOOK_KEYCHAIN_SERVICE="com.theinvestingclinic.squeeze-scanner.discord-webhook"

mkdir -p "${DATA_DIR}"

export DATABASE_URL="sqlite:///${DATA_DIR}/scanner.db"
export ALLOWED_ORIGIN="${ALLOWED_ORIGIN:-https://theinvestingclinic.com}"
export PYTHONUNBUFFERED=1

# Read the Railway webhook from macOS Keychain without copying it into this repo.
if [[ -z "${DISCORD_WEBHOOK_URL:-}" ]]; then
  SCANNER_WEBHOOK_SECRET="$(
    security find-generic-password \
      -a squeeze-scanner \
      -s "${WEBHOOK_KEYCHAIN_SERVICE}" \
      -w 2>/dev/null || true
  )"
  if [[ -n "${SCANNER_WEBHOOK_SECRET}" ]]; then
    export DISCORD_WEBHOOK_URL="${SCANNER_WEBHOOK_SECRET}"
  fi
  unset SCANNER_WEBHOOK_SECRET
fi

cd "${BACKEND_DIR}"
exec "${REPO_DIR}/.venv/bin/uvicorn" main:app --host 127.0.0.1 --port 8000
