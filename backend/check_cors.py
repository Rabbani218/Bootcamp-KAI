import urllib.request
import urllib.error

req = urllib.request.Request(
    'https://alex-universe11-bootcamp-ubsi-kai.hf.space/api/health',
    method='OPTIONS',
    headers={
        'Origin': 'https://bootcamp-eod1o4x7z-muhammad-abdurrahman-rabbanis-projects.vercel.app',
        'Access-Control-Request-Method': 'GET'
    }
)
try:
    res = urllib.request.urlopen(req)
    print("CORS Allow Origin:", res.headers.get('Access-Control-Allow-Origin'))
except urllib.error.URLError as e:
    print("Error:", e)
