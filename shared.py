import aiohttp
from logging_util import logger

API_KEY = "NRAK-YourNewRelicAPIKey"
GRAPHQL_ENDPOINT = "https://api.newrelic.com/graphql"

async def send_graphql_request(session: aiohttp.ClientSession, graphql_payload: str) -> dict:
    headers = {
        "Content-Type": "application/json",
        "API-Key": API_KEY
    }
    try:
        async with session.post(GRAPHQL_ENDPOINT, headers=headers, json={"query": graphql_payload}) as response:
            return await response.json()
    except Exception as e:
        logger.error(f"GraphQL request failed: {e}")
        return {"error": str(e)}