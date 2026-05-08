from fastapi.testclient import TestClient

from azure_region_monitor.api import app


def test_latest_snapshot_returns_sample_data():
    client = TestClient(app)

    response = client.get("/api/latest")

    assert response.status_code == 200
    assert response.json()["regions"]["swedencentral"]["aks"]["extensions.gitops"]["status"] == "available"


def test_region_endpoint_filters_latest_snapshot():
    client = TestClient(app)

    response = client.get("/api/regions/westeurope")

    assert response.status_code == 200
    assert response.json()["region"] == "westeurope"
    assert set(response.json()["services"]) == {"aks"}


def test_unknown_region_returns_404():
    client = TestClient(app)

    response = client.get("/api/regions/antarcticadev")

    assert response.status_code == 404
