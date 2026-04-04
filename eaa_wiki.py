import requests,urllib.parse 
def wiki(topic): 
    u="https://en.wikipedia.org/api/rest_v1/page/summary/"+urllib.parse.quote(topic) 
    d=requests.get(u,timeout=20).json() 
    return d.get("extract","Not found")[:300] 
print(wiki("Elon Musk")[:200]) 
