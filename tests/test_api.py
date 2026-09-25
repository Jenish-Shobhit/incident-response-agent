import json

from fastapi.testclient import TestClient

from incident_agent.api import app

client = TestClient(app)


def sse_frames(response):
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_health_reports_mock_mode():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["mock"] is True
    assert body["problems"] == []


def test_index_serves_the_operator_console():
    response = client.get("/")
    assert response.status_code == 200
    assert "AI INCIDENT RESPONSE" in response.text


def test_incident_endpoint_serves_the_bundled_incident():
    response = client.get("/incident")
    assert response.status_code == 200
    assert response.json()["incident_id"] == "INC-3172"


def test_an_uploaded_file_gets_the_same_treatment_as_the_bundled_one(raw_incident):
    """/load and /incident share one normaliser; the same file must come out identical."""
    loaded = client.post("/load", json=raw_incident)
    assert loaded.status_code == 200
    assert loaded.json()["evidence"]
    assert loaded.json() == client.get("/incident").json()


def test_load_rejects_an_unexpected_shape():
    response = client.post("/load", json={"message": "not an incident"})
    assert response.status_code == 400


def test_run_pauses_and_resumes_through_the_http_contract():
    first = client.post("/run", json={})
    assert first.status_code == 200
    first_frames = sse_frames(first)
    start = next(frame for frame in first_frames if frame["e"] == "start")
    done = next(frame for frame in first_frames if frame["e"] == "done")
    assert done["awaiting"] is True

    second = client.post(
        "/approve",
        json={"thread_id": start["thread_id"], "approved_ids": []},
    )
    assert second.status_code == 200
    second_frames = sse_frames(second)
    assert any(frame["e"] == "receipt" for frame in second_frames)
    assert second_frames[-1] == {
        "e": "done",
        "thread_id": start["thread_id"],
        "awaiting": False,
    }
