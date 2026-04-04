from eaa_web_researcher_cpu import web_search_cpu 
r=web_search_cpu("Bitcoin") 
print(r.get("response_text","")[:300]) 
