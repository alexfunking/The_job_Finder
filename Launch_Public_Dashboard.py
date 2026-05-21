import urllib.request
import os
import subprocess
import threading
import time
import re
import sys

URL_FILE = "public_url.txt"
if os.path.exists(URL_FILE):
    try:
        os.remove(URL_FILE)
    except:
        pass

exe_path = "cloudflared.exe"
if not os.path.exists(exe_path):
    print("Downloading secure Cloudflare Tunnel (this only happens once)...")
    try:
        urllib.request.urlretrieve("https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe", exe_path)
    except Exception as e:
        print(f"Failed to download cloudflared: {e}")
        time.sleep(5)
        sys.exit(1)

print("Starting Streamlit Dashboard...")
# Start streamlit
streamlit_proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "dashboard.py"])

print("Starting Cloudflare Secure Tunnel...")
# Start cloudflared
cf_proc = subprocess.Popen(
    [exe_path, "tunnel", "--url", "http://127.0.0.1:8501"], 
    stdout=subprocess.PIPE, 
    stderr=subprocess.STDOUT, 
    text=True, 
    creationflags=0x08000000 # CREATE_NO_WINDOW
)

def read_cf_output():
    for line in cf_proc.stdout:
        match = re.search(r'(https://[a-zA-Z0-9-]+\.trycloudflare\.com)', line)
        if match:
            url = match.group(1)
            print(f"\n=========================================================")
            print(f"🌍 PUBLIC URL ESTABLISHED: {url}")
            print(f"=========================================================\n")
            with open(URL_FILE, "w") as f:
                f.write(url)
            break

threading.Thread(target=read_cf_output, daemon=True).start()

try:
    streamlit_proc.wait()
except KeyboardInterrupt:
    print("Shutting down...")
finally:
    try:
        streamlit_proc.terminate()
        cf_proc.terminate()
        if os.path.exists(URL_FILE):
            os.remove(URL_FILE)
    except:
        pass
