#ifndef US_CITIES_HPP
#define US_CITIES_HPP

#include <string>
#include <vector>
#include <cmath>
#include <fstream>
#include <sstream>

struct CityAnchor {
    std::string name;
    std::string state;
    double lat;
    double lon;
    long population;
};

inline const std::vector<CityAnchor>& get_us_cities() {
    static std::vector<CityAnchor> cities;
    if (!cities.empty()) return cities;

    std::ifstream f("us_cities.csv");
    if (!f.is_open()) return cities;

    std::string line;
    std::getline(f, line); // header

    while (std::getline(f, line)) {
        if (line.empty()) continue;
        std::string name, st, slat, slon, spop;

        if (line.front() == '"') {
            size_t end_quote = line.find('"', 1);
            if (end_quote == std::string::npos) continue;
            name = line.substr(1, end_quote - 1);
            std::string rem = line.substr(end_quote + 2);
            std::stringstream rem_ss(rem);
            std::getline(rem_ss, st, ',');
            std::getline(rem_ss, slat, ',');
            std::getline(rem_ss, slon, ',');
            std::getline(rem_ss, spop, ',');
        } else {
            std::stringstream ss(line);
            std::getline(ss, name, ',');
            std::getline(ss, st, ',');
            std::getline(ss, slat, ',');
            std::getline(ss, slon, ',');
            std::getline(ss, spop, ',');
        }

        try {
            CityAnchor ca;
            ca.name = name;
            ca.state = st;
            ca.lat = std::stod(slat);
            ca.lon = std::stod(slon);
            ca.population = std::stol(spop);
            cities.push_back(ca);
        } catch (...) {}
    }
    return cities;
}

inline double haversine_km(double lat1, double lon1, double lat2, double lon2) {
    const double R = 6371.0;
    const double dLat = (lat2 - lat1) * M_PI / 180.0;
    const double dLon = (lon2 - lon1) * M_PI / 180.0;
    const double a = std::sin(dLat / 2.0) * std::sin(dLat / 2.0) +
                     std::cos(lat1 * M_PI / 180.0) * std::cos(lat2 * M_PI / 180.0) *
                     std::sin(dLon / 2.0) * std::sin(dLon / 2.0);
    const double c = 2.0 * std::atan2(std::sqrt(a), std::sqrt(1.0 - a));
    return R * c;
}

inline std::string find_closest_city(double lat, double lon, double max_km = 30.0) {
    const auto& cities = get_us_cities();
    std::string best_name = "";
    double best_dist = 1e9;

    for (const auto& c : cities) {
        double d = haversine_km(lat, lon, c.lat, c.lon);
        if (d < max_km && d < best_dist) {
            best_dist = d;
            best_name = c.name + ", " + c.state;
        }
    }

    if (best_name.empty()) {
        for (const auto& c : cities) {
            double d = haversine_km(lat, lon, c.lat, c.lon);
            if (d < 60.0 && d < best_dist) {
                best_dist = d;
                best_name = c.name + ", " + c.state;
            }
        }
    }

    if (best_name.empty()) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "Metro (%.2f, %.2f)", lat, lon);
        return std::string(buf);
    }
    return best_name;
}

#endif // US_CITIES_HPP
