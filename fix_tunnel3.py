import os, re
f = r'C:\Users\offic\EAA\eaa_control_email_v7.py'
c = open(f, encoding='utf-8').read()

# Replace the entire tunnel startup block with a file-based approach
old_block = '''state.tunnel_process = subprocess.Popen(
            [CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{PORT}", "--no-autoupdate"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for URL
        for _ in range(30):
            try:
                line = state.tunnel_process.stdout.readline()
                if "trycloudflare.com" in line:
                    match = re.search(r'https://[a-zA-Z0-9-]+\\.trycloudflare\\.com', line)
                    if match:
                        state.tunnel_url = match.group(0)
                        log(f"[TUNNEL] Started: {state.tunnel_url}")'''

new_block = '''log_path = os.path.join(os.environ.get("TEMP", "."), "cf_tunnel.log")
        cf_log = open(log_path, "w")
        state.tunnel_process = subprocess.Popen(
            [CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{PORT}", "--no-autoupdate"],
            stdout=cf_log,
            stderr=cf_log,
        )

        # Wait for URL by reading log file (no pipe = no overflow)
        for _ in range(30):
            time.sleep(1)
            try:
                with open(log_path, "r") as lf:
                    for line in lf:
                        if "trycloudflare.com" in line:
                            match = re.search(r"https://[a-zA-Z0-9-]+\\.trycloudflare\\.com", line)
                            if match:
                                state.tunnel_url = match.group(0)
                                log(f"[TUNNEL] Started: {state.tunnel_url}")'''

c = c.replace(old_block, new_block, 1)

# Remove the old readline-based URL wait loop tail (the nested if/match block)
old_tail = '''                        if match:
                                    state.tunnel_url = match.group(0)
                                    log(f"[TUNNEL] Started: {state.tunnel_url}")'''
# Already handled above

open(f, 'w', encoding='utf-8').write(c)
print('FIXED: log file approach - no pipe buffer possible')
