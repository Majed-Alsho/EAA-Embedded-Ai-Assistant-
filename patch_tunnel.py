import threading
f = r'C:\Users\offic\EAA\eaa_control_email_v7.py'
c = open(f, encoding='utf-8').read()
c = c.replace(
    '[CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{PORT}"]',
    '[CLOUDFLARED_PATH, "tunnel", "--url", f"http://localhost:{PORT}", "--no-autoupdate"]'
)
old = 'log(f"[TUNNEL] Started: {state.tunnel_url}")'
new = """log(f"[TUNNEL] Started: {state.tunnel_url}")
                        def _drain():
                            try:
                                for _ in state.tunnel_process.stdout: pass
                            except: pass
                        threading.Thread(target=_drain, daemon=True).start()"""
c = c.replace(old, new, 1)
open(f, 'w', encoding='utf-8').write(c)
print('PATCHED: drain thread + no-autoupdate')
