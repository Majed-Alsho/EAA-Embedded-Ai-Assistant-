import requests,urllib.parse 
def isgd(url): r=requests.post(\"https://is.gd/create.php\",params={\"format\":\"json\",\"url\":url},timeout=10); return r.json().get(\"shorturl\",url) 
print(isgd(\"https://example.com\")) 
