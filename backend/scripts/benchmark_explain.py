import time
import sys
import os
from sqlalchemy import text
from sqlalchemy.orm import selectinload

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.core.database import SyncSessionLocal
from app.models.entities import EquipmentItem, EquipmentModel, DiagnosticLog

def run_benchmarks():
    session = SyncSessionLocal()
    print("=" * 70)
    print("БГТУ им. В.Г. Шухова: Исследование производительности и планов (Задание 8)")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. Исследование проблемы N+1 в ORM (SQLAlchemy 2.0)
    # ------------------------------------------------------------------
    print("\n[ЭКСПЕРИМЕНТ 1] Проблема N+1 запросов при загрузке связанных сущностей:")
    
    # Сценарий A: Наивный доступ (Lazy Loading - N+1 SELECT)
    start_time = time.perf_counter()
    items_naive = session.query(EquipmentItem).limit(300).all()
    models_naive = [item.model.model_name for item in items_naive]
    elapsed_naive_ms = (time.perf_counter() - start_time) * 1000
    print(f"  -> Без оптимизации (Lazy load, 1 + 300 SELECT): {elapsed_naive_ms:.2f} мс")

    # Сценарий B: Оптимизированный доступ (Eager loading через selectinload)
    session.expire_all()
    start_time = time.perf_counter()
    items_opt = session.query(EquipmentItem).options(selectinload(EquipmentItem.model)).limit(300).all()
    models_opt = [item.model.model_name for item in items_opt]
    elapsed_opt_ms = (time.perf_counter() - start_time) * 1000
    print(f"  -> С оптимизацией (Eager selectinload, 2 SELECT): {elapsed_opt_ms:.2f} мс")
    speedup_n1 = elapsed_naive_ms / max(elapsed_opt_ms, 0.001)
    print(f"  >>> Ускорение устранения N+1: в {speedup_n1:.1f} раз!")

    # ------------------------------------------------------------------
    # 2. Исследование планов выполнения EXPLAIN ANALYZE (Индексы B-Tree)
    # ------------------------------------------------------------------
    print("\n[ЭКСПЕРИМЕНТ 2] Влияние составного индекса (current_department_id, status):")
    
    # Проверяем план выполнения с принудительным отключением index scan (Seq Scan)
    seq_query = """
        SET enable_indexscan = off;
        SET enable_bitmapscan = off;
        EXPLAIN ANALYZE 
        SELECT id, serial_number, barcode, status 
        FROM equipment_items 
        WHERE current_department_id = 1 AND status = 'IN_OPERATION';
    """
    session.execute(text("SET enable_indexscan = off;"))
    session.execute(text("SET enable_bitmapscan = off;"))
    res_seq = session.execute(text("""
        EXPLAIN ANALYZE 
        SELECT id, serial_number, barcode, status 
        FROM equipment_items 
        WHERE current_department_id = 1 AND status = 'IN_OPERATION';
    """)).fetchall()
    
    seq_plan = "\n".join([r[0] for r in res_seq])
    print("--- План без использования индекса (Sequential Scan) ---")
    print(seq_plan)

    # Проверяем план выполнения с включенным индексом (Index Scan)
    session.execute(text("SET enable_indexscan = on;"))
    session.execute(text("SET enable_bitmapscan = on;"))
    res_idx = session.execute(text("""
        EXPLAIN ANALYZE 
        SELECT id, serial_number, barcode, status 
        FROM equipment_items 
        WHERE current_department_id = 1 AND status = 'IN_OPERATION';
    """)).fetchall()
    
    idx_plan = "\n".join([r[0] for r in res_idx])
    print("\n--- План с использованием составного B-Tree индекса (Bitmap/Index Scan) ---")
    print(idx_plan)

    # ------------------------------------------------------------------
    # 3. Запрос по штрихкоду с сортировкой по времени (idx_diag_barcode_time)
    # ------------------------------------------------------------------
    print("\n[ЭКСПЕРИМЕНТ 3] Поиск по штрихкоду сканера и сортировка по времени:")
    res_barcode = session.execute(text("""
        EXPLAIN ANALYZE
        SELECT id, scanned_barcode, scan_timestamp, diagnostic_conclusion
        FROM diagnostic_logs
        WHERE scanned_barcode = '4601234567890'
        ORDER BY scan_timestamp DESC;
    """)).fetchall()
    barcode_plan = "\n".join([r[0] for r in res_barcode])
    print(barcode_plan)

    print("\n" + "=" * 70)
    print("БЕНЧМАРКИ ЗАВЕРШЕНЫ УСПЕШНО. Данные зафиксированы для записки.")
    print("=" * 70)
    session.close()

if __name__ == "__main__":
    run_benchmarks()

