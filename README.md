# Topological Metropolitan Area Delineation

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![C++17](https://img.shields.io/badge/Language-C%2B%2B17-00599C.svg)](https://isocpp.org/)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-3776AB.svg)](https://www.python.org/)
[![Resolution: 1 km](https://img.shields.io/badge/Resolution-1%20km%20(30%20arc--sec)-brightgreen.svg)](#data-sources)

A mathematically rigorous, purely topological framework for delineating metropolitan areas across the United States and the globe at native **1 km (30 arc-second)** spatial resolution.

Rather than relying on administrative proxies (such as county boundaries, municipal charters, or commuter travel surveys), this engine derives metropolitan boundaries directly from the continuous geometry and superlevel sets of the human population density surface.

---

## Table of Contents
1. [Why Administrative Boundaries Fail](#why-administrative-boundaries-fail)
2. [Mathematical Definition](#mathematical-definition)
   - [1. Continuous Density Surface & Smoothing](#1-continuous-density-surface--smoothing)
   - [2. Candidate Density Peaks (Local Maxima)](#2-candidate-density-peaks-local-maxima)
   - [3. Condition A: Steepest Uphill Watersheds](#3-condition-a-steepest-uphill-watersheds)
   - [4. Robust Anchor Metric: Population-Weighted $P_{95}$](#4-robust-anchor-metric-population-weighted-p_95)
   - [5. Condition B: Connected High-Density Corridors](#5-condition-b-connected-high-density-corridors)
   - [6. Satellite Peak Absorption & Frontier Gating](#6-satellite-peak-absorption--frontier-gating)
   - [7. Zero-Population Masking & Land Allocation](#7-zero-population-masking--land-allocation)
   - [8. Automated Municipal Anchor Naming](#8-automated-municipal-anchor-naming)
3. [Threshold Sensitivity Analysis ($\alpha$)](#threshold-sensitivity-analysis-alpha)
4. [Repository Architecture](#repository-architecture)
5. [Deliverables & Outputs](#deliverables--outputs)
6. [Building & Running the Pipeline](#building--running-the-pipeline)
7. [Data Sources & Acknowledgments](#data-sources--acknowledgments)

---

## Why Administrative Boundaries Fail

Standard government metropolitan definitions (such as the U.S. Office of Management and Budget's Metropolitan Statistical Areas / MSAs) are built from county aggregates. This introduces severe spatial distortions:
* **The Desert County Problem:** Large western counties (e.g., San Bernardino County, CA or Coconino County, AZ) attach thousands of square miles of empty desert to an urban core simply because county lines are historically broad.
* **The Fragmented Suburb Problem:** County borders arbitrarily bisect contiguous built environments, creating artificial barriers between economically and physically unified urban fabrics.
* **Commuter Survey Lag:** Survey-based travel flows lag real development patterns by decades and fail to capture morphological urban continuity.

This project reformulates metropolitan area delineation as a **topological problem on a scalar field** (the population density raster), providing a self-consistent, scale-invariant, and universally reproducible definition.

---

## Mathematical Definition

A point $(x, y)$ on the Earth's surface belongs to a metropolitan area defined by a primary population peak if it satisfies two complementary topological conditions:
* **Condition A (Downhill Watershed):** The point lies in the drainage basin of the peak along a path of strictly monotonically decreasing density.
* **Condition B (Connected Density Threshold):** The point is reachable from the peak along a contiguous path that never drops below a scale-relative threshold of the core's population density.

```
       Density ^
               |          Peak P1 (Core)
               |             /\
               |            /  \        Saddle
               |           /    \       (Passes Threshold B)
               |          /      \      /\  Peak P2 (Absorbed)
               |         /        \____/  \
     Threshold | - - - -/- - - - - - - - - \ - - - - - - - - - -
           (T) |       /                    \
               |      /                      \___ Condition A (Uphill Basin)
               +-----+--------------------------+------------------> Space
```

### 1. Continuous Density Surface & Smoothing
Given a raster of raw population counts $P(r, c)$ on a WGS-84 coordinate grid with cell spacing $\Delta\lambda = \Delta\phi = 30''$ (~1 km):
1. The geodesic surface area $A(r)$ of each cell at row $r$ (latitude $\phi$) is calculated using the WGS-84 ellipsoidal model:
   $$A(r) = R^2 \cdot \Delta\phi \cdot \Delta\lambda \cos(\phi)$$
2. Raw cell population density is:
   $$\rho(r, c) = \frac{P(r, c)}{A(r)} \quad [\text{people} / \text{km}^2]$$
3. To eliminate micro-architectural noise (e.g., single apartment blocks or parks) without blurring city-scale topology, a separable **2D Gaussian smoothing filter** ($\sigma = 1.5$ km / grid cells) is applied:
   $$S(r, c) = (\mathcal{G}_\sigma * \rho)(r, c)$$

### 2. Candidate Density Peaks (Local Maxima)
A cell $(r, c)$ is classified as a candidate density peak if its smoothed density exceeds all its 8-connected neighbors:
$$S(r, c) > S(r + \Delta r, c + \Delta c) \quad \forall (\Delta r, \Delta c) \in \{-1, 0, 1\}^2 \setminus \{(0, 0)\}$$
*(Ties are broken deterministically by linear cell index to enforce a strict total order).*
All candidate peaks are sorted in descending order of peak density: $S(P_1) \ge S(P_2) \ge \dots \ge S(P_n)$.

### 3. Condition A: Steepest Uphill Watersheds
For every populated cell $c$ ($P(c) > 0$), we compute the steepest ascent direction:
$$\text{Next}(c) = \arg\max_{n \in \mathcal{N}_8(c)} S(n)$$
Because $S(\text{Next}(c)) > S(c)$, tracing $\text{Next}(c)$ iteratively yields a strictly monotonic uphill trajectory terminating at exactly one candidate peak. The set of all cells whose uphill paths terminate at peak $P_i$ defines the **Condition A Basin** $\mathcal{B}(P_i)$. Every populated cell in the landscape belongs to exactly one basin.

### 4. Robust Anchor Metric: Population-Weighted $P_{95}$
A critical theoretical challenge is setting the threshold $T$ without causing infinite runaway cascades:
* If $T$ is set as a percentage of the single highest pixel peak, ultra-dense high-rises make thresholds unrealistically strict for the rest of the metro.
* If $T$ is based on the *area-weighted* percentile across the Condition A basin, sparse rural land dilutes the metric to near zero, causing the metro to swallow entire continents.

**The Solution:** We anchor the threshold to the **population-weighted 95th percentile density** ($P_{95}$) of the core basin:
$$P_{95}(\mathcal{B}_i) = \inf \left\{ d \;\Bigg|\; \sum_{c \in \mathcal{B}_i, S(c) \le d} P(c) \;\ge\; 0.95 \sum_{c \in \mathcal{B}_i} P(c) \right\}$$
This measures the actual density experienced by 95% of the basin's residents, remaining completely invariant to empty surrounding terrain. The metropolitan density threshold is then:
$$T_i = \alpha \cdot P_{95}(\mathcal{B}_i)$$
where $\alpha \in (0, 1)$ is the threshold percentage (e.g., $\alpha = 0.07$ for the standard 7% threshold).

### 5. Condition B: Connected High-Density Corridors
Beginning from the core basin $\mathcal{B}(P_i)$, a Breadth-First Search (BFS) expands across 8-connected neighbors that meet the density threshold:
$$\text{Condition B Frontier: } \{ c \mid S(c) \ge T_i \}$$

### 6. Satellite Peak Absorption & Frontier Gating
When the BFS frontier encounters a cell belonging to a secondary peak $P_j$ ($j > i$):
1. Peak $P_j$ is **absorbed** into the primary metropolitan area $M_i$. This naturally merges multi-nucleated regions (e.g., Dallas–Fort Worth, Minneapolis–St. Paul, Salt Lake City–Provo–Ogden).
2. The entire Condition A basin $\mathcal{B}(P_j)$ is claimed by $M_i$.
3. **Frontier Gating Rule (Anti-Cascade):** While $\mathcal{B}(P_j)$ is claimed, **only cells with $S(c) \ge T_i$ are added to the active BFS queue**. Cells below $T_i$ cannot propagate expansion. This strictly bounds expansion, preventing rural saddles from chaining independent cities together (e.g., keeping Seattle and Tacoma distinct at 20%+ thresholds, and preventing Boston from fusing into New York).

### 7. Zero-Population Masking & Land Allocation
* Populated contiguous land cells ($P(c) > 0$) lying between competing basins are allocated via shortest-path watershed propagation to their nearest claiming metro.
* Completely unpopulated land ($P(c) \le 0$) is strictly masked and excluded, ensuring wilderness, deserts, and national parks are never misattributed to urban areas.

### 8. Automated Municipal Anchor Naming
To remove human naming bias, each metro area is identified using a spatial search tree against comprehensive gazetteers:
* **United States:** USGS / Census gazetteer of 29,828 incorporated places.
* **Global:** GeoNames gazetteer of 148,000 global populated places.
Each metropolitan polygon is named after the most populous municipality located within 35 km of its primary or absorbed core peaks.

---

## Threshold Sensitivity Analysis ($\alpha$)

The framework evaluates delineation across a continuous spectrum of scale parameters $\alpha$:

| Threshold $\alpha$ | Classification | Architectural Behavior | Representative Examples |
|---|---|---|---|
| **1% – 4%** | **Megalopolitan / Macro** | Captures extensive continuous commuter sheds and dense inter-city corridors. | Wasatch Front (SLC-Provo-Ogden unified), Northeast Megalopolis (Bos-Wash corridor). |
| **7% (Standard)** | **Metropolitan Area** | **The gold standard equilibrium.** Perfectly separates adjacent independent metros while preserving contiguous suburban/exurban rings. | Dallas-Fort Worth, Minneapolis-St. Paul, Tel Aviv-Gush Dan. |
| **15% – 25%** | **Core / Micro-Urban** | Isolates central dense city footprints and splits polycentric satellites into independent hubs. | Seattle, Tacoma, and Everett separate into distinct individual metros. |

---

## Repository Architecture

```text
.
├── README.md                           # Formal mathematical formulation & project documentation
├── .gitignore                          # Excludes raw multi-gigabyte rasters & compiled binaries
├── us_analyzer/                        # United States 1 km Analysis Pipeline
│   ├── metro_analyzer.cpp              # C++ high-speed watershed & BFS delineation engine
│   ├── prepare_raster.py               # GeoTIFF preprocessing into memory-mapped raw binary rasters
│   ├── build_interactive_map.py        # Interactive Leaflet web map generator
│   ├── create_excel.py                 # Formatted Excel report generator
│   ├── generate_full_cities.py         # Municipal anchor database builder
│   ├── vectorize_grid.py               # Raster-to-GeoJSON polygon vectorizer
│   ├── us_cities.csv                   # Database of 29,828 U.S. municipalities
│   ├── us_cities.hpp                   # Fast spatial lookup header for C++
│   ├── us-states.json                  # U.S. state boundary outlines
│   ├── metadata.json                   # U.S. raster coordinate reference metadata
│   └── Makefile                        # Build script for C++ engine
├── global_engine/                      # Worldwide Multi-Continental Engine
│   ├── metro_engine.cpp                # Ultra-efficient continental engine (supports 8 GB RAM machines)
│   ├── global_metro.cpp                # Multi-threaded global orchestrator
│   ├── prepare_continental_rasters.py  # Slices global GHS-POP into continental blocks
│   ├── prepare_global_raster.py        # Global raster preprocessor
│   ├── build_multilevel_map.py         # Multi-threshold interactive map generator
│   ├── build_vector_global_map.py      # Vector GeoJSON map generator
│   ├── generate_excel_deliverables.py  # Generates sorted, beautifully styled continental spreadsheets
│   ├── world_cities.csv                # 148,000 GeoNames cities with spatial binning
│   ├── run_pipeline.sh                 # End-to-end execution script
│   └── meta_*.json                     # Bounding boxes and grid dimensions per continent
└── data/                               # Pre-computed Deliverables & Results
    ├── us_metro_areas.csv              # Complete U.S. metro catalog (population, area, density, P95)
    ├── us_metro_areas.xlsx             # Styled Excel workbook of U.S. metro areas
    ├── us_metro_areas.geojson          # Vector boundary polygons for all U.S. metros
    ├── us_metro_map.html               # Standalone interactive Leaflet web map of U.S. metros
    ├── global_metro_areas_7pct.xlsx    # Global metropolitan catalog at 7% threshold
    ├── global_metro_areas_25pct.xlsx   # Global metropolitan catalog at 25% threshold
    ├── global_metro_areas_7pct.csv.gz  # Compressed CSV of all global 7% metros
    └── global_metro_areas_25pct.csv.gz # Compressed CSV of all global 25% metros
```

---

## Deliverables & Outputs

All results are provided in both spreadsheet formats and interactive geographic visualizations:
* **Interactive U.S. Metro Map (`data/us_metro_map.html`):** Explore every metropolitan area in the contiguous United States with color-coded boundaries, core peak markers, population statistics, and municipal anchor tags.
* **Global Spreadsheets (`data/global_metro_areas_7pct.xlsx`):** Ranks every metro area across North America, South America, Europe, Africa, Asia, Oceania, and the Pacific Islands with core coordinates, population, land area, and threshold metrics.

---

## Building & Running the Pipeline

### Prerequisites
* C++17 compatible compiler (`clang++` or `g++`)
* Python 3.9+ with `numpy`, `rasterio`, and `openpyxl`
* [GDAL](https://gdal.org/) for raster transformations

### 1. Compile the Engines
```bash
# Compile U.S. Engine
cd us_analyzer
make

# Compile Continental Engine
cd ../global_engine
g++ -O3 -std=c++17 -march=native metro_engine.cpp -o metro_engine
```

### 2. Run the U.S. Delineation
```bash
cd us_analyzer
./metro_analyzer 0.04
python3 build_interactive_map.py
```

### 3. Run the Global Delineation
```bash
cd global_engine
./run_pipeline.sh
```

---

## Data Sources & Acknowledgments

* **Global Human Settlement Layer (GHSL):** European Commission, JRC — *GHS-POP R2023A (30 arcsec / 1 km)*.
* **WorldPop:** University of Southampton — *Global 1 km Population Grids*.
* **GeoNames:** Geographical database of global cities and populated places (>1,000 residents).
* **U.S. Geological Survey (USGS) & U.S. Census Bureau:** Incorporated places gazetteers and TIGER boundary shapefiles.

---

## License

This project is licensed under the [MIT License](LICENSE).
