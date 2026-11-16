import random
import sys
import os
from datetime import datetime, timedelta, date
from faker import Faker

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from sqlalchemy import text
from app.core.database import SyncSessionLocal
from app.core.security import get_password_hash
from app.models.entities import (
    Role, User, Manufacturer, EquipmentCategory, EquipmentModel,
    TechnicalSpecification, MalfunctionPattern, ModelMalfunction,
    ServiceDepartment, EquipmentItem, DiagnosticLog, MaintenanceOrder,
    SparePart, OrderSparePart
)

fake = Faker("ru_RU")
Faker.seed(42)
random.seed(42)

def seed():
    session = SyncSessionLocal()
    try:
        print("[SEED] Starting database population according to BSTU guidelines...")

        # 1. Проверяем или создаем роли
        roles = session.query(Role).all()
        role_map = {r.name: r.id for r in roles}

        # 2. Создаем пользователей для каждой роли (Задание 1)
        print("[SEED] Creating users (Admin, Technicians, Clients)...")
        users = []
        # Администратор
        if not session.query(User).filter_by(username="admin_stepan").first():
            admin = User(
                role_id=role_map["ADMIN"],
                username="admin_stepan",
                email="admin@bstu-service.ru",
                hashed_password=get_password_hash("AdminPass2026!"),
                full_name="Степанов Степан Александрович",
                is_active=True
            )
            users.append(admin)

        # 10 сервисных инженеров / техников
        tech_users = []
        for i in range(1, 11):
            uname = f"engineer_{i}"
            if not session.query(User).filter_by(username=uname).first():
                tech = User(
                    role_id=role_map["TECHNICIAN"],
                    username=uname,
                    email=f"tech{i}@bstu-service.ru",
                    hashed_password=get_password_hash("TechPass2026!"),
                    full_name=fake.name_male(),
                    is_active=True
                )
                users.append(tech)
                tech_users.append(tech)

        # 15 клиентов
        client_users = []
        for i in range(1, 16):
            uname = f"client_{i}"
            if not session.query(User).filter_by(username=uname).first():
                client = User(
                    role_id=role_map["CLIENT"],
                    username=uname,
                    email=f"client{i}@mail.ru",
                    hashed_password=get_password_hash("ClientPass2026!"),
                    full_name=fake.name(),
                    is_active=True
                )
                users.append(client)
                client_users.append(client)

        session.add_all(users)
        session.commit()
        
        all_techs = session.query(User).filter_by(role_id=role_map["TECHNICIAN"]).all()

        # 3. Сервисные подразделения (БГТУ / Белгород и филиалы)
        print("[SEED] Creating service departments...")
        dept_data = [
            ("Центральный сервисный центр БГТУ", "Белгород", "ул. Костюкова, д. 46 (Корпус ИТИ)", "+7 (4722) 55-00-01", 100),
            ("Филиал Диагностики и Ремонта №1", "Белгород", "пр-т Богдана Хмельницкого, д. 137", "+7 (4722) 34-11-22", 80),
            ("Лаборатория технического сервиса №2", "Старый Оскол", "мкр. Макаренко, д. 3а", "+7 (4725) 45-67-89", 60),
            ("Пункт экспресс-приема и сканирования", "Губкин", "ул. Мира, д. 20", "+7 (47241) 2-33-44", 40)
        ]
        depts = []
        for name, city, addr, ph, cap in dept_data:
            d = session.query(ServiceDepartment).filter_by(name=name).first()
            if not d:
                d = ServiceDepartment(name=name, city=city, address=addr, phone=ph, max_simultaneous_repairs=cap)
                session.add(d)
                session.flush()
            depts.append(d)
        session.commit()

        # 4. Производители (DNS, ASUS, MSI, LG, Samsung, Xiaomi, HP, Pantum, DEXP)
        print("[SEED] Ensuring manufacturers...")
        mfg_list = [
            ("DNS / DEXP", "Россия", "+7-800-770-7999", "service@dns-shop.ru", "https://dns-shop.ru"),
            ("ASUS", "Тайвань", "+7-800-100-2787", "support@asus.ru", "https://asus.com"),
            ("Samsung", "Южная Корея", "+7-800-555-5555", "support@samsung.com", "https://samsung.com"),
            ("Xiaomi", "Китай", "+7-800-775-6615", "service.ru@xiaomi.com", "https://mi.com"),
            ("MSI", "Тайвань", "+7-800-700-7708", "ru-service@msi.com", "https://ru.msi.com"),
            ("Lenovo", "Китай", "+7-800-301-0555", "support@lenovo.ru", "https://lenovo.com"),
            ("LG Electronics", "Южная Корея", "+7-800-200-7676", "service@lge.com", "https://lg.com"),
            ("Pantum", "Китай", "+7-800-700-1122", "support@pantum.ru", "https://pantum.ru")
        ]
        manufacturers = []
        for m_name, country, phone, email, web in mfg_list:
            m = session.query(Manufacturer).filter_by(name=m_name).first()
            if not m:
                m = Manufacturer(name=m_name, country=country, support_phone=phone, support_email=email, official_website=web)
                session.add(m)
                session.flush()
            manufacturers.append(m)
        session.commit()

        # 5. Категории
        categories = session.query(EquipmentCategory).all()

        # 6. Модели техники и их технические характеристики (1:1)
        print("[SEED] Creating equipment models and specifications...")
        models_data = [
            # Ноутбуки (CAT-LAPTOP, id ~ 1)
            ("ROG Strix G15 G513", "ASUS-ROG-G513-DNS", 2023, 24, "ASUS", "CAT-LAPTOP", 230.0, "20V / 11.5A", "354x259x22.6", 2.3, "Eclipse Gray"),
            ("TUF Gaming A15 FA506", "ASUS-TUF-FA506-DNS", 2022, 12, "ASUS", "CAT-LAPTOP", 200.0, "20V / 10A", "359x256x24.9", 2.3, "Graphite Black"),
            ("Katana GF76 11UE", "MSI-KAT-GF76-DNS", 2022, 12, "MSI", "CAT-LAPTOP", 180.0, "20V / 9A", "398x273x25.2", 2.6, "Black"),
            ("Legion 5 15ACH6H", "LEN-LEG5-15-DNS", 2022, 24, "Lenovo", "CAT-LAPTOP", 300.0, "20V / 15A", "362x260x25.7", 2.4, "Phantom Blue"),
            ("DEXP Atlas M15-I3W301", "DEXP-ATL-M15-DNS", 2023, 12, "DNS / DEXP", "CAT-LAPTOP", 65.0, "19V / 3.42A", "358x239x19.9", 1.7, "Silver"),
            
            # Смартфоны (CAT-MOBILE)
            ("Galaxy S23 Ultra 256GB", "SAM-S23U-256-DNS", 2023, 12, "Samsung", "CAT-MOBILE", 45.0, "5V-20V USB-PD", "163.4x78.1x8.9", 0.234, "Phantom Black"),
            ("Galaxy A54 5G 128GB", "SAM-A54-128-DNS", 2023, 12, "Samsung", "CAT-MOBILE", 25.0, "5V-9V FastCharge", "158.2x76.7x8.2", 0.202, "Awesome Lime"),
            ("Redmi Note 12 Pro+ 5G", "XIA-RN12P-DNS", 2023, 12, "Xiaomi", "CAT-MOBILE", 120.0, "HyperCharge 20V", "162.9x76x8.9", 0.210, "Polar White"),
            ("Xiaomi 13T Pro 512GB", "XIA-13TP-DNS", 2023, 24, "Xiaomi", "CAT-MOBILE", 120.0, "HyperCharge 20V", "162.2x75.7x8.5", 0.206, "Meadow Green"),
            
            # Крупная бытовая (CAT-MAJOR-APPLIANCE)
            ("LG F2V5HS9B Inverter AI DD", "LG-WM-F2V5-DNS", 2022, 24, "LG Electronics", "CAT-MAJOR-APPLIANCE", 1700.0, "220-240V / 50Hz", "600x455x850", 60.0, "Dark Silver"),
            ("Samsung WW70A6S23AX/LP", "SAM-WM-WW70-DNS", 2023, 12, "Samsung", "CAT-MAJOR-APPLIANCE", 2000.0, "220-240V / 50Hz", "600x450x850", 55.0, "Inox Gray"),
            ("DEXP WM-F712DSH/WB", "DEXP-WM-F712-DNS", 2023, 12, "DNS / DEXP", "CAT-MAJOR-APPLIANCE", 1800.0, "220-240V / 50Hz", "595x495x850", 58.0, "White"),
            
            # Оргтехника (CAT-OFFICE-PRINT)
            ("Pantum M6500W Laser MFP", "PAN-M6500W-DNS", 2022, 12, "Pantum", "CAT-OFFICE-PRINT", 370.0, "220-240V", "417x305x244", 7.5, "Black"),
            ("Pantum BM5100ADW Pro", "PAN-BM5100-DNS", 2023, 24, "Pantum", "CAT-OFFICE-PRINT", 650.0, "220-240V", "415x365x350", 11.2, "White/Grey")
        ]

        mfg_dict = {m.name: m.id for m in session.query(Manufacturer).all()}
        cat_dict = {c.code: c.id for c in session.query(EquipmentCategory).all()}

        models = []
        for m_name, v_code, r_year, w_months, mfg_n, cat_c, pwr, vlt, dim, wt, clr in models_data:
            m = session.query(EquipmentModel).filter_by(vendor_code=v_code).first()
            if not m:
                m = EquipmentModel(
                    category_id=cat_dict[cat_c],
                    manufacturer_id=mfg_dict[mfg_n],
                    model_name=m_name,
                    vendor_code=v_code,
                    release_year=r_year,
                    warranty_period_months=w_months
                )
                session.add(m)
                session.flush()

                spec = TechnicalSpecification(
                    model_id=m.id,
                    power_consumption_watts=pwr,
                    operating_voltage_volts=vlt,
                    dimensions_mm=dim,
                    weight_kg=wt,
                    color=clr,
                    additional_specs='{"interfaces": ["Wi-Fi 6", "Bluetooth 5.2", "USB Type-C"], "cooling": "Active dual-fan"}'
                )
                session.add(spec)
            models.append(m)
        session.commit()

        # 7. Каталог типовых дефектов и неисправностей (Malfunction Patterns)
        print("[SEED] Creating malfunction patterns...")
        patterns_data = [
            ("CAT-LAPTOP", "ERR-THRM-01", "Критический перегрев CPU/GPU и троттлинг",
             "Высокий шум вентиляторов, сброс тактовых частот, аварийное отключение под нагрузкой",
             "Засыхание жидкого металла / термопасты, засорение радиаторной решетки пылью", "HIGH",
             "Аппаратная чистка системы охлаждения, замена термоинтерфейса на высокотеплопроводный состав"),
            
            ("CAT-LAPTOP", "ERR-PWR-02", "Короткое замыкание по линии 19V / не включается",
             "Устройство не реагирует на кнопку включения, индикатор зарядки не светится",
             "Пробой входных MOSFET-ключей или керамического конденсатора первичной цепи питания", "CRITICAL",
             "Локализация пробитого элемента тепловизором, выпайка и замена силовых транзисторов"),
            
            ("CAT-LAPTOP", "ERR-DISP-03", "Артефакты изображения / мерцание матрицы",
             "Полосы на дисплее при изменении угла наклона крышки ноутбука",
             "Механический износ или микронадрыв eDP шлейфа матрицы в шарнирной петле", "MEDIUM",
             "Замена шлейфа матрицы на оригинальный компонент, регулировка натяжения шарниров"),
             
            ("CAT-MOBILE", "ERR-BAT-01", "Быстрая разрядка и вздутие аккумулятора",
             "Смартфон выключается на 30% заряда, задняя крышка деформирована",
             "Химическая деградация литий-полимерного аккумулятора вследствие циклов быстрой зарядки", "HIGH",
             "Утилизация дефектного АКБ, установка нового аккумулятора с калибровкой контроллера"),
             
            ("CAT-MOBILE", "ERR-CHG-02", "Нестабильный контакт разъема USB Type-C",
             "Зарядка прерывается при шевелении кабеля, ПК не определяет устройство",
             "Засорение порта пылью, механическое повреждение контактных ламелей", "LOW",
             "Ультразвуковая очистка разъема либо перепайка субплаты зарядки"),
             
            ("CAT-MAJOR-APPLIANCE", "ERR-PUMP-01", "Ошибка слива воды (код OE / 5E)",
             "Стиральная машина останавливается перед полосканием с водой в баке",
             "Заклинивание крыльчатки сливного насоса инородным предметом или обрыв обмотки помпы", "HIGH",
             "Очистка фильтра слива, диагностика мультиметром, замена насоса Askoll/Hanning"),
             
            ("CAT-MAJOR-APPLIANCE", "ERR-BRG-02", "Гул и вибрация при отжиме барабана",
             "Металлический скрежет и стук на оборотах свыше 800 об/мин",
             "Износ и разрушение подшипникового узла барабана из-за протечки сальника", "HIGH",
             "Разборка бака, перепрессовка подшипников (6205/6206) и замена влагостойкого сальника"),
             
            ("CAT-OFFICE-PRINT", "ERR-FUSR-01", "Замятие бумаги в термоблоке / смазывание тонера",
             "Бумага выходит гармошкой из печки, тонер стирается пальцем",
             "Повреждение термопленки фьюзера, износ резинового прижимного вала", "MEDIUM",
             "Замена термопленки с нанесением высокотемпературной смазки Molykote")
        ]

        malfunctions = []
        for cat_c, code, title, sym, cause, crit, rem in patterns_data:
            p = session.query(MalfunctionPattern).filter_by(code=code).first()
            if not p:
                p = MalfunctionPattern(
                    category_id=cat_dict[cat_c],
                    code=code,
                    title=title,
                    symptom_description=sym,
                    possible_root_cause=cause,
                    criticality_level=crit,
                    recommended_remedy=rem
                )
                session.add(p)
                session.flush()
            malfunctions.append(p)
        session.commit()

        # 8. Связывание моделей с типовыми поломками (ModelMalfunction)
        print("[SEED] Linking models with malfunction patterns...")
        for m in models:
            # Привязываем 1-3 поломки к каждой модели
            cat_malfuncs = [p for p in malfunctions if p.category_id == m.category_id]
            for p in cat_malfuncs:
                exists = session.query(ModelMalfunction).filter_by(model_id=m.id, malfunction_id=p.id).first()
                if not exists:
                    mm = ModelMalfunction(
                        model_id=m.id,
                        malfunction_id=p.id,
                        occurrence_frequency_pct=round(random.uniform(3.5, 28.0), 1),
                        typical_operating_hours=random.randint(800, 6000)
                    )
                    session.add(mm)
        session.commit()

        # 9. Запасные части (Spare Parts)
        print("[SEED] Creating spare parts catalog...")
        parts_data = [
            ("ASUS", "CAT-LAPTOP", "FAN-G513-PAIR", "Комплект вентиляторов охлаждения CPU+GPU ROG G513", 2400.0, 45),
            ("ASUS", "CAT-LAPTOP", "EDP-FA506-144", "Шлейф дисплея eDP 40pin 144Hz TUF Gaming", 1250.0, 30),
            ("MSI", "CAT-LAPTOP", "KBD-GF76-RU", "Клавиатурный модуль с подсветкой MSI Katana GF76", 3100.0, 20),
            ("Samsung", "CAT-MOBILE", "BAT-EB-BS918", "Аккумуляторная батарея Samsung S23 Ultra (5000 mAh)", 2800.0, 60),
            ("Samsung", "CAT-MOBILE", "SUB-A54-CHG", "Субплата системного разъема Type-C Samsung A54", 950.0, 50),
            ("LG Electronics", "CAT-MAJOR-APPLIANCE", "PUMP-LG-ASKOLL", "Сливной насос в сборе Askoll M231 для СМА LG", 1650.0, 75),
            ("Samsung", "CAT-MAJOR-APPLIANCE", "BRG-KIT-6205", "Ремкомплект подшипников (6205-6206) + сальник 35x65.55", 1400.0, 90),
            ("Pantum", "CAT-OFFICE-PRINT", "FUSER-FILM-M65", "Термопленка металлическая высокоскоростная Pantum M6500", 680.0, 110)
        ]
        spare_parts = []
        for mfg_n, cat_c, p_num, p_name, u_price, qty in parts_data:
            sp = session.query(SparePart).filter_by(part_number=p_num).first()
            if not sp:
                sp = SparePart(
                    manufacturer_id=mfg_dict[mfg_n],
                    compatible_category_id=cat_dict[cat_c],
                    part_number=p_num,
                    name=p_name,
                    unit_price=u_price,
                    stock_quantity=qty
                )
                session.add(sp)
                session.flush()
            spare_parts.append(sp)
        session.commit()

        # ==========================================================
        # 10. ГЕНЕРАЦИЯ ОПЕРАЦИОННЫХ ТАБЛИЦ (НЕ МЕНЕЕ 1 000 ЗАПИСЕЙ КАЖДАЯ)
        # ==========================================================
        
        # 10.1. Equipment Items: 1 200 единиц техники со штрихкодами
        print("[SEED] Generating 1,200 equipment items with unique barcodes and serial numbers...")
        existing_items_count = session.query(EquipmentItem).count()
        needed_items = 1200 - existing_items_count
        
        statuses = ["IN_OPERATION", "IN_DIAGNOSTICS", "IN_REPAIR", "REPAIRED", "DECOMMISSIONED"]
        status_weights = [0.55, 0.15, 0.15, 0.10, 0.05]
        
        items = []
        if needed_items > 0:
            for i in range(needed_items):
                model = random.choice(models)
                dept = random.choice(depts)
                
                # EAN-13 штрихкод (460 + 9 цифр + контрольная)
                barcode_num = f"460{random.randint(100000000, 999999999)}"

		checksum = sum(
            int(digit) * (1 if i % 2 == 0 else 3)
            for i, digit in enumerate(barcode_num)
            )
            
            barcode_num += str((10 - checksum % 10) % 10)

		barcode_num += str((10 - checksum % 10) % 10)
                serial_num = f"SN-{model.vendor_code[:4]}-{random.randint(100000, 999999)}-BSTU"
                
                mfg_date = fake.date_between(start_date="-3y", end_date="-1m")
                item_status = random.choices(statuses, weights=status_weights)[0]
                cost = round(random.uniform(15000.0, 180000.0), 2)
                
                item = EquipmentItem(
                    model_id=model.id,
                    current_department_id=dept.id,
                    serial_number=serial_num,
                    barcode=barcode_num,
                    manufacture_date=mfg_date,
                    status=item_status,
                    initial_cost=cost,
                    created_at=datetime.utcnow() - timedelta(days=random.randint(1, 700))
                )
                items.append(item)
            
            session.bulk_save_objects(items)
            session.commit()
            print(f"[SEED] Successfully inserted {len(items)} equipment items.")
        
        all_items = session.query(EquipmentItem).all()

        # 10.2. Diagnostic Logs: 1 500 записей диагностики (сканирование штрихкодов)
        print("[SEED] Generating 1,500 diagnostic logs from barcode scans...")
        existing_diag_count = session.query(DiagnosticLog).count()
        needed_diags = 1500 - existing_diag_count
        
        diag_actions = ["NO_ACTION", "PREVENTIVE_MAINTENANCE", "URGENT_REPAIR", "WRITE_OFF"]
        action_weights = [0.25, 0.35, 0.35, 0.05]

        diags = []
        if needed_diags > 0:
            for i in range(needed_diags):
                eq = random.choice(all_items)
                tech = random.choice(all_techs)
                
                # Ищем доступные поломки для категории этого оборудования
                cat_malfuncs = [m for m in malfunctions if m.category_id == eq.model.category_id]
                matched_p = random.choice(cat_malfuncs) if cat_malfuncs and random.random() > 0.2 else None
                
                symptom_text = matched_p.symptom_description if matched_p else fake.sentence(nb_words=8)
                conclusion_text = f"Диагностика штрихкода {eq.barcode}. Выявлено: {symptom_text}. Причина: {matched_p.possible_root_cause if matched_p else 'Естественный износ'}"
                action = random.choices(diag_actions, weights=action_weights)[0]
                
                scan_dt = datetime.utcnow() - timedelta(days=random.randint(0, 360), minutes=random.randint(1, 1440))
                
                d_log = DiagnosticLog(
                    equipment_id=eq.id,
                    diagnostician_id=tech.id,
                    department_id=eq.current_department_id,
                    scanned_barcode=eq.barcode,
                    scan_timestamp=scan_dt,
                    dns_source_url=f"https://dns-shop.ru/product/{eq.model.vendor_code.lower()}/",
                    observed_symptoms=symptom_text,
                    matched_malfunction_id=matched_p.id if matched_p else None,
                    diagnostic_conclusion=conclusion_text,
                    recommended_action=action
                )
                diags.append(d_log)
                
            session.bulk_save_objects(diags)
            session.commit()
            print(f"[SEED] Successfully inserted {len(diags)} diagnostic logs.")

        all_diags = session.query(DiagnosticLog).all()

        # 10.3. Maintenance Orders: 1 100 заказов на регламентное обслуживание и ремонт
        print("[SEED] Generating 1,100 maintenance orders...")
        existing_orders_count = session.query(MaintenanceOrder).count()
        needed_orders = 1100 - existing_orders_count
        
        order_statuses = ["NEW", "IN_PROGRESS", "WAITING_PARTS", "COMPLETED", "CANCELLED"]
        order_weights = [0.10, 0.20, 0.15, 0.50, 0.05]
        
        orders = []
        if needed_orders > 0:
            for i in range(needed_orders):
                d_log = random.choice(all_diags)
                tech = random.choice(all_techs)
                
                ord_status = random.choices(order_statuses, weights=order_weights)[0]
                ord_date = d_log.scan_timestamp + timedelta(hours=random.randint(1, 48))
                comp_date = ord_date + timedelta(days=random.randint(1, 10)) if ord_status == "COMPLETED" else None
                
                cost = round(random.uniform(1200.0, 35000.0), 2) if ord_status in ["COMPLETED", "IN_PROGRESS"] else 0.0
                
                order = MaintenanceOrder(
                    equipment_id=d_log.equipment_id,
                    department_id=d_log.department_id,
                    assigned_engineer_id=tech.id,
                    diagnostic_log_id=d_log.id,
                    order_number=f"ORD-BSTU-{ord_date.strftime('%y%m')}-{i+1:05d}",
                    order_date=ord_date,
                    completion_date=comp_date,
                    status=ord_status,
                    total_cost=cost,
                    work_summary=f"Сервисное обслуживание по результатам диагностики {d_log.id}. Устранение дефекта: {d_log.diagnostic_conclusion}"
                )
                orders.append(order)
            
            session.bulk_save_objects(orders)
            session.commit()
            print(f"[SEED] Successfully inserted {len(orders)} maintenance orders.")

        # 10.4. Order Spare Parts (M:N детали в заказах)
        print("[SEED] Attaching spare parts to completed orders...")
        existing_pairs = {
            (op.order_id, op.spare_part_id)
            for op in session.query(OrderSparePart.order_id, OrderSparePart.spare_part_id).all()
        }
        completed_orders = session.query(MaintenanceOrder).filter_by(status="COMPLETED").limit(400).all()
        order_parts = []
        for co in completed_orders:
            p = random.choice(spare_parts)
            if (co.id, p.id) in existing_pairs:
                continue
            existing_pairs.add((co.id, p.id))
            qty = random.randint(1, 3)
            op = OrderSparePart(
                order_id=co.id,
                spare_part_id=p.id,
                quantity=qty,
                applied_price=p.unit_price
            )
            order_parts.append(op)
        
        if order_parts:
            session.bulk_save_objects(order_parts)
            session.commit()
            print(f"[SEED] Successfully inserted {len(order_parts)} order spare parts links.")

        # 11. Обновление материализованного представления для Задания 10
        print("[SEED] Refreshing materialized view mv_model_failure_stats...")
        session.execute(text("REFRESH MATERIALIZED VIEW mv_model_failure_stats;"))
        session.commit()

        print("[SEED] SEEDING COMPLETE! All tables populated with 1000+ records!")

    except Exception as e:
        session.rollback()
        print(f"[SEED] ERROR during seeding: {e}")
        raise
    finally:
        session.close()

if __name__ == "__main__":
    seed()
