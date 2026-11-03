#!/usr/bin/env python3
"""
Creates a beautifully formatted Excel report for global metropolitan areas.
"""

import csv
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

def create_excel():
    csv_path = "metro_areas_07.csv"
    out_xlsx = "/Users/netanavot/Desktop/global_metro_areas_7pct.xlsx"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Global Metros (7% Cutoff)"

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    data_font = Font(name="Calibri", size=10)
    center_align = Alignment(horizontal="center", vertical="center")
    right_align = Alignment(horizontal="right", vertical="center")
    left_align = Alignment(horizontal="left", vertical="center")
    thin_border = Border(
        left=Side(style='thin', color='E0E0E0'),
        right=Side(style='thin', color='E0E0E0'),
        top=Side(style='thin', color='E0E0E0'),
        bottom=Side(style='thin', color='E0E0E0')
    )

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader)
        ws.append(headers)

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center_align

        for r_idx, row in enumerate(reader, start=2):
            rank = int(row[0])
            root_pid = int(row[1])
            name = row[2]
            country = row[3]
            lat = float(row[4])
            lon = float(row[5])
            pop = int(float(row[6]))
            area = float(row[7])
            avg_dens = float(row[8])
            peak_dens = float(row[9])
            p95_dens = float(row[10])
            thresh_dens = float(row[11])
            absorbed = int(row[12])

            ws.append([rank, root_pid, name, country, lat, lon, pop, area, avg_dens, peak_dens, p95_dens, thresh_dens, absorbed])

            # Apply styling
            for col_idx in range(1, 14):
                cell = ws.cell(row=r_idx, column=col_idx)
                cell.font = data_font
                cell.border = thin_border
                if col_idx in (1, 2):
                    cell.alignment = center_align
                    cell.number_format = "#,##0"
                elif col_idx == 3:
                    cell.alignment = left_align
                elif col_idx == 4:
                    cell.alignment = center_align
                elif col_idx in (5, 6):
                    cell.alignment = right_align
                    cell.number_format = "0.0000"
                elif col_idx == 7:
                    cell.alignment = right_align
                    cell.number_format = "#,##0"
                elif col_idx in (8, 9, 10, 11, 12):
                    cell.alignment = right_align
                    cell.number_format = "#,##0.0"
                elif col_idx == 13:
                    cell.alignment = center_align
                    cell.number_format = "#,##0"

    # Freeze header row
    ws.freeze_panes = "A2"

    # Auto-adjust column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 11)

    wb.save(out_xlsx)
    print(f"Saved {out_xlsx}")

if __name__ == "__main__":
    create_excel()
