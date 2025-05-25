import os
import json
from pathlib import Path

def save_dashboard_json(entity, mode="download"):
    name = entity.get("name", "unnamed")
    guid = entity.get("guid")
    filename = f"data/{guid}.json"
    Path("data").mkdir(exist_ok=True)
    with open(filename, "w") as f:
        json.dump(entity, f, indent=2)
