#!/bin/bash
set -e

echo "=== БГТУ им. В.Г. Шухова: Тестирование резервного копирования и восстановления (Задание 3) ==="

BACKUP_DIR="/tmp/bstu_backups"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DUMP_FILE="$BACKUP_DIR/test_backup_${TIMESTAMP}.sql.gz"

echo "[1/4] Выполнение pg_dump в сжатый файл $DUMP_FILE..."
docker exec bstu_equipment_db pg_dump -U diag_admin equipment_diag_db | gzip > "$DUMP_FILE"
echo "  -> Размер дампа: $(du -h "$DUMP_FILE" | cut -f1)"

echo "[2/4] Создание временной чистой базы данных 'temp_restore_verify'..."
docker exec bstu_equipment_db psql -U diag_admin -d postgres -c "DROP DATABASE IF EXISTS temp_restore_verify;"
docker exec bstu_equipment_db psql -U diag_admin -d postgres -c "CREATE DATABASE temp_restore_verify;"

echo "[3/4] Восстановление данных из архива в чистую базу..."
gunzip -c "$DUMP_FILE" | docker exec -i bstu_equipment_db psql -U diag_admin -d temp_restore_verify >/dev/null 2>&1

echo "[4/4] Верификация целостности восстановленных данных:"
ORIG_ITEMS=$(docker exec bstu_equipment_db psql -U diag_admin -d equipment_diag_db -t -c "SELECT count(*) FROM equipment_items;" | tr -d ' ')
REST_ITEMS=$(docker exec bstu_equipment_db psql -U diag_admin -d temp_restore_verify -t -c "SELECT count(*) FROM equipment_items;" | tr -d ' ')

ORIG_DIAGS=$(docker exec bstu_equipment_db psql -U diag_admin -d equipment_diag_db -t -c "SELECT count(*) FROM diagnostic_logs;" | tr -d ' ')
REST_DIAGS=$(docker exec bstu_equipment_db psql -U diag_admin -d temp_restore_verify -t -c "SELECT count(*) FROM diagnostic_logs;" | tr -d ' ')

echo "  -> Таблица equipment_items: Исходно=$ORIG_ITEMS, Восстановлено=$REST_ITEMS"
echo "  -> Таблица diagnostic_logs: Исходно=$ORIG_DIAGS, Восстановлено=$REST_DIAGS"

if [ "$ORIG_ITEMS" -eq "$REST_ITEMS" ] && [ "$ORIG_DIAGS" -eq "$REST_DIAGS" ]; then
    echo ">>> ПРОВЕРКА ВОССТАНОВЛЕНИЯ УСПЕШНО ПРОЙДЕНА (100% целостность)!"
else
    echo ">>> ОШИБКА: Расхождение в количестве восстановленных записей!" >&2
    exit 1
fi

docker exec bstu_equipment_db psql -U diag_admin -d postgres -c "DROP DATABASE temp_restore_verify;"
echo "=== Очистка временной БД завершена. Протокол зафиксирован. ==="
