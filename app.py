import os
import sqlite3
from datetime import date, datetime

import pandas as pd
import streamlit as st
from werkzeug.security import check_password_hash, generate_password_hash

APP_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(APP_DIR, "medication_tracker.db")

st.set_page_config(
    page_title="CareTrack | School Medication",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)


def get_db():
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'staff'
            );
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                school_id TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                class_name TEXT NOT NULL,
                guardian_contact TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS medications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                medication_name TEXT NOT NULL,
                prescribed_dose TEXT NOT NULL,
                schedule TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT DEFAULT '',
                instructions TEXT DEFAULT '',
                authorization_checked INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dose_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                medication_id INTEGER NOT NULL REFERENCES medications(id) ON DELETE CASCADE,
                scheduled_for TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('given', 'missed', 'held')),
                administered_at TEXT DEFAULT '',
                staff_username TEXT NOT NULL,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
        """)
        count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                ("admin", generate_password_hash("ChangeMe123!"), "administrator"),
            )


def query_df(sql, params=()):
    with get_db() as db:
        return pd.read_sql_query(sql, db, params=params)


def execute(sql, params=()):
    with get_db() as db:
        cur = db.execute(sql, params)
        return cur.lastrowid


def now_text():
    return datetime.now().isoformat(timespec="seconds")


def require_login():
    if not st.session_state.get("username"):
        st.info("Please sign in to access student medication records.")
        st.stop()


def show_flash():
    message = st.session_state.pop("flash_message", None)
    if message:
        kind, text = message
        if kind == "success":
            st.success(text)
        else:
            st.error(text)


def set_flash(kind, text):
    st.session_state["flash_message"] = (kind, text)


def login_page():
    st.markdown("<div class='hero'><div class='eyebrow'>SCHOOL HEALTH OFFICE</div><h1>CareTrack</h1><p>Student medication tracking</p></div>", unsafe_allow_html=True)
    left, center, right = st.columns([1, 1.2, 1])
    with center:
        with st.container(border=True):
            st.subheader("Staff sign in")
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign in", use_container_width=True, type="primary")
            if submitted:
                users = query_df("SELECT * FROM users WHERE username = ?", (username.strip(),))
                if not users.empty and check_password_hash(users.iloc[0]["password_hash"], password):
                    st.session_state["username"] = users.iloc[0]["username"]
                    st.session_state["role"] = users.iloc[0]["role"]
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
            st.caption("Demo credentials: admin / ChangeMe123! — replace before any real use.")


def dashboard():
    today = date.today().isoformat()
    students_count = int(query_df("SELECT COUNT(*) AS n FROM students").iloc[0]["n"])
    active_count = int(query_df("SELECT COUNT(*) AS n FROM medications WHERE active = 1").iloc[0]["n"])
    logs_today = int(query_df(
        "SELECT COUNT(*) AS n FROM dose_logs WHERE substr(created_at, 1, 10) = ?", (today,)
    ).iloc[0]["n"])

    st.title("Medication dashboard")
    st.caption("An overview of student records and medication events.")
    a, b, c = st.columns(3)
    a.metric("Student records", students_count)
    b.metric("Active medication plans", active_count)
    c.metric("Dose events logged today", logs_today)

    st.subheader("Active medication plans")
    meds = query_df("""
        SELECT m.id, s.id AS student_id, s.full_name AS student, s.school_id,
               s.class_name, m.medication_name, m.prescribed_dose, m.schedule
        FROM medications m JOIN students s ON s.id = m.student_id
        WHERE m.active = 1 ORDER BY s.full_name, m.medication_name
    """)
    if meds.empty:
        st.info("No active medication plans yet. Add a student, then add an authorized medication record.")
    else:
        st.dataframe(meds.drop(columns=["id", "student_id"]), use_container_width=True, hide_index=True)
        st.caption("To record a dose event, use the “Record dose event” page in the sidebar.")

    st.subheader("Recent dose events")
    logs = query_df("""
        SELECT s.full_name AS student, s.school_id, m.medication_name,
               dl.scheduled_for, dl.status, dl.administered_at, dl.staff_username, dl.notes
        FROM dose_logs dl
        JOIN medications m ON m.id = dl.medication_id
        JOIN students s ON s.id = m.student_id
        ORDER BY dl.id DESC LIMIT 10
    """)
    if logs.empty:
        st.info("No dose events recorded.")
    else:
        st.dataframe(logs, use_container_width=True, hide_index=True)


def students_page():
    st.title("Students")
    st.caption("Search by student name, school ID, or class.")
    query = st.text_input("Search students", placeholder="Enter name, school ID, or class")
    if query.strip():
        like = f"%{query.strip()}%"
        rows = query_df("""
            SELECT s.id, s.school_id, s.full_name, s.class_name,
              (SELECT COUNT(*) FROM medications m WHERE m.student_id = s.id AND m.active = 1) AS active_medications
            FROM students s
            WHERE s.full_name LIKE ? OR s.school_id LIKE ? OR s.class_name LIKE ?
            ORDER BY s.full_name
        """, (like, like, like))
    else:
        rows = query_df("""
            SELECT s.id, s.school_id, s.full_name, s.class_name,
              (SELECT COUNT(*) FROM medications m WHERE m.student_id = s.id AND m.active = 1) AS active_medications
            FROM students s ORDER BY s.full_name
        """)
    if rows.empty:
        st.info("No students found.")
    else:
        st.dataframe(rows.drop(columns=["id"]), use_container_width=True, hide_index=True)
        options = {f'{r["full_name"]} — {r["school_id"]}': int(r["id"]) for _, r in rows.iterrows()}
        selected = st.selectbox("Open student record", list(options))
        if st.button("Open selected student", type="primary"):
            st.session_state["selected_student_id"] = options[selected]
            st.session_state["page"] = "Student record"
            st.rerun()


def add_student_page():
    st.title("Add a student")
    st.caption("Enter only information needed for school medication administration.")
    with st.form("add_student_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        school_id = c1.text_input("School ID *")
        full_name = c2.text_input("Student full name *")
        class_name = c1.text_input("Class / year group *")
        guardian_contact = c2.text_input("Guardian contact (optional)")
        notes = st.text_area("Relevant notes (optional)", max_chars=1000)
        submitted = st.form_submit_button("Save student", type="primary")
    if submitted:
        if not school_id.strip() or not full_name.strip() or not class_name.strip():
            st.error("School ID, student name, and class are required.")
        else:
            try:
                execute("""
                    INSERT INTO students (school_id, full_name, class_name, guardian_contact, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (school_id.strip(), full_name.strip(), class_name.strip(),
                      guardian_contact.strip(), notes.strip(), now_text()))
                set_flash("success", "Student record added.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("That school ID already exists.")


def student_record_page():
    st.title("Student record")
    students = query_df("SELECT id, full_name, school_id, class_name, guardian_contact, notes FROM students ORDER BY full_name")
    if students.empty:
        st.info("No student records exist yet.")
        return
    options = {f'{r["full_name"]} — {r["school_id"]}': int(r["id"]) for _, r in students.iterrows()}
    default_id = st.session_state.get("selected_student_id")
    labels = list(options.keys())
    default_index = next((i for i, label in enumerate(labels) if options[label] == default_id), 0)
    selected = st.selectbox("Select student", labels, index=default_index, key="student_record_select")
    student_id = options[selected]
    st.session_state["selected_student_id"] = student_id
    row = students[students["id"] == student_id].iloc[0]

    c1, c2, c3 = st.columns(3)
    c1.metric("School ID", row["school_id"])
    c2.metric("Class", row["class_name"])
    c3.metric("Guardian contact", row["guardian_contact"] or "Not provided")
    if row["notes"]:
        st.write("**Relevant notes:**", row["notes"])

    st.subheader("Medication records")
    meds = query_df("""
        SELECT id, medication_name, prescribed_dose, schedule, start_date, end_date, instructions, active
        FROM medications WHERE student_id = ? ORDER BY active DESC, medication_name
    """, (student_id,))
    if meds.empty:
        st.info("No medication records for this student.")
    else:
        display = meds.copy()
        display["status"] = display["active"].map({1: "Active", 0: "Archived"})
        st.dataframe(display.drop(columns=["id", "active"]), use_container_width=True, hide_index=True)
        active_meds = meds[meds["active"] == 1]
        if not active_meds.empty:
            med_options = {f'{r["medication_name"]} — {r["prescribed_dose"]}': int(r["id"]) for _, r in active_meds.iterrows()}
            med_label = st.selectbox("Choose active medication to archive", list(med_options))
            if st.button("Archive selected medication"):
                execute("UPDATE medications SET active = 0 WHERE id = ?", (med_options[med_label],))
                set_flash("success", "Medication record archived; history retained.")
                st.rerun()

    st.subheader("Dose history")
    logs = query_df("""
        SELECT m.medication_name, dl.scheduled_for, dl.status, dl.administered_at,
               dl.staff_username, dl.notes
        FROM dose_logs dl JOIN medications m ON m.id = dl.medication_id
        WHERE m.student_id = ? ORDER BY dl.id DESC LIMIT 50
    """, (student_id,))
    if logs.empty:
        st.info("No dose events recorded.")
    else:
        st.dataframe(logs, use_container_width=True, hide_index=True)


def add_medication_page():
    st.title("Add medication plan")
    students = query_df("SELECT id, full_name, school_id, class_name FROM students ORDER BY full_name")
    if students.empty:
        st.warning("Add a student before adding a medication plan.")
        return
    options = {f'{r["full_name"]} — {r["school_id"]} ({r["class_name"]})': int(r["id"]) for _, r in students.iterrows()}
    with st.form("add_medication_form"):
        student_label = st.selectbox("Student *", list(options))
        c1, c2 = st.columns(2)
        medication_name = c1.text_input("Medication name *")
        prescribed_dose = c2.text_input("Prescribed dose *", placeholder="Enter exactly as authorized")
        schedule = c1.text_input("Schedule *", placeholder="Enter the approved schedule")
        start_date = c2.date_input("Start date *", value=date.today())
        end_date = st.date_input("End / review date (optional)", value=None)
        instructions = st.text_area("Instructions (from approved care plan only)", max_chars=1000)
        authorization = st.checkbox("I verified the current prescription/care plan and required guardian and school authorization.")
        submitted = st.form_submit_button("Save medication plan", type="primary")
    if submitted:
        if not all([medication_name.strip(), prescribed_dose.strip(), schedule.strip()]):
            st.error("Medication name, prescribed dose, and schedule are required.")
        elif not authorization:
            st.error("Confirm that required authorization has been checked before saving.")
        else:
            execute("""
                INSERT INTO medications
                (student_id, medication_name, prescribed_dose, schedule, start_date, end_date,
                 instructions, authorization_checked, active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?)
            """, (options[student_label], medication_name.strip(), prescribed_dose.strip(),
                  schedule.strip(), start_date.isoformat(),
                  end_date.isoformat() if end_date else "", instructions.strip(), now_text()))
            set_flash("success", "Medication plan added. Verify the schedule against the authorized care plan.")
            st.rerun()


def log_dose_page():
    st.title("Record dose event")
    meds = query_df("""
        SELECT m.id, m.medication_name, m.prescribed_dose, m.schedule, s.full_name, s.school_id
        FROM medications m JOIN students s ON s.id = m.student_id
        WHERE m.active = 1 ORDER BY s.full_name, m.medication_name
    """)
    if meds.empty:
        st.info("No active medication plans are available.")
        return
    options = {
        f'{r["full_name"]} ({r["school_id"]}) — {r["medication_name"]}': int(r["id"])
        for _, r in meds.iterrows()
    }
    with st.form("dose_event_form"):
        chosen = st.selectbox("Student and medication *", list(options))
        selected_med = meds[meds["id"] == options[chosen]].iloc[0]
        st.info(f'Prescribed dose on record: **{selected_med["prescribed_dose"]}**  \nRecorded schedule: **{selected_med["schedule"]}**')
        scheduled_date = st.date_input("Scheduled date *", value=date.today())
        scheduled_time = st.time_input("Scheduled time")
        status_label = st.selectbox("Event status *", [
            "Administered", "Missed / not administered", "Held / withheld under school protocol"
        ])
        confirmed = st.checkbox("I confirm the dose was actually administered (required for “Administered”).")
        notes = st.text_area("Notes (optional)", max_chars=1000)
        submitted = st.form_submit_button("Save dose event", type="primary")
    if submitted:
        status_map = {
            "Administered": "given",
            "Missed / not administered": "missed",
            "Held / withheld under school protocol": "held",
        }
        status = status_map[status_label]
        if status == "given" and not confirmed:
            st.error("Confirm that the dose was actually administered before logging it.")
        else:
            scheduled_for = datetime.combine(scheduled_date, scheduled_time).isoformat(timespec="minutes")
            administered_at = now_text() if status == "given" else ""
            execute("""
                INSERT INTO dose_logs
                (medication_id, scheduled_for, status, administered_at, staff_username, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (options[chosen], scheduled_for, status, administered_at,
                  st.session_state["username"], notes.strip(), now_text()))
            set_flash("success", "Dose event recorded.")
            st.rerun()


def reports_page():
    st.title("Reports")
    st.caption("Review dose-event history. Export only when authorized by school policy.")
    start = st.date_input("From date", value=date.today().replace(day=1), key="report_start")
    end = st.date_input("To date", value=date.today(), key="report_end")
    if start > end:
        st.error("The start date must be on or before the end date.")
        return
    logs = query_df("""
        SELECT s.full_name AS student, s.school_id, s.class_name,
               m.medication_name, m.prescribed_dose, dl.scheduled_for,
               dl.status, dl.administered_at, dl.staff_username, dl.notes
        FROM dose_logs dl
        JOIN medications m ON m.id = dl.medication_id
        JOIN students s ON s.id = m.student_id
        WHERE substr(dl.created_at, 1, 10) BETWEEN ? AND ?
        ORDER BY dl.created_at DESC
    """, (start.isoformat(), end.isoformat()))
    st.write(f"**{len(logs)} event(s)** recorded in the selected period.")
    if logs.empty:
        st.info("No events found for this period.")
    else:
        st.dataframe(logs, use_container_width=True, hide_index=True)
        csv = logs.to_csv(index=False).encode("utf-8")
        st.download_button("Download report as CSV", data=csv,
                           file_name=f"medication_report_{start}_{end}.csv",
                           mime="text/csv")


def account_page():
    st.title("Account")
    st.write(f"Signed in as **{st.session_state['username']}**")
    st.caption(f"Role: {st.session_state.get('role', 'staff')}")
    st.warning("This prototype has no self-service password change or user-management workflow. Do not use demo credentials for real student data.")
    with st.form("change_password_form"):
        current = st.text_input("Current password", type="password")
        new_password = st.text_input("New password", type="password")
        confirm = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Change password")
    if submitted:
        user = query_df("SELECT * FROM users WHERE username = ?", (st.session_state["username"],))
        if user.empty or not check_password_hash(user.iloc[0]["password_hash"], current):
            st.error("Current password is incorrect.")
        elif len(new_password) < 12:
            st.error("Use at least 12 characters for the new password.")
        elif new_password != confirm:
            st.error("New password and confirmation do not match.")
        else:
            execute("UPDATE users SET password_hash = ? WHERE username = ?",
                    (generate_password_hash(new_password), st.session_state["username"]))
            st.success("Password updated.")


def main():
    init_db()
    st.markdown("""
    <style>
    .stApp {background: #f4f7fa;}
    [data-testid="stHeader"] {background: rgba(244,247,250,.9);}
    .block-container {padding-top: 2rem; max-width: 1250px;}
    h1, h2, h3 {color: #17384c;}
    div[data-testid="stMetric"] {background: white; border: 1px solid #e2e9ef; padding: 18px; border-radius: 14px;}
    .hero {text-align:center; padding: 1.8rem 0 1rem;}
    .hero h1 {font-size: 3rem; margin: 0; color:#17384c;}
    .hero p {color:#718291; font-size:1.1rem;}
    .eyebrow {font-size:.72rem; letter-spacing:.14em; font-weight:800; color:#087e8b;}
    div.stButton > button[kind="primary"], div.stFormSubmitButton > button[kind="primary"] {background:#087e8b; border-color:#087e8b;}
    .safety {font-size:.82rem; color:#718291; border-top:1px solid #dce5eb; margin-top:2.5rem; padding-top:1rem;}
    </style>
    """, unsafe_allow_html=True)

    if not st.session_state.get("username"):
        login_page()
        st.markdown('<div class="safety">Important: This starter app is not a clinical decision tool. Follow the school’s approved medication policy and authorized care plan. Never rely on this app alone for dose decisions or emergency care.</div>', unsafe_allow_html=True)
        return

    with st.sidebar:
        st.markdown("## 🏥 CareTrack")
        st.caption("School medication tracker")
        st.write(f"Signed in: **{st.session_state['username']}**")
        pages = [
            "Dashboard", "Students", "Add student", "Student record",
            "Add medication plan", "Record dose event", "Reports", "Account"
        ]
        selected_page = st.radio("Navigation", pages, key="nav_page")
        st.divider()
        if st.button("Sign out", use_container_width=True):
            st.session_state.pop("username", None)
            st.session_state.pop("role", None)
            st.rerun()

    show_flash()
    if selected_page == "Dashboard":
        dashboard()
    elif selected_page == "Students":
        students_page()
    elif selected_page == "Add student":
        add_student_page()
    elif selected_page == "Student record":
        student_record_page()
    elif selected_page == "Add medication plan":
        add_medication_page()
    elif selected_page == "Record dose event":
        log_dose_page()
    elif selected_page == "Reports":
        reports_page()
    elif selected_page == "Account":
        account_page()

    st.markdown('<div class="safety">Important: Use fictional data for testing. This prototype is not production-ready and does not validate prescriptions, calculate doses, or automatically determine which doses are due. Before real use, obtain clinical, legal, privacy, and security review and implement stronger access controls and audit protections.</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
