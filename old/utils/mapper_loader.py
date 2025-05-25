import json
from pathlib import Path

MAPPER_PATH = Path("newrelic_dashboard_updater/mappers/span_to_metric_mapper.json")

def load_mapper():
    if MAPPER_PATH.exists():
        with open(MAPPER_PATH) as f:
            return json.load(f)
    return {}

def apply_mapping(query: str) -> str:
    mapping = load_mapper()
    for old, new in mapping.items():
        query = query.replace(old, new)
    return query
