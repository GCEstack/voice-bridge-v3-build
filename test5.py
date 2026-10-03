import sys, os
os.chdir(r"C:\Users\Dekan AI Brother\GCE_DON\voice-bridge-v3-build")
sys.path.insert(0, ".")
import json, tkinter as tk
from src.queue_panel import QueuePanel

# Reset dismissed
with open(r"C:\Users\Dekan AI Brother\GCE_DON\voice-bridge\queue_local.json", "w") as f:
    json.dump({"schema": "voicebridge.queue.local_state", "dismissed": [], "updated_at": "2026-10-02T00:00:00"}, f)

config = json.load(open("config.json"))
root = tk.Tk()
root.withdraw()
panel = QueuePanel(root, config)
print(f"Visible: {len(panel._items)}")
print(f"Dismissed: {len(panel.dismissed)}")
root.destroy()