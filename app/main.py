"""

Employee Attendance & Analytics API

Current implementation stage:

- MongoDB health check and indexes

- Employee creation and listing

- Punch-in

- Attendance listing

Run from the candidate_kit directory:

    python -m uvicorn app.main:app --port 8000

Environment:

    MONGO_URI

    MONGO_DB

"""

import os

from datetime import date, datetime, timedelta, timezone

from decimal import Decimal, ROUND_HALF_UP

from typing import Literal, Optional

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Query

from pydantic import (

    BaseModel,

    ConfigDict,

    Field,

    StrictInt,

    field_validator,

    model_validator,

)

from pymongo import MongoClient

from pymongo.errors import DuplicateKeyError

# Real environment variables take precedence over values in .env.

load_dotenv()

mongo_uri = os.getenv("MONGO_URI")

if not mongo_uri:

    raise RuntimeError(

        "MONGO_URI is missing. Configure it in .env or the environment."

    )

client = MongoClient(

    mongo_uri,

    serverSelectionTimeoutMS=10000,

    tz_aware=True,

)

db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

UTC = timezone.utc

MIN_EPOCH_MS = 100_000_000_000

MAX_EPOCH_MS = 4_102_444_800_000

PRESENCE_STATUSES = {"PRESENT", "WFH", "ON_DUTY"}

ALL_STATUSES = {"PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"}

app = FastAPI(

    title="Employee Attendance & Analytics API",

    version="2.0.0",

)

# ---------------------------------------------------------------------------

# Startup indexes

# ---------------------------------------------------------------------------

@app.on_event("startup")

def create_indexes():

    """Create indexes idempotently, including concurrency safeguards."""

    db.employees.create_index(

        [("emp_code", 1)],

        unique=True,

        name="uq_employee_code",

    )

    db.employees.create_index(

        [("department", 1), ("emp_code", 1)],

        name="ix_employee_department_code",

    )

    db.employees.create_index(
        [("department", 1), ("joined_on", 1)],
        name="ix_employee_department_joined_on",
    )
    db.employees.create_index(
        [("joined_on", 1)],
        name="ix_employee_joined_on",
    )

    db.attendance_logs.create_index(

        [("emp_code", 1), ("date", 1)],

        unique=True,

        name="uq_attendance_employee_date",

    )

    db.attendance_logs.create_index(

        [("date", -1), ("emp_code", 1)],

        name="ix_attendance_date_employee",

    )

    db.attendance_logs.create_index(
        [("status", 1), ("date", -1), ("emp_code", 1)],
        name="ix_attendance_status_date_employee",
    )

# ---------------------------------------------------------------------------

# Time and serialization helpers

# ---------------------------------------------------------------------------

def truncate_to_seconds(value: datetime) -> datetime:

    """Discard fractional seconds before calculations and storage."""

    return value.replace(microsecond=0)

def normalize_utc(value: datetime) -> datetime:

    """PyMongo may return naive datetimes; interpret them as UTC."""

    if value.tzinfo is None:

        value = value.replace(tzinfo=UTC)

    return truncate_to_seconds(value.astimezone(UTC))

def to_epoch_ms(value: Optional[datetime]) -> Optional[int]:

    """Convert a BSON datetime to epoch milliseconds."""

    if value is None:

        return None

    value = normalize_utc(value)

    return int(value.timestamp() * 1000)

def from_epoch_ms(value: int) -> datetime:

    """Convert validated epoch milliseconds to a UTC datetime."""

    result = datetime.fromtimestamp(value // 1000, tz=UTC)

    return truncate_to_seconds(result)

def to_ist(value: datetime) -> datetime:

    """Convert a stored instant to IST."""

    return normalize_utc(value).astimezone(IST)

def attendance_date(

    punch_in: datetime,

    shift_start: str,

    shift_end: str,

) -> str:

    """

    Determine the attendance day in IST.

    For overnight shifts, a punch-in earlier than shift_end

    belongs to the shift that started the previous day.

    """

    local = to_ist(punch_in)

    start = datetime.strptime(shift_start, "%H:%M").time()

    end = datetime.strptime(shift_end, "%H:%M").time()

    day = local.date()

    if end <= start and local.time().replace(tzinfo=None) < end:

        day -= timedelta(days=1)

    return day.isoformat()

def compute_late_minutes(

    punch_in: datetime,

    shift_start: str,

    attendance_day: str,

) -> int:

    """

    R2: Late only when strictly more than 10 minutes after shift start.

    The reported value is whole minutes since shift start, not since

    the end of the grace period.

    """

    local = to_ist(punch_in)

    start_time = datetime.strptime(shift_start, "%H:%M").time()

    shift_start_dt = datetime.combine(

        date.fromisoformat(attendance_day),

        start_time,

        tzinfo=IST,

    )

    elapsed_seconds = (local - shift_start_dt).total_seconds()

    if elapsed_seconds <= 600:

        return 0

    return max(0, int(elapsed_seconds // 60))

def compute_work_hours(

    punch_in: datetime,

    punch_out: datetime,

) -> float:

    """R4: Calculate work hours with decimal half-up rounding."""

    seconds = (

        normalize_utc(punch_out) - normalize_utc(punch_in)

    ).total_seconds()

    hours = Decimal(str(seconds)) / Decimal("3600")

    return float(

        hours.quantize(

            Decimal("0.01"),

            rounding=ROUND_HALF_UP,

        )

    )

def compute_overtime(

    punch_out: datetime,

    shift_start: str,

    shift_end: str,

    attendance_day: str,

) -> int:

    """R3: Count overtime only when it reaches 30 whole minutes."""

    start_time = datetime.strptime(shift_start, "%H:%M").time()

    end_time = datetime.strptime(shift_end, "%H:%M").time()

    end_day = date.fromisoformat(attendance_day)

    if end_time <= start_time:

        end_day += timedelta(days=1)

    shift_end_dt = datetime.combine(end_day, end_time, tzinfo=IST)

    local_out = to_ist(punch_out)

    elapsed_seconds = (local_out - shift_end_dt).total_seconds()

    if elapsed_seconds < 0:

        return 0

    minutes = int(elapsed_seconds // 60)

    return minutes if minutes >= 30 else 0

def validate_epoch_ms(value: int) -> int:

    """Reject seconds, floats, strings and out-of-range timestamps."""

    if type(value) is not int:

        raise ValueError("Timestamp must be an integer in epoch milliseconds")

    if not MIN_EPOCH_MS <= value <= MAX_EPOCH_MS:

        raise ValueError("Timestamp is outside the permitted range")

    return value

def serialize_employee(document: dict) -> dict:

    """Return an employee without MongoDB's internal _id."""

    result = {

        key: value

        for key, value in document.items()

        if key != "_id"

    }

    if result.get("created_at") is not None:

        result["created_at"] = to_epoch_ms(result["created_at"])

    return result

def serialize_attendance(document: dict) -> dict:

    """

    Serialize an attendance record according to the API contract.

    Attendance records have no public id field.

    """

    result = {

        "emp_code": document["emp_code"],

        "date": document["date"],

        "status": document["status"],

        "punch_in": to_epoch_ms(document.get("punch_in")),

        "punch_out": to_epoch_ms(document.get("punch_out")),

        "work_hours": document.get("work_hours"),

        "late_minutes": document.get("late_minutes", 0),

        "overtime_minutes": document.get("overtime_minutes", 0),

        "half_day": document.get("half_day", False),

        "history": [],

    }

    for entry in document.get("history", []):

        changes = {}

        for field, change in entry.get("changes", {}).items():

            old_value = change.get("from")

            new_value = change.get("to")

            if field in {"punch_in", "punch_out"}:

                old_value = to_epoch_ms(old_value)

                new_value = to_epoch_ms(new_value)

            changes[field] = {

                "from": old_value,

                "to": new_value,

            }

        result["history"].append(

            {

                "at": to_epoch_ms(entry["at"]),

                "by": entry["by"],

                "reason": entry["reason"],

                "changes": changes,

            }

        )

    return result

# ---------------------------------------------------------------------------

# Request models

# ---------------------------------------------------------------------------

class EmployeeIn(BaseModel):

    model_config = ConfigDict(extra="ignore")

    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")

    name: str = Field(min_length=1, max_length=100)

    email: str = Field(

        min_length=1,

        max_length=120,

        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",

    )

    department: str = Field(min_length=1, max_length=50)

    shift_start: str = Field(

        default="09:30",

        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",

    )

    shift_end: str = Field(

        default="18:30",

        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",

    )

    joined_on: str

    @field_validator("emp_code", "name", "email", "department", mode="before")

    @classmethod

    def strip_text(cls, value):

        if isinstance(value, str):

            return value.strip()

        return value

    @field_validator("joined_on")

    @classmethod

    def validate_joined_on(cls, value):

        try:

            parsed = date.fromisoformat(value)

        except (ValueError, TypeError):

            raise ValueError("joined_on must use YYYY-MM-DD format")

        if parsed.isoformat() != value:

            raise ValueError("joined_on must use YYYY-MM-DD format")

        return value

    @model_validator(mode="after")

    def validate_shift(self):

        if self.shift_start == self.shift_end:

            raise ValueError("shift_start and shift_end must differ")

        return self

class PunchInIn(BaseModel):

    model_config = ConfigDict(extra="ignore")

    emp_code: str = Field(min_length=1)

    punched_at: Optional[StrictInt] = None

    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"

    @field_validator("punched_at")

    @classmethod

    def validate_punched_at(cls, value):

        if value is not None:

            validate_epoch_ms(value)

        return value

class PunchOutIn(BaseModel):

    model_config = ConfigDict(extra="ignore")

    emp_code: str = Field(min_length=1)

    punched_at: Optional[StrictInt] = None

    @field_validator("punched_at")

    @classmethod

    def validate_punched_at(cls, value):

        if value is not None:

            validate_epoch_ms(value)

        return value

class RegularizeIn(BaseModel):

    model_config = ConfigDict(extra="ignore")

    reason: str = Field(min_length=5, max_length=200)

    regularized_by: str = Field(min_length=1, max_length=50)

    status: Optional[

        Literal["PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"]

    ] = None

    punch_in: Optional[StrictInt] = None

    punch_out: Optional[StrictInt] = None

    @field_validator("reason", "regularized_by", mode="before")

    @classmethod

    def strip_required_text(cls, value):

        if isinstance(value, str):

            return value.strip()

        return value

    @field_validator("reason")

    @classmethod

    def validate_reason(cls, value):

        if len(value) < 5:

            raise ValueError("reason must contain at least 5 characters")

        return value

    @field_validator("regularized_by")

    @classmethod

    def validate_regularized_by(cls, value):

        if not value:

            raise ValueError("regularized_by must not be empty")

        return value

    @field_validator("punch_in", "punch_out", mode="before")

    @classmethod

    def validate_punch_timestamp(cls, value):

        if value is not None:

            validate_epoch_ms(value)

        return value

# ---------------------------------------------------------------------------

# Health

# ---------------------------------------------------------------------------

@app.get("/health")

def health():

    """Return 200 only when MongoDB responds to a ping."""

    try:

        client.admin.command("ping")

        return {"status": "ok"}

    except Exception:

        raise HTTPException(

            status_code=503,

            detail="MongoDB unavailable",

        )

# ---------------------------------------------------------------------------

# Employees

# ---------------------------------------------------------------------------

@app.post("/employees", status_code=201)

def create_employee(body: EmployeeIn):

    """Create an employee using the client-supplied employee code."""

    created_at = truncate_to_seconds(datetime.now(UTC))

    document = body.model_dump()

    document["created_at"] = created_at

    try:

        db.employees.insert_one(document)

    except DuplicateKeyError:

        raise HTTPException(

            status_code=409,

            detail="emp_code already exists",

        )

    return serialize_employee(document)

@app.get("/employees")

def list_employees(

    department: Optional[str] = None,

    page: int = Query(default=1, ge=1),

    page_size: int = Query(default=20, ge=1, le=100),

):

    """List employees with filtered counts and database pagination."""

    query = {}

    if department is not None:

        query["department"] = department

    total = db.employees.count_documents(query)

    skip = (page - 1) * page_size

    documents = list(

        db.employees.find(query)

        .sort("emp_code", 1)

        .skip(skip)

        .limit(page_size)

    )

    return {

        "items": [serialize_employee(d) for d in documents],

        "total": total,

        "page": page,

        "page_size": page_size,

    }

# ---------------------------------------------------------------------------

# Attendance: punch-in

# ---------------------------------------------------------------------------

@app.post("/attendance/punch-in", status_code=201)

def punch_in(body: PunchInIn):

    """Record a punch-in with timezone-safe dates and duplicate protection."""

    employee = db.employees.find_one(

        {"emp_code": body.emp_code}

    )

    if employee is None:

        raise HTTPException(

            status_code=404,

            detail="Employee not found",

        )

    raw_time = (

        from_epoch_ms(body.punched_at)

        if body.punched_at is not None

        else datetime.now(UTC)

    )

    punched_in = normalize_utc(raw_time)

    attendance_day = attendance_date(

        punched_in,

        employee["shift_start"],

        employee["shift_end"],

    )

    document = {

        "emp_code": body.emp_code,

        "date": attendance_day,

        "status": body.status,

        "punch_in": punched_in,

        "punch_out": None,

        "work_hours": None,

        "late_minutes": compute_late_minutes(

            punched_in,

            employee["shift_start"],

            attendance_day,

        ),

        "overtime_minutes": 0,

        "half_day": False,

        "history": [],

    }

    try:

        db.attendance_logs.insert_one(document)

    except DuplicateKeyError:

        raise HTTPException(

            status_code=409,

            detail="already punched in for this date",

        )

    return serialize_attendance(document)

# ---------------------------------------------------------------------------

# Attendance: list

# ---------------------------------------------------------------------------

@app.post("/attendance/punch-out")

def punch_out(body: PunchOutIn):

    # 1. Confirm that the employee exists.

    employee = db.employees.find_one(

        {"emp_code": body.emp_code}

    )

    if employee is None:

        raise HTTPException(

            status_code=404,

            detail="Employee not found",

        )

    # 2. Normalize the requested punch-out instant.

    punched_out = (

        from_epoch_ms(body.punched_at)

        if body.punched_at is not None

        else truncate_to_seconds(datetime.now(UTC))

    )

    punched_out = normalize_utc(punched_out)

    # 3. Find the most recent attendance record that started

    #    at or before this punch-out instant.

    record = db.attendance_logs.find_one(

        {

            "emp_code": body.emp_code,

            "punch_in": {"$lte": punched_out},

        },

        sort=[("punch_in", -1)],

    )

    if record is None:

        raise HTTPException(

            status_code=404,

            detail="No punch-in found",

        )

    if record.get("punch_out") is not None:

        raise HTTPException(

            status_code=409,

            detail="Attendance record is already punched out",

        )

    punched_in = normalize_utc(record["punch_in"])

    # 4. Punch-out must be later than punch-in and no more

    #    than 24 hours afterward.

    elapsed_seconds = (punched_out - punched_in).total_seconds()

    if elapsed_seconds <= 0 or elapsed_seconds > 24 * 60 * 60:

        raise HTTPException(

            status_code=422,

            detail="punched_at must be after punch-in and within 24 hours",

        )

    # 5. Calculate all derived values from the final timestamps.

    work_hours = compute_work_hours(punched_in, punched_out)

    overtime_minutes = compute_overtime(

        punched_out,

        employee["shift_start"],

        employee["shift_end"],

        record["date"],

    )

    half_day = work_hours < 4.50

    # 6. Atomic conditional update. If two requests race,

    #    only one can change punch_out from null.

    result = db.attendance_logs.update_one(

        {

            "emp_code": body.emp_code,

            "date": record["date"],

            "punch_out": None,

        },

        {

            "$set": {

                "punch_out": punched_out,

                "work_hours": work_hours,

                "overtime_minutes": overtime_minutes,

                "half_day": half_day,

            }

        },

    )

    if result.matched_count == 0:

        raise HTTPException(

            status_code=409,

            detail="Attendance record is already punched out",

        )

    # 7. Read back the stored record for the response.

    updated = db.attendance_logs.find_one(

        {

            "emp_code": body.emp_code,

            "date": record["date"],

        }

    )

    return serialize_attendance(updated)

@app.patch("/attendance/{emp_code}/{date}")

def regularize_attendance(

    emp_code: str,

    date: date,

    body: RegularizeIn,

):

    # Reject explicitly supplied null timestamps. Omitted fields are allowed.

    for field in ("punch_in", "punch_out"):

        if field in body.model_fields_set and getattr(body, field) is None:

            raise HTTPException(

                status_code=422,

                detail=f"{field} must be an epoch-millisecond integer",

            )

    employee = db.employees.find_one({"emp_code": emp_code})

    if employee is None:

        raise HTTPException(status_code=404, detail="Employee not found")

    day = date.isoformat()

    record = db.attendance_logs.find_one(

        {"emp_code": emp_code, "date": day}

    )

    if record is None:

        raise HTTPException(

            status_code=404,

            detail="Attendance record not found",

        )

    old_history = record.get("history", [])

    old_status = record["status"]

    old_in = record.get("punch_in")

    old_out = record.get("punch_out")

    # Normalize BSON dates to UTC-aware whole-second instants.

    old_in = normalize_utc(old_in) if old_in is not None else None

    old_out = normalize_utc(old_out) if old_out is not None else None

    status = body.status if body.status is not None else old_status

    new_in = (

        from_epoch_ms(body.punch_in)

        if "punch_in" in body.model_fields_set

        else old_in

    )

    new_out = (

        from_epoch_ms(body.punch_out)

        if "punch_out" in body.model_fields_set

        else old_out

    )

    # ABSENT and LEAVE records must never have punch times.

    if status in {"ABSENT", "LEAVE"}:

        if "punch_in" in body.model_fields_set or "punch_out" in body.model_fields_set:

            raise HTTPException(

                status_code=422,

                detail="ABSENT and LEAVE cannot be supplied with punch times",

            )

        new_in = None

        new_out = None

    # Presence statuses require a punch-in.

    if status in {"PRESENT", "WFH", "ON_DUTY"} and new_in is None:

        raise HTTPException(

            status_code=422,

            detail="Presence status requires a punch_in",

        )

    # The punch-in must belong to the record's IST attendance day.

    if new_in is not None:

        computed_day = attendance_date(

            new_in,

            employee["shift_start"],

            employee["shift_end"],

        )

        if computed_day != day:

            raise HTTPException(

                status_code=422,

                detail="punch_in does not belong to the requested attendance date",

            )

    # Validate punch-out against the final punch-in.

    if new_out is not None:

        if new_in is None:

            raise HTTPException(

                status_code=422,

                detail="punch_out requires punch_in",

            )

        elapsed = (new_out - new_in).total_seconds()

        if elapsed <= 0 or elapsed > 24 * 60 * 60:

            raise HTTPException(

                status_code=422,

                detail="punch_out must be after punch_in and within 24 hours",

            )

    # Recompute all derived values from the final status and times.

    if status in {"ABSENT", "LEAVE"}:

        derived = {

            "late_minutes": 0,

            "work_hours": None,

            "overtime_minutes": 0,

            "half_day": False,

        }

    else:

        derived = {

            "late_minutes": compute_late_minutes(

                new_in,

                employee["shift_start"],

                day,

            ),

            "work_hours": None,

            "overtime_minutes": 0,

            "half_day": False,

        }

        if new_out is not None:

            derived["work_hours"] = compute_work_hours(new_in, new_out)

            derived["overtime_minutes"] = compute_overtime(

                new_out,

                employee["shift_start"],

                employee["shift_end"],

                day,

            )

            derived["half_day"] = derived["work_hours"] < 4.50

    # Build a change set containing only values that actually changed.

    proposed = {

        "status": status,

        "punch_in": new_in,

        "punch_out": new_out,

        **derived,

    }

    changes = {}

    for field, new_value in proposed.items():

        old_value = record.get(field)

        if field in {"punch_in", "punch_out"} and old_value is not None:

            old_value = normalize_utc(old_value)

        # Missing derived values have their documented defaults.

        defaults = {

            "late_minutes": 0,

            "work_hours": None,

            "overtime_minutes": 0,

            "half_day": False,

        }

        if field not in record and field in defaults:

            old_value = defaults[field]

        if old_value != new_value:

            changes[field] = {"from": old_value, "to": new_value}

    if not changes:

        raise HTTPException(

            status_code=422,

            detail="The correction does not change the record",

        )

    corrected_at = truncate_to_seconds(datetime.now(UTC))

    audit_entry = {

        "at": corrected_at,

        "by": body.regularized_by,

        "reason": body.reason,

        "changes": changes,

    }

    update_fields = dict(proposed)

    # Compare the prior history in the update filter. If another correction

    # wins first, this update matches nothing and cannot lose that audit entry.

    history_filter = (

        {"history": old_history}

        if "history" in record

        else {"history": {"$exists": False}}

    )

    result = db.attendance_logs.update_one(

        {

            "emp_code": emp_code,

            "date": day,

            **history_filter,

        },

        {

            "$set": update_fields,

            "$push": {"history": audit_entry},

        },

    )

    if result.matched_count == 0:

        raise HTTPException(

            status_code=409,

            detail="Attendance record changed concurrently; retry the correction",

        )

    updated = db.attendance_logs.find_one(

        {"emp_code": emp_code, "date": day}

    )

    return serialize_attendance(updated)

@app.get("/attendance")

def list_attendance(

    emp_code: Optional[str] = None,

    date_from: Optional[date] = None,

    date_to: Optional[date] = None,

    status: Optional[

        Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]

    ] = None,

    page: int = Query(default=1, ge=1),

    page_size: int = Query(default=20, ge=1, le=100),

):

    """Filter, count, sort and paginate attendance in MongoDB."""

    if date_from and date_to and date_from > date_to:

        raise HTTPException(

            status_code=422,

            detail="date_from must be on or before date_to",

        )

    query = {}

    if emp_code is not None:

        query["emp_code"] = emp_code

    if date_from is not None or date_to is not None:

        date_filter = {}

        if date_from is not None:

            date_filter["$gte"] = date_from.isoformat()

        if date_to is not None:

            date_filter["$lte"] = date_to.isoformat()

        query["date"] = date_filter

    if status is not None:

        query["status"] = status

    total = db.attendance_logs.count_documents(query)

    skip = (page - 1) * page_size

    documents = list(

        db.attendance_logs.find(query)

        .sort([("date", -1), ("emp_code", 1)])

        .skip(skip)

        .limit(page_size)

    )

    return {

        "items": [serialize_attendance(d) for d in documents],

        "total": total,

        "page": page,

        "page_size": page_size,

    }

# ---------------------------------------------------------------------------

# Remaining assignment endpoints will be added in later steps:

# POST  /attendance/punch-out

# PATCH /attendance/{emp_code}/{date}

# GET   /analytics/employees/{emp_code}/monthly

# GET   /analytics/departments/summary

# GET   /analytics/leaderboard/late

# GET   /analytics/departments/{department}/trend

# GET   /admin/explain/{endpoint}

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Analytics: employee monthly summary (MongoDB aggregation; R5-R8)
# ---------------------------------------------------------------------------

def _month_bounds(month: str) -> tuple[str, str, str]:
    """Return inclusive first/last day and exclusive first day of next month."""
    try:
        parsed = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="month must use YYYY-MM format")
    if parsed.strftime("%Y-%m") != month:
        raise HTTPException(status_code=422, detail="month must use YYYY-MM format")
    first = parsed.replace(day=1)
    if first.month == 12:
        next_first = date(first.year + 1, 1, 1)
    else:
        next_first = date(first.year, first.month + 1, 1)
    last = next_first - timedelta(days=1)
    return first.isoformat(), last.isoformat(), next_first.isoformat()


def _round_half_up(value, places: int = 2):
    if value is None:
        return None
    quantum = Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(
    emp_code: str,
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
):
    """Monthly employee analytics. All attendance calculations run in MongoDB."""
    month_start, month_end, next_month_start = _month_bounds(month)
    pipeline = [
        {"$match": {"emp_code": emp_code}},
        {"$lookup": {
            "from": "attendance_logs",
            "let": {"code": "$emp_code"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$emp_code", "$$code"]},
                    {"$gte": ["$date", month_start]},
                    {"$lte": ["$date", month_end]},
                ]}}},
                {"$set": {
                    "_day": {"$dateFromString": {"dateString": "$date"}},
                    "_half_day": {"$ifNull": ["$half_day", False]},
                    "_late": {"$ifNull": ["$late_minutes", 0]},
                    "_overtime": {"$ifNull": ["$overtime_minutes", 0]},
                }},
                {"$set": {"_weekday": {"$dayOfWeek": "$_day"}}},
                {"$project": {
                    "status": 1, "_weekday": 1, "_half_day": 1,
                    "_late": 1, "_overtime": 1,
                }},
            ],
            "as": "_logs",
        }},
        {"$set": {
            "_joined_start": {"$max": ["$joined_on", month_start]},
            "_month_next": next_month_start,
        }},
        {"$set": {
            "_start_date": {"$dateFromString": {"dateString": "$_joined_start"}},
            "_next_date": {"$dateFromString": {"dateString": "$_month_next"}},
        }},
        {"$set": {
            "_calendar_offsets": {"$range": [0, {"$max": [0, {"$dateDiff": {
                "startDate": "$_start_date", "endDate": "$_next_date", "unit": "day"
            }}]}]},
        }},
        {"$set": {
            "_calendar_days": {"$map": {
                "input": "$_calendar_offsets", "as": "offset",
                "in": {"$dateAdd": {"startDate": "$_start_date", "unit": "day", "amount": "$$offset"}},
            }},
        }},
        {"$set": {
            "working_days": {"$size": {"$filter": {
                "input": "$_calendar_days", "as": "day",
                "cond": {"$and": [
                    {"$ne": [{"$dayOfWeek": "$$day"}, 1]},
                    {"$ne": [{"$dayOfWeek": "$$day"}, 7]},
                ]},
            }}},
            "present_days": {"$sum": {"$map": {
                "input": "$_logs", "as": "log",
                "in": {"$cond": [
                    {"$and": [
                        {"$in": ["$$log.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                        {"$and": [
                            {"$ne": ["$$log._weekday", 1]},
                            {"$ne": ["$$log._weekday", 7]},
                        ]},
                    ]},
                    {"$cond": ["$$log._half_day", 0.5, 1]},
                    0,
                ]},
            }}},
            "leave_days": {"$size": {"$filter": {"input": "$_logs", "as": "log", "cond": {"$eq": ["$$log.status", "LEAVE"]}}}},
            "late_count": {"$size": {"$filter": {"input": "$_logs", "as": "log", "cond": {"$gt": ["$$log._late", 0]}}}},
            "total_late_minutes": {"$sum": {"$map": {"input": "$_logs", "as": "log", "in": "$$log._late"}}},
            "total_overtime_minutes": {"$sum": {"$map": {"input": "$_logs", "as": "log", "in": "$$log._overtime"}}},
        }},
        {"$project": {
            "_id": 0, "emp_code": 1, "working_days": 1, "present_days": 1,
            "leave_days": 1, "late_count": 1,
            "total_late_minutes": 1, "total_overtime_minutes": 1,
        }},
    ]
    rows = list(db.employees.aggregate(pipeline))
    if not rows:
        raise HTTPException(status_code=404, detail="employee not found")
    result = rows[0]
    working_days = int(result.get("working_days", 0))
    present_days = float(result.get("present_days", 0))
    attendance_pct = None if working_days == 0 else _round_half_up(present_days / working_days * 100, 2)
    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": int(result.get("leave_days", 0)),
        "late_count": int(result.get("late_count", 0)),
        "total_late_minutes": int(result.get("total_late_minutes", 0)),
        "total_overtime_minutes": int(result.get("total_overtime_minutes", 0)),
        "attendance_pct": attendance_pct,
    }


# ---------------------------------------------------------------------------
# Analytics: department summary (MongoDB aggregation; R6-R9)
# ---------------------------------------------------------------------------

@app.get("/analytics/departments/summary")
def department_summary(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: str | None = Query(None),
):
    """Department-level monthly analytics; employees without logs still count."""
    month_start, month_end, _ = _month_bounds(month)
    employee_match = {"joined_on": {"$lte": month_end}}
    if department is not None:
        employee_match["department"] = department

    pipeline = [
        {"$match": employee_match},
        {"$lookup": {
            "from": "attendance_logs",
            "let": {"code": "$emp_code"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$emp_code", "$$code"]},
                    {"$gte": ["$date", month_start]},
                    {"$lte": ["$date", month_end]},
                ]}}},
                {"$set": {
                    "_day": {"$dateFromString": {"dateString": "$date"}},
                    "_half_day": {"$ifNull": ["$half_day", False]},
                    "_late": {"$ifNull": ["$late_minutes", 0]},
                    "_work_hours": {"$ifNull": ["$work_hours", None]},
                }},
                {"$set": {"_weekday": {"$dayOfWeek": "$_day"}}},
                {"$project": {
                    "status": 1, "_weekday": 1, "_half_day": 1,
                    "_late": 1, "_work_hours": 1,
                }},
            ],
            "as": "_logs",
        }},
        {"$unwind": {"path": "$_logs", "preserveNullAndEmptyArrays": True}},
        {"$set": {
            "_present_day": {"$cond": [
                {"$and": [
                    {"$in": ["$_logs.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                    {"$ne": ["$_logs._weekday", 1]},
                    {"$ne": ["$_logs._weekday", 7]},
                ]},
                {"$cond": ["$_logs._half_day", 0.5, 1]},
                0,
            ]},
            "_avg_work_hours": {"$cond": [
                {"$and": [
                    {"$in": ["$_logs.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                    {"$ne": ["$_logs._work_hours", None]},
                ]},
                "$_logs._work_hours",
                None,
            ]},
            "_late_count": {"$cond": [{"$gt": ["$_logs._late", 0]}, 1, 0]},
            "_late_minutes": {"$ifNull": ["$_logs._late", 0]},
            "_leave_count": {"$cond": [{"$eq": ["$_logs.status", "LEAVE"]}, 1, 0]},
            "_on_duty_count": {"$cond": [{"$eq": ["$_logs.status", "ON_DUTY"]}, 1, 0]},
        }},
        {"$group": {
            "_id": "$department",
            "headcount": {"$addToSet": "$emp_code"},
            "present_days": {"$sum": "$_present_day"},
            "avg_work_hours": {"$avg": "$_avg_work_hours"},
            "late_count": {"$sum": "$_late_count"},
            "total_late_minutes": {"$sum": "$_late_minutes"},
            "leave_count": {"$sum": "$_leave_count"},
            "on_duty_count": {"$sum": "$_on_duty_count"},
        }},
        {"$project": {
            "_id": 0,
            "department": "$_id",
            "headcount": {"$size": "$headcount"},
            "present_days": 1,
            "avg_work_hours": 1,
            "late_count": 1,
            "total_late_minutes": 1,
            "leave_count": 1,
            "on_duty_count": 1,
        }},
        {"$sort": {"department": 1}},
    ]

    rows = list(db.employees.aggregate(pipeline))
    items = []
    for row in rows:
        if int(row.get("headcount", 0)) <= 0:
            continue
        items.append({
            "department": row["department"],
            "headcount": int(row["headcount"]),
            "present_days": _round_half_up(row.get("present_days", 0), 2),
            "avg_work_hours": _round_half_up(row.get("avg_work_hours"), 2),
            "late_count": int(row.get("late_count", 0)),
            "total_late_minutes": int(row.get("total_late_minutes", 0)),
            "leave_count": int(row.get("leave_count", 0)),
            "on_duty_count": int(row.get("on_duty_count", 0)),
        })
    return {"month": month, "items": items}


# ---------------------------------------------------------------------------
# Analytics: late-comers leaderboard (MongoDB aggregation; R8)
# ---------------------------------------------------------------------------

@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    limit: int = Query(10, ge=1, le=50),
    department: str | None = Query(None),
):
    """Rank employees by monthly late minutes, preserving competition ties."""
    month_start, month_end, _ = _month_bounds(month)

    pipeline = [
        {"$match": {"date": {"$gte": month_start, "$lte": month_end}}},
        {"$set": {"_late": {"$ifNull": ["$late_minutes", 0]}}},
        {"$group": {
            "_id": "$emp_code",
            "total_late_minutes": {"$sum": "$_late"},
            "late_count": {"$sum": {"$cond": [{"$gt": ["$_late", 0]}, 1, 0]}},
        }},
        {"$match": {"total_late_minutes": {"$gt": 0}}},
        {"$lookup": {
            "from": "employees",
            "localField": "_id",
            "foreignField": "emp_code",
            "as": "_employee",
        }},
        {"$unwind": "$_employee"},
    ]
    # Filter before $rank so the rank is computed within the selected department.
    if department is not None:
        pipeline.append({"$match": {"_employee.department": department}})

    pipeline.extend([
        {"$setWindowFields": {
            "sortBy": {"total_late_minutes": -1},
            "output": {"rank": {"$rank": {}}},
        }},
        {"$match": {"rank": {"$lte": limit}}},
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {"$project": {
            "_id": 0,
            "rank": 1,
            "emp_code": "$_id",
            "name": "$_employee.name",
            "department": "$_employee.department",
            "total_late_minutes": 1,
            "late_count": 1,
        }},
    ])

    rows = list(db.attendance_logs.aggregate(pipeline))
    return {
        "month": month,
        "items": [{
            "rank": int(row["rank"]),
            "emp_code": row["emp_code"],
            "name": row["name"],
            "department": row["department"],
            "total_late_minutes": int(row["total_late_minutes"]),
            "late_count": int(row["late_count"]),
        } for row in rows],
    }


# ---------------------------------------------------------------------------
# Analytics: daily department trend (MongoDB gap filling; MongoDB 6.0+)
# ---------------------------------------------------------------------------

@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
):
    """Return a row for every date in the requested range, including weekends/gaps."""
    if to_date < from_date:
        raise HTTPException(status_code=422, detail="to must be on or after from")
    day_count = (to_date - from_date).days + 1
    if day_count > 92:
        raise HTTPException(status_code=422, detail="date range cannot exceed 92 days")

    if db.employees.find_one({"department": department}, {"_id": 1}) is None:
        raise HTTPException(status_code=404, detail="Unknown department")

    start_dt = datetime.combine(from_date, datetime.min.time(), tzinfo=UTC)
    end_exclusive = datetime.combine(to_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    pipeline = [
        {"$documents": [{"_day": start_dt}]},
        {"$densify": {
            "field": "_day",
            "range": {"step": 1, "unit": "day", "bounds": [start_dt, end_exclusive]},
        }},
        {"$set": {"date": {"$dateToString": {"date": "$_day", "format": "%Y-%m-%d", "timezone": "UTC"}}}},
        {"$lookup": {
            "from": "employees",
            "let": {"day": "$date"},
            "pipeline": [{"$match": {"$expr": {"$and": [
                {"$eq": ["$department", department]},
                {"$lte": ["$joined_on", "$$day"]},
            ]}}}, {"$count": "n"}],
            "as": "_headcount_rows",
        }},
        {"$lookup": {
            "from": "attendance_logs",
            "let": {"day": "$date"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$date", "$$day"]}}},
                {"$lookup": {"from": "employees", "localField": "emp_code", "foreignField": "emp_code", "as": "_emp"}},
                {"$unwind": "$_emp"},
                {"$match": {"_emp.department": department}},
                {"$project": {"status": 1, "half_day": 1, "late_minutes": 1}},
            ],
            "as": "_logs",
        }},
        {"$set": {
            "is_working_day": {"$not": [{"$in": [{"$dayOfWeek": "$_day"}, [1, 7]]}]},
            "headcount": {"$ifNull": [{"$arrayElemAt": ["$_headcount_rows.n", 0]}, 0]},
            "present_count": {"$sum": {"$map": {"input": "$_logs", "as": "log", "in": {
                "$cond": [
                    {"$in": ["$$log.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                    {"$cond": [{"$ifNull": ["$$log.half_day", False]}, 0.5, 1]},
                    0,
                ]
            }}}},
            "late_count": {"$size": {"$filter": {"input": "$_logs", "as": "log", "cond": {"$gt": [{"$ifNull": ["$$log.late_minutes", 0]}, 0]}}}},
        }},
        {"$set": {"attendance_rate": {"$cond": [
            {"$and": ["$is_working_day", {"$gt": ["$headcount", 0]}]},
            {"$divide": ["$present_count", "$headcount"]},
            None,
        ]}}},
        {"$setWindowFields": {
            "sortBy": {"_day": 1},
            "output": {"_moving_avg": {"$avg": "$attendance_rate", "window": {"documents": [-6, 0]}}},
        }},
        {"$sort": {"_day": 1}},
        {"$project": {"_id": 0, "date": 1, "is_working_day": 1, "headcount": 1,
                       "present_count": 1, "late_count": 1, "attendance_rate": 1, "_moving_avg": 1}},
    ]
    try:
        rows = list(db.aggregate(pipeline))
    except Exception as exc:
        # MongoDB 6.0+ is required for $densify/$setWindowFields/$documents.
        raise HTTPException(status_code=500, detail=f"Trend aggregation failed: {exc}")

    items = []
    for row in rows:
        rate = row.get("attendance_rate")
        moving = row.get("_moving_avg")
        items.append({
            "date": row["date"],
            "is_working_day": bool(row["is_working_day"]),
            "headcount": int(row.get("headcount", 0)),
            "present_count": _round_half_up(row.get("present_count", 0), 2),
            "late_count": int(row.get("late_count", 0)),
            "attendance_rate": _round_half_up(rate, 4) if rate is not None else None,
            "moving_avg_7d": _round_half_up(moving, 4) if moving is not None else None,
        })
    return {"department": department, "items": items}



# ---------------------------------------------------------------------------
# Admin: explain the main database operation for a supported endpoint
# ---------------------------------------------------------------------------

from bson.json_util import dumps as bson_dumps, RELAXED_JSON_OPTIONS
import json


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: Literal[
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend",
    ],
    emp_code: str | None = Query(None),
    month: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    status: Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"] | None = Query(None),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """Return MongoDB executionStats for the selected endpoint's main operation."""
    if endpoint == "attendance_list":
        query = {}
        if emp_code is not None:
            query["emp_code"] = emp_code
        if date_from is not None or date_to is not None:
            bounds = {}
            if date_from is not None:
                bounds["$gte"] = date_from.isoformat()
            if date_to is not None:
                bounds["$lte"] = date_to.isoformat()
            query["date"] = bounds
        if status is not None:
            query["status"] = status
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status_code=422, detail="date_from must be on or before date_to")
        collection_name = "attendance_logs"
        command = {
            "find": collection_name,
            "filter": query,
            "sort": {"date": -1, "emp_code": 1},
            "skip": (page - 1) * page_size,
            "limit": page_size,
        }
    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(status_code=422, detail="emp_code and month are required")
        month_start, month_end, next_month_start = _month_bounds(month)
        collection_name = "employees"
        # Explain the indexed employee lookup and its month-scoped attendance lookup.
        command = {"aggregate": collection_name, "pipeline": [
            {"$match": {"emp_code": emp_code}},
            {"$lookup": {"from": "attendance_logs", "let": {"code": "$emp_code"}, "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$emp_code", "$$code"]},
                    {"$gte": ["$date", month_start]},
                    {"$lte": ["$date", month_end]},
                ]}}},
            ], "as": "_logs"}},
        ], "cursor": {}}
    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(status_code=422, detail="month is required")
        month_start, month_end, _ = _month_bounds(month)
        employee_match = {"joined_on": {"$lte": month_end}}
        if department is not None:
            employee_match["department"] = department
        collection_name = "employees"
        # Preserve the summary's employee-side filtering and cross-collection join.
        command = {"aggregate": collection_name, "pipeline": [
            {"$match": employee_match},
            {"$lookup": {"from": "attendance_logs", "let": {"code": "$emp_code"}, "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$emp_code", "$$code"]},
                    {"$gte": ["$date", month_start]},
                    {"$lte": ["$date", month_end]},
                ]}}},
            ], "as": "_logs"}},
        ], "cursor": {}}
    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(status_code=422, detail="month is required")
        month_start, month_end, _ = _month_bounds(month)
        collection_name = "attendance_logs"
        pipeline = [
            {"$match": {"date": {"$gte": month_start, "$lte": month_end}}},
            {"$set": {"_late": {"$ifNull": ["$late_minutes", 0]}}},
            {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": "$_late"},
                        "late_count": {"$sum": {"$cond": [{"$gt": ["$_late", 0]}, 1, 0]}}}},
            {"$match": {"total_late_minutes": {"$gt": 0}}},
            {"$lookup": {"from": "employees", "localField": "_id", "foreignField": "emp_code", "as": "_employee"}},
            {"$unwind": "$_employee"},
        ]
        if department is not None:
            pipeline.append({"$match": {"_employee.department": department}})
        pipeline.extend([
            {"$setWindowFields": {"sortBy": {"total_late_minutes": -1}, "output": {"rank": {"$rank": {}}}}},
            {"$match": {"rank": {"$lte": limit}}},
            {"$sort": {"total_late_minutes": -1, "_id": 1}},
        ])
        command = {"aggregate": collection_name, "pipeline": pipeline, "cursor": {}}
    else:  # department_trend
        if department is None or from_date is None or to_date is None:
            raise HTTPException(status_code=422, detail="department, from and to are required")
        if to_date < from_date:
            raise HTTPException(status_code=422, detail="to must be on or after from")
        if (to_date - from_date).days + 1 > 92:
            raise HTTPException(status_code=422, detail="date range cannot exceed 92 days")
        if db.employees.find_one({"department": department}, {"_id": 1}) is None:
            raise HTTPException(status_code=404, detail="Unknown department")
        # Atlas deployments may reject database-level aggregate: 1 commands.
        # Explain the collection-backed part of the trend query instead: date
        # filtering and the employee join used to scope attendance to a department.
        # The route's $documents/$densify stages generate calendar dates separately.
        collection_name = "attendance_logs"
        command = {
            "aggregate": collection_name,
            "pipeline": [
                {
                    "$match": {
                        "date": {
                            "$gte": from_date.isoformat(),
                            "$lte": to_date.isoformat(),
                        }
                    }
                },
                {
                    "$lookup": {
                        "from": "employees",
                        "localField": "emp_code",
                        "foreignField": "emp_code",
                        "as": "_employee",
                    }
                },
                {"$unwind": "$_employee"},
                {"$match": {"_employee.department": department}},
                {
                    "$project": {
                        "_id": 0,
                        "emp_code": 1,
                        "date": 1,
                        "status": 1,
                        "half_day": 1,
                        "late_minutes": 1,
                    }
                },
            ],
            "cursor": {},
        }

    explain_doc = client[db.name].command(
        "explain", command, verbosity="executionStats"
    )
    # Relaxed Extended JSON keeps BSON-specific explain values JSON serializable.
    safe_explain = json.loads(bson_dumps(explain_doc, json_options=RELAXED_JSON_OPTIONS))
    return {"endpoint": endpoint, "collection": collection_name, "explain": safe_explain}
