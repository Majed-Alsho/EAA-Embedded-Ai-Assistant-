import requests 
def stock(sym): 
    u=f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d" 
    d=requests.get(u,timeout=20).json()["chart"]["result"][0]["meta"] 
    return d.get("regularMarketPrice","N/A") 
print("AAPL:",stock("AAPL")) 
