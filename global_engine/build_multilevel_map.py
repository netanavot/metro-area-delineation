#!/usr/bin/env python3
"""
Builds an interactive global metropolitan areas HTML map with TRUE VECTOR POLYGONS
at native 1 km (30 arc-sec) resolution across 5 discrete thresholds:
  1% (Macro), 4% (Broad), 7% (Standard), 15% (Tight), 25% (Micro).
Includes instant discrete button switcher, 4 basemaps (Dark, Satellite, OSM, Voyager),
search & fly-to, top 500 leaderboard, and full interactive inspection.
"""

import os
import sys
import json
import csv
import time
import zlib
import base64
import numpy as np
import cv2

REGIONS = ['pacific_islands', 'oceania', 'south_america', 'north_america', 'europe_africa', 'asia']
LEVELS = [1, 4, 7, 15, 25]
LEVEL_DESCS = {
    1: "Macro Metros",
    4: "Broad Metros",
    7: "Standard Metros",
    15: "Tight Metros",
    25: "Micro Metros"
}

def vectorize_all_levels():
    t_start = time.time()
    print("========================================================")
    print("Building Interactive Multi-Level Global Vector Map")
    print("Levels: 1% (Macro), 4% (Broad), 7% (Standard), 15% (Tight), 25% (Micro)")
    print("========================================================\n")

    compressed_geojson_by_level = {}
    summaries_by_level = {}

    # Preload metadata for all regions
    region_metas = {}
    for reg in REGIONS:
        with open(f"meta_{reg}.json") as fp:
            region_metas[reg] = json.load(fp)

    for lvl in LEVELS:
        t_lvl = time.time()
        print(f"\n>>> Processing Level {lvl}% ({LEVEL_DESCS[lvl]})...")
        all_features = []
        all_metro_summaries = []

        for reg in REGIONS:
            t_reg = time.time()
            meta = region_metas[reg]
            H, W = meta['rows'], meta['cols']
            origin_lat, origin_lon = meta['origin_lat'], meta['origin_lon']
            dlat, dlon = meta['pixel_size_lat'], meta['pixel_size_lon']

            bin_file = f"metro_ranks_{reg}_{lvl:02d}.bin"
            csv_file = f"metro_areas_{reg}_{lvl:02d}.csv"

            if not os.path.exists(bin_file) or not os.path.exists(csv_file):
                print(f"  Skipping {reg}: {bin_file} not found")
                continue

            # Load regional CSV
            target_metros = {}
            with open(csv_file, 'r', encoding='utf-8') as fp:
                for r in csv.DictReader(fp):
                    rk = int(r['Rank'])
                    pop = float(r['Total_Population'])
                    # Include all metros >= 2,500 pop (or >= 500 in Oceania/Pacific Islands)
                    if pop >= 2500 or (reg in ('oceania', 'pacific_islands') and pop >= 500):
                        info = {
                            'r': rk,
                            'reg': reg,
                            'n': r['Core_Name'],
                            'c': r['Country'],
                            'la': round(float(r['Peak_Latitude']), 3),
                            'lo': round(float(r['Peak_Longitude']), 3),
                            'p': int(pop),
                            'a': int(float(r['Total_Area_sqkm'])),
                            'd': int(float(r['Avg_Density_ppl_km2'])),
                            'pd': int(float(r['Peak_Density'])),
                            'th': int(float(r['Threshold_Density'])),
                            'ab': int(r['Absorbed_Peaks_Count'])
                        }
                        target_metros[rk] = info
                        all_metro_summaries.append(info)

            if not target_metros:
                continue

            # Load 32-bit rank grid
            ranks = np.fromfile(bin_file, dtype=np.int32).reshape((H, W))

            # Fast scatter vectorization: find nonzeros matching target ranks
            target_keys = set(target_metros.keys())
            nz_r, nz_c = np.nonzero(ranks > 0)
            nz_ranks = ranks[nz_r, nz_c]

            # Filter to target ranks
            mask_in_target = np.array([rk in target_keys for rk in nz_ranks], dtype=bool)
            if not np.any(mask_in_target):
                continue

            filtered_ranks = nz_ranks[mask_in_target]
            filtered_r = nz_r[mask_in_target]
            filtered_c = nz_c[mask_in_target]

            sort_idx = np.argsort(filtered_ranks)
            sorted_ranks = filtered_ranks[sort_idx]
            sorted_r = filtered_r[sort_idx]
            sorted_c = filtered_c[sort_idx]

            change_idx = np.flatnonzero(np.diff(sorted_ranks)) + 1
            splits = np.concatenate(([0], change_idx, [len(sorted_ranks)]))

            reg_features = 0
            for i in range(len(splits) - 1):
                s, e = splits[i], splits[i+1]
                rk = int(sorted_ranks[s])
                m_info = target_metros.get(rk)
                if not m_info: continue

                rs = sorted_r[s:e]
                cs = sorted_c[s:e]

                min_r, max_r = rs.min(), rs.max()
                min_c, max_c = cs.min(), cs.max()

                sub_h = max_r - min_r + 3
                sub_w = max_c - min_c + 3

                sub_mask = np.zeros((sub_h, sub_w), dtype=np.uint8)
                sub_mask[rs - min_r + 1, cs - min_c + 1] = 1

                cnts, _ = cv2.findContours(sub_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                poly_rings = []
                for cnt in cnts:
                    if cv2.contourArea(cnt) < 1.0: continue
                    # epsilon=1.0 at native 1km gives clean organic curves with zero blockiness
                    simp = cv2.approxPolyDP(cnt, epsilon=1.0, closed=True)
                    if len(simp) < 3: continue
                    ring = []
                    for pt in simp:
                        col = min_c - 1 + pt[0][0]
                        row = min_r - 1 + pt[0][1]
                        lon = round(origin_lon + (col + 0.5) * dlon, 3)
                        lat = round(origin_lat - (row + 0.5) * dlat, 3)
                        ring.append([lon, lat])
                    if ring[0] != ring[-1]: ring.append(ring[0])
                    poly_rings.append(ring)

                if not poly_rings: continue
                geom_type = 'Polygon' if len(poly_rings) == 1 else 'MultiPolygon'
                coords = [poly_rings[0]] if len(poly_rings) == 1 else [[r] for r in poly_rings]

                all_features.append({
                    'type': 'Feature',
                    'properties': m_info,
                    'geometry': {'type': geom_type, 'coordinates': coords}
                })
                reg_features += 1

            print(f"  {reg:16s}: {reg_features:,} vector metros in {time.time()-t_reg:.2f}s")

        # Global sorting of summary for leaderboard
        all_metro_summaries.sort(key=lambda m: m['p'], reverse=True)
        for idx, m in enumerate(all_metro_summaries, start=1):
            m['gr'] = idx

        # Re-assign global rank property to features
        m_map = {(m['reg'], m['r']): m['gr'] for m in all_metro_summaries}
        for f in all_features:
            props = f['properties']
            props['gr'] = m_map.get((props['reg'], props['r']), 0)

        total_pop_covered = sum(m['p'] for m in all_metro_summaries)
        summaries_by_level[lvl] = {
            'total_count': len(all_metro_summaries),
            'total_pop': total_pop_covered,
            'top_metros': all_metro_summaries[:500]
        }

        # Compress GeoJSON
        gj = {'type': 'FeatureCollection', 'features': all_features}
        raw_json = json.dumps(gj, separators=(',', ':'))
        compressed = zlib.compress(raw_json.encode('utf-8'), 9)
        b64 = base64.b64encode(compressed).decode('ascii')
        compressed_geojson_by_level[lvl] = b64

        print(f"Level {lvl}% complete: {len(all_features):,} vector features, raw {len(raw_json)/(1024*1024):.1f} MB -> gzipped {len(compressed)/(1024*1024):.2f} MB in {time.time()-t_lvl:.2f}s")

    print(f"\nAll 5 levels vectorized in {time.time()-t_start:.2f}s!")
    build_html_file(compressed_geojson_by_level, summaries_by_level)

def build_html_file(geojson_data, summaries):
    t0 = time.time()
    js_geojson_map = json.dumps({str(k): v for k, v in geojson_data.items()})
    js_summaries = json.dumps({str(k): v for k, v in summaries.items()})
    default_lvl = 7

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Worldwide Metropolitan Areas — True 1 km Native Resolution</title>

  <!-- Leaflet CSS & JS -->
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <!-- Pako (High-speed zlib decompression in browser) -->
  <script src="https://cdnjs.cloudflare.com/ajax/libs/pako/2.1.0/pako.min.js"></script>

  <!-- Google Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600;700&display=swap" rel="stylesheet">

  <style>
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    body {{
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      color: #0f172a;
      background: #020617;
      height: 100vh;
      overflow: hidden;
      display: flex;
    }}

    /* Sidebar Layout */
    #sidebar {{
      width: 420px;
      min-width: 420px;
      height: 100vh;
      background: #ffffff;
      border-right: 1px solid #e2e8f0;
      display: flex;
      flex-direction: column;
      z-index: 1000;
      box-shadow: 4px 0 24px rgba(0,0,0,0.06);
    }}

    .header {{
      padding: 20px 22px 14px;
      background: #0f172a;
      color: #f8fafc;
    }}
    .header-badge {{
      display: inline-block;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.8px;
      text-transform: uppercase;
      color: #38bdf8;
      background: rgba(56, 189, 248, 0.12);
      padding: 3px 8px;
      border-radius: 999px;
      margin-bottom: 8px;
    }}
    .header h1 {{
      font-size: 18px;
      font-weight: 800;
      letter-spacing: -0.4px;
      margin-bottom: 4px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .header p {{
      font-size: 11px;
      color: #94a3b8;
      line-height: 1.45;
    }}

    /* 5-Button Discrete Threshold Switcher */
    .switcher-card {{
      padding: 16px 20px;
      background: #f8fafc;
      border-bottom: 1px solid #e2e8f0;
    }}
    .switcher-label-row {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 10px;
    }}
    .switcher-title {{
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.6px;
      color: #475569;
    }}
    .switcher-current {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 14px;
      font-weight: 800;
      color: #0284c7;
    }}
    .level-btn-group {{
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 6px;
    }}
    .level-btn {{
      background: #ffffff;
      border: 1px solid #cbd5e1;
      padding: 8px 4px;
      border-radius: 8px;
      cursor: pointer;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
      transition: all 0.15s ease;
    }}
    .level-btn:hover {{
      border-color: #0284c7;
      background: #f0f9ff;
    }}
    .level-btn.active {{
      background: #0284c7;
      border-color: #0284c7;
      color: #ffffff;
      box-shadow: 0 4px 12px rgba(2, 132, 199, 0.25);
    }}
    .level-btn-pct {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 13px;
      font-weight: 800;
    }}
    .level-btn-desc {{
      font-size: 9px;
      font-weight: 600;
      text-transform: uppercase;
      opacity: 0.85;
    }}

    /* Global Summary Stats */
    .stats-row {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      padding: 12px 20px;
      background: #ffffff;
      border-bottom: 1px solid #e2e8f0;
      gap: 8px;
    }}
    .stat-cell {{
      display: flex;
      flex-direction: column;
    }}
    .stat-label {{
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: #64748b;
      margin-bottom: 2px;
    }}
    .stat-number {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 14px;
      font-weight: 800;
      color: #0f172a;
    }}

    /* Search & Filters */
    .controls {{
      padding: 12px 20px;
      background: #ffffff;
      border-bottom: 1px solid #e2e8f0;
    }}
    .search-box {{
      position: relative;
    }}
    .search-input {{
      width: 100%;
      padding: 9px 12px 9px 34px;
      font-size: 12px;
      font-family: inherit;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      outline: none;
      transition: all 0.15s ease;
      background: #f8fafc url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="%2394a3b8" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>') no-repeat 10px center;
    }}
    .search-input:focus {{
      background-color: #ffffff;
      border-color: #0284c7;
      box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.12);
    }}

    /* Leaderboard List */
    #metro-list {{
      flex: 1;
      overflow-y: auto;
      padding: 6px 10px;
    }}
    .metro-item {{
      display: flex;
      align-items: center;
      padding: 9px 12px;
      border-radius: 8px;
      cursor: pointer;
      margin-bottom: 4px;
      transition: background 0.1s ease;
      gap: 10px;
      border: 1px solid transparent;
    }}
    .metro-item:hover {{
      background: #f1f5f9;
      border-color: #e2e8f0;
    }}
    .metro-item.active {{
      background: #e0f2fe;
      border-color: #38bdf8;
    }}
    .metro-rank {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      font-weight: 700;
      color: #64748b;
      min-width: 32px;
      text-align: right;
    }}
    .metro-dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex-shrink: 0;
      box-shadow: 0 0 0 1px rgba(0,0,0,0.1);
    }}
    .metro-info {{
      flex: 1;
      min-width: 0;
    }}
    .metro-name-row {{
      display: flex;
      align-items: baseline;
      gap: 6px;
    }}
    .metro-name {{
      font-size: 13px;
      font-weight: 700;
      color: #0f172a;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .metro-country {{
      font-size: 10px;
      font-weight: 700;
      color: #64748b;
      background: #f1f5f9;
      padding: 1px 5px;
      border-radius: 4px;
    }}
    .metro-pop {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
      font-weight: 700;
      color: #0284c7;
      text-align: right;
    }}

    /* Detail Card Footer */
    #detail-panel {{
      padding: 16px 20px;
      background: #f8fafc;
      border-top: 1px solid #e2e8f0;
    }}
    .detail-header {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      margin-bottom: 12px;
    }}
    .detail-title {{
      font-size: 15px;
      font-weight: 800;
      color: #0f172a;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .detail-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px 14px;
    }}
    .detail-cell {{
      display: flex;
      flex-direction: column;
    }}
    .detail-cell .label {{
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: #64748b;
      margin-bottom: 2px;
    }}
    .detail-cell .val {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 13px;
      font-weight: 700;
      color: #0f172a;
    }}

    /* Map Layout */
    #map-container {{
      flex: 1;
      height: 100vh;
      position: relative;
    }}
    #map {{
      width: 100%;
      height: 100%;
      background: #020617;
    }}

    /* Basemap Switcher Toolbar */
    .basemap-picker {{
      position: absolute;
      top: 16px;
      right: 16px;
      z-index: 1000;
      background: rgba(15, 23, 42, 0.88);
      backdrop-filter: blur(10px);
      padding: 4px;
      border-radius: 10px;
      display: flex;
      gap: 4px;
      border: 1px solid rgba(255, 255, 255, 0.12);
      box-shadow: 0 8px 24px rgba(0,0,0,0.3);
    }}
    .basemap-btn {{
      background: transparent;
      border: none;
      color: #94a3b8;
      padding: 6px 12px;
      font-size: 11px;
      font-weight: 700;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.15s ease;
    }}
    .basemap-btn:hover {{
      color: #f8fafc;
      background: rgba(255, 255, 255, 0.08);
    }}
    .basemap-btn.active {{
      background: #38bdf8;
      color: #0f172a;
    }}

    /* Loading Toast */
    #loading-toast {{
      position: absolute;
      bottom: 24px;
      right: 24px;
      z-index: 1000;
      background: rgba(15, 23, 42, 0.92);
      backdrop-filter: blur(8px);
      color: #f8fafc;
      padding: 10px 18px;
      border-radius: 999px;
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 12px;
      font-weight: 600;
      border: 1px solid rgba(255, 255, 255, 0.15);
      box-shadow: 0 8px 32px rgba(0,0,0,0.4);
      transition: opacity 0.2s;
    }}
    .spinner {{
      width: 14px;
      height: 14px;
      border: 2px solid rgba(255, 255, 255, 0.25);
      border-top-color: #38bdf8;
      border-radius: 50%;
      animation: spin 0.6s linear infinite;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  </style>
</head>
<body>

<div id="sidebar">
  <div class="header">
    <div class="header-badge">🌍 Worldwide 1 km Native Resolution</div>
    <h1>Global Metro Explorer</h1>
    <p>Topological Superlevel Set & Downhill Watershed Delineation (GHS-POP 2020)</p>
  </div>

  <div class="switcher-card">
    <div class="switcher-label-row">
      <span class="switcher-title">Delineation Threshold</span>
      <span class="switcher-current" id="switcher-desc">7% — Standard Metros</span>
    </div>
    <div class="level-btn-group">
      <button class="level-btn" onclick="selectLevel(1)" id="btn-lvl-1">
        <span class="level-btn-pct">1%</span>
        <span class="level-btn-desc">Macro</span>
      </button>
      <button class="level-btn" onclick="selectLevel(4)" id="btn-lvl-4">
        <span class="level-btn-pct">4%</span>
        <span class="level-btn-desc">Broad</span>
      </button>
      <button class="level-btn active" onclick="selectLevel(7)" id="btn-lvl-7">
        <span class="level-btn-pct">7%</span>
        <span class="level-btn-desc">Standard</span>
      </button>
      <button class="level-btn" onclick="selectLevel(15)" id="btn-lvl-15">
        <span class="level-btn-pct">15%</span>
        <span class="level-btn-desc">Tight</span>
      </button>
      <button class="level-btn" onclick="selectLevel(25)" id="btn-lvl-25">
        <span class="level-btn-pct">25%</span>
        <span class="level-btn-desc">Micro</span>
      </button>
    </div>
  </div>

  <div class="stats-row">
    <div class="stat-cell">
      <span class="stat-label">Active Metros</span>
      <span class="stat-number" id="stat-count">—</span>
    </div>
    <div class="stat-cell">
      <span class="stat-label">Pop Covered</span>
      <span class="stat-number" id="stat-pop">—</span>
    </div>
    <div class="stat-cell">
      <span class="stat-label">#1 Metro</span>
      <span class="stat-number" id="stat-top" style="font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">—</span>
    </div>
  </div>

  <div class="controls">
    <div class="search-box">
      <input type="text" class="search-input" id="search-box" placeholder="Search cities (e.g. Tokyo, Paris, Seattle, Tel Aviv)...">
    </div>
  </div>

  <div id="metro-list"></div>

  <div id="detail-panel">
    <div class="detail-header">
      <div class="detail-title">
        <span class="metro-dot" id="detail-dot"></span>
        <span id="detail-name">Select a Metro Area</span>
        <span class="metro-country" id="detail-country">GL</span>
      </div>
    </div>
    <div class="detail-grid">
      <div class="detail-cell">
        <span class="label">Global Rank</span>
        <span class="val" id="detail-rank">#—</span>
      </div>
      <div class="detail-cell">
        <span class="label">Total Population</span>
        <span class="val" id="detail-pop">—</span>
      </div>
      <div class="detail-cell">
        <span class="label">Total Area</span>
        <span class="val" id="detail-area">— km²</span>
      </div>
      <div class="detail-cell">
        <span class="label">Average Density</span>
        <span class="val" id="detail-density">— ppl/km²</span>
      </div>
      <div class="detail-cell">
        <span class="label">Peak Density</span>
        <span class="val" id="detail-peak-density">— ppl/km²</span>
      </div>
      <div class="detail-cell">
        <span class="label">Threshold Density</span>
        <span class="val" id="detail-threshold">— ppl/km²</span>
      </div>
    </div>
  </div>
</div>

<div id="map-container">
  <div class="basemap-picker">
    <button class="basemap-btn active" onclick="switchBasemap('dark', this)">Dark</button>
    <button class="basemap-btn" onclick="switchBasemap('satellite', this)">Satellite</button>
    <button class="basemap-btn" onclick="switchBasemap('osm', this)">OpenStreetMap</button>
    <button class="basemap-btn" onclick="switchBasemap('voyager', this)">Voyager</button>
  </div>
  <div id="map"></div>
  <div id="loading-toast">
    <div class="spinner"></div>
    <span id="toast-text">Rendering 1 km vector polygons...</span>
  </div>
</div>

<script>
// ============= Embedded Multi-Level Data =============
const LEVELS = {LEVELS};
const LEVEL_DESCS = {json.dumps(LEVEL_DESCS)};
const DEFAULT_LVL = {default_lvl};
const GEOJSON_DATA = {js_geojson_map};
const SUMMARIES = {js_summaries};

// ============= Golden-Ratio Stable Color Palette =============
function getMetroColor(id) {{
  const hue = ((id * 137.507764) % 360) / 360.0;
  const s = 0.85, v = 0.92;
  const c = v * s;
  const x = c * (1 - Math.abs(((hue * 6) % 2) - 1));
  const m = v - c;
  let r, g, b;
  const h6 = hue * 6;
  if (h6 < 1) {{ r=c; g=x; b=0; }}
  else if (h6 < 2) {{ r=x; g=c; b=0; }}
  else if (h6 < 3) {{ r=0; g=c; b=x; }}
  else if (h6 < 4) {{ r=0; g=x; b=c; }}
  else if (h6 < 5) {{ r=x; g=0; b=c; }}
  else {{ r=c; g=0; b=x; }}
  const R = Math.round((r + m) * 255);
  const G = Math.round((g + m) * 255);
  const B = Math.round((b + m) * 255);
  return '#' + ((1 << 24) + (R << 16) + (G << 8) + B).toString(16).slice(1);
}}

// ============= State =============
let currentLevel = DEFAULT_LVL;
let decompressedCache = {{}};
let vectorLayer = null;
let selectedFeature = null;

// ============= Map Setup =============
const map = L.map('map', {{
  center: [25.0, 15.0],
  zoom: 3,
  minZoom: 2,
  maxZoom: 18,
  zoomControl: true,
  preferCanvas: true
}});

const basemaps = {{
  dark: L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    attribution: '&copy; CARTO &copy; OpenStreetMap',
    subdomains: 'abcd',
    maxZoom: 18
  }}),
  satellite: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{x}}/{{y}}', {{
    attribution: 'Tiles &copy; Esri World Imagery',
    maxNativeZoom: 18,
    maxZoom: 18
  }}),
  osm: L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 18
  }}),
  voyager: L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    attribution: '&copy; CARTO &copy; OpenStreetMap',
    subdomains: 'abcd',
    maxZoom: 18
  }})
}};
basemaps.dark.addTo(map);

function switchBasemap(name, btn) {{
  document.querySelectorAll('.basemap-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  Object.values(basemaps).forEach(l => map.removeLayer(l));
  basemaps[name].addTo(map);
  if (vectorLayer) vectorLayer.bringToFront();
}}

// ============= Decompression & Rendering =============
const canvasRenderer = L.canvas({{ padding: 0.5 }});

function showToast(text) {{
  const toast = document.getElementById('loading-toast');
  document.getElementById('toast-text').innerText = text;
  toast.style.display = 'flex';
  toast.style.opacity = '1';
}}

function hideToast() {{
  const toast = document.getElementById('loading-toast');
  toast.style.opacity = '0';
  setTimeout(() => {{ toast.style.display = 'none'; }}, 200);
}}

function getGeoJSONForLevel(lvl) {{
  if (decompressedCache[lvl]) return decompressedCache[lvl];
  const b64 = GEOJSON_DATA[String(lvl)];
  if (!b64) return null;
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; ++i) u8[i] = bin.charCodeAt(i);
  const jsonStr = pako.inflate(u8, {{ to: 'string' }});
  const gj = JSON.parse(jsonStr);
  decompressedCache[lvl] = gj;
  return gj;
}}

function updateSidebarStats(lvl) {{
  const summary = SUMMARIES[String(lvl)];
  if (!summary) return;
  document.getElementById('stat-count').innerText = summary.total_count.toLocaleString();
  document.getElementById('stat-pop').innerText = (summary.total_pop / 1e9).toFixed(2) + 'B';
  const top1 = summary.top_metros[0];
  document.getElementById('stat-top').innerText = top1 ? (top1.n + ' (' + (top1.p/1e6).toFixed(1) + 'M)') : '—';
  document.getElementById('switcher-desc').innerText = lvl + '% — ' + LEVEL_DESCS[lvl];

  // Render top list
  renderMetroList(summary.top_metros);
}}

function renderMetroList(list) {{
  const container = document.getElementById('metro-list');
  container.innerHTML = '';
  const searchVal = document.getElementById('search-box').value.trim().toLowerCase();

  const filtered = searchVal
    ? list.filter(m => m.n.toLowerCase().includes(searchVal) || m.c.toLowerCase().includes(searchVal))
    : list.slice(0, 300);

  filtered.forEach(m => {{
    const el = document.createElement('div');
    el.className = 'metro-item';
    const color = getMetroColor(m.gr);
    el.innerHTML = `
      <span class="metro-rank">#${{m.gr}}</span>
      <span class="metro-dot" style="background:${{color}}"></span>
      <div class="metro-info">
        <div class="metro-name-row">
          <span class="metro-name">${{m.n}}</span>
          <span class="metro-country">${{m.c}}</span>
        </div>
      </div>
      <span class="metro-pop">${{(m.p >= 1e6 ? (m.p/1e6).toFixed(2) + 'M' : (m.p/1e3).toFixed(0) + 'k')}}</span>
    `;
    el.onclick = () => {{
      selectMetro(m);
      map.flyTo([m.la, m.lo], 10, {{ duration: 1.2 }});
    }};
    container.appendChild(el);
  }});
}}

function selectMetro(m) {{
  document.getElementById('detail-dot').style.background = getMetroColor(m.gr);
  document.getElementById('detail-name').innerText = m.n;
  document.getElementById('detail-country').innerText = m.c;
  document.getElementById('detail-rank').innerText = '#' + m.gr;
  document.getElementById('detail-pop').innerText = m.p.toLocaleString();
  document.getElementById('detail-area').innerText = m.a.toLocaleString() + ' km²';
  document.getElementById('detail-density').innerText = m.d.toLocaleString() + ' ppl/km²';
  document.getElementById('detail-peak-density').innerText = m.pd.toLocaleString() + ' ppl/km²';
  document.getElementById('detail-threshold').innerText = m.th.toLocaleString() + ' ppl/km²';
}}

function loadVectorLayer(lvl) {{
  showToast(`Rendering ${{lvl}}% vector layer...`);
  setTimeout(() => {{
    const gj = getGeoJSONForLevel(lvl);
    if (!gj) {{
      hideToast();
      return;
    }}

    if (vectorLayer) map.removeLayer(vectorLayer);

    vectorLayer = L.geoJSON(gj, {{
      renderer: canvasRenderer,
      style: function(feat) {{
        const color = getMetroColor(feat.properties.gr);
        return {{
          color: color,
          weight: 1.2,
          opacity: 0.9,
          fillColor: color,
          fillOpacity: 0.45
        }};
      }},
      onEachFeature: function(feat, layer) {{
        const p = feat.properties;
        layer.on('click', function(e) {{
          L.DomEvent.stopPropagation(e);
          selectMetro(p);
        }});
        layer.bindTooltip(`<strong>${{p.n}}</strong> (${{p.c}})<br>Pop: ${{p.p.toLocaleString()}}<br>Rank: #${{p.gr}}`, {{
          sticky: true,
          direction: 'auto'
        }});
      }}
    }}).addTo(map);

    updateSidebarStats(lvl);
    hideToast();
  }}, 20);
}}

function selectLevel(lvl) {{
  if (currentLevel === lvl) return;
  currentLevel = lvl;
  document.querySelectorAll('.level-btn').forEach(b => b.classList.remove('active'));
  const activeBtn = document.getElementById('btn-lvl-' + lvl);
  if (activeBtn) activeBtn.classList.add('active');
  loadVectorLayer(lvl);
}}

// Search Filter
document.getElementById('search-box').addEventListener('input', () => {{
  const summary = SUMMARIES[String(currentLevel)];
  if (summary) renderMetroList(summary.top_metros);
}});

// Initialize
window.addEventListener('load', () => {{
  loadVectorLayer(DEFAULT_LVL);
}});
</script>

</body>
</html>
"""

    out_desktop = "/Users/netanavot/Desktop/global_metro_map.html"
    out_local = "/Users/netanavot/metro_global/global_metro_map.html"

    with open(out_desktop, "w", encoding="utf-8") as fp:
        fp.write(html_content)
    with open(out_local, "w", encoding="utf-8") as fp:
        fp.write(html_content)

    print(f"\n========================================================")
    print(f"SUCCESS! Interactive Vector Map Created:")
    print(f"  -> {out_desktop} ({os.path.getsize(out_desktop)/(1024*1024):.1f} MB)")
    print(f"  -> {out_local} ({os.path.getsize(out_local)/(1024*1024):.1f} MB)")
    print(f"========================================================\n")

if __name__ == "__main__":
    vectorize_all_levels()
