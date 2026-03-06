import urllib.request, json
u = urllib.request.urlopen('https://pypi.org/pypi/mediapipe/json')
data = json.loads(u.read())
for v in data['releases']:
    for f in data['releases'][v]:
        if 'win' in f['filename']:
            print(f['filename'])
