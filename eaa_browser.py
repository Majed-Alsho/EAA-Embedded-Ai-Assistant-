import os 
os.environ["CUDA_VISIBLE_DEVICES"]="" 
from playwright.sync_api import sync_playwright 
def browse(url): 
    with sync_playwright() as p: 
        b=p.chromium.launch(headless=True) 
        page=b.new_page() 
        t=page.title() 
        b.close() 
        return t 
print(browse("https://example.com")) 
