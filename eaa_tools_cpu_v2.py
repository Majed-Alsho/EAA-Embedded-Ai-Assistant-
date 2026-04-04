import os,json,urllib.parse,requests
os.environ["CUDA_VISIBLE_DEVICES"]=""
class CPUTools:
    def __init__(self): self.t=20; self.s=requests.Session()
    def btc(self): return self.s.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",timeout=self.t).json()["bitcoin"]["usd"]
    def weather(self,city="Riyadh"): return self.s.get(f"https://wttr.in/{city}?format=j1",timeout=self.t).json()["current_condition"][0]["temp_C"]
if __name__=="__main__":
    t=CPUTools()
    print("BTC:$",t.btc())
    print("Riyadh:",t.weather(),"C")
