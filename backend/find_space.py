import urllib.request
import re

url = "https://huggingface.co/spaces/Alex-Universe11/Bootcamp-UBSI-KAI"
req = urllib.request.Request(url, method="GET")
try:
    with urllib.request.urlopen(req) as response:
        html = response.read().decode('utf-8')
        match = re.search(r'<iframe[^>]+src="([^"]+)"', html)
        if match:
            print("Iframe SRC:", match.group(1))
        else:
            print("Iframe not found.")
except Exception as e:
    print("Error:", e)
