import aiohttp
from modules.queries import build_dashboard_export_query, build_nrql_validation_query

API_KEY = "NRAK-YourNewRelicAPIKey"
GRAPHQL_ENDPOINT = "https://api.newrelic.com/graphql"

async def fetch_dashboard_json(session: aiohttp.ClientSession, dashboard_guid: str) -> dict:
    query = build_dashboard_export_query(dashboard_guid)
    headers = {
        "Content-Type": "application/json",
        "API-Key": API_KEY
    }
    async with session.post(GRAPHQL_ENDPOINT, headers=headers, json={"query": query}) as response:
        result = await response.json()
        return result['data']['actor']['entity']

async def validate_nrql_query(session: aiohttp.ClientSession, account_id: int, query: str) -> bool:
    validation_query = build_nrql_validation_query(account_id, query)
    headers = {
        "Content-Type": "application/json",
        "API-Key": API_KEY
    }
    async with session.post(GRAPHQL_ENDPOINT, headers=headers, json={"query": validation_query}) as response:
        result = await response.json()
        return result['data']['actor']['account']['nrql']['queryValidate']['valid']