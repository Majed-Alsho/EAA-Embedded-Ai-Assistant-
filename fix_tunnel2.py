f = r'C:\Users\offic\EAA\eaa_control_email_v7.py'
c = open(f, encoding='utf-8').read()
# Replace drain thread approach with DEVNULL (no pipe = no overflow possible)
old = """log(f"[TUNNEL] Started: {state.tunnel_url}")
                        def _drain():
                            try:
                                for _ in state.tunnel_process.stdout: pass
                            except: pass
                        threading.Thread(target=_drain, daemon=True).start()"""
new = 'log(f"[TUNNEL] Started: {state.tunnel_url}")'
c = c.replace(old, new, 1)
# Also redirect stderr to DEVNULL
c = c.replace('stdout=subprocess.PIPE,\n            stderr=subprocess.STDOUT,\n            text=True', 'stdout=subprocess.DEVNULL,\n            stderr=subprocess.DEVNULL')
open(f, 'w', encoding='utf-8').write(c)
print('FIXED: DEVNULL - no pipe buffer possible')
