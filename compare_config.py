import json

v3_config = json.load(open('config.json'))
old_config = json.load(open(r'..\voice-bridge\config.json'))

print("v3-build config:")
print(f"  registry_path: {v3_config['handoff_queue']['registry_path']}")
print(f"  local_state:   {v3_config['handoff_queue']['local_state']}")
print()
print("OLD voice-bridge config:")
print(f"  registry_path: {old_config['handoff_queue']['registry_path']}")
print(f"  local_state:   {old_config['handoff_queue']['local_state']}")