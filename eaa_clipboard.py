import subprocess 
def copy(text): subprocess.run(["powershell","-Command","Set-Clipboard",text]) 
def paste(): r=subprocess.run(["powershell","-Command","Get-Clipboard"],capture_output=True,text=True); return r.stdout 
copy("EAA V8 test"); print("Copied!"); print("Paste:",paste()) 
