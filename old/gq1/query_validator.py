# newrelic_dashboard_updater/graphql/query_validator.py

import aiohttp
import asyncio
import csv
from pathlib import Path
from newrelic_dashboard_updater.config import API_KEY
from newrelic_dashboard_updater.utils.logger import logger
from newrelic_dashboard_updater.utils.variable_resolver import replace_variables, apply_mapping

NRQL_VALIDATION_BATCH_QUERY = """
query {
PLACEHOLDER
}
"""

async def validate_nrql_batch(batch):
    headers = {"Api-Key": API_KEY, "Content-Type": "application/json"}

    parts = []
    for i, row in enumerate(batch):
        alias = f"q{i}"
        account_id = row["accountId"]
        nrql = row["nrqlQuery"].replace('"', '\\"').replace("\n", " ")
        parts.append(f"""
          {alias}: actor {{
            account(id: {account_id}) {{
              nrql(query: \"{nrql}\") {{
                results
              }}
            }}
          }}
        """)

    gql = NRQL_VALIDATION_BATCH_QUERY.replace("PLACEHOLDER", "\n".join(parts))

    async with aiohttp.ClientSession() as session:
        async with session.post("https://api.newrelic.com/graphql", headers=headers, json={"query": gql}) as resp:
            if resp.status != 200:
                logger.error(f"Failed NRQL batch validation: HTTP {resp.status}")
                return ["failed"] * len(batch)

            try:
                data = await resp.json()
                errors = data.get("errors", [])
                error_paths = {err["path"][0] for err in errors} if errors else set()
                return ["failed" if f"q{i}" in error_paths else "success" for i in range(len(batch))]
            except Exception as e:
                logger.exception("Error parsing NRQL batch response")
                return ["failed"] * len(batch)


async def run_nrql_query(account_id, query):
    headers = {"Api-Key": API_KEY, "Content-Type": "application/json"}
    payload = {
        "query": f"""query {{
            actor {{
                account(id: {account_id}) {{
                    nrql(query: \"{query.replace('"', '\\"')}\") {{
                        results
                    }}
                }}
            }}
        }}"""
    }
    async with aiohttp.ClientSession() as session:
        async with session.post("https://api.newrelic.com/graphql", headers=headers, json=payload) as resp:
            if resp.status != 200:
                logger.error(f"Failed to run NRQL query: {query}, status={resp.status}")
                return []
            data = await resp.json()
            try:
                return data["data"]["actor"]["account"]["nrql"]["results"]
            except Exception:
                logger.error(f"Failed to parse response for NRQL: {query}")
                return []

def extract_variable_values(variable):
    if variable.get("type") == "nrqlQuery":
        query = variable.get("nrqlQuery", {}).get("query")
        account_id = variable.get("nrqlQuery", {}).get("accountId")
        return query, account_id
    return None, None

async def resolve_dashboard_variables(dashboard_variables):
    resolved = {}
    tasks = []

    async def resolve_one(var):
        name = var.get("name")
        query, account_id = extract_variable_values(var)
        if query and account_id:
            values = await run_nrql_query(account_id, query)
            resolved[name] = [v for result in values for v in result.values() if isinstance(v, str)]
        else:
            resolved[name] = var.get("values") or var.get("defaultValues") or []

    for var in dashboard_variables:
        tasks.append(resolve_one(var))

    await asyncio.gather(*tasks)
    return resolved

def replace_widget_variables(nrql, variables):
    for key, values in variables.items():
        if not values:
            continue
        value_str = f"IN ({', '.join([f'\'{v}\'' for v in values])})" if len(values) > 1 else f"= '{values[0]}'"
        nrql = nrql.replace(f"${key}", value_str)
    return nrql

def write_dashboard_summary_csv(summary_data, filename="dashboard_validation_summary.csv"):
    path = Path(filename)
    fieldnames = ["dashboard_guid", "dashboard_name", "validated", "failed", "skipped", "total"]
    with path.open("w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_data)


async def process_dashboard_widgets(dashboard_json, mapping_rules, mode="validate"):
    variables = await resolve_dashboard_variables(dashboard_json.get("variables", []))
    widget_jobs = []
    counters = {"total": 0, "validated": 0, "failed": 0, "skipped": 0}

    for page in dashboard_json.get("pages", []):
        for widget in page.get("widgets", []):
            cfg = widget.get("rawConfiguration", {})
            query_obj = cfg.get("nrqlQueries", [{}])[0]
            query = query_obj.get("query")
            if query and "from span" in query.lower():
                account_id = query_obj.get("accountId") or dashboard_json.get("permissions", [{}])[0].get("accountId")
                new_query = replace_widget_variables(query, variables)
                new_query = replace_variables(new_query, variables)
                new_query = apply_mapping(new_query, mapping_rules)
                widget_jobs.append({
                    "accountId": account_id,
                    "nrqlQuery": new_query,
                    "original_query": query,
                    "page": page,
                    "widget": widget
                })
            else:
                widget["validation"] = "NA"
                counters["skipped"] += 1

    for i in range(0, len(widget_jobs), 25):
        batch = widget_jobs[i:i+25]
        results = await validate_nrql_batch(batch)
        for job, result in zip(batch, results):
            job["widget"]["validation"] = result
            counters["total"] += 1
            if result == "success":
                counters["validated"] += 1
                if mode == "update":
                    job["widget"]["rawConfiguration"]["nrqlQueries"][0]["query"] = job["nrqlQuery"]
                elif mode == "dry-run":
                    logger.debug(f"[Dry Run] Would update widget {job['widget'].get('id')} with query: {job['nrqlQuery']}")
            elif result == "failed":
                counters["failed"] += 1
                job["widget"]["validation"] = "failed"

    logger.info(f"Processed dashboard {dashboard_json.get('name', '')}: Total={counters['total']} Valid={counters['validated']} Failed={counters['failed']} Skipped={counters['skipped']}")
    return {
        "dashboard_guid": dashboard_json.get("guid", "unknown"),
        "dashboard_name": dashboard_json.get("name", "unnamed"),
        **counters
    }
