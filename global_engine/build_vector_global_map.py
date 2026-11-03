#!/usr/bin/env python3
"""
Builds an interactive global metropolitan areas HTML map with TRUE VECTOR POLYGONS.
Eliminates all pixelation by extracting smooth GeoJSON vector contours for each threshold.
Enforces stable color palette keyed by Root_Peak_ID so cities never flicker or change color.
"""

import os
import sys
import shutil
import json
import csv
import time
import zlib
import base64
import numpy as np
import cv2

def vectorize_all_levels():
    t0 = time.time()
    with open("metadata.json") as f:
        meta = json.load(f)

    H, W = meta["rows"], meta["cols"]
    origin_lat = meta["origin_lat"]
    origin_lon = meta["origin_lon"]
    dlat = meta["pixel_size_lat"]
    dlon = meta["pixel_size_lon"]

    # Threshold levels to include in the interactive slider (1% to 20%)
    levels = list(range(1, 21))
    print(f"Vectorizing {len(levels)} threshold levels: {levels}")

    compressed_geojson_by_level = {}
    metro_summaries_by_level = {}

    for lvl in levels:
        t_lvl = time.time()
        bin_path = f"metro_ranks_{lvl:02d}.bin"
        csv_path = f"metro_areas_{lvl:02d}.csv"

        if not os.path.exists(bin_path) or not os.path.exists(csv_path):
            print(f"Skipping {lvl}%: {bin_path} not found")
            continue

        ranks = np.fromfile(bin_path, dtype=np.int32).reshape((H, W))

        # Load metro metadata
        meta_by_rank = {}
        top_list = []
        with open(csv_path, 'r', encoding='utf-8') as fp:
            for r in csv.DictReader(fp):
                rk = int(r['Rank'])
                info = {
                    'r': rk,
                    'pid': int(r['Root_Peak_ID']),
                    'n': r['Core_Name'],
                    'c': r['Country'],
                    'la': round(float(r['Peak_Latitude']), 2),
                    'lo': round(float(r['Peak_Longitude']), 2),
                    'p': int(float(r['Total_Population'])),
                    'a': int(float(r['Total_Area_sqkm'])),
                    'd': int(float(r['Avg_Density_ppl_km2'])),
                    'pd': int(float(r['Peak_Density'])),
                    'th': int(float(r['Threshold_Density']))
                }
                meta_by_rank[rk] = info
                if len(top_list) < 500:
                    top_list.append(info)

        metro_summaries_by_level[lvl] = {
            'total_count': len(meta_by_rank),
            'top_metros': top_list
        }

        # Vectorize using sorted nonzero run slicing
        nz_r, nz_c = np.nonzero(ranks)
        nz_ranks = ranks[nz_r, nz_c]

        sort_idx = np.argsort(nz_ranks)
        sorted_ranks = nz_ranks[sort_idx]
        sorted_r = nz_r[sort_idx]
        sorted_c = nz_c[sort_idx]

        change_idx = np.flatnonzero(np.diff(sorted_ranks)) + 1
        splits = np.concatenate(([0], change_idx, [len(sorted_ranks)]))

        total_metros = len(splits) - 1
        features = []

        # epsilon=1.3 at 2km → ~2.4km simplification, produces smooth organic curves without blockiness
        POLY_EPSILON = 1.3

        for i in range(total_metros):
            s = splits[i]
            e = splits[i+1]
            rank = int(sorted_ranks[s])
            m_info = meta_by_rank.get(rank)
            if not m_info:
                continue

            rs = sorted_r[s:e]
            cs = sorted_c[s:e]

            # Check if this metro wraps across the antimeridian
            is_wrapped = (cs.max() - cs.min()) > (W // 2)
            components = []
            if is_wrapped:
                m_left = cs < (W // 2)
                if np.any(m_left):
                    components.append((rs[m_left], cs[m_left]))
                m_right = ~m_left
                if np.any(m_right):
                    components.append((rs[m_right], cs[m_right]))
            else:
                components.append((rs, cs))

            poly_rings = []
            for sub_rs, sub_cs in components:
                r0, r1 = max(0, int(sub_rs.min()) - 1), min(H, int(sub_rs.max()) + 2)
                c0, c1 = max(0, int(sub_cs.min()) - 1), min(W, int(sub_cs.max()) + 2)

                sub = (ranks[r0:r1, c0:c1] == rank).astype(np.uint8)
                contours, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                for cnt in contours:
                    if cv2.contourArea(cnt) < 1.0:
                        continue
                    # Smooth approximation for crisp vector boundaries at 2km resolution
                    simp = cv2.approxPolyDP(cnt, epsilon=POLY_EPSILON, closed=True)
                    if len(simp) < 3:
                        continue
                    ring = []
                    for pt in simp:
                        col = c0 + pt[0][0]
                        row = r0 + pt[0][1]
                        lon = round(origin_lon + (col + 0.5) * dlon, 3)
                        lat = round(origin_lat - (row + 0.5) * dlat, 3)
                        ring.append([lon, lat])
                    if ring[0] != ring[-1]:
                        ring.append(ring[0])
                    poly_rings.append(ring)

            if not poly_rings:
                continue

            geom_type = 'Polygon' if len(poly_rings) == 1 else 'MultiPolygon'
            coords = [poly_rings[0]] if len(poly_rings) == 1 else [[r] for r in poly_rings]

            features.append({
                'type': 'Feature',
                'properties': m_info,
                'geometry': {'type': geom_type, 'coordinates': coords}
            })

        gj = {'type': 'FeatureCollection', 'features': features}
        raw_json = json.dumps(gj, separators=(',', ':'))
        compressed = zlib.compress(raw_json.encode('utf-8'), 9)
        b64 = base64.b64encode(compressed).decode('ascii')
        compressed_geojson_by_level[lvl] = b64

        print(f"  {lvl:02d}%: {len(features):,} vector metros, raw {len(raw_json)/(1024*1024):.2f} MB -> gzipped {len(compressed)/1024:.1f} KB in {time.time()-t_lvl:.2f}s")

    print(f"\nAll levels vectorized in {time.time()-t0:.2f}s!")
    build_html(levels, compressed_geojson_by_level, metro_summaries_by_level)

def build_html(levels, geojson_data, summaries):
    t0 = time.time()
    js_geojson_map = json.dumps({str(k): v for k, v in geojson_data.items()})
    js_summaries = json.dumps({str(k): v for k, v in summaries.items()})
    js_levels = json.dumps(levels)
    default_lvl = 7 if 7 in levels else levels[len(levels)//2]

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Worldwide Metropolitan Areas — True Vector Hierarchy</title>

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
      background: #090d16;
      overflow: hidden;
      display: flex;
      height: 100vh;
      width: 100vw;
    }}
    #sidebar {{
      width: 440px;
      height: 100vh;
      background: #ffffff;
      border-right: 1px solid #e2e8f0;
      display: flex;
      flex-direction: column;
      z-index: 1000;
      box-shadow: 4px 0 24px rgba(0,0,0,0.12);
      flex-shrink: 0;
    }}
    #map-container {{
      flex: 1;
      height: 100vh;
      position: relative;
    }}
    #map {{
      width: 100%;
      height: 100%;
      background: #090d16;
    }}

    /* Header */
    .header {{
      padding: 18px 22px 14px;
      background: #090d16;
      color: #ffffff;
      border-bottom: 1px solid #1e293b;
    }}
    .header-badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
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

    /* Interactive Slider Card */
    .slider-card {{
      padding: 16px 22px;
      background: #f8fafc;
      border-bottom: 1px solid #e2e8f0;
    }}
    .slider-title-row {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 8px;
    }}
    .slider-label {{
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.6px;
      color: #475569;
    }}
    .slider-val {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 26px;
      font-weight: 800;
      color: #0284c7;
    }}
    .slider-val span {{
      font-size: 14px;
      color: #64748b;
    }}
    .range-input-wrapper {{
      position: relative;
      margin: 8px 0 6px;
    }}
    input[type=range] {{
      -webkit-appearance: none;
      width: 100%;
      height: 8px;
      border-radius: 4px;
      background: #cbd5e1;
      outline: none;
      cursor: pointer;
    }}
    input[type=range]::-webkit-slider-thumb {{
      -webkit-appearance: none;
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background: #0284c7;
      border: 3px solid #ffffff;
      box-shadow: 0 2px 8px rgba(2, 132, 199, 0.45);
      cursor: pointer;
      transition: transform 0.1s, box-shadow 0.1s;
    }}
    input[type=range]::-webkit-slider-thumb:hover {{
      transform: scale(1.18);
      box-shadow: 0 4px 12px rgba(2, 132, 199, 0.6);
    }}
    .slider-ticks {{
      display: flex;
      justify-content: space-between;
      font-family: 'JetBrains Mono', monospace;
      font-size: 10px;
      color: #94a3b8;
      padding: 0 2px;
    }}

    /* Global Summary Stats */
    .stats-row {{
      display: grid;
      grid-template-columns: 1fr 1fr 1.2fr;
      gap: 10px;
      padding: 12px 22px;
      background: #ffffff;
      border-bottom: 1px solid #e2e8f0;
    }}
    .stat-cell {{
      display: flex;
      flex-direction: column;
    }}
    .stat-label {{
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: #64748b;
      margin-bottom: 2px;
    }}
    .stat-number {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 15px;
      font-weight: 700;
      color: #0f172a;
    }}

    /* Search & Filter */
    .controls {{
      padding: 12px 22px;
      background: #f8fafc;
      border-bottom: 1px solid #e2e8f0;
      display: flex;
      gap: 10px;
    }}
    .search-box {{
      flex: 1;
      position: relative;
    }}
    .search-input {{
      width: 100%;
      padding: 9px 12px 9px 34px;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      font-size: 12.5px;
      font-family: inherit;
      outline: none;
      background: #ffffff url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='8'%3E%3C/circle%3E%3Cline x1='21' y1='21' x2='16.65' y2='16.65'%3E%3C/line%3E%3C/svg%3E") 10px center no-repeat;
      transition: border-color 0.15s, box-shadow 0.15s;
    }}
    .search-input:focus {{
      border-color: #0284c7;
      box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.15);
    }}

    /* Metro List */
    #metro-list {{
      flex: 1;
      overflow-y: auto;
      background: #ffffff;
    }}
    .metro-item {{
      padding: 10px 22px;
      border-bottom: 1px solid #f1f5f9;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 12px;
      transition: background 0.12s;
    }}
    .metro-item:hover {{
      background: #f0f9ff;
    }}
    .metro-item.active {{
      background: #e0f2fe;
      border-left: 4px solid #0284c7;
    }}
    .metro-rank-badge {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      font-weight: 700;
      color: #64748b;
      min-width: 32px;
    }}
    .metro-color-dot {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
      border: 1.5px solid rgba(0,0,0,0.15);
      flex-shrink: 0;
    }}
    .metro-info-col {{
      flex: 1;
      min-width: 0;
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
      display: inline-block;
      font-size: 10px;
      font-weight: 700;
      color: #475569;
      background: #e2e8f0;
      padding: 1px 5px;
      border-radius: 4px;
      margin-left: 6px;
    }}
    .metro-sub {{
      font-size: 11px;
      color: #64748b;
      margin-top: 2px;
      display: flex;
      gap: 10px;
    }}
    .metro-sub b {{
      color: #334155;
    }}

    /* Detail Inspector Panel */
    #detail-panel {{
      padding: 16px 22px;
      background: #f8fafc;
      border-top: 2px solid #0284c7;
      display: none;
      animation: slideUp 0.15s ease-out;
    }}
    @keyframes slideUp {{
      from {{ transform: translateY(10px); opacity: 0; }}
      to {{ transform: translateY(0); opacity: 1; }}
    }}
    .detail-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
    }}
    .detail-title {{
      font-size: 16px;
      font-weight: 800;
      color: #0f172a;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .detail-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px 14px;
    }}
    .detail-cell {{
      display: flex;
      flex-direction: column;
    }}
    .detail-cell .label {{
      font-size: 9.5px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: #64748b;
    }}
    .detail-cell .val {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 12.5px;
      font-weight: 700;
      color: #0f172a;
    }}

    /* Floating Basemap Switcher */
    .basemap-picker {{
      position: absolute;
      top: 14px;
      right: 14px;
      z-index: 1000;
      background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 8px;
      padding: 6px;
      display: flex;
      gap: 4px;
    }}
    .basemap-btn {{
      padding: 5px 10px;
      font-size: 11px;
      font-weight: 600;
      color: #94a3b8;
      background: transparent;
      border: none;
      border-radius: 5px;
      cursor: pointer;
      transition: all 0.15s;
    }}
    .basemap-btn.active {{
      background: #0284c7;
      color: #ffffff;
    }}

    /* Loading Toast */
    #loading-toast {{
      position: absolute;
      bottom: 24px;
      right: 24px;
      z-index: 1000;
      background: rgba(15, 23, 42, 0.92);
      backdrop-filter: blur(10px);
      color: #ffffff;
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
    <div class="header-badge">🌍 Worldwide Vector Hierarchy</div>
    <h1>Global Metro Explorer</h1>
    <p>Topological Superlevel Set & Downhill Watershed Delineation (WorldPop / GHS-POP 2020)</p>
  </div>

  <div class="slider-card">
    <div class="slider-title-row">
      <div class="slider-label">Core P95 Cutoff Threshold</div>
      <div class="slider-val" id="thresh-val">{default_lvl}<span>%</span></div>
    </div>
    <div class="range-input-wrapper">
      <input type="range" id="thresh-slider" min="0" max="{len(levels)-1}" value="{levels.index(default_lvl)}" step="1">
    </div>
    <div class="slider-ticks">
      <span>{levels[0]}% (Macro)</span>
      <span>10%</span>
      <span>{levels[-1]}% (Micro)</span>
    </div>
  </div>

  <div class="stats-row">
    <div class="stat-cell">
      <span class="stat-label">Metro Areas</span>
      <span class="stat-number" id="stat-count">—</span>
    </div>
    <div class="stat-cell">
      <span class="stat-label">Pop Covered</span>
      <span class="stat-number" id="stat-pop">—</span>
    </div>
    <div class="stat-cell">
      <span class="stat-label">#1 Metro</span>
      <span class="stat-number" id="stat-top" style="font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">—</span>
    </div>
  </div>

  <div class="controls">
    <div class="search-box">
      <input type="text" class="search-input" id="search-box" placeholder="Search cities (e.g. Tokyo, Paris, New York)...">
    </div>
  </div>

  <div id="metro-list"></div>

  <div id="detail-panel">
    <div class="detail-header">
      <div class="detail-title">
        <span class="metro-color-dot" id="detail-dot"></span>
        <span id="detail-name">City Name</span>
        <span class="metro-country" id="detail-country">US</span>
      </div>
    </div>
    <div class="detail-grid">
      <div class="detail-cell">
        <span class="label">Rank</span>
        <span class="val" id="detail-rank">#1</span>
      </div>
      <div class="detail-cell">
        <span class="label">Total Population</span>
        <span class="val" id="detail-pop">0</span>
      </div>
      <div class="detail-cell">
        <span class="label">Total Area</span>
        <span class="val" id="detail-area">0 km²</span>
      </div>
      <div class="detail-cell">
        <span class="label">Average Density</span>
        <span class="val" id="detail-density">0 ppl/km²</span>
      </div>
      <div class="detail-cell">
        <span class="label">Peak Density</span>
        <span class="val" id="detail-peak-density">0 ppl/km²</span>
      </div>
      <div class="detail-cell">
        <span class="label">Cutoff Threshold</span>
        <span class="val" id="detail-threshold">0 ppl/km²</span>
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
    <span id="toast-text">Rendering vector polygons...</span>
  </div>
</div>

<script>
// ============= Configuration =============
const LEVELS = {js_levels};
const DEFAULT_LVL = {default_lvl};
const GEOJSON_DATA = {js_geojson_map};
const SUMMARIES = {js_summaries};

// ============= Stable Color Palette Keyed to Root_Peak_ID =============
function getPeakColor(pid) {{
  const hue = ((pid * 137.507764) % 360) / 360.0;
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
let currentGeoJSON = null;
let decompressedCache = {{}};
let vectorLayer = null;
let selectedFeature = null;

// ============= Map Setup =============
const map = L.map('map', {{
  center: [25.0, 15.0],
  zoom: 3,
  minZoom: 2,
  maxZoom: 18,
  zoomControl: true
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

function switchBasemap(type, btn) {{
  document.querySelectorAll('.basemap-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  for (const k in basemaps) {{
    if (map.hasLayer(basemaps[k])) {{
      map.removeLayer(basemaps[k]);
    }}
  }}
  basemaps[type].addTo(map);
  if (vectorLayer && typeof vectorLayer.bringToFront === 'function') {{
    vectorLayer.bringToFront();
  }}
}}

// ============= High-Speed Decompressor =============
function getDecompressedGeoJSON(lvl) {{
  if (decompressedCache[lvl]) return decompressedCache[lvl];
  const b64 = GEOJSON_DATA[String(lvl)];
  if (!b64) return null;
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  const decomp = pako.inflate(u8, {{ to: 'string' }});
  const parsed = JSON.parse(decomp);
  // Sort features by area descending so smaller child metros are drawn on top and clickable!
  parsed.features.sort((a, b) => (b.properties.a || 0) - (a.properties.a || 0));
  decompressedCache[lvl] = parsed;
  return parsed;
}}

// ============= Style Function =============
function getFeatureStyle(feature) {{
  const isSelected = selectedFeature && selectedFeature.properties.r === feature.properties.r;
  const color = getPeakColor(feature.properties.pid);
  return {{
    fillColor: color,
    weight: isSelected ? 2.5 : 1.0,
    opacity: isSelected ? 1.0 : 0.7,
    color: isSelected ? '#ffffff' : 'rgba(255, 255, 255, 0.45)',
    fillOpacity: isSelected ? 0.85 : 0.62
  }};
}}

// ============= Select & Inspect Metro =============
function inspectFeature(props, flyTo = false) {{
  selectedFeature = {{ properties: props }};
  const color = getPeakColor(props.pid);

  document.getElementById('detail-panel').style.display = 'block';
  document.getElementById('detail-dot').style.background = color;
  document.getElementById('detail-name').textContent = props.n;
  document.getElementById('detail-country').textContent = props.c || '--';
  document.getElementById('detail-rank').textContent = '#' + props.r;
  document.getElementById('detail-pop').textContent = props.p.toLocaleString();
  document.getElementById('detail-area').textContent = props.a.toLocaleString() + ' km²';
  document.getElementById('detail-density').textContent = props.d.toLocaleString() + ' ppl/km²';
  document.getElementById('detail-peak-density').textContent = props.pd.toLocaleString() + ' ppl/km²';
  document.getElementById('detail-threshold').textContent = props.th.toLocaleString() + ' ppl/km²';

  document.querySelectorAll('.metro-item').forEach(el => el.classList.remove('active'));
  const listItem = document.getElementById('item-' + props.r);
  if (listItem) {{
    listItem.classList.add('active');
    listItem.scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
  }}

  if (flyTo) {{
    map.flyTo([props.la, props.lo], Math.max(map.getZoom(), 8), {{ duration: 0.8 }});
  }}

  if (vectorLayer) {{
    vectorLayer.setStyle(getFeatureStyle);
  }}
}}

// ============= Render Sidebar List =============
function renderSidebarList(filterText = '') {{
  const listEl = document.getElementById('metro-list');
  const summary = SUMMARIES[String(currentLevel)];
  if (!summary) return;

  const query = filterText.toLowerCase().trim();
  let items = summary.top_metros;
  if (query) {{
    items = items.filter(m => m.n.toLowerCase().includes(query) || (m.c && m.c.toLowerCase().includes(query)));
  }}

  let html = '';
  for (let i = 0; i < Math.min(items.length, 250); i++) {{
    const m = items[i];
    const color = getPeakColor(m.pid);
    const isActive = (selectedFeature && selectedFeature.properties.r === m.r) ? ' active' : '';

    html += `<div class="metro-item${{isActive}}" id="item-${{m.r}}" onclick='inspectFeature(${{JSON.stringify(m)}}, true)'>
      <div class="metro-rank-badge">#${{m.r}}</div>
      <div class="metro-color-dot" style="background:${{color}}"></div>
      <div class="metro-info-col">
        <div class="metro-name">${{m.n}}<span class="metro-country">${{m.c || '--'}}</span></div>
        <div class="metro-sub">
          <span>Pop: <b>${{m.p.toLocaleString()}}</b></span>
          <span>Area: <b>${{m.a.toLocaleString()}} km²</b></span>
        </div>
      </div>
    </div>`;
  }}
  listEl.innerHTML = html;
}}

// ============= Threshold Switcher =============
function setLevel(lvl) {{
  currentLevel = lvl;
  document.getElementById('thresh-val').innerHTML = lvl + '<span>%</span>';

  const toast = document.getElementById('loading-toast');
  toast.style.opacity = '1';
  document.getElementById('toast-text').textContent = `Rendering ${{lvl}}% vector hierarchy...`;

  setTimeout(() => {{
    const gj = getDecompressedGeoJSON(lvl);
    if (!gj) return;

    if (vectorLayer) {{
      map.removeLayer(vectorLayer);
    }}

    vectorLayer = L.geoJSON(gj, {{
      renderer: L.canvas({{ padding: 0.5 }}),
      style: getFeatureStyle,
      onEachFeature: function(feature, layer) {{
        layer.on('click', function(e) {{
          L.DomEvent.stopPropagation(e);
          inspectFeature(feature.properties, false);
        }});
        layer.on('mouseover', function() {{
          if (!selectedFeature || selectedFeature.properties.r !== feature.properties.r) {{
            layer.setStyle({{ weight: 2.0, color: '#ffffff', fillOpacity: 0.8 }});
          }}
        }});
        layer.on('mouseout', function() {{
          if (!selectedFeature || selectedFeature.properties.r !== feature.properties.r) {{
            vectorLayer.resetStyle(layer);
          }}
        }});
      }}
    }}).addTo(map);

    // Update Summary Header
    const summary = SUMMARIES[String(lvl)];
    if (summary) {{
      document.getElementById('stat-count').textContent = summary.total_count.toLocaleString();
      let totalPop = 0;
      for (const m of summary.top_metros) totalPop += m.p;
      document.getElementById('stat-pop').textContent = (totalPop / 1e9).toFixed(2) + 'B+';
      document.getElementById('stat-top').textContent = summary.top_metros.length ? summary.top_metros[0].n : '--';
    }}

    renderSidebarList(document.getElementById('search-box').value);

    setTimeout(() => {{ toast.style.opacity = '0'; }}, 200);
  }}, 15);
}}

// ============= App Initialization =============
document.addEventListener('DOMContentLoaded', () => {{
  setLevel(DEFAULT_LVL);

  const slider = document.getElementById('thresh-slider');
  slider.addEventListener('input', (e) => {{
    const idx = parseInt(e.target.value);
    const lvl = LEVELS[idx];
    document.getElementById('thresh-val').innerHTML = lvl + '<span>%</span>';
  }});
  slider.addEventListener('change', (e) => {{
    const idx = parseInt(e.target.value);
    const lvl = LEVELS[idx];
    setLevel(lvl);
  }});

  document.getElementById('search-box').addEventListener('input', (e) => {{
    renderSidebarList(e.target.value);
  }});

  map.on('click', () => {{
    selectedFeature = null;
    document.getElementById('detail-panel').style.display = 'none';
    document.querySelectorAll('.metro-item').forEach(el => el.classList.remove('active'));
    if (vectorLayer) vectorLayer.setStyle(getFeatureStyle);
  }});
}});
</script>
</body>
</html>"""

    out_file = "global_metro_map.html"
    print(f"Writing {out_file}...")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    size_mb = os.path.getsize(out_file) / (1024 * 1024)
    print(f"Successfully generated TRUE VECTOR {out_file} ({size_mb:.2f} MB) in {time.time()-t0:.2f}s!")

    desktop_path = "/Users/netanavot/Desktop/global_metro_map.html"
    shutil.copyfile(out_file, desktop_path)
    print(f"Deployed map to {desktop_path}")

if __name__ == "__main__":
    vectorize_all_levels()
