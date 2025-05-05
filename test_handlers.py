import pytest
from unittest.mock import AsyncMock, patch
import aiohttp
from handlers.shared import send_graphql_request
from handlers.dashboard_widget_handler import validate_nrql_query, fetch_dashboard_json
from handlers.alert_condition_handler import fetch_alert_conditions

@pytest.mark.asyncio
@patch("aiohttp.ClientSession.post")
async def test_validate_nrql_query_success(mock_post):
    mock_response = AsyncMock()
    mock_response.__aenter__.return_value.json = AsyncMock(return_value={
        "data": {
            "actor": {
                "account": {
                    "nrql": {
                        "queryValidate": {
                            "valid": True
                        }
                    }
                }
            }
        }
    })
    mock_post.return_value = mock_response

    async with aiohttp.ClientSession() as session:
        result = await validate_nrql_query(session, 12345, "SELECT 1 FROM Metric")
        assert result is True

@pytest.mark.asyncio
@patch("aiohttp.ClientSession.post")
async def test_fetch_alert_conditions(mock_post):
    mock_response = AsyncMock()
    mock_response.__aenter__.return_value.json = AsyncMock(return_value={
        "data": {
            "actor": {
                "account": {
                    "alerts": {
                        "nrqlConditionsSearch": {
                            "nrqlConditions": [
                                {"id": "1", "name": "Cond A", "nrql": {"query": "SELECT 1"}}
                            ]
                        }
                    }
                }
            }
        }
    })
    mock_post.return_value = mock_response

    async with aiohttp.ClientSession() as session:
        conditions = await fetch_alert_conditions(session, 12345)
        assert isinstance(conditions, list)