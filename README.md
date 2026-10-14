# Attendly — Employee Attendance & Analytics System

A full-stack employee attendance management and workforce analytics application built with **React, FastAPI, Python, and MongoDB Atlas**. Attendly helps HR administrators manage employees, track attendance, correct attendance records, and analyze workforce trends through an interactive dashboard.

## Features

- **Interactive Dashboard:** Overview of employees, attendance records, presence rate, and late arrivals.
- **Employee Management:** Register employees and view employee details, departments, and shift information.
- **Attendance Tracking:** Record employee punch-in and punch-out times.
- **Attendance Regularization:** Correct attendance status or timestamps with a reason and administrator identification.
- **Audit History:** Maintain a record of attendance corrections, including the changes made.
- **Work-Hour Calculations:** Calculate work hours and attendance-related metrics.
- **Analytics Dashboard:** View department summaries and monthly attendance metrics.
- **Late-Arrival Leaderboard:** Analyze late-arrival statistics by employee.
- **Date Filters:** Filter attendance records by a selected date range.
- **CSV Export:** Export attendance records for reporting and analysis.
- **REST API:** FastAPI endpoints for employee management, attendance operations, and analytics.

## Tech Stack

| Layer | Technologies |
|---|---|
| Frontend | React, Vite, JavaScript, CSS |
| Data Visualization | Recharts |
| Icons | Lucide React |
| Backend | Python, FastAPI |
| Database | MongoDB Atlas |
| API Testing | Pytest, FastAPI TestClient |
| Version Control | Git, GitHub |

## Architecture

```text
┌──────────────────────────────┐
│       React Dashboard        │
│                              │
│ Employees · Attendance       │
│ Analytics · CSV Reports      │
└──────────────┬───────────────┘
               │ HTTP / REST API
               ▼
┌──────────────────────────────┐
│          FastAPI             │
│                              │
│ Validation · Business Logic  │
│ Attendance · Analytics       │
│ Regularization · Audit Trail  │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│        MongoDB Atlas         │
│                              │
│ Employee and Attendance Data │
└──────────────────────────────┘
```

## Project Structure

```text
candidate_kit/
├── app/
│   ├── __init__.py
│   └── main.py
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── assets/
│   │   ├── App.jsx
│   │   ├── App.css
│   │   ├── index.css
│   │   └── main.jsx
│   ├── package.json
│   └── vite.config.js
├── sample_data/
│   ├── attendance_logs.json
│   └── employees.json
├── tests/
│   └── test_api.py
├── .env.example
├── .gitignore
├── DATA_MODEL.md
├── DECISIONS.md
├── openapi.yaml
├── requirements.txt
├── sample_seed.py
└── README.md
```

## Prerequisites

Install the following before running the application:

- Python 3.10 or a compatible Python version supported by the dependencies.
- Node.js and npm.
- A MongoDB database, such as MongoDB Atlas.
- Git.

## Installation and Setup

### 1. Clone the repository

Replace `YOUR_USERNAME` with your GitHub username.

```bash
git clone https://github.com/YOUR_USERNAME/attendly-attendance-analytics.git
cd attendly-attendance-analytics
```

### 2. Configure the backend

Create and activate a Python virtual environment.

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
MONGO_URI=your_mongodb_connection_string
MONGO_DB=attendance_db
```

Replace the placeholder with your own MongoDB connection string. Configure database access and network permissions in MongoDB Atlas as required.

**Security:** Never commit your actual `.env` file, database credentials, or other secrets to GitHub.

### 3. Start the backend

From the project root, with the virtual environment activated:

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

The API should be available at:

- API base URL: `http://127.0.0.1:8000`
- Interactive API documentation: `http://127.0.0.1:8000/docs`

Keep this terminal running.

### 4. Start the frontend

Open a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open the local URL displayed by Vite, normally:

`http://localhost:5173`

The frontend's Vite development proxy forwards configured API paths to the FastAPI server on port 8000.

## API Overview

The backend provides REST endpoints for the following operations. Consult `/docs` or `openapi.yaml` for the exact request parameters, schemas, and responses.

| Operation | Endpoint |
|---|---|
| Health check | `GET /health` |
| List employees | `GET /employees` |
| Register employee | `POST /employees` |
| List attendance | `GET /attendance` |
| Punch in | `POST /attendance/punch-in` |
| Punch out | `POST /attendance/punch-out` |
| Regularize attendance | `PATCH /attendance/{emp_code}/{date}` |
| Department summary | `GET /analytics/departments/summary` |
| Late-arrival leaderboard | `GET /analytics/leaderboard/late` |

## Attendance Regularization

Attendly supports corrections to existing attendance records.

A regularization request can include:

- Attendance status.
- Corrected punch-in and punch-out timestamps.
- Reason for the correction.
- Identity of the administrator making the correction.

The backend validates corrections, recalculates derived attendance metrics, and appends an audit-history entry. Timestamp fields use epoch milliseconds.

Invalid corrections and attempts to make no actual changes are rejected by the API.

## Running Tests

From the project root, activate your virtual environment and run:

```powershell
python -m pytest -q
```

**Verified test result:** 10 tests passed during local verification.

The test suite covers backend API behavior, including attendance operations, regularization, and analytics.

Build the frontend for production:

```powershell
cd frontend
npm run build
```

The generated production files are written to `frontend/dist/`.

## Environment Variables

| Variable | Description |
|---|---|
| `MONGO_URI` | MongoDB connection string |
| `MONGO_DB` | Database name; defaults to `attendance_db` |

Keep environment-specific credentials outside version control.

## Future Enhancements

Potential future improvements include:

- Authentication and role-based authorization.
- Employee self-service portal.
- Approval workflows for attendance corrections.
- More detailed reporting and downloadable monthly summaries.
- Improved frontend code-splitting and performance optimization.
- Automated CI testing and production deployment.

## Project Status

**Core functionality implemented and locally verified.**

The backend test suite passed 10 tests, the frontend production build completed successfully, and the main application workflows were manually verified locally.

Production deployment and production security validation should be completed separately before the application is presented as a live production service.

## Author

**YOUR NAME**

- GitHub: https://github.com/YOUR_USERNAME

## License

Choose a license before allowing others to reuse or redistribute this project. If you intend to make it open source, consider adding a suitable license file.
