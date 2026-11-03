#!/bin/bash
# Master pipeline: prepare raster → run C++ delineation → build HTML map
set -e

cd "$(dirname "$0")"

echo "=== Step 1: Prepare global raster ==="
python3 prepare_global_raster.py ppp_2020_1km_Aggregated.tif

echo ""
echo "=== Step 2: Compile & run global metro delineation ==="
# Already compiled, but recompile just in case
clang++ -O3 -std=c++17 -o global_metro global_metro.cpp
./global_metro 1 20 1

echo ""
echo "=== Step 3: Build interactive HTML map ==="
python3 build_global_map.py

echo ""
echo "=== Step 4: Deploy to Desktop ==="
cp global_metro_map.html ~/Desktop/global_metro_map.html
echo "Done! Open ~/Desktop/global_metro_map.html in your browser."
