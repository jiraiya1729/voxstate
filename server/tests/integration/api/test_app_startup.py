from fastapi.testclient import TestClient

from app.main import create_app


def test_app_starts_and_health_endpoint_works() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
