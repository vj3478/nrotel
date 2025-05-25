# newrelic_dashboard_updater/graphql/dashboard_updater.py

import aiohttp
import asyncio
from newrelic_dashboard_updater.utils.logger import logger
from newrelic_dashboard_updater.config import API_KEY

UPDATE_WIDGET_QUERY = """
mutation($dashboardId: EntityGuid!, $pageId: EntityGuid!, $widgetId: ID!, $configuration: DashboardWidgetConfigurationInput!) {
  dashboardUpdateWidget(dashboardId: $dashboardId, pageId: $pageId, widgetId: $widgetId, configuration: $configuration) {
    widget {
      id
    }
  }
}
"""

async def update_widget_query(dashboard_id, page_id, widget_id, new_query, original_query):
    if original_query.strip() == new_query.strip():
        logger.info(f"No change in NRQL for widget {widget_id}; skipping update.")
        return True

    headers = {
        "Api-Key": API_KEY,
        "Content-Type": "application/json"
    }

    # Escape special characters
    sanitized_query = new_query.replace('"', '\\"').replace('\n', ' ')

    payload = {
        "query": UPDATE_WIDGET_QUERY,
        "variables": {
            "dashboardId": dashboard_id,
            "pageId": page_id,
            "widgetId": widget_id,
            "configuration": {
                "nrqlQueries": [
                    {"query": sanitized_query}
                ]
            }
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.post("https://api.newrelic.com/graphql", headers=headers, json=payload) as resp:
            if resp.status != 200:
                logger.error(f"Failed to update widget {widget_id}: {resp.status}")
                return False
            result = await resp.json()
            if "errors" in result:
                logger.error(f"GraphQL errors updating widget {widget_id}: {result['errors']}")
                return False
            logger.info(f"Successfully updated widget {widget_id} on dashboard {dashboard_id}, page {page_id}")
            return True
