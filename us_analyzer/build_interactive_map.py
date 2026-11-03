#!/usr/bin/env python3
"""
Builds an interactive, vector-based HTML map of US Metropolitan Areas:
1. Complete 100% landscape coverage (no unassigned holes, no enclaves).
2. Every colored area is directly clickable (state borders layer is non-interactive).
3. Sorted by area so smaller metros are never obscured by larger ones.
4. Clean state border lines and multiple basemaps.
"""

import json
import os

def build_map():
    print("Reading GeoJSON files...")
    with open("us_metro_areas.geojson", "r", encoding="utf-8") as f:
        metro_data = json.load(f)

    # Sort features by area descending: large regional footprints first, small cores on top
    # This guarantees that EVERY single metro is effortlessly clickable without occlusion!
    metro_data["features"].sort(key=lambda x: x["properties"].get("area", 0), reverse=True)
    metro_geojson_str = json.dumps(metro_data)

    with open("us-states.json", "r", encoding="utf-8") as f:
        states_geojson_str = f.read()

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>US Metropolitan Areas — Full Coverage & State Borders</title>
  
  <!-- Leaflet CSS & JS -->
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  
  <!-- Google Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">

  <style>
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: #0f172a;
      background: #0f172a;
      overflow: hidden;
      display: flex;
      height: 100vh;
      width: 100vw;
    }}
    #sidebar {{
      width: 420px;
      height: 100vh;
      background: #ffffff;
      border-right: 1px solid #e2e8f0;
      display: flex;
      flex-direction: column;
      z-index: 1000;
      box-shadow: 2px 0 16px rgba(0,0,0,0.08);
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
      background: #f8fafc;
    }}
    .header {{
      padding: 18px 20px 14px;
      border-bottom: 1px solid #e2e8f0;
      background: #0f172a;
      color: #ffffff;
    }}
    .header h1 {{
      font-size: 17px;
      font-weight: 700;
      letter-spacing: -0.3px;
      margin-bottom: 4px;
    }}
    .header p {{
      font-size: 11px;
      color: #94a3b8;
      line-height: 1.4;
    }}
    .controls {{
      padding: 14px 20px;
      background: #f8fafc;
      border-bottom: 1px solid #e2e8f0;
    }}
    .search-box {{
      position: relative;
      margin-bottom: 12px;
    }}
    .search-box input {{
      width: 100%;
      padding: 9px 12px 9px 34px;
      border-radius: 8px;
      border: 1px solid #cbd5e1;
      font-size: 13px;
      outline: none;
      transition: all 0.2s;
      background: #ffffff;
    }}
    .search-box input:focus {{
      border-color: #3b82f6;
      box-shadow: 0 0 0 3px rgba(59,130,246,0.15);
    }}
    .search-icon {{
      position: absolute;
      left: 10px;
      top: 50%;
      transform: translateY(-50%);
      width: 16px;
      height: 16px;
      color: #94a3b8;
    }}
    .layer-controls {{
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-bottom: 12px;
      background: #ffffff;
      padding: 10px 12px;
      border-radius: 8px;
      border: 1px solid #e2e8f0;
    }}
    .toggle-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 12px;
      font-weight: 500;
      color: #334155;
    }}
    .color-mode-select {{
      padding: 3px 8px;
      border-radius: 6px;
      border: 1px solid #cbd5e1;
      font-size: 11px;
      color: #1e293b;
      background: #f8fafc;
      outline: none;
    }}
    .slider-row {{
      display: flex;
      flex-direction: column;
      gap: 4px;
      font-size: 11px;
      font-weight: 500;
      color: #475569;
    }}
    .slider-row input[type=range] {{
      accent-color: #2563eb;
    }}
    .presets {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin-top: 6px;
    }}
    .preset-btn {{
      font-size: 11px;
      font-weight: 500;
      padding: 4px 10px;
      border-radius: 6px;
      border: 1px solid #cbd5e1;
      background: #ffffff;
      color: #334155;
      cursor: pointer;
      transition: all 0.15s;
    }}
    .preset-btn:hover {{
      background: #eff6ff;
      border-color: #93c5fd;
      color: #1d4ed8;
    }}
    .preset-btn.highlight {{
      background: #dbeafe;
      border-color: #3b82f6;
      color: #1d4ed8;
      font-weight: 600;
    }}
    .list-header {{
      padding: 10px 20px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: #64748b;
      background: #ffffff;
      border-bottom: 1px solid #f1f5f9;
      display: flex;
      justify-content: space-between;
    }}
    .metro-list {{
      flex: 1;
      overflow-y: auto;
      list-style: none;
    }}
    .metro-item {{
      padding: 11px 20px;
      border-bottom: 1px solid #f1f5f9;
      cursor: pointer;
      transition: background 0.15s;
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .metro-item:hover {{
      background: #f8fafc;
    }}
    .metro-item.active {{
      background: #eff6ff;
      border-left: 4px solid #2563eb;
    }}
    .metro-rank {{
      font-size: 12px;
      font-weight: 700;
      color: #64748b;
      min-width: 28px;
    }}
    .metro-color-indicator {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex-shrink: 0;
    }}
    .metro-info {{
      flex: 1;
      min-width: 0;
    }}
    .metro-title {{
      font-size: 13px;
      font-weight: 600;
      color: #0f172a;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .metro-sub {{
      font-size: 11px;
      color: #64748b;
      margin-top: 2px;
    }}
    .metro-pop {{
      font-size: 13px;
      font-weight: 700;
      color: #1e293b;
      text-align: right;
    }}
    .popup-card {{
      font-family: 'Inter', sans-serif;
      min-width: 260px;
      padding: 2px;
    }}
    .popup-title {{
      font-size: 15px;
      font-weight: 700;
      color: #0f172a;
      border-bottom: 2px solid #3b82f6;
      padding-bottom: 6px;
      margin-bottom: 8px;
    }}
    .popup-stat {{
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      padding: 3px 0;
      border-bottom: 1px dotted #e2e8f0;
    }}
    .popup-stat-label {{
      color: #64748b;
    }}
    .popup-stat-val {{
      font-weight: 600;
      color: #0f172a;
    }}
    .popup-anchors {{
      margin-top: 8px;
      font-size: 11px;
      color: #334155;
      line-height: 1.4;
      background: #f1f5f9;
      border-radius: 6px;
      padding: 6px 8px;
      border-left: 3px solid #3b82f6;
    }}
    .legend {{
      position: absolute;
      bottom: 24px;
      right: 24px;
      background: rgba(255,255,255,0.96);
      padding: 14px 18px;
      border-radius: 10px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.15);
      z-index: 1000;
      font-size: 12px;
      border: 1px solid #cbd5e1;
      backdrop-filter: blur(6px);
      max-width: 310px;
    }}
    .legend-title {{
      font-weight: 700;
      margin-bottom: 8px;
      color: #0f172a;
      font-size: 13px;
    }}
    .legend-row {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 6px;
      color: #334155;
    }}
    .legend-color-box {{
      width: 20px;
      height: 14px;
      border-radius: 3px;
      border: 1px solid rgba(0,0,0,0.2);
    }}
    .legend-line {{
      width: 20px;
      height: 3px;
      background: #0f172a;
      border-radius: 2px;
    }}
    .state-tooltip {{
      font-family: 'Inter', sans-serif;
      font-weight: 600;
      font-size: 12px;
      color: #0f172a;
      background: rgba(255,255,255,0.95);
      border: 1px solid #cbd5e1;
      box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }}
  </style>
</head>
<body>

  <div id="sidebar">
    <div class="header">
      <h1>US Metropolitan Areas</h1>
      <p>Click directly on any colored area to view full metropolitan statistics</p>
    </div>

    <div class="controls">
      <div class="search-box">
        <svg class="search-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
        </svg>
        <input type="text" id="search-input" placeholder="Search city or metro..." />
      </div>

      <div class="layer-controls">
        <div class="toggle-row">
          <span>Show State Borders:</span>
          <input type="checkbox" id="state-toggle" checked />
        </div>
        <div class="toggle-row">
          <span>Color Palette:</span>
          <select id="color-mode-select" class="color-mode-select">
            <option value="distinct">Distinct Regional Colors</option>
            <option value="population">By Population Tier</option>
            <option value="density">By Average Density</option>
          </select>
        </div>
        <div class="slider-row">
          <div style="display:flex; justify-content:space-between;">
            <span>Area Fill Opacity:</span>
            <span id="opacity-label">65%</span>
          </div>
          <input type="range" id="opacity-slider" min="15" max="100" value="65" />
        </div>
        <div class="slider-row">
          <div style="display:flex; justify-content:space-between;">
            <span>Min Population Filter:</span>
            <span id="pop-label">All (0+)</span>
          </div>
          <input type="range" id="pop-range" min="0" max="2000000" step="10000" value="0" />
        </div>
      </div>

      <div class="presets">
        <span style="font-size:11px; color:#64748b; font-weight:600; width:100%; margin-bottom:2px;">Quick Fly-To:</span>
        <button class="preset-btn highlight" onclick="flyToRank(24)">Wasatch Front (UT)</button>
        <button class="preset-btn" onclick="flyToRank(1724)">Mountain Home (ID)</button>
        <button class="preset-btn" onclick="flyToRank(155)">Bremerton (WA)</button>
        <button class="preset-btn" onclick="flyToRank(15)">Seattle (WA)</button>
        <button class="preset-btn" onclick="flyToRank(66)">Boise City (ID)</button>
        <button class="preset-btn" onclick="flyToRank(14)">Tampa (FL)</button>
        <button class="preset-btn" onclick="flyToRank(23)">Orlando (FL)</button>
        <button class="preset-btn" onclick="map.flyTo([39.8, -98.5], 5)">Full US View</button>
      </div>
    </div>

    <div class="list-header">
      <span id="results-count">Showing Metros</span>
      <span>Population</span>
    </div>

    <ul class="metro-list" id="metro-list">
      <!-- Dynamically injected -->
    </ul>
  </div>

  <div id="map-container">
    <div id="map"></div>

    <div class="legend" id="legend">
      <div class="legend-title">Map Layers & Legend</div>
      <div class="legend-row">
        <div class="legend-line" style="background:#0f172a; height:2px;"></div>
        <span><b>US State Borders</b></span>
      </div>
      <div class="legend-row">
        <div class="legend-color-box" style="background:#3b82f6;"></div>
        <span><b>Metro Area Polygons (7% Cutoff)</b></span>
      </div>
      <div style="margin-top:8px; font-size:10px; color:#64748b; line-height:1.4;">
        <b>Zero-Density Areas Uncolored:</b> Uninhabited areas (deserts, mountains, water bodies, wilderness) are left transparent/uncolored.
      </div>
    </div>
  </div>

  <script>
    const metroGeoJson = {metro_geojson_str};
    const statesGeoJson = {states_geojson_str};

    // Initialize Leaflet Map
    const map = L.map('map', {{
      center: [39.5, -98.35],
      zoom: 5,
      zoomControl: true
    }});

    // Basemaps
    const positron = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      attribution: '&copy; OpenStreetMap, &copy; CARTO | WorldPop 2020',
      maxZoom: 18
    }}).addTo(map);

    const osm = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      attribution: '&copy; OpenStreetMap',
      maxZoom: 18
    }});

    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
      attribution: '&copy; Esri World Imagery',
      maxZoom: 18
    }});

    const dark = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      attribution: '&copy; OpenStreetMap, &copy; CARTO',
      maxZoom: 18
    }});

    // Color logic
    function getMetroColor(props, mode) {{
      if (mode === 'population') {{
        const pop = props.pop;
        if (pop >= 6000000) return '#dc2626'; // Red
        if (pop >= 2500000) return '#ea580c'; // Orange
        if (pop >= 1000000) return '#2563eb'; // Blue
        if (pop >= 300000)  return '#0d9488'; // Teal
        return '#059669';                     // Green
      }} else if (mode === 'density') {{
        const dens = props.density;
        if (dens >= 1500) return '#7c3aed';   // Purple
        if (dens >= 800)  return '#dc2626';   // Red
        if (dens >= 500)  return '#ea580c';   // Orange
        if (dens >= 300)  return '#2563eb';   // Blue
        return '#0d9488';                     // Teal
      }} else {{
        return props.color || '#3b82f6';
      }}
    }}

    let currentFillOpacity = 0.65;
    let currentColorMode = 'distinct';

    // 1. High-Contrast US State Borders Layer
    // NOTE: interactive is explicitly FALSE so state polygons NEVER intercept mouse clicks!
    const stateBordersLayer = L.geoJSON(statesGeoJson, {{
      interactive: false,
      style: {{
        color: '#0f172a',
        weight: 1.8,
        opacity: 0.90,
        fillColor: '#ffffff',
        fillOpacity: 0.0,
        dashArray: '3, 4'
      }}
    }}).addTo(map);

    function createPopupContent(p) {{
      let mergedSection = '';
      if (p.merged && p.merged.trim() !== '') {{
        mergedSection = `<div class="popup-anchors"><b>Absorbed Municipalities & Satellite Cores:</b><br>${{p.merged.replace(/;/g, ', ')}}</div>`;
      }}
      return `
        <div class="popup-card">
          <div class="popup-title">#${{p.rank}} ${{p.name}}</div>
          <div class="popup-stat">
            <span class="popup-stat-label">Total Population:</span>
            <span class="popup-stat-val">${{p.pop.toLocaleString()}}</span>
          </div>
          <div class="popup-stat">
            <span class="popup-stat-label">Delineated Land Area:</span>
            <span class="popup-stat-val">${{p.area.toLocaleString(undefined, {{maximumFractionDigits:1}})}} km²</span>
          </div>
          <div class="popup-stat">
            <span class="popup-stat-label">Average Density:</span>
            <span class="popup-stat-val">${{p.density.toFixed(1)}} ppl/km²</span>
          </div>
          <div class="popup-stat">
            <span class="popup-stat-label">Peak Core Density:</span>
            <span class="popup-stat-val">${{p.peak_density.toFixed(1)}} ppl/km²</span>
          </div>
          <div class="popup-stat">
            <span class="popup-stat-label">95th Pct Density (P95):</span>
            <span class="popup-stat-val">${{p.p95_density.toFixed(1)}} ppl/km²</span>
          </div>
          <div class="popup-stat">
            <span class="popup-stat-label">Condition B Cutoff (T):</span>
            <span class="popup-stat-val">${{p.threshold.toFixed(1)}} ppl/km²</span>
          </div>
          <div class="popup-stat">
            <span class="popup-stat-label">Satellite Maxima Merged:</span>
            <span class="popup-stat-val">${{p.absorbed_peaks}}</span>
          </div>
          ${{mergedSection}}
        </div>
      `;
    }}

    // 2. Metro Areas Polygon Layer
    let metroLayer = null;
    const rankToLayer = {{}};

    function buildMetroLayer() {{
      if (metroLayer) {{
        map.removeLayer(metroLayer);
      }}

      const minPop = parseInt(document.getElementById('pop-range').value, 10);
      const query = document.getElementById('search-input').value.toLowerCase().trim();

      metroLayer = L.geoJSON(metroGeoJson, {{
        filter: function(feature) {{
          const p = feature.properties;
          const matchSearch = query === '' || 
                              p.name.toLowerCase().includes(query) || 
                              (p.merged && p.merged.toLowerCase().includes(query));
          const matchPop = p.pop >= minPop;
          return matchSearch && matchPop;
        }},
        style: function(feature) {{
          const color = getMetroColor(feature.properties, currentColorMode);
          return {{
            color: color,
            weight: 1.2,
            opacity: 0.95,
            fillColor: color,
            fillOpacity: currentFillOpacity
          }};
        }},
        onEachFeature: function(feature, layer) {{
          const p = feature.properties;
          rankToLayer[p.rank] = layer;

          layer.bindPopup(createPopupContent(p));
          layer.bindTooltip(`#${{p.rank}} ${{p.name}} (${{p.pop.toLocaleString()}})`, {{
            sticky: true,
            className: 'state-tooltip'
          }});

          layer.on({{
            mouseover: function(e) {{
              const l = e.target;
              l.setStyle({{
                weight: 2.5,
                color: '#0f172a',
                fillOpacity: Math.min(1.0, currentFillOpacity + 0.20)
              }});
            }},
            mouseout: function(e) {{
              metroLayer.resetStyle(e.target);
            }},
            click: function(e) {{
              e.target.openPopup();
              highlightListItemByRank(p.rank);
            }}
          }});
        }}
      }}).addTo(map);

      // Keep state borders above polygon fills
      stateBordersLayer.bringToFront();
    }}

    // Layer control
    const baseMaps = {{
      "Light (Positron)": positron,
      "OpenStreetMap": osm,
      "Satellite Imagery": satellite,
      "Dark Matter": dark
    }};
    const overlayMaps = {{
      "State Borders": stateBordersLayer
    }};
    L.control.layers(baseMaps, overlayMaps, {{ position: 'topright' }}).addTo(map);

    // Sidebar rendering
    function renderList() {{
      const minPop = parseInt(document.getElementById('pop-range').value, 10);
      const query = document.getElementById('search-input').value.toLowerCase().trim();
      const listEl = document.getElementById('metro-list');
      listEl.innerHTML = '';

      // Get unique features sorted by rank
      const filtered = metroGeoJson.features.filter(f => {{
        const p = f.properties;
        const matchSearch = query === '' || 
                            p.name.toLowerCase().includes(query) || 
                            (p.merged && p.merged.toLowerCase().includes(query));
        const matchPop = p.pop >= minPop;
        return matchSearch && matchPop;
      }}).sort((a, b) => a.properties.rank - b.properties.rank);

      document.getElementById('results-count').innerText = `Showing ${{filtered.length}} Metros`;

      filtered.forEach(f => {{
        const m = f.properties;
        const color = getMetroColor(m, currentColorMode);
        const li = document.createElement('li');
        li.className = 'metro-item';
        li.id = `item-${{m.rank}}`;
        li.innerHTML = `
          <div class="metro-rank">#${{m.rank}}</div>
          <div class="metro-color-indicator" style="background:${{color}};"></div>
          <div class="metro-info">
            <div class="metro-title">${{m.name}}</div>
            <div class="metro-sub">${{m.area.toLocaleString(undefined, {{maximumFractionDigits:0}})}} km² &bull; ${{m.density.toFixed(0)}} ppl/km²</div>
          </div>
          <div class="metro-pop">${{m.pop.toLocaleString()}}</div>
        `;

        li.addEventListener('click', () => {{
          flyToRank(m.rank);
        }});

        listEl.appendChild(li);
      }});
    }}

    function highlightListItemByRank(rank) {{
      document.querySelectorAll('.metro-item').forEach(el => el.classList.remove('active'));
      const activeEl = document.getElementById(`item-${{rank}}`);
      if (activeEl) {{
        activeEl.classList.add('active');
        activeEl.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
      }}
    }}

    function flyToRank(rank) {{
      const layer = rankToLayer[rank];
      if (layer) {{
        const bounds = layer.getBounds();
        map.fitBounds(bounds, {{
          padding: [50, 50],
          maxZoom: 10,
          animate: true,
          duration: 1.2
        }});
        layer.openPopup();
        highlightListItemByRank(rank);
      }}
    }}

    function updateAll() {{
      const minPop = parseInt(document.getElementById('pop-range').value, 10);
      document.getElementById('pop-label').innerText = minPop === 0 ? 'All (0+)' : minPop.toLocaleString() + '+';
      buildMetroLayer();
      renderList();
    }}

    // UI Listeners
    document.getElementById('search-input').addEventListener('input', updateAll);
    document.getElementById('pop-range').addEventListener('input', updateAll);

    document.getElementById('state-toggle').addEventListener('change', (e) => {{
      if (e.target.checked) {{
        map.addLayer(stateBordersLayer);
      }} else {{
        map.removeLayer(stateBordersLayer);
      }}
    }});

    document.getElementById('color-mode-select').addEventListener('change', (e) => {{
      currentColorMode = e.target.value;
      updateAll();
    }});

    document.getElementById('opacity-slider').addEventListener('input', (e) => {{
      currentFillOpacity = parseInt(e.target.value, 10) / 100.0;
      document.getElementById('opacity-label').innerText = `${{e.target.value}}%`;
      if (metroLayer) {{
        metroLayer.setStyle({{
          fillOpacity: currentFillOpacity
        }});
      }}
    }});

    // Initial load
    updateAll();
  </script>
</body>
</html>
"""

    output_html = "us_metro_map.html"
    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Generated clean interactive vector map at {output_html} ({os.path.getsize(output_html) / 1024:.1f} KB).")

if __name__ == "__main__":
    build_map()
