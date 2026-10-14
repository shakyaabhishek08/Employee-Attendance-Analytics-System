import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  ArrowDownToLine,
  ArrowUpFromLine,
  BarChart3,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Download,
  FileClock,
  LayoutDashboard,
  LoaderCircle,
  RefreshCw,
  Search,
  Users,
  UserPlus,
  X,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import "./App.css";

const today = () => new Date().toISOString().slice(0, 10);
const currentMonth = () => today().slice(0, 7);

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });

  const text = await response.text();
  let data = null;

  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }

  if (!response.ok) {
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : `Request failed (${response.status})`;
    throw new Error(detail);
  }

  return data;
}

const asArray = (data) => {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.items)) return data.items;
  if (Array.isArray(data?.results)) return data.results;
  return [];
};

const displayDate = (value) => {
  if (!value) return "—";
  const parsed = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? String(value)
    : parsed.toLocaleDateString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      });
};

const displayTime = (value) => {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? String(value)
    : parsed.toLocaleTimeString("en-IN", {
        hour: "2-digit",
        minute: "2-digit",
      });
};

const number = (value) => Number(value ?? 0).toLocaleString("en-IN");
const statusClass = (status) =>
  `status status-${String(status || "unknown").toLowerCase().replaceAll("_", "-")}`;

function MetricCard({ title, value, detail, icon: Icon, tone = "blue" }) {
  return (
    <article className="metric-card">
      <div className={`metric-icon ${tone}`}>
        <Icon size={20} />
      </div>
      <p className="metric-title">{title}</p>
      <div className="metric-value">{value}</div>
      <p className="metric-detail">{detail}</p>
    </article>
  );
}

function EmptyState({ message = "No records found." }) {
  return <div className="empty-state">{message}</div>;
}

function App() {
  const [activeTab, setActiveTab] = useState("Overview");
  const [month, setMonth] = useState(currentMonth());
  const [dateFrom, setDateFrom] = useState(today().slice(0, 7) + "-01");
  const [dateTo, setDateTo] = useState(today());
  const [departmentFilter, setDepartmentFilter] = useState("All");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const [employees, setEmployees] = useState([]);
  const [attendance, setAttendance] = useState([]);
  const [departmentStats, setDepartmentStats] = useState([]);
  const [lateLeaderboard, setLateLeaderboard] = useState([]);
  const [employeeTotal, setEmployeeTotal] = useState(0);
  const [attendanceTotal, setAttendanceTotal] = useState(0);
  const [health, setHealth] = useState("checking");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showEmployeeForm, setShowEmployeeForm] = useState(false);
  const [regularizationRecord, setRegularizationRecord] = useState(null);
  const [regularizationForm, setRegularizationForm] = useState({
    status: "PRESENT",
    punch_in: "",
    punch_out: "",
    reason: "",
    regularized_by: "HR Administrator",
  });
  const [regularizing, setRegularizing] = useState(false);
  const [busyCode, setBusyCode] = useState("");

  const [employeeForm, setEmployeeForm] = useState({
    emp_code: "",
    name: "",
    email: "",
    department: "Engineering",
    shift_start: "09:30",
    shift_end: "18:30",
    joined_on: today(),
  });

  const [punchCode, setPunchCode] = useState("");
  const [punchStatus, setPunchStatus] = useState("PRESENT");

  const departments = useMemo(
    () => [...new Set(employees.map((employee) => employee.department).filter(Boolean))].sort(),
    [employees],
  );

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    setError("");

    const results = await Promise.allSettled([
      api("/health"),
      api("/employees?page=1&page_size=100"),
      api(
        `/attendance?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}&page=1&page_size=100`,
      ),
      api(`/analytics/departments/summary?month=${encodeURIComponent(month)}`),
      api(`/analytics/leaderboard/late?month=${encodeURIComponent(month)}`),
    ]);

    const [healthResult, employeeResult, attendanceResult, departmentResult, lateResult] = results;
    const failures = [];

    if (healthResult.status === "fulfilled") {
      setHealth("online");
    } else {
      setHealth("offline");
      failures.push(`Health check: ${healthResult.reason?.message || "Request failed"}`);
    }

    if (employeeResult.status === "fulfilled") {
      const data = employeeResult.value;
      const items = asArray(data);
      setEmployees(items);
      setEmployeeTotal(Number(data?.total ?? items.length));
    } else {
      failures.push(`Employees: ${employeeResult.reason?.message || "Request failed"}`);
    }

    if (attendanceResult.status === "fulfilled") {
      const data = attendanceResult.value;
      const items = asArray(data);
      setAttendance(items);
      setAttendanceTotal(Number(data?.total ?? items.length));
    } else {
      failures.push(`Attendance: ${attendanceResult.reason?.message || "Request failed"}`);
    }

    if (departmentResult.status === "fulfilled") {
      setDepartmentStats(asArray(departmentResult.value));
    } else {
      failures.push(`Department analytics: ${departmentResult.reason?.message || "Request failed"}`);
    }

    if (lateResult.status === "fulfilled") {
      setLateLeaderboard(asArray(lateResult.value));
    } else {
      failures.push(`Late-arrival analytics: ${lateResult.reason?.message || "Request failed"}`);
    }

    if (failures.length) {
      setError(`Some dashboard data could not be loaded:\n${failures.join("\n")}`);
    }

    setLoading(false);
  }, [dateFrom, dateTo, month]);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  const filteredEmployees = useMemo(() => {
    const query = search.trim().toLowerCase();
    return employees.filter((employee) => {
      const matchesDepartment =
        departmentFilter === "All" || employee.department === departmentFilter;
      const matchesSearch =
        !query ||
        [employee.emp_code, employee.name, employee.email, employee.department]
          .some((value) => String(value ?? "").toLowerCase().includes(query));
      return matchesDepartment && matchesSearch;
    });
  }, [employees, departmentFilter, search]);

  const filteredAttendance = useMemo(() => {
    const query = search.trim().toLowerCase();
    return attendance.filter((record) => {
      const matchesSearch =
        !query ||
        [record.emp_code, record.status, record.date]
          .some((value) => String(value ?? "").toLowerCase().includes(query));
      return matchesSearch;
    });
  }, [attendance, search]);

  const presentRecords = attendance.filter((item) =>
    ["PRESENT", "WFH", "ON_DUTY"].includes(item.status),
  ).length;

  const attendanceRate = attendance.length
    ? Math.round((presentRecords / attendance.length) * 100)
    : 0;

  const departmentChart = departmentStats.map((item) => ({
    department: item.department,
    headcount: Number(item.headcount ?? 0),
    presentDays: Number(item.present_days ?? 0),
    lateCount: Number(item.late_count ?? 0),
  }));

  const statusChart = [
    { name: "Present", value: attendance.filter((item) => item.status === "PRESENT").length },
    { name: "WFH", value: attendance.filter((item) => item.status === "WFH").length },
    { name: "On duty", value: attendance.filter((item) => item.status === "ON_DUTY").length },
    { name: "Leave", value: attendance.filter((item) => item.status === "LEAVE").length },
    { name: "Absent", value: attendance.filter((item) => item.status === "ABSENT").length },
  ].filter((item) => item.value > 0);

  async function registerEmployee(event) {
    event.preventDefault();
    setError("");
    setNotice("");

    try {
      await api("/employees", {
        method: "POST",
        body: JSON.stringify(employeeForm),
      });
      setNotice(`Employee ${employeeForm.emp_code} registered successfully.`);
      setShowEmployeeForm(false);
      setEmployeeForm({
        emp_code: "",
        name: "",
        email: "",
        department: "Engineering",
        shift_start: "09:30",
        shift_end: "18:30",
        joined_on: today(),
      });
      await loadDashboard();
    } catch (err) {
      setError(err.message);
    }
  }

  async function punchIn() {
    if (!punchCode.trim()) {
      setError("Enter an employee code before punching in.");
      return;
    }

    setBusyCode(punchCode);
    setError("");
    setNotice("");

    try {
      await api("/attendance/punch-in", {
        method: "POST",
        body: JSON.stringify({ emp_code: punchCode.trim(), status: punchStatus }),
      });
      setNotice(`Punch-in recorded for ${punchCode.trim()}.`);
      await loadDashboard();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyCode("");
    }
  }

  function exportAttendanceCsv() {
    const rows = filteredAttendance.map((record) => ({
      employee_code: record.emp_code ?? "",
      date: record.date ?? "",
      status: record.status ?? "",
      punch_in: record.punch_in ?? "",
      punch_out: record.punch_out ?? "",
      work_hours: record.work_hours ?? "",
      late_minutes: record.late_minutes ?? 0,
    }));

    if (!rows.length) {
      setNotice("There are no attendance records to export for the current filters.");
      return;
    }

    const columns = [
      ["employee_code", "Employee code"],
      ["date", "Date"],
      ["status", "Status"],
      ["punch_in", "Punch in"],
      ["punch_out", "Punch out"],
      ["work_hours", "Work hours"],
      ["late_minutes", "Late minutes"],
    ];
    const escapeCsv = (value) => {
      const text = String(value ?? "");
      return `"${text.replaceAll('"', '""')}"`;
    };
    const csv = [
      columns.map(([, label]) => escapeCsv(label)).join(","),
      ...rows.map((row) => columns.map(([key]) => escapeCsv(row[key])).join(",")),
    ].join("\r\n");
    const blob = new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `attendly-attendance-${dateFrom}-to-${dateTo}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setNotice(`Exported ${rows.length} attendance record(s).`);
  }

  function toLocalDateTimeInput(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const pad = (part) => String(part).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function openRegularization(record) {
    setRegularizationRecord(record);
    setRegularizationForm({
      status: record.status || "PRESENT",
      punch_in: toLocalDateTimeInput(record.punch_in),
      punch_out: toLocalDateTimeInput(record.punch_out),
      reason: "",
      regularized_by: "HR Administrator",
    });
    setError("");
    setNotice("");
  }

  async function submitRegularization(event) {
    event.preventDefault();
    if (!regularizationRecord) return;
    if (regularizationForm.reason.trim().length < 5) {
      setError("Please enter a correction reason with at least 5 characters.");
      return;
    }
    if (!regularizationForm.regularized_by.trim()) {
      setError("Enter the name or identifier of the person making the correction.");
      return;
    }

    const body = {
      reason: regularizationForm.reason.trim(),
      regularized_by: regularizationForm.regularized_by.trim(),
      status: regularizationForm.status,
    };

    // ABSENT and LEAVE must not be sent with punch timestamps; the API clears them.
    if (!["ABSENT", "LEAVE"].includes(regularizationForm.status)) {
      if (!regularizationForm.punch_in) {
        setError("Punch-in is required for Present, WFH, and On duty statuses.");
        return;
      }
      const punchInMs = new Date(regularizationForm.punch_in).getTime();
      if (!Number.isFinite(punchInMs)) {
        setError("Enter a valid punch-in date and time.");
        return;
      }
      body.punch_in = punchInMs;
      if (regularizationForm.punch_out) {
        const punchOutMs = new Date(regularizationForm.punch_out).getTime();
        if (!Number.isFinite(punchOutMs)) {
          setError("Enter a valid punch-out date and time.");
          return;
        }
        if (punchOutMs <= punchInMs) {
          setError("Punch-out must be later than punch-in.");
          return;
        }
        body.punch_out = punchOutMs;
      }
    }

    setRegularizing(true);
    setError("");
    setNotice("");
    try {
      const path = `/attendance/${encodeURIComponent(regularizationRecord.emp_code)}/${encodeURIComponent(String(regularizationRecord.date).slice(0, 10))}`;
      const updated = await api(path, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setRegularizationRecord(null);
      setNotice(`Attendance correction saved for ${updated?.emp_code || regularizationRecord.emp_code} on ${displayDate(updated?.date || regularizationRecord.date)}.`);
      await loadDashboard();
    } catch (err) {
      setError(err.message || "Unable to save the attendance correction.");
    } finally {
      setRegularizing(false);
    }
  }

  async function punchOut(empCode) {
    setBusyCode(empCode);
    setError("");
    setNotice("");

    try {
      await api("/attendance/punch-out", {
        method: "POST",
        body: JSON.stringify({ emp_code: empCode }),
      });
      setNotice(`Punch-out recorded for ${empCode}.`);
      await loadDashboard();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyCode("");
    }
  }

  const navItems = [
    { label: "Overview", icon: LayoutDashboard },
    { label: "Employees", icon: Users },
    { label: "Attendance", icon: CalendarDays },
    { label: "Analytics", icon: BarChart3 },
  ];

  const currentPage = activeTab === "Overview" ? "Overview" : activeTab;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Activity size={23} /></div>
          <div>
            <strong>Attendly</strong>
            <span>WORKFORCE INTELLIGENCE</span>
          </div>
        </div>

        <div className="workspace-label">WORKSPACE</div>
        <nav className="nav-list">
          {navItems.map(({ label, icon: Icon }) => (
            <button
              className={`nav-item ${activeTab === label ? "active" : ""}`}
              key={label}
              onClick={() => {
                setActiveTab(label);
                setSearch("");
                setPage(1);
              }}
            >
              <Icon size={18} />
              <span>{label}</span>
              {activeTab === label && <span className="nav-active-dot" />}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="api-status">
            <span className={`health-dot ${health}`} />
            <div>
              <strong>API connection</strong>
              <span>{health === "online" ? "Connected" : health === "checking" ? "Checking..." : "Unavailable"}</span>
            </div>
          </div>
          <div className="profile">
            <div className="avatar">HR</div>
            <div><strong>HR Administrator</strong><span>Workspace admin</span></div>
          </div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumb">Workspace <ChevronRight size={14} /> <strong>{currentPage}</strong></div>
          <div className="top-actions">
            <span className="today-label"><CalendarDays size={16} /> {displayDate(today())}</span>
            <button className="icon-button" onClick={loadDashboard} title="Refresh dashboard" aria-label="Refresh dashboard">
              <RefreshCw size={17} className={loading ? "spin" : ""} />
            </button>
            <div className="top-avatar">HR</div>
          </div>
        </header>

        <div className="page-content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">WORKFORCE OVERVIEW</p>
              <h1>{activeTab === "Overview" ? "Attendance dashboard" : activeTab}</h1>
              <p className="subtitle">Monitor attendance, manage employees, and understand workforce trends.</p>
            </div>
            <div className="heading-actions">
              <label className="month-control">
                <CalendarDays size={16} />
                <input aria-label="Analytics month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
              </label>
              <button className="primary-button" onClick={() => setShowEmployeeForm(true)}>
                <UserPlus size={17} /> Add employee
              </button>
            </div>
          </div>

          {error && <div className="alert error-alert"><AlertCircle size={18} /><span>{error}</span><button onClick={() => setError("")} aria-label="Dismiss error"><X size={16} /></button></div>}
          {notice && <div className="alert success-alert"><CheckCircle2 size={18} /><span>{notice}</span><button onClick={() => setNotice("")} aria-label="Dismiss notice"><X size={16} /></button></div>}

          {loading && (
            <div className="loading-line"><LoaderCircle size={17} className="spin" /> Loading latest data…</div>
          )}

          {(activeTab === "Overview" || activeTab === "Analytics") && (
            <>
              <section className="metrics-grid">
                <MetricCard title="Total employees" value={number(employeeTotal)} detail="Registered workforce" icon={Users} tone="blue" />
                <MetricCard title="Attendance records" value={number(attendanceTotal)} detail={`${displayDate(dateFrom)} – ${displayDate(dateTo)}`} icon={CalendarDays} tone="purple" />
                <MetricCard title="Presence rate" value={`${attendanceRate}%`} detail="Among loaded records" icon={CheckCircle2} tone="green" />
                <MetricCard title="Late entries" value={number(lateLeaderboard.reduce((sum, item) => sum + Number(item.late_count ?? item.count ?? 0), 0))} detail={`Analytics for ${month}`} icon={Clock3} tone="orange" />
              </section>

              <section className="filter-strip">
                <div>
                  <span className="filter-label">Attendance period</span>
                  <div className="date-range">
                    <input type="date" value={dateFrom} max={dateTo} onChange={(e) => setDateFrom(e.target.value)} aria-label="From date" />
                    <span>to</span>
                    <input type="date" value={dateTo} min={dateFrom} onChange={(e) => setDateTo(e.target.value)} aria-label="To date" />
                  </div>
                </div>
                <div className="filter-note"><Activity size={16} /> Data is loaded from your FastAPI backend</div>
              </section>

              <section className="charts-grid">
                <article className="panel chart-panel">
                  <div className="panel-heading">
                    <div><h2>Department overview</h2><p>Headcount and late-arrival comparison</p></div>
                    <span className="panel-tag">{month}</span>
                  </div>
                  {departmentChart.length ? (
                    <div className="chart-area">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={departmentChart} margin={{ top: 10, right: 10, left: -18, bottom: 5 }}>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e9edf4" />
                          <XAxis dataKey="department" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                          <YAxis allowDecimals={false} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                          <Tooltip />
                          <Bar dataKey="headcount" name="Headcount" fill="#4567e8" radius={[5, 5, 0, 0]} />
                          <Bar dataKey="lateCount" name="Late entries" fill="#f5a14b" radius={[5, 5, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  ) : <EmptyState message="No department metrics for this month yet." />}
                </article>

                <article className="panel chart-panel">
                  <div className="panel-heading">
                    <div><h2>Attendance breakdown</h2><p>Records in the selected date range</p></div>
                  </div>
                  {statusChart.length ? (
                    <div className="pie-layout">
                      <div className="pie-chart">
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart>
                            <Pie data={statusChart} dataKey="value" nameKey="name" innerRadius={58} outerRadius={86} paddingAngle={3}>
                              {statusChart.map((item, index) => (
                                <Cell key={item.name} fill={["#4567e8", "#7a65df", "#26a77b", "#f5a14b", "#e46f7c"][index % 5]} />
                              ))}
                            </Pie>
                            <Tooltip />
                          </PieChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="legend-list">
                        {statusChart.map((item, index) => (
                          <div className="legend-row" key={item.name}>
                            <span className="legend-dot" style={{ background: ["#4567e8", "#7a65df", "#26a77b", "#f5a14b", "#e46f7c"][index % 5] }} />
                            <span>{item.name}</span><strong>{item.value}</strong>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : <EmptyState message="Attendance records will appear here." />}
                </article>
              </section>

              <section className="panel">
                <div className="panel-heading">
                  <div><h2>Department performance</h2><p>Monthly summary from MongoDB analytics</p></div>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Department</th><th>Headcount</th><th>Present days</th><th>Avg. work hours</th><th>Late entries</th><th>Leave count</th></tr></thead>
                    <tbody>
                      {departmentStats.map((item) => (
                        <tr key={item.department}>
                          <td><span className="department-cell"><span className="department-avatar">{String(item.department || "?").slice(0, 1)}</span><strong>{item.department}</strong></span></td>
                          <td>{number(item.headcount)}</td><td>{number(item.present_days)}</td>
                          <td>{item.avg_work_hours == null ? "—" : `${Number(item.avg_work_hours).toFixed(2)} h`}</td>
                          <td><span className="late-pill">{number(item.late_count)}</span></td><td>{number(item.leave_count)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!departmentStats.length && <EmptyState />}
                </div>
              </section>

              <section className="panel">
                <div className="panel-heading">
                  <div><h2>Late-arrival leaderboard</h2><p>Employees with the most late entries this month</p></div>
                  <span className="panel-tag">{month}</span>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Employee</th><th>Department</th><th>Late entries</th><th>Late minutes</th></tr></thead>
                    <tbody>
                      {lateLeaderboard.map((item, index) => (
                        <tr key={item.emp_code || item.employee_code || index}>
                          <td><strong>{item.name || item.emp_code || item.employee_code || "Employee"}</strong><div className="muted-cell">{item.emp_code || item.employee_code || ""}</div></td>
                          <td>{item.department || "—"}</td><td><span className="late-pill">{number(item.late_count ?? item.count)}</span></td><td>{number(item.total_late_minutes ?? item.late_minutes)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!lateLeaderboard.length && <EmptyState message="No late-arrival data for this month." />}
                </div>
              </section>
            </>
          )}

          {activeTab === "Employees" && (
            <section className="panel">
              <div className="panel-heading employee-toolbar">
                <div><h2>Employee directory</h2><p>{employeeTotal} registered employees</p></div>
                <div className="table-tools">
                  <div className="search-box"><Search size={16} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search employees..." /></div>
                  <select value={departmentFilter} onChange={(e) => setDepartmentFilter(e.target.value)} aria-label="Filter department">
                    <option>All</option>{departments.map((item) => <option key={item}>{item}</option>)}
                  </select>
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Employee</th><th>Code</th><th>Department</th><th>Shift</th><th>Joined</th><th>Action</th></tr></thead>
                  <tbody>
                    {filteredEmployees.map((employee) => (
                      <tr key={employee.emp_code}>
                        <td><div className="employee-cell"><div className="employee-avatar">{String(employee.name || "?").split(" ").map((part) => part[0]).slice(0, 2).join("").toUpperCase()}</div><div><strong>{employee.name}</strong><span>{employee.email}</span></div></div></td>
                        <td><code>{employee.emp_code}</code></td><td>{employee.department}</td>
                        <td>{employee.shift_start || "09:30"} – {employee.shift_end || "18:30"}</td><td>{displayDate(employee.joined_on)}</td>
                        <td><button className="small-action" disabled={busyCode === employee.emp_code} onClick={() => punchOut(employee.emp_code)}><ArrowDownToLine size={14} /> Punch out</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!filteredEmployees.length && <EmptyState message="No employees match your search." />}
              </div>
            </section>
          )}

          {activeTab === "Attendance" && (
            <>
              <section className="panel punch-panel">
                <div><h2>Quick attendance action</h2><p>Record a punch-in for a registered employee.</p></div>
                <div className="punch-controls">
                  <input value={punchCode} onChange={(e) => setPunchCode(e.target.value.toUpperCase())} placeholder="Employee code, e.g. EMP1001" aria-label="Employee code" />
                  <select value={punchStatus} onChange={(e) => setPunchStatus(e.target.value)} aria-label="Attendance status">
                    <option value="PRESENT">Present</option><option value="WFH">Work from home</option><option value="ON_DUTY">On duty</option>
                  </select>
                  <button className="primary-button" disabled={Boolean(busyCode)} onClick={punchIn}><ArrowUpFromLine size={16} /> Punch in</button>
                </div>
              </section>
              <section className="panel">
                <div className="panel-heading employee-toolbar">
                  <div><h2>Attendance records</h2><p>{attendanceTotal} records in selected range</p></div>
                  <div className="table-tools">
                    <div className="search-box"><Search size={16} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search records..." /></div>
                    <button className="secondary-button" onClick={exportAttendanceCsv}><Download size={15} /> Export CSV</button>
                    <button className="secondary-button" onClick={loadDashboard}><RefreshCw size={15} /> Refresh</button>
                  </div>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Employee code</th><th>Date</th><th>Status</th><th>Punch in</th><th>Punch out</th><th>Work hours</th><th>Late minutes</th><th>Action</th></tr></thead>
                    <tbody>
                      {filteredAttendance.map((record, index) => (
                        <tr key={`${record.emp_code}-${record.date}-${index}`}>
                          <td><code>{record.emp_code}</code></td><td>{displayDate(record.date)}</td>
                          <td><span className={statusClass(record.status)}>{record.status || "Unknown"}</span></td>
                          <td>{displayTime(record.punch_in)}</td><td>{displayTime(record.punch_out)}</td>
                          <td>{record.work_hours == null ? "—" : `${Number(record.work_hours).toFixed(2)} h`}</td><td>{number(record.late_minutes)}</td>
                          <td><div className="table-tools"><button className="small-action" onClick={() => openRegularization(record)} title="Correct attendance"><FileClock size={14} /> Correct</button>{record.punch_out ? <span className="muted-cell">Completed</span> : <button className="small-action" disabled={busyCode === record.emp_code} onClick={() => punchOut(record.emp_code)}><ArrowDownToLine size={14} /> Punch out</button>}</div></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!filteredAttendance.length && <EmptyState message="No attendance records for these filters." />}
                </div>
              </section>
            </>
          )}

          <footer className="footer">
            <span>Attendly · Employee Attendance & Analytics</span>
            <span><span className={`health-dot ${health}`} /> API {health === "online" ? "connected" : health}</span>
          </footer>
        </div>
      </main>

      {regularizationRecord && (
        <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !regularizing) setRegularizationRecord(null); }}>
          <section className="modal">
            <div className="modal-heading">
              <div><p className="eyebrow">ATTENDANCE MANAGEMENT</p><h2>Correct attendance</h2><p className="subtitle">{regularizationRecord.emp_code} · {displayDate(regularizationRecord.date)}</p></div>
              <button className="icon-button" disabled={regularizing} onClick={() => setRegularizationRecord(null)} aria-label="Close correction form"><X size={18} /></button>
            </div>
            {Array.isArray(regularizationRecord.history) && regularizationRecord.history.length > 0 && (
              <section className="panel" style={{ marginBottom: 16 }}>
                <h3>Previous corrections</h3>
                <div className="table-wrap">
                  <table><thead><tr><th>When</th><th>By</th><th>Reason</th><th>Fields changed</th></tr></thead>
                    <tbody>{[...regularizationRecord.history].reverse().map((entry, index) => (
                      <tr key={`${entry.at || "history"}-${index}`}>
                        <td>{entry.at ? new Date(entry.at).toLocaleString("en-IN") : "—"}</td>
                        <td>{entry.by || "—"}</td><td>{entry.reason || "—"}</td>
                        <td>{Object.keys(entry.changes || {}).join(", ") || "—"}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              </section>
            )}
            <form className="employee-form" onSubmit={submitRegularization}>
              <label>Attendance status
                <select required value={regularizationForm.status} onChange={(e) => setRegularizationForm({ ...regularizationForm, status: e.target.value })}>
                  <option value="PRESENT">Present</option><option value="WFH">Work from home</option><option value="ON_DUTY">On duty</option><option value="ABSENT">Absent</option><option value="LEAVE">Leave</option>
                </select>
              </label>
              {!["ABSENT", "LEAVE"].includes(regularizationForm.status) && (
                <>
                  <label>Punch-in time<input type="datetime-local" required value={regularizationForm.punch_in} onChange={(e) => setRegularizationForm({ ...regularizationForm, punch_in: e.target.value })} /></label>
                  <label>Punch-out time <span className="muted-cell">(optional)</span><input type="datetime-local" value={regularizationForm.punch_out} onChange={(e) => setRegularizationForm({ ...regularizationForm, punch_out: e.target.value })} /></label>
                </>
              )}
              <label>Correction reason<textarea required minLength={5} maxLength={200} rows={3} value={regularizationForm.reason} onChange={(e) => setRegularizationForm({ ...regularizationForm, reason: e.target.value })} placeholder="Explain why this attendance record needs correction" /></label>
              <label>Corrected by<input required maxLength={50} value={regularizationForm.regularized_by} onChange={(e) => setRegularizationForm({ ...regularizationForm, regularized_by: e.target.value })} /></label>
              <p className="muted-cell">Every successful correction is recorded in the backend audit history. No-op corrections are rejected by the API.</p>
              <div className="modal-actions"><button type="button" className="secondary-button" disabled={regularizing} onClick={() => setRegularizationRecord(null)}>Cancel</button><button type="submit" className="primary-button" disabled={regularizing}><FileClock size={16} /> {regularizing ? "Saving correction…" : "Save correction"}</button></div>
            </form>
          </section>
        </div>
      )}

      {showEmployeeForm && (
        <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowEmployeeForm(false); }}>
          <section className="modal">
            <div className="modal-heading"><div><p className="eyebrow">EMPLOYEE DIRECTORY</p><h2>Add employee</h2></div><button className="icon-button" onClick={() => setShowEmployeeForm(false)} aria-label="Close form"><X size={18} /></button></div>
            <form className="employee-form" onSubmit={registerEmployee}>
              <label>Employee code<input required pattern="EMP[0-9]{4,6}" title="Use EMP followed by 4–6 digits, for example EMP1001" value={employeeForm.emp_code} onChange={(e) => setEmployeeForm({ ...employeeForm, emp_code: e.target.value.toUpperCase() })} placeholder="EMP1001" /></label>
              <label>Full name<input required maxLength={100} value={employeeForm.name} onChange={(e) => setEmployeeForm({ ...employeeForm, name: e.target.value })} placeholder="Alex Morgan" /></label>
              <label>Email address<input required type="email" value={employeeForm.email} onChange={(e) => setEmployeeForm({ ...employeeForm, email: e.target.value })} placeholder="alex@company.com" /></label>
              <label>Department<input required maxLength={50} value={employeeForm.department} onChange={(e) => setEmployeeForm({ ...employeeForm, department: e.target.value })} placeholder="Engineering" /></label>
              <div className="form-two-col"><label>Shift starts<input type="time" required value={employeeForm.shift_start} onChange={(e) => setEmployeeForm({ ...employeeForm, shift_start: e.target.value })} /></label><label>Shift ends<input type="time" required value={employeeForm.shift_end} onChange={(e) => setEmployeeForm({ ...employeeForm, shift_end: e.target.value })} /></label></div>
              <label>Joining date<input type="date" required value={employeeForm.joined_on} onChange={(e) => setEmployeeForm({ ...employeeForm, joined_on: e.target.value })} /></label>
              <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowEmployeeForm(false)}>Cancel</button><button type="submit" className="primary-button"><UserPlus size={16} /> Save employee</button></div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}

export default App;