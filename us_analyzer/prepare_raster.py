#!/usr/bin/env python3
"""
Prepares the WorldPop population raster for high-performance C++ processing.
Extracts CONUS (Contiguous United States, 99.3% of US population) into an optimized
compact binary grid, removing massive empty ocean padding.
"""

import os
import sys
import json
import numpy as np
import tifffile

def prepare_raster(tif_path):
    print(f"Reading {tif_path}...")
    with tifffile.TiffFile(tif_path) as tif:
        page = tif.pages[0]
        data = page.asarray()
        tags = page.tags

        scale_x, scale_y = 0.008333333333333333, 0.008333333333333333 # ~30 arc-sec (1/120 deg)
        origin_x, origin_y = -179.151249, 71.391250

        if 33550 in tags:
            scale = tags[33550].value
            scale_x, scale_y = float(scale[0]), float(scale[1])
        if 33922 in tags:
            tiepoint = tags[33922].value
            if len(tiepoint) >= 6:
                origin_x = float(tiepoint[3]) - float(tiepoint[0]) * scale_x
                origin_y = float(tiepoint[4]) + float(tiepoint[1]) * scale_y

    print(f"Raw Raster: {data.shape[0]} rows x {data.shape[1]} cols")
    print(f"Origin (Top-Left): Lon {origin_x:.6f}, Lat {origin_y:.6f}")

    # Clean NaNs and negatives
    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    data[data < 0] = 0.0
    data = data.astype(np.float32)

    total_pop = float(np.sum(data))
    print(f"Total population in national raster: {total_pop:,.0f}")

    # Crop to CONUS (Contiguous United States: Lat 24.0° to 50.0°, Lon -126.0° to -66.0°)
    lat_north, lat_south = 50.0, 24.0
    lon_west, lon_east = -126.0, -66.0

    r_min = max(0, int((origin_y - lat_north) / scale_y))
    r_max = min(data.shape[0], int((origin_y - lat_south) / scale_y))
    c_min = max(0, int((lon_west - origin_x) / scale_x))
    c_max = min(data.shape[1], int((lon_east - origin_x) / scale_x))

    conus_data = data[r_min:r_max, c_min:c_max].copy()
    conus_pop = float(np.sum(conus_data))
    conus_origin_lat = origin_y - r_min * scale_y
    conus_origin_lon = origin_x + c_min * scale_x

    print(f"\n--- CONUS Optimized Grid ---")
    print(f"Dimensions: {conus_data.shape[0]} rows x {conus_data.shape[1]} cols ({conus_data.size:,} cells)")
    print(f"Origin (NW): Lon {conus_origin_lon:.6f}, Lat {conus_origin_lat:.6f}")
    print(f"Population: {conus_pop:,.0f} ({conus_pop / total_pop * 100:.2f}% of US total)")
    print(f"Memory footprint: {conus_data.nbytes / (1024*1024):.1f} MB (blazing fast in C++)")

    # Save population.bin and metadata.json
    output_bin = "population.bin"
    output_meta = "metadata.json"
    print(f"Writing binary grid to {output_bin}...")
    conus_data.tofile(output_bin)

    metadata = {
        "rows": int(conus_data.shape[0]),
        "cols": int(conus_data.shape[1]),
        "origin_lon": float(conus_origin_lon),
        "origin_lat": float(conus_origin_lat),
        "pixel_size_lon": float(scale_x),
        "pixel_size_lat": float(scale_y),
        "total_population": float(conus_pop)
    }

    with open(output_meta, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"Metadata saved to {output_meta}.")
    print("Optimization complete!")

if __name__ == "__main__":
    tif_path = sys.argv[1] if len(sys.argv) > 1 else "usa_ppp_2020_1km_Aggregated.tif"
    if not os.path.exists(tif_path):
        print(f"File {tif_path} not found.")
        sys.exit(1)
    prepare_raster(tif_path)
