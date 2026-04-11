import json, urllib.request
for path in ('settings','opportunities'):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/' + path, timeout=5) as r:
            data = json.load(r)
        print(path + ': ' + json.dumps(data)[:4000])
    except Exception as exc:
        print(path + ' ERROR: ' + repr(exc))
