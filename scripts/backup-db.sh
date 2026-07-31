#!/bin/zsh
set -euo pipefail
umask 077

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
DATABASE_PATH="${REPO_DIR}/data/scanner.db"
BACKUP_DIR="${REPO_DIR}/backups"

[[ -f "${DATABASE_PATH}" ]] || exit 0
mkdir -p "${BACKUP_DIR}"

BACKUP_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_PATH="${BACKUP_DIR}/scanner-${BACKUP_STAMP}.db"
TEMP_DIR="$(mktemp -d "${BACKUP_DIR}/.scanner-backup.XXXXXX")"
TEMP_PATH="${TEMP_DIR}/scanner.db"

cleanup() {
  rm -f "${TEMP_PATH}"
  rmdir "${TEMP_DIR}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP

sqlite3 "${DATABASE_PATH}" ".backup '${TEMP_PATH}'"
chmod 600 "${TEMP_PATH}"

QUICK_CHECK_RESULT="$(sqlite3 -batch -noheader "${TEMP_PATH}" "PRAGMA quick_check;")"
if [[ "${QUICK_CHECK_RESULT}" != "ok" ]]; then
  print -u2 -- "Backup validation failed: PRAGMA quick_check returned ${QUICK_CHECK_RESULT}"
  exit 1
fi

REQUIRED_TABLE_COUNT="$(
  sqlite3 -batch -noheader "${TEMP_PATH}" \
    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name IN ('scan_results', 'scan_runs');"
)"
if [[ "${REQUIRED_TABLE_COUNT}" != "2" ]]; then
  print -u2 -- "Backup validation failed: required tables scan_results and scan_runs were not both present"
  exit 1
fi

mv -f "${TEMP_PATH}" "${BACKUP_PATH}"
rmdir "${TEMP_DIR}"
trap - EXIT INT TERM HUP

find "${BACKUP_DIR}" -type f -name 'scanner-*.db' -mtime +14 -delete
