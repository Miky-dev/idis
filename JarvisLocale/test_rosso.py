import requests

urls = [
    "http://192.168.1.212/rosso",
    "http://192.168.1.212/rossa",
    "http://192.168.1.212/alba_rossa",
    "http://192.168.1.212/albarossa",
    "http://192.168.1.212/alba-rossa",
    "http://192.168.1.212/red"
]

for url in urls:
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            print(f"FOUND 200: {url}")
            break
    except Exception as e:
        pass
else:
    print("NONE RETURNED 200")
