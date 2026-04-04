import os,subprocess 
def list_dir(p="C:\\Users\\offic\\EAA"): 
    return os.listdir(p) 
def read_file(f): 
    return open(f).read()[:500] 
print(list_dir()[:10]) 
