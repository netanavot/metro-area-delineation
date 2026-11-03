#!/usr/bin/env python3
"""
Prepares the global population raster at ~2km resolution (scale_factor=2).
Streams through the GHS-POP 2020 GeoTIFF and accumulates into a 2x downsampled grid.
Grid: ~10,692 x 21,601 = 231M cells, ~0.86 GB as float32.
"""

import os
import sys
import json
import time
import numpy as np
import tifffile

SCALE_FACTOR = 2  # 2x downsampling: ~0.01667° ≈ 1.85 km at equator

def prepare_raster(tif_path):
    t0 = time.time()
    print(f"Opening {tif_path}...")
    with tifffile.TiffFile(tif_path) as tif:
        page = tif.pages[0]
        rows_raw, cols_raw = page.shape
        tags = page.tags

        scale_x, scale_y = 0.008333333333333333, 0.008333333333333333
        origin_x, origin_y = -180.0079159313, 89.0995831776

        if 33550 in tags:
            scale = tags[33550].value
            scale_x, scale_y = float(scale[0]), float(scale[1])
        if 33922 in tags:
            tiepoint = tags[33922].value
            if len(tiepoint) >= 6:
                origin_x = float(tiepoint[3]) - float(tiepoint[0]) * scale_x
                origin_y = float(tiepoint[4]) + float(tiepoint[1]) * scale_y

        print(f"Source raster: {rows_raw} rows x {cols_raw} cols")
        print(f"Origin (NW): Lon {origin_x:.6f}, Lat {origin_y:.6f}")
        print(f"Pixel scale: {scale_x:.8f} deg x {scale_y:.8f} deg")

        rows_out = rows_raw // SCALE_FACTOR
        cols_out = cols_raw // SCALE_FACTOR
        new_scale_x = scale_x * SCALE_FACTOR
        new_scale_y = scale_y * SCALE_FACTOR

        print(f"\nTarget downsampled grid: {rows_out} rows x {cols_out} cols ({rows_out * cols_out:,} cells)")
        print(f"Cell size: {new_scale_x:.6f} deg x {new_scale_y:.6f} deg (~{new_scale_x * 111.32:.1f} km at equator)")
        out_size_gb = rows_out * cols_out * 4 / 1024**3
        print(f"Output size: {out_size_gb:.2f} GB as float32")

        # Output grid in memory (~0.86 GB at scale_factor=2)
        out_grid = np.zeros((rows_out, cols_out), dtype=np.float32)

        print("\nStreaming tiles from GeoTIFF...")
        tile_count = 0
        populated_tiles = 0
        total_raw_pop = 0.0

        for data, key, shape in page.segments():
            tile_count += 1
            if data is None:
                continue

            arr = data[0, :, :, 0]
            # Replace NaNs/infinities/negatives
            valid_mask = np.isfinite(arr) & (arr > 0)
            if not np.any(valid_mask):
                continue

            populated_tiles += 1
            arr = np.where(valid_mask, arr, 0.0)
            tile_sum = float(np.sum(arr))
            total_raw_pop += tile_sum

            r_start = key[2]
            c_start = key[3]
            th, tw = arr.shape

            max_r = rows_out * SCALE_FACTOR
            max_c = cols_out * SCALE_FACTOR
            if r_start >= max_r or c_start >= max_c:
                continue

            if r_start + th > max_r:
                th = max_r - r_start
                arr = arr[:th, :]
            if c_start + tw > max_c:
                tw = max_c - c_start
                arr = arr[:, :tw]

            r_indices = np.repeat(np.arange(r_start, r_start + th) // SCALE_FACTOR, tw)
            c_indices = np.tile(np.arange(c_start, c_start + tw) // SCALE_FACTOR, th)

            np.add.at(out_grid, (r_indices, c_indices), arr.ravel().astype(np.float32))

            if populated_tiles % 1000 == 0:
                print(f"  Processed {populated_tiles} populated tiles ({tile_count} total)... Current pop: {total_raw_pop:,.0f}")

    total_out_pop = float(np.sum(out_grid))
    pop_cells = int(np.sum(out_grid > 0))
    print(f"\nProcessing complete in {time.time() - t0:.1f}s!")
    print(f"Populated tiles: {populated_tiles:,} / {tile_count:,}")
    print(f"Total global population: {total_out_pop:,.0f} (source: {total_raw_pop:,.0f})")
    print(f"Preservation ratio: {total_out_pop / total_raw_pop * 100:.3f}%")
    print(f"Populated cells: {pop_cells:,} ({pop_cells / (rows_out * cols_out) * 100:.2f}% of Earth surface)")

    # Save population.bin and metadata.json
    output_bin = "population.bin"
    output_meta = "metadata.json"
    print(f"Writing binary grid to {output_bin} ({out_grid.nbytes / (1024*1024):.1f} MB)...")
    out_grid.tofile(output_bin)

    metadata = {
        "rows": int(rows_out),
        "cols": int(cols_out),
        "origin_lon": float(origin_x),
        "origin_lat": float(origin_y),
        "pixel_size_lon": float(new_scale_x),
        "pixel_size_lat": float(new_scale_y),
        "total_population": float(total_out_pop),
        "scale_factor": SCALE_FACTOR,
        "source_rows": int(rows_raw),
        "source_cols": int(cols_raw)
    }

    with open(output_meta, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"Metadata written to {output_meta}.")

if __name__ == "__main__":
    tif_file = sys.argv[1] if len(sys.argv) > 1 else "GHS_POP_E2020_GLOBE_R2023A_4326_30ss_V1_0.tif"
    if not os.path.exists(tif_file):
        print(f"File {tif_file} not found.")
        sys.exit(1)
    prepare_raster(tif_file)
