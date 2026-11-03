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

all_city_list = list(cities.values())
# Sort by population descending
all_city_list.sort(key=lambda x: (-x[0], x[1]))

with open("us_cities.csv", "w", encoding="utf-8") as f:
    f.write("City,State,Lat,Lon,Population\n")
    for pop, name, st, lat, lon in all_city_list:
        esc = name.replace('"', '""')
        f.write(f'"{esc}",{st},{lat:.6f},{lon:.6f},{pop}\n')

print(f"Exported {len(all_city_list)} cities to us_cities.csv")
