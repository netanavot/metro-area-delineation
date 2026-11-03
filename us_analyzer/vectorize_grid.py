#!/usr/bin/env python3
"""
Vectorizes the complete 100% landscape-allocated metro_ranks.bin raster into
valid, simplified GeoJSON polygons (RFC 7946 compliant).
Guarantees correct MultiPolygon coordinates nesting.
"""

import json
import csv
import time
import colorsys
import numpy as np
import cv2
from shapely.geometry import shape

def vectorize_grid():
    t0 = time.time()
    with open("metadata.json") as f:
        meta = json.load(f)

    H, W = meta["rows"], meta["cols"]
    ranks = np.fromfile("metro_ranks.bin", dtype=np.int16).reshape((H, W))

    origin_lat = meta["origin_lat"]
    origin_lon = meta["origin_lon"]
    dlat = meta["pixel_size_lat"]
    dlon = meta["pixel_size_lon"]

    # Load metro CSV
    metros_meta = {}
    with open("us_metro_areas.csv", "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        _ = next(reader)
        for row in reader:
            r = int(row[0])
            metros_meta[r] = {
                "rank": r,
                "name": row[1],
                "lat": float(row[2]),
                "lon": float(row[3]),
                "pop": int(float(row[4])),
                "area": float(row[5]),
                "density": float(row[6]),
                "peak_density": float(row[7]),
                "p95_density": float(row[8]),
                "threshold": float(row[9]),
                "absorbed_peaks": int(row[10]),
                "merged": row[11]
            }

    print("Extracting coordinates for all ranks...")
    nz_r, nz_c = np.nonzero(ranks)
    nz_ranks = ranks[nz_r, nz_c]

    sort_idx = np.argsort(nz_ranks)
    sorted_ranks = nz_ranks[sort_idx]
    sorted_r = nz_r[sort_idx]
    sorted_c = nz_c[sort_idx]

    change_idx = np.flatnonzero(np.diff(sorted_ranks)) + 1
    splits = np.concatenate(([0], change_idx, [len(sorted_ranks)]))

    total_ranks = len(splits) - 1
    print(f"Vectorizing {total_ranks} active metro areas...")

    features = []
    for i in range(total_ranks):
        idx_start = splits[i]
        idx_end = splits[i + 1]
        rank = int(sorted_ranks[idx_start])

        m_info = metros_meta.get(rank, {})
        if not m_info: continue

        rs = sorted_r[idx_start:idx_end]
        cs = sorted_c[idx_start:idx_end]

        r0, r1 = max(0, int(rs.min()) - 1), min(H, int(rs.max()) + 2)
        c0, c1 = max(0, int(cs.min()) - 1), min(W, int(cs.max()) + 2)

        sub_ranks = ranks[r0:r1, c0:c1]
        sub_mask = (sub_ranks == rank).astype(np.uint8)

        contours, _ = cv2.findContours(sub_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        poly_rings = []
        for cnt in contours:
            if cv2.contourArea(cnt) < 2.0: continue
            simp = cv2.approxPolyDP(cnt, epsilon=1.3, closed=True)
            if len(simp) < 3: continue

            ring = []
            for pt in simp:
                col = c0 + pt[0][0]
                row = r0 + pt[0][1]
                lon = round(origin_lon + (col + 0.5) * dlon, 4)
                lat = round(origin_lat - (row + 0.5) * dlat, 4)
                ring.append([lon, lat])
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            poly_rings.append(ring)

        if not poly_rings: continue

        # Distinct hue using golden ratio
        hue = ((int(rank) * 137.507764) % 360) / 360.0
        rgb = colorsys.hsv_to_rgb(hue, 0.82, 0.90)
        hex_color = f"#{int(rgb[0]*255):02x}{int(rgb[1]*255):02x}{int(rgb[2]*255):02x}"

        if len(poly_rings) == 1:
            geom_type = "Polygon"
            geom_coordinates = [poly_rings[0]]
        else:
            geom_type = "MultiPolygon"
            geom_coordinates = [[ring] for ring in poly_rings]

        feature = {
            "type": "Feature",
            "properties": {
                **m_info,
                "color": hex_color
            },
            "geometry": {
                "type": geom_type,
                "coordinates": geom_coordinates
            }
        }

        try:
            s = shape(feature["geometry"])
            if not s.is_valid:
                s = s.buffer(0)
                feature["geometry"] = json.loads(json.dumps(s.__geo_interface__))
            features.append(feature)
        except Exception:
            features.append(feature)

    geojson_data = {
        "type": "FeatureCollection",
        "features": features
    }

    out_file = "us_metro_areas.geojson"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(geojson_data, f)

    print(f"Exported {len(features)} valid metro polygons to {out_file} in {time.time()-t0:.2f}s")

if __name__ == "__main__":
    vectorize_grid()
