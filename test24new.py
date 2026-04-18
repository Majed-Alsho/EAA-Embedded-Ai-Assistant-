import requests, time

tools = [
    ("ping_host", "Use the ping_host tool to ping google.com"),
    ("hardware_stats", "Use the hardware_stats tool to get CPU and memory info"),
    ("dns_resolve", "Use the dns_resolve tool to resolve google.com"),
    ("whois_lookup", "Use the whois_lookup tool to look up whois for google.com"),
    ("traceroute", "Use the traceroute tool to traceroute google.com with max 10 hops"),
    ("subdomain_enum", "Use the subdomain_enum tool to enumerate subdomains for google.com"),
    ("port_scan", "Use the port_scan tool to scan ports 80 and 443 on google.com"),
    ("rss_read", "Use the rss_read tool to read the RSS feed at https://news.ycombinator.com/rss"),
    ("html_extract", "Use the html_extract tool to extract all links from https://example.com"),
    ("wayback_fetch", "Use the wayback_fetch tool to fetch the Wayback Machine snapshot of example.com"),
    ("github_issue", "Use the github_issue tool to list open issues in repo python/cpython"),
    ("docker_list", "Use the docker_list tool to list all containers"),
    ("docker_logs", "Use the docker_logs tool to get logs, container_id is test"),
    ("video_trim", "Use the video_trim tool, input_path is C:/Users/offic/EAA/beep_sound.wav"),
    ("video_extract_audio", "Use the video_extract_audio tool, input_path is C:/Users/offic/EAA/beep_sound.wav"),
    ("video_compress", "Use the video_compress tool, input_path is C:/Users/offic/EAA/beep_sound.wav"),
    ("pdf_split", "Use the pdf_split tool, input_path is C:/Users/offic/EAA/beep_sound.wav"),
    ("pdf_merge", "Use the pdf_merge tool"),
    ("pdf_watermark", "Use the pdf_watermark tool, input_path is C:/Users/offic/EAA/beep_sound.wav"),
    ("mqtt_publish", "Use the mqtt_publish tool with host localhost, topic test/topic, message hello"),
    ("mqtt_subscribe", "Use the mqtt_subscribe tool with host localhost, topic test/topic, timeout 3"),
]

ok = 0
fail = 0
err_only = 0
for name, msg in tools:
    print(f"[{name}]", end=" ", flush=True)
    t0 = time.time()
    try:
        r = requests.post("http://localhost:8000/v1/agent/chat", json={"message": msg}, timeout=120)
        d = r.json()
        if d.get("success"):
            ok += 1
            print(f"OK ({time.time()-t0:.0f}s)")
        else:
            err = d.get("error", "")
            if "not installed" in err or "not found" in err or "Docker" in err:
                err_only += 1
                print(f"N/A ({time.time()-t0:.0f}s) - {err[:80]}")
            else:
                fail += 1
                print(f"ERR ({time.time()-t0:.0f}s) - {err[:80]}")
    except Exception as e:
        fail += 1
        print(f"FAIL ({time.time()-t0:.0f}s) {e}")
    time.sleep(1)

print(f"\nDONE: {ok} OK, {fail} FAIL, {err_only} N/A (missing deps) out of {len(tools)}")
