import sys, os
os.chdir(r"C:\Users\Dekan AI Brother\GCE_DON\voice-bridge-v3-build")
sys.path.insert(0, ".")
import json, tkinter as tk
from src.queue_panel import QueuePanel

config = json.load(open("config.json"))
root = tk.Tk()
root.geometry("800x600")
panel = QueuePanel(root, config)
print(f"Panel: {panel}")
print(f"Items: {len(panel._items)} visible")
root.after(1000, root.destroy)
root.mainloop()
print("OK")