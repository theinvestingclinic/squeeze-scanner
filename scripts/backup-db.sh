#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
DATABASE_PATH="${REPO_DIR}/data/scanner.db"
BACKUP_DIR="${REPO_DIR}/backups"

[[ -f "${DATABASE_PATH}" ]] || exit 0
mkdir -p "${BACKUP_DIR}"

BACKUP_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_PATH="${BACKUP_DIR}/scanner-${BACKUP_STAMP}.db"
sqlite3 "${DATABASE_PATH}" ".backup '${BACKUP_PATH}'"
find "${BACKUP_DIR}" -type f -name 'scanner-*.db' -mtime +14 -delete
