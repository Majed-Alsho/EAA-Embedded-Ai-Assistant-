import os,requests,re 
from datetime import datetime 
s=requests.Session() 
t=20 
def btc(): return s.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",timeout=t).json()["bitcoin"]["usd"] 
def eth(): return s.get("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",timeout=t).json()["ethereum"]["usd"] 
def weather(): d=s.get("https://wttr.in/Riyadh?format=j1",timeout=t).json(); c=d["current_condition"][0]; return c["temp_C"]+"C "+c["weatherDesc"][0]["value"] 
def calc(e): return eval(e) 
def now(): return datetime.now().strftime("%H:%M:%S") 
print("BTC:$",btc()); print("ETH:$",eth()); print("Weather:",weather()); print("Calc:",calc("25*4")); print("Time:",now()) 
