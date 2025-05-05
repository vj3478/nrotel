import aiohttp
from modules.queries import build_alert_conditions_export_query

API_KEY = "NRAK-YourNewRelicAPIKey"
GRAPHQL_ENDPOINT = "https://api.newrelic.com/graphql"

async def fetch_alert_conditions(session: aiohttp.ClientSession, account_id: int) -> list:
    query = build_alert_conditions_export_query(account_id)
    headers = {
        "Content-Type": "application/json",
        "API-Key": API_KEY
    }
    async with session.post(GRAPHQL_ENDPOINT, headers=headers, json={"query": query}) as response:
        result = await response.json()
        return result['data']['actor']['account']['alerts']['nrqlConditionsSearch']['nrqlConditions']