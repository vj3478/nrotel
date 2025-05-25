from newrelic_dashboard_updater.utils.logger import logger

def replace_variables(query: str, config: dict) -> str:
    variables = config.get("variables", {})
    for key, val in variables.items():
        try:
            if isinstance(val, dict):
                if "value" in val:
                    val = val["value"]
                elif "defaultValues" in val:
                    val = val["defaultValues"]
                else:
                    logger.warning(f"No usable value found for variable {{{key}}}")
                    continue
            if isinstance(val, list):
                val = ", ".join(f"'{v}'" if not isinstance(v, (int, float)) else str(v) for v in val)
            else:
                val = f"'{val}'" if isinstance(val, str) else str(val)
            query = query.replace(f"{{{key}}}", val)
        except Exception as e:
            logger.warning(f"Failed to resolve variable {{{key}}}: {e}")
            continue
    return query


