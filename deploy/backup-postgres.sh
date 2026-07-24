#!/usr/bin/env bash
# Nightly Postgres backup (docs/09 §6). Everything durable — reports, audit rows, and
# LangGraph checkpoints — lives in Postgres, so a single dump captures full state. Redis
# is disposable and is never backed up.
#
# Cron example (2am daily, keep 14 days), as the deploy user:
#   0 2 * * * /opt/research-assistant/deploy/backup-postgres.sh >> /var/log/mara-backup.log 2>&1
#
# Restore:
#   gunzip -c backup-YYYY-MM-DD.sql.gz | docker compose -f docker-compose.full.yml exec -T postgres \
#     psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.full.yml}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/research-assistant}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
POSTGRES_USER="${POSTGRES_USER:-research_user}"
POSTGRES_DB="${POSTGRES_DB:-research_db}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%F)"
OUT="$BACKUP_DIR/backup-$STAMP.sql.gz"

echo "[backup] dumping $POSTGRES_DB → $OUT"
docker compose -f "$COMPOSE_FILE" exec -T postgres \
	pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
	| gzip > "$OUT"

echo "[backup] pruning backups older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -name 'backup-*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete

echo "[backup] done: $(du -h "$OUT" | cut -f1)"
