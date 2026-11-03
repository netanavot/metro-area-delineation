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
#include "us_cities.hpp"

struct RasterMeta {
    int rows = 0;
    int cols = 0;
    double origin_lon = -125.0;
    double origin_lat = 50.0;
    double pixel_size_lon = 0.008333333333333333;
    double pixel_size_lat = 0.008333333333333333;
    double total_pop = 0.0;
};

struct MetroArea {
    int id;
    int peak_r;
    int peak_c;
    double peak_lat;
    double peak_lon;
    std::string name;
    double peak_density;
    double p95_density;
    double threshold_density;
    double total_pop;
    double total_area_sqkm;
    double avg_density;
    int absorbed_peaks_count;
    std::vector<std::string> absorbed_city_names;
};

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
        parse_int("rows", meta.rows);
        parse_int("cols", meta.cols);
        parse_double("origin_lon", meta.origin_lon);
        parse_double("origin_lat", meta.origin_lat);
        parse_double("pixel_size_lon", meta.pixel_size_lon);
        parse_double("pixel_size_lat", meta.pixel_size_lat);
        parse_double("total_population", meta.total_pop);
    }
    return true;
}

void apply_gaussian_smoothing(const std::vector<float>& input, std::vector<float>& output,
                              int rows, int cols, float sigma = 1.5f) {
    output.resize(rows * cols);
    int radius = std::ceil(3.0f * sigma);
    int k_size = 2 * radius + 1;
    std::vector<float> kernel(k_size);
    float sum = 0.0f;
    for (int i = -radius; i <= radius; ++i) {
        float val = std::exp(-(i * i) / (2.0f * sigma * sigma));
        kernel[i + radius] = val;
        sum += val;
    }
    for (float& w : kernel) w /= sum;

    std::vector<float> temp(rows * cols);

    for (int r = 0; r < rows; ++r) {
        for (int c = 0; c < cols; ++c) {
            float val = 0.0f;
            float w_sum = 0.0f;
            for (int k = -radius; k <= radius; ++k) {
                int sc = c + k;
                if (sc >= 0 && sc < cols) {
                    float w = kernel[k + radius];
                    val += input[r * cols + sc] * w;
                    w_sum += w;
                }
            }
            temp[r * cols + c] = (w_sum > 0.0f) ? (val / w_sum) : 0.0f;
        }
    }

    for (int r = 0; r < rows; ++r) {
        for (int c = 0; c < cols; ++c) {
            float val = 0.0f;
            float w_sum = 0.0f;
            for (int k = -radius; k <= radius; ++k) {
                int sr = r + k;
                if (sr >= 0 && sr < rows) {
                    float w = kernel[k + radius];
                    val += temp[sr * cols + c] * w;
                    w_sum += w;
                }
            }
            output[r * cols + c] = (w_sum > 0.0f) ? (val / w_sum) : 0.0f;
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
    struct DensityPop { float density; float pop; };
    std::vector<DensityPop> items;
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
    std::sort(items.begin(), items.end(), [](const DensityPop& a, const DensityPop& b) {
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

int main(int argc, char** argv) {
    std::string bin_path = "population.bin";
    std::string meta_path = "metadata.json";
    std::string mask_path = "us_landmask.bin";
    double threshold_fraction = 0.04;
    float sigma_km = 1.5f;

    RasterMeta meta;
    if (!load_metadata(meta_path, meta)) return 1;

    size_t total_cells = (size_t)meta.rows * meta.cols;
    std::vector<float> raw_pop(total_cells);
    std::ifstream bin_file(bin_path, std::ios::binary);
    bin_file.read(reinterpret_cast<char*>(raw_pop.data()), total_cells * sizeof(float));
    bin_file.close();

    std::vector<uint8_t> landmask(total_cells, 0);
    std::ifstream mask_file(mask_path, std::ios::binary);
    if (mask_file.is_open()) {
        mask_file.read(reinterpret_cast<char*>(landmask.data()), total_cells * sizeof(uint8_t));
        mask_file.close();
    }

    std::vector<double> row_areas(meta.rows);
    for (int r = 0; r < meta.rows; ++r) row_areas[r] = get_cell_area_km2(r, meta);

    std::vector<float> raw_density(total_cells, 0.0f);
    for (int r = 0; r < meta.rows; ++r) {
        double area = row_areas[r];
        for (int c = 0; c < meta.cols; ++c) {
            int idx = r * meta.cols + c;
            if (landmask[idx]) {
                float p = raw_pop[idx];
                raw_density[idx] = (p > 0.0f && area > 0.0) ? (float)(p / area) : 0.0f;
            }
        }
    }

    std::cout << "Smoothing density... ";
    std::vector<float> smooth_density;
    apply_gaussian_smoothing(raw_density, smooth_density, meta.rows, meta.cols, sigma_km);
    std::cout << "Done.\n";

    const int dr[8] = {-1, -1, -1,  0, 0,  1, 1, 1};
    const int dc[8] = {-1,  0,  1, -1, 1, -1, 0, 1};

    // Candidate peaks down to 25 ppl/km2
    std::cout << "Finding candidate density peaks (>= 25.0 ppl/km2)... ";
    const float MIN_PEAK_DENSITY = 75.0f;
    std::vector<int> peak_indices;
    for (int r = 1; r < meta.rows - 1; ++r) {
        for (int c = 1; c < meta.cols - 1; ++c) {
            int idx = r * meta.cols + c;
            if (!landmask[idx]) continue;
            float val = smooth_density[idx];
            if (val < MIN_PEAK_DENSITY) continue;

            bool is_peak = true;
            for (int k = 0; k < 8; ++k) {
                int nr = r + dr[k];
                int nc = c + dc[k];
                int n_idx = nr * meta.cols + nc;
                float n_val = smooth_density[n_idx];
                if (n_val > val || (n_val == val && n_idx < idx)) {
                    is_peak = false;
                    break;
                }
            }
            if (is_peak) peak_indices.push_back(idx);
        }
    }

    std::sort(peak_indices.begin(), peak_indices.end(), [&](int a, int b) {
        return smooth_density[a] > smooth_density[b];
    });
    std::cout << "Found " << peak_indices.size() << " candidate peaks.\n";

    std::cout << "Computing Condition A uphill watersheds... ";
    std::vector<int> uphill_target(total_cells, -1);
    for (int r = 0; r < meta.rows; ++r) {
        for (int c = 0; c < meta.cols; ++c) {
            int idx = r * meta.cols + c;
            if (!landmask[idx]) continue;
            float val = smooth_density[idx];
            if (val <= 0.0f) continue;

            float max_uphill = val;
            int best_n = idx;
            for (int k = 0; k < 8; ++k) {
                int nr = r + dr[k];
                int nc = c + dc[k];
                if (nr >= 0 && nr < meta.rows && nc >= 0 && nc < meta.cols) {
                    int n_idx = nr * meta.cols + nc;
                    if (landmask[n_idx]) {
                        float n_val = smooth_density[n_idx];
                        if (n_val > max_uphill) {
                            max_uphill = n_val;
                            best_n = n_idx;
                        }
                    }
                }
            }
            if (best_n != idx) uphill_target[idx] = best_n;
        }
    }

    std::vector<int> cell_peak_id(total_cells, -1);
    for (size_t i = 0; i < peak_indices.size(); ++i) {
        cell_peak_id[peak_indices[i]] = (int)i;
    }

    for (int idx = 0; idx < (int)total_cells; ++idx) {
        if (!landmask[idx] || smooth_density[idx] <= 0.0f) continue;
        int curr = idx;
        std::vector<int> path;
        while (curr != -1 && cell_peak_id[curr] == -1) {
            path.push_back(curr);
            curr = uphill_target[curr];
        }
        int root_peak = (curr != -1) ? cell_peak_id[curr] : -1;
        for (int node : path) cell_peak_id[node] = root_peak;
    }

    std::vector<std::vector<int>> peak_basins(peak_indices.size());
    for (int idx = 0; idx < (int)total_cells; ++idx) {
        int pid = cell_peak_id[idx];
        if (pid >= 0 && pid < (int)peak_basins.size()) {
            peak_basins[pid].push_back(idx);
        }
    }
    std::cout << "Done.\n";

    // Metro delineation: NO MINIMUM POPULATION CUTOFF!
    std::cout << "Delineating metros from highest density downwards (no pop cutoff)...\n";
    std::vector<int> claimed_metro_id(total_cells, -2);
    for (size_t i = 0; i < total_cells; ++i) {
        if (landmask[i]) claimed_metro_id[i] = -1;
    }

    std::vector<bool> peak_absorbed(peak_indices.size(), false);
    std::vector<MetroArea> metros;
    std::unordered_set<std::string> existing_metro_names;

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
        std::vector<bool> in_current_metro(total_cells, false);
        for (int c_idx : peak_basins[p]) {
            if (claimed_metro_id[c_idx] == -1) {
                current_cells.push_back(c_idx);
                in_current_metro[c_idx] = true;
            }
        }
        if (current_cells.empty()) continue;
        peak_absorbed[p] = true;

        // Anchor threshold to core P95 to prevent runaway dilution
        double p95 = calc_weighted_p95(current_cells, smooth_density, raw_pop);
        double threshold = threshold_fraction * p95;

        std::vector<int> absorbed_peaks_in_metro;
        absorbed_peaks_in_metro.push_back((int)p);

        std::queue<int> frontier;
        for (int c_idx : current_cells) {
            frontier.push(c_idx);
        }

        while (!frontier.empty()) {
            int curr = frontier.front();
            frontier.pop();

            int cr = curr / meta.cols;
            int cc = curr % meta.cols;

            for (int k = 0; k < 8; ++k) {
                int nr = cr + dr[k];
                int nc = cc + dc[k];
                if (nr < 0 || nr >= meta.rows || nc < 0 || nc >= meta.cols) continue;

                int n_idx = nr * meta.cols + nc;
                if (!landmask[n_idx]) continue;
                if (in_current_metro[n_idx]) continue;
                if (claimed_metro_id[n_idx] != -1) continue;

                if (smooth_density[n_idx] >= threshold) {
                    in_current_metro[n_idx] = true;
                    current_cells.push_back(n_idx);
                    frontier.push(n_idx);

                    int n_pid = cell_peak_id[n_idx];
                    if (n_pid >= 0 && !peak_absorbed[n_pid]) {
                        peak_absorbed[n_pid] = true;
                        absorbed_peaks_in_metro.push_back(n_pid);

                        for (int basin_cell : peak_basins[n_pid]) {
                            if (!in_current_metro[basin_cell] && claimed_metro_id[basin_cell] == -1) {
                                in_current_metro[basin_cell] = true;
                                current_cells.push_back(basin_cell);
                                frontier.push(basin_cell);
                            }
                        }
                    }
                }
            }
        }

        // Commit unconditionally! (NO POPULATION CUTOFF)
        int metro_id = (int)metros.size();
        double total_metro_pop = 0.0;
        double total_metro_area = 0.0;
        for (int c_idx : current_cells) {
            claimed_metro_id[c_idx] = metro_id;
            int cr = c_idx / meta.cols;
            total_metro_pop += raw_pop[c_idx];
            total_metro_area += row_areas[cr];
        }

        // Resolve Anchor Cities
        const auto& all_cities = get_us_cities();
        std::vector<CityAnchor> metro_anchors;
        auto add_anchor = [&](double lat, double lon) {
            std::string cname = find_closest_city(lat, lon, 50.0);
            for (const auto& ac : all_cities) {
                if (ac.name + ", " + ac.state == cname) {
                    bool already = false;
                    for (const auto& existing : metro_anchors) {
                        if (existing.name == ac.name && existing.state == ac.state) {
                            already = true; break;
                        }
                    }
                    if (!already) metro_anchors.push_back(ac);
                    break;
                }
            }
        };

        add_anchor(peak_lat, peak_lon);
        for (size_t k = 1; k < absorbed_peaks_in_metro.size(); ++k) {
            int sub_p = absorbed_peaks_in_metro[k];
            int sub_idx = peak_indices[sub_p];
            int sr = sub_idx / meta.cols;
            int sc = sub_idx % meta.cols;
            double slat = meta.origin_lat - (sr + 0.5) * meta.pixel_size_lat;
            double slon = meta.origin_lon + (sc + 0.5) * meta.pixel_size_lon;
            add_anchor(slat, slon);
        }

        std::sort(metro_anchors.begin(), metro_anchors.end(), [](const CityAnchor& a, const CityAnchor& b) {
            return a.population > b.population;
        });

        std::string primary_name = find_closest_city(peak_lat, peak_lon, 50.0);
        if (!metro_anchors.empty()) primary_name = metro_anchors[0].name + ", " + metro_anchors[0].state;

        if (existing_metro_names.count(primary_name)) {
            bool found_alt = false;
            for (const auto& alt : metro_anchors) {
                std::string alt_name = alt.name + ", " + alt.state;
                if (!existing_metro_names.count(alt_name)) {
                    primary_name = alt_name;
                    found_alt = true;
                    break;
                }
            }
            if (!found_alt) {
                char buf[64];
                std::snprintf(buf, sizeof(buf), "%s (Core %.2f, %.2f)", primary_name.c_str(), peak_lat, peak_lon);
                primary_name = std::string(buf);
            }
        }
        existing_metro_names.insert(primary_name);

        MetroArea ma;
        ma.id = metro_id;
        ma.peak_r = root_r;
        ma.peak_c = root_c;
        ma.peak_lat = peak_lat;
        ma.peak_lon = peak_lon;
        ma.name = primary_name;
        ma.peak_density = peak_dens;
        ma.p95_density = p95;
        ma.threshold_density = threshold;
        ma.total_pop = total_metro_pop;
        ma.total_area_sqkm = total_metro_area;
        ma.avg_density = total_metro_area > 0 ? (total_metro_pop / total_metro_area) : 0;
        ma.absorbed_peaks_count = (int)absorbed_peaks_in_metro.size() - 1;

        for (size_t k = 1; k < metro_anchors.size(); ++k) {
            ma.absorbed_city_names.push_back(metro_anchors[k].name + ", " + metro_anchors[k].state);
        }

        metros.push_back(ma);
    }
    std::cout << "Delineated " << metros.size() << " metropolitan areas across the US!\n";

    // Allocate 100% of US land: expand strictly into unassigned US land
    std::cout << "Expanding to partition 100% of US land among metros... ";
    std::queue<int> land_q;
    for (int idx = 0; idx < (int)total_cells; ++idx) {
        if (claimed_metro_id[idx] >= 0) land_q.push(idx);
    }

    while (!land_q.empty()) {
        int curr = land_q.front();
        land_q.pop();
        int mid = claimed_metro_id[curr];

        int cr = curr / meta.cols;
        int cc = curr % meta.cols;

        for (int k = 0; k < 8; ++k) {
            int nr = cr + dr[k];
            int nc = cc + dc[k];
            if (nr >= 0 && nr < meta.rows && nc >= 0 && nc < meta.cols) {
                int n_idx = nr * meta.cols + nc;
                if (landmask[n_idx] && claimed_metro_id[n_idx] == -1) {
                    claimed_metro_id[n_idx] = mid;
                    land_q.push(n_idx);
                }
            }
        }
    }
    std::cout << "Done.\n";

    // Bridge offshore islands
    std::cout << "Bridging coastal islands... ";
    std::queue<int> bridge_q;
    std::vector<int> water_owner(total_cells, -1);
    for (int idx = 0; idx < (int)total_cells; ++idx) {
        if (claimed_metro_id[idx] >= 0) {
            int cr = idx / meta.cols;
            int cc = idx % meta.cols;
            bool touches_water = false;
            for (int k = 0; k < 8; ++k) {
                int nr = cr + dr[k];
                int nc = cc + dc[k];
                if (nr >= 0 && nr < meta.rows && nc >= 0 && nc < meta.cols) {
                    int n_idx = nr * meta.cols + nc;
                    if (!landmask[n_idx]) {
                        touches_water = true;
                        break;
                    }
                }
            }
            if (touches_water) {
                water_owner[idx] = claimed_metro_id[idx];
                bridge_q.push(idx);
            }
        }
    }

    while (!bridge_q.empty()) {
        int curr = bridge_q.front();
        bridge_q.pop();
        int mid = water_owner[curr];

        int cr = curr / meta.cols;
        int cc = curr % meta.cols;

        for (int k = 0; k < 8; ++k) {
            int nr = cr + dr[k];
            int nc = cc + dc[k];
            if (nr >= 0 && nr < meta.rows && nc >= 0 && nc < meta.cols) {
                int n_idx = nr * meta.cols + nc;
                if (landmask[n_idx] == 1) {
                    if (claimed_metro_id[n_idx] == -1) {
                        claimed_metro_id[n_idx] = mid;
                        water_owner[n_idx] = mid;
                        bridge_q.push(n_idx);
                    }
                } else {
                    if (water_owner[n_idx] == -1) {
                        water_owner[n_idx] = mid;
                        bridge_q.push(n_idx);
                    }
                }
            }
        }
    }
    std::cout << "Done.\n";

    // Recalculate totals
    for (auto& m : metros) {
        m.total_pop = 0;
        m.total_area_sqkm = 0;
    }
    for (int idx = 0; idx < (int)total_cells; ++idx) {
        int mid = claimed_metro_id[idx];
        if (mid >= 0 && mid < (int)metros.size()) {
            int cr = idx / meta.cols;
            metros[mid].total_pop += raw_pop[idx];
            metros[mid].total_area_sqkm += row_areas[cr];
        }
    }

    std::sort(metros.begin(), metros.end(), [](const MetroArea& a, const MetroArea& b) {
        return a.total_pop > b.total_pop;
    });

    std::cout << "Total final metros: " << metros.size() << "\n";
    std::cout << "Top 10:\n";
    for (size_t i = 0; i < std::min(metros.size(), (size_t)10); ++i) {
        std::cout << "  #" << (i+1) << " " << metros[i].name << " - Pop: " << (long long)metros[i].total_pop 
                  << " - Area: " << metros[i].total_area_sqkm << " km2\n";
    }

    // Check specific cities: Mountain Home, Bremerton, Boise, Seattle, Salt Lake City
    for (size_t i = 0; i < metros.size(); ++i) {
        std::string n = metros[i].name;
        if (n.find("Mountain Home") != std::string::npos ||
            n.find("Bremerton") != std::string::npos ||
            n.find("Boise") != std::string::npos ||
            n.find("Seattle") != std::string::npos ||
            n.find("Salt Lake City") != std::string::npos) {
            std::cout << "Spotcheck: #" << (i+1) << " " << n << " - Pop: " << (long long)metros[i].total_pop
                      << " - Absorbed: ";
            for (const auto& a : metros[i].absorbed_city_names) std::cout << a << "; ";
            std::cout << "\n";
        }
    }

    return 0;
}
