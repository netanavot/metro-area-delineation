CXX = clang++
CXXFLAGS = -O3 -std=c++17 -Wall -Wextra

TARGET = metro_analyzer
SRCS = metro_analyzer.cpp
HEADERS = us_cities.hpp

all: $(TARGET)

$(TARGET): $(SRCS) $(HEADERS)
	$(CXX) $(CXXFLAGS) $(SRCS) -o $(TARGET)

clean:
	rm -f $(TARGET) population.bin metadata.json us_metro_areas.csv

run: $(TARGET)
	python3 prepare_raster.py usa_ppp_2020_1km_Aggregated.tif
	./$(TARGET) population.bin metadata.json

.PHONY: all clean run
