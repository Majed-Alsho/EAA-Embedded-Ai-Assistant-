import time,threading 
timers={} 
def set_timer(name,seconds,callback): 
    def _run(): time.sleep(seconds); callback(name) 
    t=threading.Thread(target=_run); t.start(); timers[name]=t 
print(\"Timer module ready\") 
