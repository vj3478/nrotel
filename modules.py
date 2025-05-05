import json
from logging_util import logger
from common.common import search_and_replace_in_nrql, load_json_file

MAPPING_RULES = load_json_file("src/mapping_rules.json")

def apply_mapping_rules(query: str) -> str:
    return search_and_replace_in_nrql(query, MAPPING_RULES)

def extract_widget_configs_from_dashboard_json(dashboard_json: dict):
    configs = []
    try:
        for page in dashboard_json.get("pages", []):
            for widget in page.get("widgets", []):
                raw_config = widget.get("rawConfiguration", {})
                layout = widget.get("layout", {})
                nrql_queries = raw_config.get("nrqlQueries", [])
                if not nrql_queries:
                    continue
                for query in nrql_queries:
                    original = query.get("query", "")
                    transformed = apply_mapping_rules(original)
                    config = {
                        "widget_guid": widget.get("id"),
                        "account_id": query.get("accountId", 0),
                        "nrql_query": original,
                        "updated_query": transformed,
                        "visualization_id": raw_config.get("visualization", "viz.line"),
                        "facet": raw_config.get("facet", []),
                        "y_axis_left": raw_config.get("yAxisLeft", {}),
                        "y_axis_right": raw_config.get("yAxisRight", {}),
                        "linked_entity_guids": raw_config.get("linkedEntityGuids", []),
                        "thresholds": raw_config.get("thresholds", []),
                        "legend": raw_config.get("legend", {}),
                        "title": raw_config.get("title", ""),
                        "layout": {
                            "column": layout.get("column", 0),
                            "row": layout.get("row", 0),
                            "width": layout.get("width", 6),
                            "height": layout.get("height", 4)
                        }
                    }
                    configs.append(config)
    except Exception as e:
        logger.exception(f"Error extracting widget configurations: {e}")
    return configs

def update_configs_with_status(configs, results):
    for config, result in zip(configs, results):
        config['update_status'] = 'success' if not isinstance(result, Exception) else f"error: {result}"
    return configs