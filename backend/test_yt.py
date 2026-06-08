import urllib.request, json, urllib.error
data=json.dumps({'youtube_url':'https://youtu.be/LZr7jt3MmKM?si=zDZm5YGavRbKbN1-'}).encode('utf-8')
req=urllib.request.Request('https://alex-universe11-bootcamp-ubsi-kai.hf.space/api/v1/resolve-youtube', data=data, headers={'Content-Type': 'application/json'})
try:
    urllib.request.urlopen(req)
except urllib.error.HTTPError as e:
    print(e.read().decode('utf-8'))
