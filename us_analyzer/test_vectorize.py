import time, json, numpy as np, cv2

t0 = time.time()
with open("metadata.json") as f:
    meta = json.load(f)

H, W = meta["rows"], meta["cols"]
# Read test ranks if we write them
print("Ready to test vectorization")
