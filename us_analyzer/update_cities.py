import urllib.request, csv

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

url = "https://raw.githubusercontent.com/plotly/datasets/master/us-cities-top-1k.csv"
req = urllib.request.urlopen(url)
reader = csv.DictReader(l.decode() for l in req.readlines())
cities = []
for r in reader:
    name = r['City'].strip()
    st = state_map.get(r['State'].strip(), r['State'].strip())
    pop = int(float(r['Population']))
    lat = float(r['lat'])
    lon = float(r['lon'])
    cities.append((pop, name, st, lat, lon))

# Sort by population descending
cities.sort(key=lambda x: x[0], reverse=True)

hpp_content = """#ifndef US_CITIES_HPP
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

for pop, name, st, lat, lon in cities:
    escaped_name = name.replace('"', '\\"')
    hpp_content += f'        {{"{escaped_name}", "{st}", {lat:.6f}, {lon:.6f}, {pop}}},\n'

hpp_content += """    };
    return cities;
}

// Great-circle distance using Haversine formula (km)
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

inline std::string find_closest_city(double lat, double lon, double max_km = 80.0) {
    const auto& cities = get_us_cities();
    std::string best_name = "";
    double best_dist = 1e9;
    for (const auto& c : cities) {
        double d = haversine_km(lat, lon, c.lat, c.lon);
        if (d < best_dist) {
            best_dist = d;
            best_name = c.name + ", " + c.state;
        }
    }
    if (best_dist > max_km || best_name.empty()) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "Metro (%.2f, %.2f)", lat, lon);
        return std::string(buf);
    }
    return best_name;
}

#endif // US_CITIES_HPP
"""

with open("us_cities.hpp", "w") as f:
    f.write(hpp_content)

print(f"Generated us_cities.hpp with {len(cities)} cities.")
