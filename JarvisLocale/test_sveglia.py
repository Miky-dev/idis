import requests
import time

for url in ["http://192.168.1.212/", "http://192.168.1.212/lavoro"]:
    t0 = time.time()
    try:
        r = requests.get(url, timeout=5)
        print(f"GET {url} -> {r.status_code} (took {time.time()-t0:.3f}s)")
    except Exception as e:
        print(f"GET {url} -> Exception: {e} (took {time.time()-t0:.3f}s)")
