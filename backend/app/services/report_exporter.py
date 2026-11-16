import io
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

from openpyxl.utils import get_column_letter

def export_to_xlsx(title: str, user_name: str, params: dict, headers: list[str], rows: list[list]) -> bytes:
    """Генерация стилизованного XLSX отчета по ГОСТ/БГТУ"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Отчёт"

    # Заголовок отчета
    ws.merge_cells("A1:G1")
    ws["A1"] = title.upper()
    ws["A1"].font = Font(name="Times New Roman", size=14, bold=True)
    ws["A1"].alignment = Alignment(horizontal="center")

    # Метаданные (дата, сформировал, параметры)
    ws["A3"] = f"Дата формирования: {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')} UTC"
    ws["A4"] = f"Сформировал пользователь: {user_name}"
    param_str = ", ".join([f"{k}: {v}" for k, v in params.items() if v is not None]) or "Все"
    ws["A5"] = f"Параметры фильтрации: {param_str}"
    
    for r in range(3, 6):
        ws[f"A{r}"].font = Font(name="Times New Roman", size=10, italic=True)

    # Шапка таблицы
    start_row = 7
    header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin")
    )

    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=start_row, column=col_num, value=header)
        cell.font = Font(name="Times New Roman", size=11, bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    # Строки данных
    current_row = start_row + 1
    for row_data in rows:
        for col_num, val in enumerate(row_data, 1):
            cell = ws.cell(row=current_row, column=col_num, value=val)
            cell.font = Font(name="Times New Roman", size=10)
            cell.border = thin_border
            if isinstance(val, (int, float)):
                cell.alignment = Alignment(horizontal="right")
            else:
                cell.alignment = Alignment(horizontal="left")
        current_row += 1

    # Автоподбор ширины колонок
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_to_pdf(title: str, user_name: str, params: dict, headers: list[str], rows: list[list]) -> bytes:
    """Генерация PDF отчета с русским шрифтом и таблицей"""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    elements = []

    # Регистрируем кириллический шрифт из системы (DejaVuSans / LiberationSans / FreeSans)
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
    ]
    font_name = "Helvetica"
    for fp in font_paths:
        if os.path.exists(fp):
            pdfmetrics.registerFont(TTFont("CustomCyrillic", fp))
            font_name = "CustomCyrillic"
            break

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'RepTitle',
        parent=styles['Heading1'],
        fontName=font_name,
        fontSize=14,
        alignment=1, # Center
        spaceAfter=10
    )
    meta_style = ParagraphStyle(
        'RepMeta',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=9,
        textColor=colors.gray,
        spaceAfter=4
    )

    elements.append(Paragraph(title, title_style))
    elements.append(Paragraph(f"Дата формирования: {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')} UTC", meta_style))
    elements.append(Paragraph(f"Сформировал пользователь: {user_name}", meta_style))
    param_str = ", ".join([f"{k}: {v}" for k, v in params.items() if v is not None]) or "Все"
    elements.append(Paragraph(f"Параметры фильтрации: {param_str}", meta_style))
    elements.append(Spacer(1, 15))

    # Формируем таблицу ReportLab
    table_data = [[Paragraph(f"<b>{h}</b>", ParagraphStyle('Th', fontName=font_name, fontSize=9, alignment=1)) for h in headers]]
    for r in rows:
        formatted_row = []
        for cell_val in r:
            text = str(cell_val if cell_val is not None else "")
            formatted_row.append(Paragraph(text, ParagraphStyle('Td', fontName=font_name, fontSize=8)))
        table_data.append(formatted_row)

    t = Table(table_data, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#D9E1F2")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(t)

    doc.build(elements)
    return buf.getvalue()
