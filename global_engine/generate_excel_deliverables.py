#!/usr/bin/env python3
"""
Generates comprehensive, beautifully formatted Excel deliverables for
Global Metropolitan Areas at 7% (Standard) and 25% (Micro) thresholds.
Saves directly to /Users/netanavot/Desktop/
"""

import os
import sys
import csv
import glob
import time
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

REGIONS = ['north_america', 'south_america', 'europe_africa', 'asia', 'oceania', 'pacific_islands']

def create_global_excel(pct=7):
    t0 = time.time()
    out_xlsx = f"/Users/netanavot/Desktop/global_metro_areas_{pct}pct.xlsx"
    out_csv = f"/Users/netanavot/Desktop/global_metro_areas_{pct}pct.csv"
    print(f"\n========================================================")
    print(f"Creating Global Metro Deliverable for {pct}% Threshold")
    print(f"========================================================")

    # 1. Merge and sort all continental CSVs
    all_metros = []
    total_regional_pop = 0.0

    for reg in REGIONS:
        csv_file = f"metro_areas_{reg}_{pct:02d}.csv"
        if not os.path.exists(csv_file):
            print(f"Warning: {csv_file} not found!")
            continue
        with open(csv_file, 'r', encoding='utf-8') as fp:
            reader = csv.DictReader(fp)
            count = 0
            for r in reader:
                pop = float(r['Total_Population'])
                if pop < 1.0: continue
                all_metros.append({
                    'name': r['Core_Name'],
                    'country': r['Country'],
                    'lat': float(r['Peak_Latitude']),
                    'lon': float(r['Peak_Longitude']),
                    'pop': int(pop),
                    'area': float(r['Total_Area_sqkm']),
                    'avg_density': float(r['Avg_Density_ppl_km2']),
                    'peak_density': float(r['Peak_Density']),
                    'p95_density': float(r['P95_Weighted_Density']),
                    'threshold_density': float(r['Threshold_Density']),
                    'absorbed_peaks': int(r['Absorbed_Peaks_Count']),
                    'region': reg
                })
                total_regional_pop += pop
                count += 1
            print(f"  Loaded {count:,} metros from {reg}")

    # Sort descending by population
    print(f"Total metros merged: {len(all_metros):,}, Total Pop: {total_regional_pop:,.0f}")
    all_metros.sort(key=lambda m: m['pop'], reverse=True)

    # Assign Global Ranks
    for idx, m in enumerate(all_metros, start=1):
        m['global_rank'] = idx

    # 2. Write Complete Global CSV (all metros down to 1 person)
    print(f"Writing complete raw CSV to {out_csv}...")
    with open(out_csv, 'w', encoding='utf-8', newline='') as fp:
        writer = csv.writer(fp)
        writer.writerow([
            "Global_Rank", "Core_Name", "Country", "Region", "Peak_Latitude", "Peak_Longitude",
            "Total_Population", "Total_Area_sqkm", "Avg_Density_ppl_km2", "Peak_Density",
            "P95_Weighted_Density", "Threshold_Density", "Absorbed_Peaks_Count"
        ])
        for m in all_metros:
            writer.writerow([
                m['global_rank'], m['name'], m['country'], m['region'],
                f"{m['lat']:.4f}", f"{m['lon']:.4f}", m['pop'],
                f"{m['area']:.1f}", f"{m['avg_density']:.1f}",
                f"{m['peak_density']:.1f}", f"{m['p95_density']:.1f}",
                f"{m['threshold_density']:.1f}", m['absorbed_peaks']
            ])
    print(f"Saved complete CSV ({os.path.getsize(out_csv)/(1024*1024):.1f} MB)")

    # 3. Create Excel Workbook (pop >= 1,000 to fit safely within Excel's 1,048,576 row limit)
    excel_metros = [m for m in all_metros if m['pop'] >= 1000]
    excel_pop = sum(m['pop'] for m in excel_metros)
    print(f"Writing {len(excel_metros):,} metros (pop >= 1,000, covering {excel_pop/total_regional_pop*100:.2f}% of world pop) to Excel...")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Global Metros ({pct}% Cutoff)"

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

    headers = [
        "Global Rank", "Core Name", "Country", "Region", "Peak Latitude", "Peak Longitude",
        "Total Population", "Total Area (km²)", "Avg Density (ppl/km²)", "Peak Density",
        "P95 Density", "Threshold Density", "Absorbed Peaks"
    ]
    ws.append(headers)

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align

    # Batch append rows
    batch_size = 10000
    for r_idx, m in enumerate(excel_metros, start=2):
        ws.append([
            m['global_rank'], m['name'], m['country'], m['region'],
            m['lat'], m['lon'], m['pop'], m['area'],
            m['avg_density'], m['peak_density'], m['p95_density'],
            m['threshold_density'], m['absorbed_peaks']
        ])
        if r_idx % 25000 == 0:
            print(f"  Appended {r_idx:,} rows...")

    print("Styling cells and applying number formats...")
    for row in ws.iter_rows(min_row=2, max_row=len(excel_metros)+1, min_col=1, max_col=13):
        for col_idx, cell in enumerate(row, start=1):
            cell.font = data_font
            cell.border = thin_border
            if col_idx == 1:
                cell.alignment = center_align
                cell.number_format = "#,##0"
            elif col_idx in (2, 4):
                cell.alignment = left_align
            elif col_idx == 3:
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

    ws.freeze_panes = "A2"

    # Set column widths
    col_widths = {
        'A': 13, 'B': 24, 'C': 10, 'D': 16, 'E': 14, 'F': 14,
        'G': 17, 'H': 16, 'I': 22, 'J': 14, 'K': 14, 'L': 18, 'M': 16
    }
    for col_letter, width in col_widths.items():
        ws.column_dimensions[col_letter].width = width

    wb.save(out_xlsx)
    print(f"Saved {out_xlsx} ({os.path.getsize(out_xlsx)/(1024*1024):.1f} MB) in {time.time()-t0:.2f}s!")

if __name__ == "__main__":
    create_global_excel(7)
    create_global_excel(25)
