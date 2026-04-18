f = r'C:\Users\offic\EAA\eaa_control_email_v7.py'
c = open(f, encoding='utf-8').read()

old = '''state.tunnel_process = subprocess.Popen(
            [CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{PORT}", "--no-autoupdate"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Wait for URL
        for _ in range(30):
            try:
                line = state.tunnel_process.stdout.readline()
                if "trycloudflare.com" in line:
                    match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
                    if match:
                        state.tunnel_url = match.group(0)
                        log(f"[TUNNEL] Started: {state.tunnel_url}")'''

new = '''import tempfile
        cf_log = open(os.path.join(tempfile.gettempdir(), "cf_tunnel.log"), "w")
        state.tunnel_process = subprocess.Popen(
            [CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{PORT}", "--no-autoupdate"],
            stdout=cf_log,
            stderr=cf_log
        )

        # Wait for URL by reading log file (no pipe = no overflow possible)
        for _ in range(30):
            time.sleep(1)
            try:
                with open(cf_log.name, "r") as lf:
                    for line in lf:
                        if "trycloudflare.com" in line:
                            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                            if match:
                                state.tunnel_url = match.group(0)
                                log(f"[TUNNEL] Started: {state.tunnel_url}")'''

c = c.replace(old, new, 1)
open(f, 'w', encoding='utf-8').write(c)
print('FIXED: log file approach, no pipe')
