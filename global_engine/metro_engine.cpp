/*
 * Continental Metropolitan Delineation Engine
 * ===========================================
 * Precision 1 km (30 arc-sec) Native Resolution
 * 
 * Implements the exact mathematical definition:
 *   1. Candidate peaks: all local maxima with raw_pop > 0 (no arbitrary cutoffs)
 *   2. Condition A: steepest uphill watershed assigns every populated cell to a peak basin
 *   3. Core Density P95: weighted 95th percentile density of the core peak basin
 *   4. Condition B: BFS expansion strictly along smooth_density >= Threshold
 *      Satellite peak absorption: satellite basin cells are claimed, but ONLY cells
 *      with smooth_density >= Threshold propagate the BFS frontier (fixing Seattle/Tacoma cascade)
 *   5. Land allocation: remaining contiguous unassigned cells with raw_pop > 0 allocated via land_q
 *      Zero-population cells (raw_pop <= 0) remain strictly uncolored (rank 0)
 *   6. Municipal Anchor naming: highest-population municipality within 35 km
 */

#include <iostream>
#include <vector>
#include <string>
#include <fstream>
#include <sstream>
#include <cmath>
#include <algorithm>
#include <queue>
#include <iomanip>
#include <chrono>
#include <unordered_set>
#include <unordered_map>
#include <cstring>

struct RasterMeta {
    std::string name;
    int rows = 0;
    int cols = 0;
    double origin_lon = 0.0;
    double origin_lat = 0.0;
    double pixel_size_lon = 0.0083333333;
    double pixel_size_lat = 0.0083333333;
    double total_pop = 0.0;
};

struct CityEntry {
    std::string name;
    std::string country;
    double lat;
    double lon;
    int population;
};

struct MetroArea {
    int id;
    int root_peak_idx;
    int peak_r;
    int peak_c;
    double peak_lat;
    double peak_lon;
    std::string name;
    std::string country;
    double peak_density;
    double p95_density;
    double threshold_density;
    double total_pop;
    double total_area_sqkm;
    double avg_density;
    int absorbed_peaks_count;
};

// ============= Spatial Hashing for 148K World Cities =============
static std::vector<CityEntry> g_cities;
static std::vector<int> g_city_bins[181][361];

void load_cities(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) {
        std::cerr << "Warning: Could not open " << path << "\n";
        return;
    }
    std::string line;
    std::getline(file, line); // header
    while (std::getline(file, line)) {
        if (line.empty()) continue;
        std::stringstream ss(line);
        std::string name, country, lat_s, lon_s, pop_s;
        if (line[0] == '"') {
            size_t end_q = line.find("\",", 1);
            if (end_q == std::string::npos) continue;
            name = line.substr(1, end_q - 1);
            std::string rest = line.substr(end_q + 2);
            ss.str(rest);
            ss.clear();
        } else {
            std::getline(ss, name, ',');
        }
        std::getline(ss, country, ',');
        std::getline(ss, lat_s, ',');
        std::getline(ss, lon_s, ',');
        std::getline(ss, pop_s, ',');
        if (lat_s.empty() || lon_s.empty() || pop_s.empty()) continue;
        CityEntry ce;
        ce.name = name;
        ce.country = country;
        try {
            ce.lat = std::stod(lat_s);
            ce.lon = std::stod(lon_s);
            ce.population = std::stoi(pop_s);
        } catch (...) { continue; }
        int idx = (int)g_cities.size();
        g_cities.push_back(std::move(ce));

        int b_lat = std::clamp((int)std::floor(g_cities[idx].lat + 90.0), 0, 180);
        int b_lon = std::clamp((int)std::floor(g_cities[idx].lon + 180.0), 0, 360);
        g_city_bins[b_lat][b_lon].push_back(idx);
    }
    std::cout << "Loaded " << g_cities.size() << " cities into spatial grid index.\n";
}

struct CityLookupResult {
    std::string name;
    std::string country;
    int pop = 0;
};

// Select the municipality with the HIGHEST POPULATION within search radius
CityLookupResult find_best_anchor(double lat, double lon, double max_dist_km = 35.0) {
    int best_idx = -1;
    int best_pop = -1;
    double max_dist_sq = max_dist_km * max_dist_km;
    double rlat = lat * M_PI / 180.0;
    double cos_lat = std::cos(rlat);

    int center_lat_bin = std::clamp((int)std::floor(lat + 90.0), 0, 180);
    int center_lon_bin = std::clamp((int)std::floor(lon + 180.0), 0, 360);
    int delta_bin = (int)std::ceil(max_dist_km / 100.0) + 1;

    for (int d_lat = -delta_bin; d_lat <= delta_bin; ++d_lat) {
        int b_lat = center_lat_bin + d_lat;
        if (b_lat < 0 || b_lat > 180) continue;

        for (int d_lon = -delta_bin; d_lon <= delta_bin; ++d_lon) {
            int b_lon = center_lon_bin + d_lon;
            while (b_lon < 0) b_lon += 360;
            while (b_lon >= 360) b_lon -= 360;

            for (int city_idx : g_city_bins[b_lat][b_lon]) {
                double dlat = (g_cities[city_idx].lat - lat) * 111.32;
                double dlon_deg = g_cities[city_idx].lon - lon;
                if (dlon_deg > 180.0) dlon_deg -= 360.0;
                if (dlon_deg < -180.0) dlon_deg += 360.0;
                double dlon = dlon_deg * 111.32 * cos_lat;

                double dist_sq = dlat * dlat + dlon * dlon;
                if (dist_sq <= max_dist_sq) {
                    if (g_cities[city_idx].population > best_pop) {
                        best_pop = g_cities[city_idx].population;
                        best_idx = city_idx;
                    }
                }
            }
        }
    }

    if (best_idx >= 0) {
        return {g_cities[best_idx].name, g_cities[best_idx].country, g_cities[best_idx].population};
    }

    // Fallback: nearest city if no city within max_dist_km
    double best_dist_sq = 1e18;
    int nearest_idx = -1;
    for (int d_lat = -2; d_lat <= 2; ++d_lat) {
        int b_lat = center_lat_bin + d_lat;
        if (b_lat < 0 || b_lat > 180) continue;
        for (int d_lon = -2; d_lon <= 2; ++d_lon) {
            int b_lon = center_lon_bin + d_lon;
            while (b_lon < 0) b_lon += 360;
            while (b_lon >= 360) b_lon -= 360;
            for (int city_idx : g_city_bins[b_lat][b_lon]) {
                double dlat = (g_cities[city_idx].lat - lat) * 111.32;
                double dlon_deg = g_cities[city_idx].lon - lon;
                if (dlon_deg > 180.0) dlon_deg -= 360.0;
                if (dlon_deg < -180.0) dlon_deg += 360.0;
                double dlon = dlon_deg * 111.32 * cos_lat;
                double dist_sq = dlat * dlat + dlon * dlon;
                if (dist_sq < best_dist_sq) {
                    best_dist_sq = dist_sq;
                    nearest_idx = city_idx;
                }
            }
        }
    }
    if (nearest_idx >= 0) {
        return {g_cities[nearest_idx].name, g_cities[nearest_idx].country, g_cities[nearest_idx].population};
    }

    char buf[64];
    std::snprintf(buf, sizeof(buf), "Location (%.2f, %.2f)", lat, lon);
    return {std::string(buf), "Global", 0};
}

bool load_metadata(const std::string& meta_path, RasterMeta& meta) {
    std::ifstream file(meta_path);
    if (!file.is_open()) return false;
    std::string line;
    while (std::getline(file, line)) {
        auto parse_double = [&](const std::string& key, double& val) {
            auto pos = line.find("\"" + key + "\"");
            if (pos != std::string::npos) {
                auto colon = line.find(":", pos);
                if (colon != std::string::npos) val = std::stod(line.substr(colon + 1));
            }
        };
        auto parse_int = [&](const std::string& key, int& val) {
            auto pos = line.find("\"" + key + "\"");
            if (pos != std::string::npos) {
                auto colon = line.find(":", pos);
                if (colon != std::string::npos) val = std::stoi(line.substr(colon + 1));
            }
        };
        auto parse_str = [&](const std::string& key, std::string& val) {
            auto pos = line.find("\"" + key + "\"");
            if (pos != std::string::npos) {
                auto colon = line.find(":", pos);
                if (colon != std::string::npos) {
                    auto q1 = line.find("\"", colon + 1);
                    auto q2 = line.find("\"", q1 + 1);
                    if (q1 != std::string::npos && q2 != std::string::npos)
                        val = line.substr(q1 + 1, q2 - q1 - 1);
                }
            }
        };
        parse_str("name", meta.name);
        parse_int("rows", meta.rows);
        parse_int("cols", meta.cols);
        parse_double("origin_lon", meta.origin_lon);
        parse_double("origin_lat", meta.origin_lat);
        parse_double("pixel_size_lon", meta.pixel_size_lon);
        parse_double("pixel_size_lat", meta.pixel_size_lat);
        parse_double("total_pop", meta.total_pop);
    }
    return true;
}

// Separable Gaussian smoothing (sigma in grid cells)
void apply_gaussian_smoothing(const std::vector<float>& input, std::vector<float>& output,
                              int rows, int cols, float sigma = 1.5f) {
    output.resize((size_t)rows * cols);
    int radius = (int)std::ceil(3.0f * sigma);
    int k_size = 2 * radius + 1;
    std::vector<float> kernel(k_size);
    float sum = 0.0f;
    for (int i = -radius; i <= radius; ++i) {
        float val = std::exp(-(i * i) / (2.0f * sigma * sigma));
        kernel[i + radius] = val;
        sum += val;
    }
    for (float& w : kernel) w /= sum;

    std::vector<float> temp((size_t)rows * cols);

    // Horizontal pass
    for (int r = 0; r < rows; ++r) {
        size_t row_offset = (size_t)r * cols;
        for (int c = 0; c < cols; ++c) {
            float val = 0.0f;
            float w_sum = 0.0f;
            for (int k = -radius; k <= radius; ++k) {
                int sc = c + k;
                if (sc >= 0 && sc < cols) {
                    float w = kernel[k + radius];
                    val += input[row_offset + sc] * w;
                    w_sum += w;
                }
            }
            temp[row_offset + c] = (w_sum > 0.0f) ? (val / w_sum) : 0.0f;
        }
    }

    // Vertical pass
    for (int r = 0; r < rows; ++r) {
        size_t row_offset = (size_t)r * cols;
        for (int c = 0; c < cols; ++c) {
            float val = 0.0f;
            float w_sum = 0.0f;
            for (int k = -radius; k <= radius; ++k) {
                int sr = r + k;
                if (sr >= 0 && sr < rows) {
                    float w = kernel[k + radius];
                    val += temp[(size_t)sr * cols + c] * w;
                    w_sum += w;
                }
            }
            output[row_offset + c] = (w_sum > 0.0f) ? (val / w_sum) : 0.0f;
        }
    }
}

inline double get_cell_area_km2(int r, const RasterMeta& meta) {
    const double R = 6371.0;
    double lat = meta.origin_lat - (r + 0.5) * meta.pixel_size_lat;
    double dlat_rad = meta.pixel_size_lat * M_PI / 180.0;
    double dlon_rad = meta.pixel_size_lon * M_PI / 180.0;
    double dy = R * dlat_rad;
    double dx = R * std::cos(lat * M_PI / 180.0) * dlon_rad;
    return std::abs(dy * dx);
}

double calc_weighted_p95(const std::vector<int>& cells,
                         const std::vector<float>& smoothed_density,
                         const std::vector<float>& raw_pop) {
    if (cells.empty()) return 0.0;
    struct DP { float density; float pop; };
    std::vector<DP> items;
    items.reserve(cells.size());
    double total_w = 0.0;
    for (int idx : cells) {
        float p = raw_pop[idx];
        if (p > 0.0f) {
            items.push_back({smoothed_density[idx], p});
            total_w += p;
        }
    }
    if (total_w <= 0.0 || items.empty()) return 0.0;
    std::sort(items.begin(), items.end(), [](const DP& a, const DP& b) {
        return a.density < b.density;
    });
    double target_w = 0.95 * total_w;
    double cumulative_w = 0.0;
    for (const auto& item : items) {
        cumulative_w += item.pop;
        if (cumulative_w >= target_w) return item.density;
    }
    return items.back().density;
}

struct Neighbor {
    int r, c;
};

inline void get_neighbors(int r, int c, int rows, int cols, Neighbor out[8], int& count) {
    static const int dr[8] = {-1, -1, -1,  0, 0,  1, 1, 1};
    static const int dc[8] = {-1,  0,  1, -1, 1, -1, 0, 1};
    count = 0;
    for (int k = 0; k < 8; ++k) {
        int nr = r + dr[k];
        int nc = c + dc[k];
        if (nr >= 0 && nr < rows && nc >= 0 && nc < cols) {
            out[count++] = {nr, nc};
        }
    }
}

int main(int argc, char** argv) {
    std::string region = "north_america";
    if (argc > 1) region = argv[1];

    std::vector<double> threshold_levels = {1.0, 4.0, 7.0, 15.0, 25.0};
    if (argc > 2) {
        threshold_levels.clear();
        for (int i = 2; i < argc; ++i) threshold_levels.push_back(std::stod(argv[i]));
    }

    std::cout << "========================================================\n";
    std::cout << "   CONTINENTAL METRO DELINEATION: " << region << "\n";
    std::cout << "   Resolution: True 1 km (30 arc-sec native)\n";
    std::cout << "   Thresholds: ";
    for (double t : threshold_levels) std::cout << (int)t << "% ";
    std::cout << "\n========================================================\n\n";

    auto t_total_start = std::chrono::high_resolution_clock::now();

    std::string meta_path = "meta_" + region + ".json";
    std::string bin_path = "pop_" + region + ".bin";

    RasterMeta meta;
    if (!load_metadata(meta_path, meta)) {
        std::cerr << "Failed to load " << meta_path << "\n";
        return 1;
    }
    std::cout << "Region: " << meta.name << " (" << meta.rows << " rows x " << meta.cols << " cols = "
              << (size_t)meta.rows * meta.cols << " cells)\n";
    std::cout << "Total Pop in Meta: " << std::fixed << std::setprecision(0) << meta.total_pop << "\n";

    load_cities("world_cities.csv");

    size_t total_cells = (size_t)meta.rows * meta.cols;
    std::vector<float> raw_pop(total_cells);
    {
        std::ifstream bin_file(bin_path, std::ios::binary);
        if (!bin_file.is_open()) {
            std::cerr << "Failed to open " << bin_path << "\n";
            return 1;
        }
        bin_file.read(reinterpret_cast<char*>(raw_pop.data()), total_cells * sizeof(float));
        bin_file.close();
    }

    std::vector<double> row_areas(meta.rows);
    for (int r = 0; r < meta.rows; ++r) row_areas[r] = get_cell_area_km2(r, meta);

    std::vector<float> raw_density(total_cells, 0.0f);
    size_t pop_cells = 0;
    double actual_total_pop = 0.0;
    for (int r = 0; r < meta.rows; ++r) {
        double area = row_areas[r];
        size_t row_offset = (size_t)r * meta.cols;
        for (int c = 0; c < meta.cols; ++c) {
            size_t idx = row_offset + c;
            float p = raw_pop[idx];
            if (p > 0.0f && area > 0.0) {
                raw_density[idx] = (float)(p / area);
                pop_cells++;
                actual_total_pop += p;
            }
        }
    }
    std::cout << "Populated land cells: " << pop_cells << ", Actual pop: "
              << std::fixed << std::setprecision(0) << actual_total_pop << "\n";

    std::cout << "Smoothing density (Gaussian sigma=1.5 cells)... " << std::flush;
    auto t0 = std::chrono::high_resolution_clock::now();
    std::vector<float> smooth_density;
    apply_gaussian_smoothing(raw_density, smooth_density, meta.rows, meta.cols, 1.5f);
    auto t1 = std::chrono::high_resolution_clock::now();
    std::cout << "Done (" << std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count() << " ms)\n";

    // Free raw_density immediately
    { std::vector<float>().swap(raw_density); }

    // Condition A steepest uphill watershed with strict total order (density, -idx)
    // Guarantees an acyclic tree where EVERY populated cell terminates at a peak!
    std::cout << "Finding candidate density peaks & uphill watersheds... " << std::flush;
    t0 = std::chrono::high_resolution_clock::now();
    std::vector<int> uphill_target(total_cells, -1);
    std::vector<int> peak_indices;
    Neighbor nbrs[8];
    int n_count;

    for (int r = 0; r < meta.rows; ++r) {
        size_t row_offset = (size_t)r * meta.cols;
        for (int c = 0; c < meta.cols; ++c) {
            size_t idx = row_offset + c;
            if (raw_pop[idx] <= 0.0f) continue;
            float val = smooth_density[idx];
            if (val <= 0.0f) continue;

            float max_val = val;
            int best_n = (int)idx;

            get_neighbors(r, c, meta.rows, meta.cols, nbrs, n_count);
            for (int k = 0; k < n_count; ++k) {
                size_t n_idx = (size_t)nbrs[k].r * meta.cols + nbrs[k].c;
                if (raw_pop[n_idx] <= 0.0f) continue;
                float n_val = smooth_density[n_idx];
                if (n_val > max_val || (n_val == max_val && (int)n_idx < best_n)) {
                    max_val = n_val;
                    best_n = (int)n_idx;
                }
            }
            if (best_n == (int)idx) {
                peak_indices.push_back((int)idx);
            } else {
                uphill_target[idx] = best_n;
            }
        }
    }

    std::sort(peak_indices.begin(), peak_indices.end(), [&](int a, int b) {
        return smooth_density[a] > smooth_density[b];
    });

    std::vector<int> cell_peak_id(total_cells, -1);
    for (size_t i = 0; i < peak_indices.size(); ++i) {
        cell_peak_id[peak_indices[i]] = (int)i;
    }

    for (size_t idx = 0; idx < total_cells; ++idx) {
        if (raw_pop[idx] <= 0.0f) continue;
        int curr = (int)idx;
        std::vector<int> path;
        while (curr != -1 && cell_peak_id[curr] == -1) {
            path.push_back(curr);
            curr = uphill_target[curr];
        }
        int root_peak = (curr != -1) ? cell_peak_id[curr] : -1;
        for (int node : path) cell_peak_id[node] = root_peak;
    }

    // Free uphill_target
    { std::vector<int>().swap(uphill_target); }

    std::vector<std::vector<int>> peak_basins(peak_indices.size());
    for (size_t idx = 0; idx < total_cells; ++idx) {
        int pid = cell_peak_id[idx];
        if (pid >= 0 && pid < (int)peak_basins.size()) {
            peak_basins[pid].push_back((int)idx);
        }
    }
    t1 = std::chrono::high_resolution_clock::now();
    std::cout << "Found " << peak_indices.size() << " candidate peaks in "
              << std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count() << " ms.\n";

    // Precalculate peak core P95 densities
    std::cout << "Precalculating peak core P95 densities... " << std::flush;
    t0 = std::chrono::high_resolution_clock::now();
    std::vector<double> peak_core_p95(peak_indices.size(), 0.0);
    for (size_t p = 0; p < peak_indices.size(); ++p) {
        peak_core_p95[p] = calc_weighted_p95(peak_basins[p], smooth_density, raw_pop);
    }
    t1 = std::chrono::high_resolution_clock::now();
    std::cout << "Done (" << std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count() << " ms)\n\n";

    // Reusable buffers
    std::vector<int> claimed_metro_id(total_cells, -2);
    std::vector<uint8_t> in_current_metro(total_cells, 0);

    for (double thresh_pct : threshold_levels) {
        double threshold_fraction = thresh_pct / 100.0;
        int pct_int = (int)std::round(thresh_pct);

        auto t_thresh_start = std::chrono::high_resolution_clock::now();
        std::cout << ">>> Running Threshold " << pct_int << "%... " << std::flush;

        // Reset claimed_metro_id: -1 for available populated cells, -2 for pop 0
        for (size_t i = 0; i < total_cells; ++i) {
            claimed_metro_id[i] = (raw_pop[i] > 0.0f) ? -1 : -2;
        }

        std::vector<bool> peak_absorbed(peak_indices.size(), false);
        std::vector<MetroArea> metros;
        std::unordered_map<std::string, int> name_counts;

        for (size_t p = 0; p < peak_indices.size(); ++p) {
            if (peak_absorbed[p]) continue;

            int root_peak_idx = peak_indices[p];
            if (claimed_metro_id[root_peak_idx] != -1) continue;

            int root_r = root_peak_idx / meta.cols;
            int root_c = root_peak_idx % meta.cols;
            double peak_lat = meta.origin_lat - (root_r + 0.5) * meta.pixel_size_lat;
            double peak_lon = meta.origin_lon + (root_c + 0.5) * meta.pixel_size_lon;
            double peak_dens = smooth_density[root_peak_idx];

            std::vector<int> current_cells;
            for (int c_idx : peak_basins[p]) {
                if (claimed_metro_id[c_idx] == -1) {
                    current_cells.push_back(c_idx);
                    in_current_metro[c_idx] = 1;
                }
            }
            if (current_cells.empty()) continue;
            peak_absorbed[p] = true;

            double p95 = peak_core_p95[p];
            if (p95 <= 0.0) p95 = peak_dens;
            double threshold = threshold_fraction * p95;

            std::vector<int> absorbed_peaks_in_metro;
            absorbed_peaks_in_metro.push_back((int)p);

            std::queue<int> frontier;
            for (int c_idx : current_cells) frontier.push(c_idx);

            while (!frontier.empty()) {
                int curr = frontier.front();
                frontier.pop();

                int cr = curr / meta.cols;
                int cc_val = curr % meta.cols;

                get_neighbors(cr, cc_val, meta.rows, meta.cols, nbrs, n_count);
                for (int k = 0; k < n_count; ++k) {
                    int nr = nbrs[k].r;
                    int nc = nbrs[k].c;
                    int n_idx = nr * meta.cols + nc;

                    if (in_current_metro[n_idx]) continue;
                    if (claimed_metro_id[n_idx] != -1) continue;

                    // Condition B contiguity threshold test
                    if (smooth_density[n_idx] >= threshold) {
                        in_current_metro[n_idx] = 1;
                        current_cells.push_back(n_idx);
                        frontier.push(n_idx);

                        int n_pid = cell_peak_id[n_idx];
                        if (n_pid >= 0 && !peak_absorbed[n_pid]) {
                            peak_absorbed[n_pid] = true;
                            absorbed_peaks_in_metro.push_back(n_pid);

                            for (int basin_cell : peak_basins[n_pid]) {
                                if (!in_current_metro[basin_cell] && claimed_metro_id[basin_cell] == -1) {
                                    in_current_metro[basin_cell] = 1;
                                    current_cells.push_back(basin_cell);
                                    // CRITICAL: Only push to frontier if density >= threshold!
                                    // This strictly halts propagation at rural troughs and prevents runaway absorption cascades.
                                    if (smooth_density[basin_cell] >= threshold) {
                                        frontier.push(basin_cell);
                                    }
                                }
                            }
                        }
                    }
                }
            }

            int metro_id = (int)metros.size();
            for (int c_idx : current_cells) {
                claimed_metro_id[c_idx] = metro_id;
                in_current_metro[c_idx] = 0;
            }

            // Find best municipal anchor (highest population city within 35 km)
            CityLookupResult best_anchor = find_best_anchor(peak_lat, peak_lon, 35.0);
            for (size_t k = 1; k < absorbed_peaks_in_metro.size(); ++k) {
                int sub_p = absorbed_peaks_in_metro[k];
                int sub_idx = peak_indices[sub_p];
                int sr = sub_idx / meta.cols;
                int sc = sub_idx % meta.cols;
                double slat = meta.origin_lat - (sr + 0.5) * meta.pixel_size_lat;
                double slon = meta.origin_lon + (sc + 0.5) * meta.pixel_size_lon;
                CityLookupResult sub_anchor = find_best_anchor(slat, slon, 35.0);
                if (sub_anchor.pop > best_anchor.pop) best_anchor = sub_anchor;
            }

            std::string metro_name = best_anchor.name;
            int count = ++name_counts[metro_name];
            if (count > 1) {
                metro_name += " " + std::to_string(count);
            }

            MetroArea ma;
            ma.id = metro_id;
            ma.root_peak_idx = root_peak_idx;
            ma.peak_r = root_r;
            ma.peak_c = root_c;
            ma.peak_lat = peak_lat;
            ma.peak_lon = peak_lon;
            ma.name = metro_name;
            ma.country = best_anchor.country;
            ma.peak_density = peak_dens;
            ma.p95_density = p95;
            ma.threshold_density = threshold;
            ma.total_pop = 0;
            ma.total_area_sqkm = 0;
            ma.avg_density = 0;
            ma.absorbed_peaks_count = (int)absorbed_peaks_in_metro.size() - 1;

            metros.push_back(ma);
        }

        // Allocate remaining populated unassigned land (raw_pop > 0), leaving 0-pop cells unassigned
        std::queue<int> land_q;
        for (size_t idx = 0; idx < total_cells; ++idx) {
            if (claimed_metro_id[idx] >= 0) land_q.push((int)idx);
        }

        while (!land_q.empty()) {
            int curr = land_q.front();
            land_q.pop();
            int mid = claimed_metro_id[curr];

            int cr = curr / meta.cols;
            int cc_val = curr % meta.cols;

            get_neighbors(cr, cc_val, meta.rows, meta.cols, nbrs, n_count);
            for (int k = 0; k < n_count; ++k) {
                int nr = nbrs[k].r;
                int nc = nbrs[k].c;
                size_t n_idx = (size_t)nr * meta.cols + nc;
                if (claimed_metro_id[n_idx] == -1 && raw_pop[n_idx] > 0.0f) {
                    claimed_metro_id[n_idx] = mid;
                    land_q.push((int)n_idx);
                }
            }
        }

        // Calculate totals strictly on populated colored cells
        for (auto& m : metros) {
            m.total_pop = 0;
            m.total_area_sqkm = 0;
        }
        for (size_t idx = 0; idx < total_cells; ++idx) {
            int mid = claimed_metro_id[idx];
            if (mid >= 0 && mid < (int)metros.size() && raw_pop[idx] > 0.0f) {
                int cr = (int)(idx / meta.cols);
                metros[mid].total_pop += raw_pop[idx];
                metros[mid].total_area_sqkm += row_areas[cr];
            }
        }
        for (auto& m : metros) {
            m.avg_density = m.total_area_sqkm > 0 ? (m.total_pop / m.total_area_sqkm) : 0;
        }

        // Sort by population descending
        std::sort(metros.begin(), metros.end(), [](const MetroArea& a, const MetroArea& b) {
            return a.total_pop > b.total_pop;
        });

        // Map each cell to 1-based rank (0 for uncolored ocean/desert)
        int max_mid = 0;
        for (const auto& m : metros) if (m.id > max_mid) max_mid = m.id;
        std::vector<int32_t> id_to_rank(max_mid + 1, 0);
        for (size_t r = 0; r < metros.size(); ++r) {
            id_to_rank[metros[r].id] = (int32_t)(r + 1);
        }

        std::vector<int32_t> metro_ranks(total_cells, 0);
        size_t colored_count = 0;
        double colored_pop = 0.0;
        for (size_t idx = 0; idx < total_cells; ++idx) {
            int mid = claimed_metro_id[idx];
            if (mid >= 0 && mid < (int)id_to_rank.size() && raw_pop[idx] > 0.0f) {
                metro_ranks[idx] = id_to_rank[mid];
                colored_count++;
                colored_pop += raw_pop[idx];
            } else {
                metro_ranks[idx] = 0;
            }
        }

        auto t_thresh_end = std::chrono::high_resolution_clock::now();
        long ms = std::chrono::duration_cast<std::chrono::milliseconds>(t_thresh_end - t_thresh_start).count();
        std::cout << metros.size() << " metros | Colored: " << colored_count << " cells ("
                  << std::fixed << std::setprecision(0) << colored_pop << " ppl, "
                  << std::setprecision(2) << (colored_pop / actual_total_pop * 100.0) << "%) in "
                  << ms << " ms\n";

        // Write binary rank grid (int32_t to support up to 2 billion metros with 0 overflow)
        char buf[64];
        std::snprintf(buf, sizeof(buf), "metro_ranks_%s_%02d.bin", region.c_str(), pct_int);
        std::ofstream grid_out(buf, std::ios::binary);
        grid_out.write(reinterpret_cast<const char*>(metro_ranks.data()), total_cells * sizeof(int32_t));
        grid_out.close();

        // Write CSV report
        std::snprintf(buf, sizeof(buf), "metro_areas_%s_%02d.csv", region.c_str(), pct_int);
        std::ofstream csv(buf);
        csv << "Rank,Core_Name,Country,Peak_Latitude,Peak_Longitude,Total_Population,Total_Area_sqkm,Avg_Density_ppl_km2,Peak_Density,P95_Weighted_Density,Threshold_Density,Absorbed_Peaks_Count\n";
        for (size_t i = 0; i < metros.size(); ++i) {
            const auto& m = metros[i];
            if (m.total_pop < 1.0) continue;
            csv << (i + 1) << ",\""
                << m.name << "\","
                << m.country << ","
                << std::fixed << std::setprecision(4)
                << m.peak_lat << "," << m.peak_lon << ","
                << std::setprecision(0) << m.total_pop << ","
                << std::setprecision(1) << m.total_area_sqkm << ","
                << std::setprecision(1) << m.avg_density << ","
                << std::setprecision(1) << m.peak_density << ","
                << std::setprecision(1) << m.p95_density << ","
                << std::setprecision(1) << m.threshold_density << ","
                << m.absorbed_peaks_count << "\n";
        }
        csv.close();
    }

    auto t_total_end = std::chrono::high_resolution_clock::now();
    long total_ms = std::chrono::duration_cast<std::chrono::milliseconds>(t_total_end - t_total_start).count();
    std::cout << "\nRegion " << region << " complete across all 5 thresholds in " << (total_ms / 1000.0) << " s!\n\n";

    return 0;
}
