f = r'C:\Users\offic\EAA\eaa_control_email_v7.py'
c = open(f, encoding='utf-8').read()

# Find and replace the entire start_tunnel function body
old = '''        import tempfile
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
                                log(f"[TUNNEL] Started: {state.tunnel_url}")

                        # SEND EMAIL NOTIFICATION! (run in thread, but retry on failure)
                        def _email_with_retry():
                            # Try up to 3 times with delay
                            for attempt in range(3):
                                ok = send_tunnel_notification(
                                    state.tunnel_url, API_KEY, SECRET_PHRASE,
                                    "Tunnel Restarted" if attempt > 0 else "Server Started"
                                )
                                if ok:
                                    return
                                time.sleep(3 * (attempt + 1))  # 3s, 6s, 9s
                            log("[EMAIL] All 3 email attempts failed")

                        threading.Thread(target=_email_with_retry, daemon=True).start()

                        return state.tunnel_url
            except:
                pass

        log("[TUNNEL] Failed to get URL")
        return None'''

new = '''        import tempfile
        cf_log_path = os.path.join(tempfile.gettempdir(), "cf_tunnel.log")
        cf_log = open(cf_log_path, "w")
        state.tunnel_process = subprocess.Popen(
            [CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{PORT}", "--no-autoupdate"],
            stdout=cf_log,
            stderr=cf_log
        )

        # Wait for URL by reading log file (no pipe = no overflow)
        for _ in range(30):
            time.sleep(1)
            try:
                with open(cf_log_path, "r") as lf:
                    for line in lf:
                        if "trycloudflare.com" in line:
                            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                            if match:
                                state.tunnel_url = match.group(0)
                                log(f"[TUNNEL] Started: {state.tunnel_url}")

                                def _email_with_retry():
                                    for attempt in range(3):
                                        ok = send_tunnel_notification(
                                            state.tunnel_url, API_KEY, SECRET_PHRASE,
                                            "Tunnel Restarted" if attempt > 0 else "Server Started"
                                        )
                                        if ok:
                                            return
                                        time.sleep(3 * (attempt + 1))
                                    log("[EMAIL] All 3 email attempts failed")

                                threading.Thread(target=_email_with_retry, daemon=True).start()
                                return state.tunnel_url
            except:
                pass

        log("[TUNNEL] Failed to get URL")
        return None'''

if old in c:
    c = c.replace(old, new, 1)
    open(f, 'w', encoding='utf-8').write(c)
    print('FIXED: correct indentation + log file approach')
else:
    print('ERROR: old block not found!')
