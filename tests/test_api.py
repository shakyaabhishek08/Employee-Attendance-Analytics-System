
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

# Load local configuration, but run tests against a separate database.
load_dotenv()

production_db = os.getenv("MONGO_DB", "attendance_db")
test_db = os.getenv("TEST_MONGO_DB", "candidate_kit_test")

if test_db == production_db:
    raise RuntimeError(
        "Refusing to run tests against the configured application database. "
        "Set TEST_MONGO_DB to a separate database name."
    )

os.environ["MONGO_DB"] = test_db

from app.main import app, db  # noqa: E402


IST = timezone(timedelta(hours=5, minutes=30))


def epoch_ms(day, time):
    """Convert an IST date/time to epoch milliseconds."""
    instant = datetime.fromisoformat(f"{day}T{time}:00+05:30")
    return int(instant.timestamp() * 1000)


@pytest.fixture(scope="session")
def api():
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def clean_test_database():
    """Use only the isolated test database."""
    db.attendance_logs.delete_many({})
    db.employees.delete_many({})
    yield
    db.attendance_logs.delete_many({})
    db.employees.delete_many({})


def create_employee(api, code="EMP990001", department="Engineering"):
    response = api.post(
        "/employees",
        json={
            "emp_code": code,
            "name": "Test Employee",
            "email": f"{code.lower()}@example.com",
            "department": department,
            "shift_start": "09:30",
            "shift_end": "18:30",
            "joined_on": "2026-07-01",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def punch_in(api, code="EMP990001", time="10:15"):
    return api.post(
        "/attendance/punch-in",
        json={
            "emp_code": code,
            "punched_at": epoch_ms("2026-07-06", time),
        },
    )


def punch_out(api, code="EMP990001", time="19:15"):
    return api.post(
        "/attendance/punch-out",
        json={
            "emp_code": code,
            "punched_at": epoch_ms("2026-07-06", time),
        },
    )


def test_health(api):
    response = api.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_duplicate_employee_returns_409(api):
    create_employee(api)

    response = api.post(
        "/employees",
        json={
            "emp_code": "EMP990001",
            "name": "Duplicate Employee",
            "email": "duplicate@example.com",
            "department": "Engineering",
            "joined_on": "2026-07-01",
        },
    )

    assert response.status_code == 409


def test_concurrent_punch_in_creates_one_record(api):
    create_employee(api)

    def send_request(_):
        return api.post(
            "/attendance/punch-in",
            json={
                "emp_code": "EMP990001",
                "punched_at": epoch_ms("2026-07-06", "10:15"),
            },
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(send_request, range(8)))

    statuses = [r.status_code for r in responses]

    assert statuses.count(201) == 1
    assert statuses.count(409) == 7
    assert db.attendance_logs.count_documents(
        {"emp_code": "EMP990001", "date": "2026-07-06"}
    ) == 1


def test_concurrent_punch_out_closes_record_once(api):
    create_employee(api)
    assert punch_in(api).status_code == 201

    def send_request(_):
        return punch_out(api)

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(send_request, range(8)))

    statuses = [r.status_code for r in responses]

    assert statuses.count(200) == 1
    assert statuses.count(409) == 7

    record = db.attendance_logs.find_one({"emp_code": "EMP990001"})
    assert record["punch_out"] is not None
    assert record["work_hours"] == 9.0


def test_regularization_appends_audit_and_rejects_noop(api):
    create_employee(api)
    assert punch_in(api).status_code == 201
    assert punch_out(api).status_code == 200

    url = "/attendance/EMP990001/2026-07-06"

    response = api.patch(
        url,
        json={
            "status": "WFH",
            "reason": "Corrected work mode",
            "regularized_by": "qa",
        },
    )

    assert response.status_code == 200, response.text
    record = response.json()

    assert record["status"] == "WFH"
    assert len(record["history"]) == 1
    assert record["history"][0]["by"] == "qa"
    assert record["history"][0]["reason"] == "Corrected work mode"
    assert set(record["history"][0]["changes"]) == {"status"}

    no_op = api.patch(
        url,
        json={
            "status": "WFH",
            "reason": "Another correction",
            "regularized_by": "qa",
        },
    )

    assert no_op.status_code == 422

    stored = db.attendance_logs.find_one({"emp_code": "EMP990001"})
    assert len(stored["history"]) == 1


def test_monthly_summary_department_summary_and_leaderboard(api):
    create_employee(api)
    assert punch_in(api).status_code == 201
    assert punch_out(api).status_code == 200

    monthly = api.get(
        "/analytics/employees/EMP990001/monthly",
        params={"month": "2026-07"},
    )
    assert monthly.status_code == 200, monthly.text
    assert monthly.json()["present_days"] == 1.0
    assert monthly.json()["late_count"] == 1
    assert monthly.json()["total_late_minutes"] == 45

    summary = api.get(
        "/analytics/departments/summary",
        params={"month": "2026-07", "department": "Engineering"},
    )
    assert summary.status_code == 200, summary.text
    item = summary.json()["items"][0]
    assert item["headcount"] == 1
    assert item["present_days"] == 1.0

    leaderboard = api.get(
        "/analytics/leaderboard/late",
        params={"month": "2026-07", "limit": 10},
    )
    assert leaderboard.status_code == 200, leaderboard.text
    assert leaderboard.json()["items"][0]["emp_code"] == "EMP990001"
    assert leaderboard.json()["items"][0]["total_late_minutes"] == 45


def test_department_trend_fills_every_requested_date(api):
    create_employee(api)
    assert punch_in(api).status_code == 201
    assert punch_out(api).status_code == 200

    response = api.get(
        "/analytics/departments/Engineering/trend",
        params={"from": "2026-07-01", "to": "2026-07-10"},
    )

    assert response.status_code == 200, response.text

    items = response.json()["items"]
    assert len(items) == 10
    assert items[0]["date"] == "2026-07-01"
    assert items[-1]["date"] == "2026-07-10"

    monday = next(item for item in items if item["date"] == "2026-07-06")
    assert monday["headcount"] == 1
    assert monday["present_count"] == 1.0
    assert monday["attendance_rate"] == 1.0


def test_explain_endpoint_variants(api):
    create_employee(api)

    requests = [
        ("attendance_list", {}),
        (
            "employee_monthly",
            {"emp_code": "EMP990001", "month": "2026-07"},
        ),
        ("department_summary", {"month": "2026-07"}),
        ("late_leaderboard", {"month": "2026-07"}),
        (
            "department_trend",
            {
                "department": "Engineering",
                "from": "2026-07-01",
                "to": "2026-07-02",
            },
        ),
    ]

    for endpoint, params in requests:
        response = api.get(f"/admin/explain/{endpoint}", params=params)

        assert response.status_code == 200, (
            f"{endpoint}: {response.status_code} {response.text}"
        )

        result = response.json()
        assert result["endpoint"] == endpoint
        assert "explain" in result
        assert isinstance(result["explain"], dict)


def test_invalid_timestamp_returns_422(api):
    create_employee(api)

    response = api.post(
        "/attendance/punch-in",
        json={
            "emp_code": "EMP990001",
            "punched_at": 1_720_000_000,
        },
    )

    assert response.status_code == 422


def test_invalid_pagination_returns_422(api):
    response = api.get("/employees", params={"page": 0})
    assert response.status_code == 422

    response = api.get("/attendance", params={"page_size": 101})
    assert response.status_code == 422
