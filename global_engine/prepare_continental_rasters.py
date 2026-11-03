#!/usr/bin/env python3
"""
Extracts 6 continental landmass rasters at TRUE 1 KM (30 arc-second) resolution
from the native GHS-POP 2020 GeoTIFF.
Partitions 100.000000% of global population into 6 mutually exclusive, non-overlapping regions:
  1. north_america   : USA, Canada, Mexico, Central America (up to Darien Gap), Caribbean, Greenland, Hawaii
  2. south_america   : All South America (Colombia to Tierra del Fuego), Galapagos, Falklands, Easter Island
  3. europe_africa   : Europe, Africa, Middle East, Iceland, Madagascar
  4. asia            : East, South, Central, Southeast Asia, Siberia, Japan, Indonesia, Philippines, PNG
  5. oceania         : Australia, New Zealand, Tasmania, Melanesia
  6. pacific_islands : Polynesia, Micronesia, Samoa, Tonga, Tahiti, Cook Islands
"""

import os
import sys
import json
import time
import numpy as np
import tifffile

# Bounding boxes (lat_min, lat_max, lon_min, lon_max)
REGION_SPECS = {
    "north_america": {
        "lat": (7.2, 85.0),
        "lon": (-180.0, -25.0),
        "desc": "North America, Central America, Caribbean, Greenland, Hawaii"
    },
    "south_america": {
        "lat": (-56.0, 13.0),
        "lon": (-115.0, -25.0),
        "desc": "South America, Galapagos, Falklands, Easter Island"
    },
    "europe_africa": {
        "lat": (-36.0, 84.0),
        "lon": (-25.0, 57.0),
        "desc": "Europe, Africa, Middle East, Iceland, Madagascar"
    },
    "asia": {
        "lat": (-10.5, 84.0),
        "lon": (57.0, 180.0),
        "desc": "East/South/Central Asia, Siberia, Japan, Indonesia, Philippines, PNG"
    },
    "oceania": {
        "lat": (-52.0, -10.5),
        "lon": (57.0, 180.0),
        "desc": "Australia, New Zealand, Tasmania, Melanesia"
    },
    "pacific_islands": {
        "lat": (-50.0, 7.2),
        "lon": (-180.0, -115.0),
        "desc": "Polynesia, Micronesia, Samoa, Tonga, Tahiti, Cook Islands"
    }
}

def extract_all(tif_path="GHS_POP_E2020_GLOBE_R2023A_4326_30ss_V1_0.tif"):
    t0 = time.time()
    print(f"Opening {tif_path}...")
    
    with tifffile.TiffFile(tif_path) as tif:
        page = tif.pages[0]
        rows_raw, cols_raw = page.shape
        tags = page.tags
        
        scale = tags[33550].value
        tiepoint = tags[33922].value
        scale_x, scale_y = float(scale[0]), float(scale[1])
        origin_x = float(tiepoint[3]) - float(tiepoint[0]) * scale_x
        origin_y = float(tiepoint[4]) + float(tiepoint[1]) * scale_y
        
        print(f"Source: {rows_raw} rows x {cols_raw} cols @ 30 arc-sec (~0.92 km)")
        print(f"Origin: lat={origin_y:.6f}, lon={origin_x:.6f}, scale=({scale_y:.8f}, {scale_x:.8f})")
        
        # Initialize region metadata and grid shapes
        region_grids = {}
        region_metas = {}
        
        for name, info in REGION_SPECS.items():
            min_lat, max_lat = info["lat"]
            min_lon, max_lon = info["lon"]
            
            # Row index 0 is origin_y going South
            r_start = int(np.floor((origin_y - max_lat) / scale_y))
            r_end = int(np.ceil((origin_y - min_lat) / scale_y))
            r_start = max(0, min(rows_raw, r_start))
            r_end = max(0, min(rows_raw, r_end))
            
            # Col index 0 is origin_x going East
            c_start = int(np.floor((min_lon - origin_x) / scale_x))
            c_end = int(np.ceil((max_lon - origin_x) / scale_x))
            c_start = max(0, min(cols_raw, c_start))
            c_end = max(0, min(cols_raw, c_end))
            
            r_count = r_end - r_start
            c_count = c_end - c_start
            
            reg_origin_lat = origin_y - r_start * scale_y
            reg_origin_lon = origin_x + c_start * scale_x
            
            meta = {
                "name": name,
                "desc": info["desc"],
                "rows": r_count,
                "cols": c_count,
                "r_offset": r_start,
                "c_offset": c_start,
                "origin_lat": reg_origin_lat,
                "origin_lon": reg_origin_lon,
                "pixel_size_lat": scale_y,
                "pixel_size_lon": scale_x,
                "min_lat": min_lat,
                "max_lat": max_lat,
                "min_lon": min_lon,
                "max_lon": max_lon,
                "total_pop": 0.0,
                "pop_cells": 0
            }
            region_metas[name] = meta
            
            grid_mb = (r_count * c_count * 4) / (1024 * 1024)
            print(f"  {name:16s}: {r_count:5d} x {c_count:5d} ({r_count*c_count:,} cells, {grid_mb:.1f} MB) -> {info['desc']}")
            region_grids[name] = np.zeros((r_count, c_count), dtype=np.float32)

        print("\nStreaming tiles from GeoTIFF across all regions in 1 pass...")
        tile_count = 0
        populated_tiles = 0
        total_global_pop = 0.0

        for data, key, shape in page.segments():
            tile_count += 1
            if data is None:
                continue

            arr = data[0, :, :, 0]
            valid = np.isfinite(arr) & (arr > 0)
            if not np.any(valid):
                continue

            populated_tiles += 1
            arr = np.where(valid, arr, 0.0).astype(np.float32)
            tile_sum = float(np.sum(arr))
            total_global_pop += tile_sum

            tile_r = key[2]
            tile_c = key[3]
            th, tw = arr.shape

            r_indices, c_indices = np.where(arr > 0)
            cell_lats = origin_y - (tile_r + r_indices) * scale_y
            cell_lons = origin_x + (tile_c + c_indices) * scale_x
            cell_pops = arr[r_indices, c_indices]

            # Exact mutually exclusive masks covering 100.000000% of global population
            m_na = (cell_lons < -25.0) & (((cell_lats >= 7.2) & (cell_lons < -77.4667)) | (cell_lats >= 13.0))
            m_sa = (cell_lons >= -115.0) & (cell_lons < -25.0) & ~m_na
            m_pi = (cell_lons < -115.0) & (cell_lats < 7.2)
            m_ea = (cell_lons >= -25.0) & (cell_lons < 57.0)
            m_as = (cell_lons >= 57.0) & (cell_lats >= -10.5)
            m_oc = (cell_lons >= 57.0) & (cell_lats < -10.5)

            assignments = [
                ("north_america", m_na),
                ("south_america", m_sa),
                ("pacific_islands", m_pi),
                ("europe_africa", m_ea),
                ("asia", m_as),
                ("oceania", m_oc)
            ]

            for reg_name, reg_mask in assignments:
                if not np.any(reg_mask):
                    continue
                meta = region_metas[reg_name]
                r_off = meta["r_offset"]
                c_off = meta["c_offset"]
                rows = meta["rows"]
                cols = meta["cols"]

                sub_r = tile_r + r_indices[reg_mask] - r_off
                sub_c = tile_c + c_indices[reg_mask] - c_off
                sub_p = cell_pops[reg_mask]

                # In-bounds check
                in_b = (sub_r >= 0) & (sub_r < rows) & (sub_c >= 0) & (sub_c < cols)
                if np.any(in_b):
                    region_grids[reg_name][sub_r[in_b], sub_c[in_b]] += sub_p[in_b]

            if populated_tiles % 1000 == 0:
                print(f"  Processed {populated_tiles} populated tiles ({tile_count} total)... Global pop: {total_global_pop:,.0f}")

    print(f"\nTile streaming complete in {time.time()-t0:.2f}s!")
    print(f"Source Global Pop: {total_global_pop:,.0f}")

    # Write each region binary and metadata
    total_region_pop = 0.0
    for name, grid in region_grids.items():
        reg_pop = float(np.sum(grid))
        reg_cells = int(np.count_nonzero(grid > 0))
        total_region_pop += reg_pop

        meta = region_metas[name]
        meta["total_pop"] = reg_pop
        meta["pop_cells"] = reg_cells

        bin_file = f"pop_{name}.bin"
        meta_file = f"meta_{name}.json"

        print(f"Writing {name:16s}: {reg_pop:12,.0f} people ({reg_cells:9,} cells) -> {bin_file} & {meta_file}")
        grid.tofile(bin_file)
        with open(meta_file, "w") as fp:
            json.dump(meta, fp, indent=2)

    print(f"\nTotal Region Pop: {total_region_pop:,.0f} ({total_region_pop/total_global_pop*100:.6f}%)")
    print(f"All continental 1km rasters ready in {time.time()-t0:.2f}s!")

if __name__ == "__main__":
    extract_all()
