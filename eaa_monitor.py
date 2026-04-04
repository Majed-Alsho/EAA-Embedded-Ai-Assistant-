import subprocess,psutil 
def gpu(): r=subprocess.run(["nvidia-smi","--query-gpu=memory.used,utilization.gpu,temperature.gpu","--format=csv,noheader"],capture_output=True,text=True); return r.stdout 
def cpu(): return psutil.cpu_percent() 
def ram(): return psutil.virtual_memory().percent 
print("GPU:",gpu()); print("CPU:",cpu(),"%"); print("RAM:",ram(),"%") 
