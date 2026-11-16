#!/bin/sh
set -e

echo "[BACKUP-DAEMON] Starting PostgreSQL Backup Daemon..."
echo "[BACKUP-DAEMON] Target DB: $PGDATABASE on host $PGHOST:$PGPORT"
echo "[BACKUP-DAEMON] Backup Dir: $BACKUP_DIR | Retention: $RETENTION_DAYS days"

mkdir -p "$BACKUP_DIR"

while true; do
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    BACKUP_FILE="$BACKUP_DIR/backup_${PGDATABASE}_${TIMESTAMP}.sql.gz"
    
    echo "[BACKUP-DAEMON] Running scheduled backup at $(date)..."
    pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$PGDATABASE" | gzip > "$BACKUP_FILE"
    
    if [ -f "$BACKUP_FILE" ] && [ -s "$BACKUP_FILE" ]; then
        echo "[BACKUP-DAEMON] Backup created successfully: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
    else
        echo "[BACKUP-DAEMON] ERROR: Backup failed!" >&2
    fi

    # Ротация: удаление дампов старше $RETENTION_DAYS дней
    echo "[BACKUP-DAEMON] Cleaning backups older than $RETENTION_DAYS days..."
    find "$BACKUP_DIR" -type f -name "backup_${PGDATABASE}_*.sql.gz" -mtime +$RETENTION_DAYS -exec rm -f {} \;
    
    # Спим 24 часа (для тестов/демо также вызывается вручную из API)
    sleep 86400 &
    wait $!
done

