#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=== Step 1: Compiling C++ Metro Analyzer ==="
clang++ -O3 -std=c++17 -Wall metro_analyzer.cpp -o metro_analyzer
echo "Compilation successful."

echo "=== Step 2: Preparing Raster Data ==="
python3 prepare_raster.py usa_ppp_2020_1km_Aggregated.tif

echo "=== Step 3: Running Metro Area Delineation Pipeline ==="
./metro_analyzer population.bin metadata.json

echo "Results saved to us_metro_areas.csv"
