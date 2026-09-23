from fastapi.testclient import TestClient

from app.inventory_activity import api
from app.main import create_app

TEST_ADMIN_TOKEN = "test-administrator-token-not-for-production-123456"


def login(client):
    client.headers["Origin"] = "http://localhost:5173"
    assert client.post("/api/auth/login", json={"token": TEST_ADMIN_TOKEN}).status_code == 200
from test_inventory_activity import row, workbook


def test_job_api_persistence_filters_explanation_and_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    monkeypatch.setenv("INVENTORY_ADMIN_TOKEN", TEST_ADMIN_TOKEN)
    with TestClient(create_app()) as client:
        login(client)
        config = client.get("/api/activity/config").json()
        assert config["policy"]["threshold_value"] == 180
        response = client.post("/api/activity/jobs", files={"file": ("test.xlsx", workbook(row("A", 180), row("B", 0, sequence=2)))})
        assert response.status_code == 200
        job = response.json()
        assert job["status"] == "completed"
    with TestClient(create_app()) as client:
        login(client)
        base = f"/api/activity/jobs/{job['job_id']}"
        assert client.get(base).json()["status"] == "completed"
        assert client.get(base + "/overview").json()["counts"]["inactive_candidate_count"] == 1
        assert client.get(base + "/assessments?inactive_only=true").json()["total"] == 1
        assert client.get(base + "/assessments?q=B").json()["items"][0]["material_code"] == "B"
        assert client.get(base + "/assessments?offset=99").json()["items"] == []
        assert client.get(base + "/assessments?limit=501").status_code == 422
        detail = client.get(base + "/materials/A/explanation").json()
        assert detail["source_records"][0]["excel_row"] == 2
        assert detail["assessment"]["inactive_candidate"] is True
        assert client.get(base + "/materials/unknown/explanation").status_code == 404
        for fmt in ("json", "csv", "ttl", "report"):
            download = client.get(base + "/download/" + fmt)
            assert download.status_code == 200
            assert len(download.content) > 100
        assert client.get(base + "/download/exe").status_code == 404
        assert (tmp_path / job["job_id"] / "source.xlsx").exists()


def test_api_failure_and_threshold_override(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    monkeypatch.setenv("INVENTORY_ADMIN_TOKEN", TEST_ADMIN_TOKEN)
    with TestClient(create_app()) as client:
        login(client)
        job = client.post("/api/activity/jobs", files={"file": ("bad.xlsx", b"invalid")}).json()
        assert job["status"] == "failed"
        assert client.get(f"/api/activity/jobs/{job['job_id']}/overview").status_code == 409
        assert client.get("/api/activity/jobs/unknown").status_code == 404
        response = client.post("/api/activity/jobs", files={"file": ("test.xlsx", workbook(row(days=179)))}, data={"threshold_days": "179"})
        job = response.json()
        overview = client.get(f"/api/activity/jobs/{job['job_id']}/overview").json()
        assert overview["counts"]["inactive_candidate_count"] == 1
        assert overview["policy"]["threshold_value"] == 179
        assert overview["policy"]["policy_id"] == "slow-moving-custom-179d"
