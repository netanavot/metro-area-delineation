import urllib.request, csv

# 1. Load top 1k cities with population
url_top1k = "https://raw.githubusercontent.com/plotly/datasets/master/us-cities-top-1k.csv"
req1 = urllib.request.urlopen(url_top1k)
reader1 = csv.DictReader(l.decode("utf-8", errors="ignore") for l in req1.readlines())
state_map = {
    'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR', 'California': 'CA',
    'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE', 'District of Columbia': 'DC',
    'Florida': 'FL', 'Georgia': 'GA', 'Hawaii': 'HI', 'Idaho': 'ID', 'Illinois': 'IL',
    'Indiana': 'IN', 'Iowa': 'IA', 'Kansas': 'KS', 'Kentucky': 'KY', 'Louisiana': 'LA',
    'Maine': 'ME', 'Maryland': 'MD', 'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN',
    'Mississippi': 'MS', 'Missouri': 'MO', 'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV',
    'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY',
    'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK', 'Oregon': 'OR',
    'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC', 'South Dakota': 'SD',
    'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT', 'Vermont': 'VT', 'Virginia': 'VA',
    'Washington': 'WA', 'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY'
}

cities = {}
for r in reader1:
    cname = r['City'].strip()
    st = state_map.get(r['State'].strip(), r['State'].strip())
    pop = int(float(r['Population']))
    lat = float(r['lat'])
    lon = float(r['lon'])
    cities[(cname.lower(), st.upper())] = (pop, cname, st, lat, lon)

print(f"Loaded {len(cities)} top cities.")

# 2. Load kelvins database
url_kelvins = "https://raw.githubusercontent.com/kelvins/US-Cities-Database/main/csv/us_cities.csv"
req2 = urllib.request.urlopen(url_kelvins)
reader2 = csv.DictReader(l.decode("utf-8", errors="ignore") for l in req2.readlines())
for r in reader2:
    cname = r['CITY'].strip()
    st = r['STATE_CODE'].strip()
    key = (cname.lower(), st.upper())
    if key not in cities:
        try:
            lat = float(r['LATITUDE'])
            lon = float(r['LONGITUDE'])
            cities[key] = (0, cname, st, lat, lon)
        except:
            pass

print(f"Total merged cities: {len(cities)}")

all_city_list = list(cities.values())
# Sort by population descending, then name
all_city_list.sort(key=lambda x: (-x[0], x[1]))

hpp = """#ifndef US_CITIES_HPP
#define US_CITIES_HPP

#include <string>
#include <vector>
#include <cmath>

struct CityAnchor {
    std::string name;
    std::string state;
    double lat;
    double lon;
    long population;
};

inline const std::vector<CityAnchor>& get_us_cities() {
    static const std::vector<CityAnchor> cities = {
"""

for pop, name, st, lat, lon in all_city_list:
    escaped_name = name.replace('"', '\\"')
    hpp += f'        {{"{escaped_name}", "{st}", {lat:.6f}, {lon:.6f}, {pop}}},\n'

hpp += """    };
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
    long best_pop = -1;

    // First pass: find within max_km, preferring higher population if close
    for (const auto& c : cities) {
        double d = haversine_km(lat, lon, c.lat, c.lon);
        if (d < max_km) {
            // If distance is very close (< 10km), prioritize closest
            // If distance is between 10-30km, prioritize major city if within reason
            if (d < best_dist) {
                best_dist = d;
                best_name = c.name + ", " + c.state;
                best_pop = c.population;
            }
        }
    }

    if (best_name.empty()) {
        // Expand search to 60 km
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
"""

with open("us_cities.hpp", "w", encoding="utf-8") as f:
    f.write(hpp)

print("Saved updated us_cities.hpp successfully!")
