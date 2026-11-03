#!/usr/bin/env python3
"""
Builds an interactive global metropolitan areas HTML map with a threshold slider.
- Pre-computed 1% to 20% multi-threshold surfaces
- High-performance Canvas tile rendering on Leaflet
- Compact RLE + zlib raster encoding
- Real-time client-side decompression and threshold switching
"""

import os
import sys
import json
import csv
import time
import zlib
import base64
import numpy as np

def fast_compress_rle(ranks):
    """Vectorized RLE using numpy with 16-bit run splitting, then zlib."""
    flat = ranks.ravel()
    diffs = np.diff(flat)
    change_indices = np.flatnonzero(diffs) + 1
    starts = np.concatenate(([0], change_indices))
    ends = np.concatenate((change_indices, [len(flat)]))
    counts = ends - starts
    values = flat[starts]

    out_vals = []
    out_counts = []
    for v, c in zip(values, counts):
        while c > 65535:
            out_vals.append(v)
            out_counts.append(65535)
            c -= 65535
        out_vals.append(v)
        out_counts.append(c)

    vals_arr = np.array(out_vals, dtype=np.int16)
    counts_arr = np.array(out_counts, dtype=np.uint16)

    interleaved = np.empty((len(vals_arr) * 2,), dtype=np.int16)
    interleaved[0::2] = vals_arr
    interleaved[1::2] = counts_arr.view(np.int16)

    comp = zlib.compress(interleaved.tobytes(), 6)
    return base64.b64encode(comp).decode('ascii')

def load_metro_csv(csv_path, max_count=5000):
    metros = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= max_count:
                break
            metros.append([
                int(row['Rank']),
                row['Core_Name'],
                row.get('Country', ''),
                round(float(row['Peak_Latitude']), 2),
                round(float(row['Peak_Longitude']), 2),
                int(float(row['Total_Population'])),
                int(float(row['Total_Area_sqkm'])),
                int(float(row['Avg_Density_ppl_km2'])),
                int(float(row['Peak_Density'])),
                int(float(row['Threshold_Density'])),
                int(row.get('Absorbed_Peaks_Count', 0))
            ])
    return metros

def build_map():
    t0 = time.time()
    with open("metadata.json") as f:
        meta = json.load(f)

    rows = meta["rows"]
    cols = meta["cols"]
    origin_lat = meta["origin_lat"]
    origin_lon = meta["origin_lon"]
    dlat = meta["pixel_size_lat"]
    dlon = meta["pixel_size_lon"]

    print(f"Grid: {rows} rows x {cols} cols ({rows * cols:,} cells)")

    threshold_files = {}
    for fname in sorted(os.listdir('.')):
        if fname.startswith('metro_ranks_') and fname.endswith('.bin'):
            pct = int(fname.replace('metro_ranks_', '').replace('.bin', ''))
            csv_name = f'metro_areas_{pct:02d}.csv'
            if os.path.exists(csv_name):
                threshold_files[pct] = (fname, csv_name)

    if not threshold_files:
        print("No metro_ranks_XX.bin files found.")
        sys.exit(1)

    thresholds = sorted(threshold_files.keys())
    print(f"Processing {len(thresholds)} threshold levels: {thresholds}")

    all_raster_data = {}
    all_metro_data = {}

    for pct in thresholds:
        ranks_file, csv_file = threshold_files[pct]
        t_sub = time.time()
        ranks = np.fromfile(ranks_file, dtype=np.int16).reshape((rows, cols))
        comp_b64 = fast_compress_rle(ranks)
        all_raster_data[pct] = comp_b64

        metros = load_metro_csv(csv_file, max_count=5000)
        all_metro_data[pct] = metros
        print(f"  {pct:02d}%: {len(metros):,} metros loaded, raster compressed to {len(comp_b64)//1024:,} KB ({time.time()-t_sub:.2f}s)")

    js_raster_data = json.dumps({str(k): v for k, v in all_raster_data.items()})
    js_metro_data = json.dumps({str(k): v for k, v in all_metro_data.items()})
    thresh_list_js = json.dumps(thresholds)

    thresh_min = min(thresholds)
    thresh_max = max(thresholds)
    thresh_default = 7 if 7 in thresholds else thresholds[len(thresholds)//2]

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Global Metropolitan Areas Explorer — Interactive Threshold</title>

  <!-- Leaflet CSS & JS -->
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <!-- Pako (High-speed zlib decompression in JS) -->
  <script src="https://cdnjs.cloudflare.com/ajax/libs/pako/2.1.0/pako.min.js"></script>

  <!-- Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">

  <style>
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    body {{
      font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
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

    /* Slider Section */
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
      font-size: 24px;
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

    /* Floating Map Tooltip & Basemap selector */
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

    /* Loading Spinner */
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
    <div class="header-badge">🌍 Worldwide Metropolitan Engine</div>
    <h1>Global Metro Explorer</h1>
    <p>Topological Superlevel Set & Downhill Watershed Delineation (WorldPop / GHS-POP 2020)</p>
  </div>

  <div class="slider-card">
    <div class="slider-title-row">
      <div class="slider-label">Core P95 Cutoff Threshold</div>
      <div class="slider-val" id="thresh-val">{thresh_default}<span>%</span></div>
    </div>
    <div class="range-input-wrapper">
      <input type="range" id="thresh-slider" min="{thresh_min}" max="{thresh_max}" value="{thresh_default}" step="1">
    </div>
    <div class="slider-ticks">
      <span>{thresh_min}% (Macro)</span>
      <span>10%</span>
      <span>{thresh_max}% (Micro)</span>
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
    <button class="basemap-btn active" onclick="switchBasemap('dark')">Dark</button>
    <button class="basemap-btn" onclick="switchBasemap('satellite')">Satellite</button>
    <button class="basemap-btn" onclick="switchBasemap('voyager')">Voyager</button>
  </div>
  <div id="map"></div>
  <div id="loading-toast">
    <div class="spinner"></div>
    <span id="toast-text">Rendering global metros...</span>
  </div>
</div>

<script>
// ============= Configuration =============
const GRID_ROWS = {rows};
const GRID_COLS = {cols};
const ORIGIN_LAT = {origin_lat};
const ORIGIN_LON = {origin_lon};
const DLAT = {dlat};
const DLON = {dlon};
const THRESHOLDS = {thresh_list_js};
const DEFAULT_THRESH = {thresh_default};

// ============= Embedded Multi-Threshold Data =============
const RASTER_DATA = {js_raster_data};
const METRO_DATA = {js_metro_data};

// ============= Precomputed Fast Golden-Ratio Palette =============
const PALETTE_SIZE = 16384;
const paletteR = new Uint8Array(PALETTE_SIZE);
const paletteG = new Uint8Array(PALETTE_SIZE);
const paletteB = new Uint8Array(PALETTE_SIZE);
const hexPalette = [];

for (let i = 0; i < PALETTE_SIZE; i++) {{
  const hue = ((i * 137.507764) % 360) / 360.0;
  const s = 0.82, v = 0.90;
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
  paletteR[i] = R;
  paletteG[i] = G;
  paletteB[i] = B;
  hexPalette[i] = '#' + ((1 << 24) + (R << 16) + (G << 8) + B).toString(16).slice(1);
}}

// ============= State =============
let currentThreshold = DEFAULT_THRESH;
let currentRanks = null;
let currentMetros = [];
let rankToMetro = new Map();
let decodedRasters = {{}};
let selectedRank = -1;
let metroOverlay = null;

// ============= High-Speed Raster Decompressor =============
function decompressRaster(b64) {{
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);

  const inflated = pako.inflate(u8);
  const int16View = new Int16Array(inflated.buffer, inflated.byteOffset, inflated.byteLength / 2);
  const uint16View = new Uint16Array(inflated.buffer, inflated.byteOffset, inflated.byteLength / 2);

  const totalCells = GRID_ROWS * GRID_COLS;
  const out = new Uint16Array(totalCells);

  let outIdx = 0;
  const numPairs = int16View.length / 2;
  for (let p = 0; p < numPairs && outIdx < totalCells; p++) {{
    const val = int16View[p * 2];
    const count = uint16View[p * 2 + 1];
    const uval = (val < 0) ? 0 : val;
    for (let c = 0; c < count && outIdx < totalCells; c++) {{
      out[outIdx++] = uval;
    }}
  }}
  return out;
}}

// ============= Map Setup =============
const map = L.map('map', {{
  center: [25.0, 15.0],
  zoom: 3,
  minZoom: 2,
  maxZoom: 13,
  zoomSnap: 0.5,
  worldCopyJump: true
}});

const basemaps = {{
  dark: L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    attribution: '&copy; CARTO &copy; OpenStreetMap',
    subdomains: 'abcd',
    maxZoom: 19
  }}),
  satellite: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
    attribution: 'Tiles &copy; Esri',
    maxZoom: 19
  }}),
  voyager: L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    attribution: '&copy; CARTO &copy; OpenStreetMap',
    subdomains: 'abcd',
    maxZoom: 19
  }})
}};
basemaps.dark.addTo(map);

function switchBasemap(type) {{
  document.querySelectorAll('.basemap-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  for (const k in basemaps) map.removeLayer(basemaps[k]);
  basemaps[type].addTo(map);
  if (metroOverlay) metroOverlay.bringToFront();
}}

// ============= Ultra-Fast Canvas Grid Layer =============
const MetroTileLayer = L.GridLayer.extend({{
  createTile: function(coords) {{
    const tile = document.createElement('canvas');
    const tileSize = this.getTileSize();
    tile.width = tileSize.x;
    tile.height = tileSize.y;

    if (!currentRanks) return tile;

    const ctx = tile.getContext('2d');
    const imgData = ctx.createImageData(tileSize.x, tileSize.y);
    const data = imgData.data;

    const z = coords.z;
    const tileX = coords.x;
    const tileY = coords.y;
    const n = Math.pow(2, z);

    // Precompute lat/lon to raster rows/cols once per row & column
    const tile_rows = new Int32Array(tileSize.y);
    for (let py = 0; py < tileSize.y; py++) {{
      const mapY = (tileY + (py + 0.5) / tileSize.y) / n;
      if (mapY < 0.0 || mapY >= 1.0) {{
        tile_rows[py] = -1;
        continue;
      }}
      const latRad = Math.atan(Math.sinh(Math.PI * (1.0 - 2.0 * mapY)));
      const lat = latRad * 180.0 / Math.PI;
      const row = Math.floor((ORIGIN_LAT - lat) / DLAT);
      tile_rows[py] = (row >= 0 && row < GRID_ROWS) ? row : -1;
    }}

    const tile_cols = new Int32Array(tileSize.x);
    for (let px = 0; px < tileSize.x; px++) {{
      let mapX = (tileX + (px + 0.5) / tileSize.x) / n;
      mapX = mapX - Math.floor(mapX);
      const lon = mapX * 360.0 - 180.0;
      let col = Math.floor((lon - ORIGIN_LON) / DLON);
      while (col < 0) col += GRID_COLS;
      while (col >= GRID_COLS) col -= GRID_COLS;
      tile_cols[px] = col;
    }}

    let hasAnyPixel = false;
    for (let py = 0; py < tileSize.y; py++) {{
      const r = tile_rows[py];
      if (r < 0) continue;
      const row_offset = r * GRID_COLS;
      const py_offset = py * tileSize.x;

      for (let px = 0; px < tileSize.x; px++) {{
        const c = tile_cols[px];
        const rank = currentRanks[row_offset + c];
        if (rank > 0) {{
          const pIdx = (py_offset + px) * 4;
          const palIdx = rank % PALETTE_SIZE;
          data[pIdx]     = paletteR[palIdx];
          data[pIdx + 1] = paletteG[palIdx];
          data[pIdx + 2] = paletteB[palIdx];
          data[pIdx + 3] = (rank === selectedRank) ? 245 : 160;
          hasAnyPixel = true;
        }}
      }}
    }}

    if (hasAnyPixel) {{
      ctx.putImageData(imgData, 0, 0);
    }}
    return tile;
  }}
}});

// ============= Map Click Interaction =============
map.on('click', function(e) {{
  if (!currentRanks || !currentMetros) return;
  const lat = e.latlng.lat;
  let lon = e.latlng.lng;
  while (lon > 180.0) lon -= 360.0;
  while (lon < -180.0) lon += 360.0;

  const row = Math.floor((ORIGIN_LAT - lat) / DLAT);
  let col = Math.floor((lon - ORIGIN_LON) / DLON);
  while (col < 0) col += GRID_COLS;
  while (col >= GRID_COLS) col -= GRID_COLS;

  if (row < 0 || row >= GRID_ROWS) return;

  const rank = currentRanks[row * GRID_COLS + col];
  if (rank > 0) {{
    selectMetro(rank, false);
  }} else {{
    selectedRank = -1;
    document.getElementById('detail-panel').style.display = 'none';
    document.querySelectorAll('.metro-item').forEach(el => el.classList.remove('active'));
    metroOverlay.redraw();
  }}
}});

// ============= Select & Inspect Metro =============
function selectMetro(rank, flyTo = true) {{
  selectedRank = rank;
  const m = rankToMetro.get(rank);

  document.querySelectorAll('.metro-item').forEach(el => el.classList.remove('active'));
  const listItem = document.getElementById('item-' + rank);
  if (listItem) {{
    listItem.classList.add('active');
    listItem.scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
  }}

  if (m) {{
    document.getElementById('detail-panel').style.display = 'block';
    document.getElementById('detail-dot').style.background = hexPalette[rank % PALETTE_SIZE];
    document.getElementById('detail-name').textContent = m[1];
    document.getElementById('detail-country').textContent = m[2] || '--';
    document.getElementById('detail-rank').textContent = '#' + m[0];
    document.getElementById('detail-pop').textContent = m[5].toLocaleString();
    document.getElementById('detail-area').textContent = m[6].toLocaleString() + ' km²';
    document.getElementById('detail-density').textContent = m[7].toLocaleString() + ' ppl/km²';
    document.getElementById('detail-peak-density').textContent = m[8].toLocaleString() + ' ppl/km²';
    document.getElementById('detail-threshold').textContent = m[9].toLocaleString() + ' ppl/km²';

    if (flyTo) {{
      map.flyTo([m[3], m[4]], Math.max(map.getZoom(), 8), {{ duration: 1.0 }});
    }}
  }} else {{
    document.getElementById('detail-panel').style.display = 'block';
    document.getElementById('detail-dot').style.background = hexPalette[rank % PALETTE_SIZE];
    document.getElementById('detail-name').textContent = 'Metro Area #' + rank;
    document.getElementById('detail-country').textContent = '--';
    document.getElementById('detail-rank').textContent = '#' + rank;
    document.getElementById('detail-pop').textContent = 'N/A';
    document.getElementById('detail-area').textContent = 'N/A';
    document.getElementById('detail-density').textContent = 'N/A';
    document.getElementById('detail-peak-density').textContent = 'N/A';
    document.getElementById('detail-threshold').textContent = 'N/A';
  }}

  metroOverlay.redraw();
}}

// ============= Render Metro Sidebar List =============
function renderMetroList(filterText = '') {{
  const listEl = document.getElementById('metro-list');
  const query = filterText.toLowerCase().trim();

  let filtered = currentMetros;
  if (query) {{
    filtered = currentMetros.filter(m =>
      m[1].toLowerCase().includes(query) || (m[2] && m[2].toLowerCase().includes(query))
    );
  }} else {{
    filtered = currentMetros.slice(0, 300);
  }}

  let html = '';
  for (let i = 0; i < filtered.length; i++) {{
    const m = filtered[i];
    const rank = m[0];
    const color = hexPalette[rank % PALETTE_SIZE];
    const isActive = (rank === selectedRank) ? ' active' : '';

    html += `<div class="metro-item${{isActive}}" id="item-${{rank}}" onclick="selectMetro(${{rank}}, true)">
      <div class="metro-rank-badge">#${{rank}}</div>
      <div class="metro-color-dot" style="background:${{color}}"></div>
      <div class="metro-info-col">
        <div class="metro-name">${{m[1]}}<span class="metro-country">${{m[2] || '--'}}</span></div>
        <div class="metro-sub">
          <span>Pop: <b>${{m[5].toLocaleString()}}</b></span>
          <span>Area: <b>${{m[6].toLocaleString()}} km²</b></span>
        </div>
      </div>
    </div>`;
  }}
  listEl.innerHTML = html;
}}

// ============= Threshold Switch Handler =============
function setThreshold(pct) {{
  currentThreshold = pct;
  document.getElementById('thresh-val').innerHTML = pct + '<span>%</span>';
  document.getElementById('thresh-slider').value = pct;

  const toast = document.getElementById('loading-toast');
  toast.style.opacity = '1';
  document.getElementById('toast-text').textContent = `Calculating ${{pct}}% threshold...`;

  setTimeout(() => {{
    if (!decodedRasters[pct]) {{
      decodedRasters[pct] = decompressRaster(RASTER_DATA[String(pct)]);
    }}
    currentRanks = decodedRasters[pct];
    currentMetros = METRO_DATA[String(pct)] || [];

    rankToMetro.clear();
    let totalPop = 0;
    for (const m of currentMetros) {{
      rankToMetro.set(m[0], m);
      totalPop += m[5];
    }}

    document.getElementById('stat-count').textContent = currentMetros.length.toLocaleString();
    document.getElementById('stat-pop').textContent = (totalPop / 1e9).toFixed(2) + 'B';
    document.getElementById('stat-top').textContent = currentMetros.length ? currentMetros[0][1] : '--';

    selectedRank = -1;
    document.getElementById('detail-panel').style.display = 'none';

    renderMetroList(document.getElementById('search-box').value);
    metroOverlay.redraw();

    setTimeout(() => {{ toast.style.opacity = '0'; }}, 250);
  }}, 20);
}}

// ============= App Initialization =============
document.addEventListener('DOMContentLoaded', () => {{
  metroOverlay = new MetroTileLayer({{
    tileSize: 256,
    opacity: 1,
    updateWhenZooming: false,
    updateWhenIdle: true
  }});
  metroOverlay.addTo(map);

  setThreshold(DEFAULT_THRESH);

  const slider = document.getElementById('thresh-slider');
  slider.addEventListener('input', (e) => {{
    document.getElementById('thresh-val').innerHTML = e.target.value + '<span>%</span>';
  }});
  slider.addEventListener('change', (e) => {{
    setThreshold(parseInt(e.target.value));
  }});

  document.getElementById('search-box').addEventListener('input', (e) => {{
    renderMetroList(e.target.value);
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
    print(f"Generated {out_file} ({size_mb:.2f} MB) in {time.time()-t0:.2f} seconds!")

if __name__ == "__main__":
    build_map()
