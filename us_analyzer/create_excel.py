#!/usr/bin/env python3
"""
Converts us_metro_areas.csv into a beautifully formatted, publication-quality Excel workbook (.xlsx).
Includes auto-filtering, freeze panes, conditional formatting, and summary statistics.
"""

import csv
import os
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

def create_excel(csv_path="us_metro_areas.csv", xlsx_path="us_metro_areas.xlsx"):
    wb = openpyxl.Workbook()
    
    # -------------------------------------------------------------
    # Sheet 1: All US Metro Areas
    # -------------------------------------------------------------
    ws = wb.active
    ws.title = "US Metro Areas"
    ws.views.sheetView[0].showGridLines = True

    # Styling definitions
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid") # Dark navy
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=11)
    bold_font = Font(name="Calibri", size=11, bold=True)
    
    thin_border_side = Side(border_style="thin", color="D9D9D9")
    data_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
    header_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=Side(border_style="medium", color="1F4E79"))

    zebra_fill = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")

    headers = [
        "Rank",
        "Metropolitan Core Area",
        "Peak Latitude",
        "Peak Longitude",
        "Total Population",
        "Land Area (km²)",
        "Avg Density (ppl/km²)",
        "Peak Density (ppl/km²)",
        "95th Pct Density (ppl/km²)",
        "Threshold T (ppl/km²)",
        "Absorbed Peaks",
        "Merged Anchor Cities & Suburbs"
    ]

    ws.append(headers)

    # Style header row
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center" if col_idx not in [2, 12] else "left", vertical="center", wrap_text=True)
        cell.border = header_border

    ws.row_dimensions[1].height = 28

    total_pop_sum = 0
    total_area_sum = 0
    row_count = 0

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        _ = next(reader) # skip header
        for r_idx, row in enumerate(reader, start=2):
            rank = int(row[0])
            name = row[1]
            lat = float(row[2])
            lon = float(row[3])
            pop = int(float(row[4]))
            area = float(row[5])
            avg_dens = float(row[6])
            peak_dens = float(row[7])
            p95_dens = float(row[8])
            thresh = float(row[9])
            abs_count = int(row[10])
            merged = row[11]

            total_pop_sum += pop
            total_area_sum += area
            row_count += 1

            ws.append([
                rank,
                name,
                lat,
                lon,
                pop,
                area,
                avg_dens,
                peak_dens,
                p95_dens,
                thresh,
                abs_count,
                merged
            ])

            # Apply cell styles and formatting
            fill = zebra_fill if r_idx % 2 == 0 else PatternFill(fill_type=None)
            
            for c_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=r_idx, column=c_idx)
                cell.font = data_font
                cell.border = data_border
                if fill.fill_type:
                    cell.fill = fill

            # Number Formats
            ws.cell(row=r_idx, column=1).alignment = Alignment(horizontal="center") # Rank
            ws.cell(row=r_idx, column=2).font = bold_font if rank <= 25 else data_font # Name
            ws.cell(row=r_idx, column=3).number_format = "0.0000" # Lat
            ws.cell(row=r_idx, column=4).number_format = "0.0000" # Lon
            ws.cell(row=r_idx, column=5).number_format = "#,##0" # Population
            ws.cell(row=r_idx, column=6).number_format = "#,##0.0" # Area
            ws.cell(row=r_idx, column=7).number_format = "#,##0.0" # Avg Dens
            ws.cell(row=r_idx, column=8).number_format = "#,##0.0" # Peak Dens
            ws.cell(row=r_idx, column=9).number_format = "#,##0.0" # P95 Dens
            ws.cell(row=r_idx, column=10).number_format = "#,##0.0" # Threshold
            ws.cell(row=r_idx, column=11).alignment = Alignment(horizontal="center") # Absorbed peaks

            ws.row_dimensions[r_idx].height = 20

    # Auto-filter and freeze pane
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{row_count + 1}"
    ws.freeze_panes = "C2" # Freeze Rank and Metro Name

    # Column widths
    column_widths = {
        1: 8,   # Rank
        2: 28,  # Name
        3: 13,  # Lat
        4: 14,  # Lon
        5: 16,  # Population
        6: 15,  # Area
        7: 18,  # Avg Dens
        8: 18,  # Peak Dens
        9: 20,  # P95 Dens
        10: 16, # Threshold
        11: 14, # Absorbed Peaks
        12: 50   # Merged Anchors
    }
    for col_idx, width in column_widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    # -------------------------------------------------------------
    # Sheet 2: Methodology & Parameter Reference
    # -------------------------------------------------------------
    ws_meta = wb.create_sheet(title="Methodology & Summary")
    ws_meta.views.sheetView[0].showGridLines = True

    meta_title_font = Font(name="Calibri", size=14, bold=True, color="1F4E79")
    meta_section_font = Font(name="Calibri", size=12, bold=True, color="000000")
    meta_label_font = Font(name="Calibri", size=11, bold=True)
    meta_val_font = Font(name="Calibri", size=11)

    ws_meta.append(["Mathematical Metropolitan Area Delineation — Overview"])
    ws_meta.cell(row=1, column=1).font = meta_title_font
    ws_meta.append([])

    meta_rows = [
        ("Dataset", "WorldPop 2020 United States Population Raster (30 arc-sec / ~1 km resolution)"),
        ("Geographic Scope", "Contiguous United States (CONUS)"),
        ("Total Gridded Population Analyzed", f"{total_pop_sum:,.0f} people"),
        ("Total Metro Areas Detected", f"{row_count} metropolitan areas"),
        ("Gaussian Smoothing Filter", "Sigma = 1.5 km (removes micro-peaks while preserving urban drainage structure)"),
        ("Condition A (Topographic Watershed)", "Uphill steepest ascent flow tracing; cells belong to downhill basin of density peak"),
        ("Condition B (Connected Superlevel Set)", "Contiguous component expansion reachable via paths of density ≥ Threshold T"),
        ("Absorbed Peak Rule", "Any satellite peak contacted via Condition B merges and brings its entire Condition A basin"),
        ("Threshold Formula", "T = 4.0% of Population-Weighted 95th Percentile Density (P95_weighted)"),
        ("Provable Termination Guarantee", "Monotonically non-increasing threshold updates guarantee exact finite convergence"),
        ("Key Validation Test Case 1", "Wasatch Front: Salt Lake City, Ogden, and Provo unite into 1 single metro area (~2.55M pop)"),
        ("Key Validation Test Case 2", "Northeast Corridor: New York, Philadelphia, Boston, and Washington DC remain independent")
    ]

    for label, val in meta_rows:
        ws_meta.append([label, val])
        curr_r = ws_meta.max_row
        ws_meta.cell(row=curr_r, column=1).font = meta_label_font
        ws_meta.cell(row=curr_r, column=2).font = meta_val_font
        ws_meta.row_dimensions[curr_r].height = 22

    ws_meta.column_dimensions["A"].width = 35
    ws_meta.column_dimensions["B"].width = 85

    wb.save(xlsx_path)
    print(f"Successfully generated Excel file at {xlsx_path} with {row_count} metro areas.")

if __name__ == "__main__":
    create_excel()
