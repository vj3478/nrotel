import pytest
from main import app

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def test_update_dashboard_missing_guid(client):
    response = client.post('/update-dashboard', json={})
    assert response.status_code == 400
    assert b'dashboard_guid is required' in response.data