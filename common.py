import json
import csv
from logging_util import logger

def save_to_csv(data, filename):
    try:
        with open(filename, mode='w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
    except Exception as e:
        logger.exception(f"Error saving to CSV {filename}: {e}")

def save_to_json(data, filename):
    try:
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.exception(f"Error saving to JSON {filename}: {e}")

def load_csv_to_json(filename):
    try:
        with open(filename, newline='') as f:
            return list(csv.DictReader(f))
    except Exception as e:
        logger.exception(f"Error loading CSV {filename}: {e}")
        return []

def load_json_file(filename):
    try:
        with open(filename) as f:
            return json.load(f)
    except Exception as e:
        logger.exception(f"Error loading JSON {filename}: {e}")
        return {}

def search_and_replace_in_nrql(query: str, rules: dict) -> str:
    for old, new in rules.items():
        query = query.replace(old, new)
    return query