import os,requests,re 
os.environ["CUDA_VISIBLE_DEVICES"]="" 
class Tools: 
    def btc(self): return requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",timeout=20).json()["bitcoin"]["usd"] 
    def eth(self): return requests.get("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",timeout=20).json()["ethereum"]["usd"] 
    def weather(self): d=requests.get("https://wttr.in/Riyadh?format=j1",timeout=20).json(); c=d["current_condition"][0]; return c["temp_C"]+"C,"+c["weatherDesc"][0]["value"] 
t=Tools(); print("BTC:$",t.btc()); print("ETH:$",t.eth()); print("Weather:",t.weather()) 
