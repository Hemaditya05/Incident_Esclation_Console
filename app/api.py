import os
from datetime import datetime
from functools import wraps

import boto3
from botocore.exceptions import ClientError
from flask import Flask, request, jsonify, render_template, redirect, url_for, session

from app.incident_service import (
    create_incident,
    update_incident_status,
    get_incident_by_id,
    get_all_incidents
)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)
app.secret_key = "incident-console-phase2-secret-key"

REGION = "ap-south-1"
COGNITO_CLIENT_ID = "1rn6no56bi90gfr3q0eimajilc"

cognito = boto3.client("cognito-idp", region_name=REGION)

TEAM_OPTIONS = [
    "Network Support",
    "Security Operations",
    "Desktop Support",
    "DevOps",
    "Database Team",
    "Application Support",
    "Cloud Operations",
    "Other"
]

CATEGORY_OPTIONS = [
    "network",
    "security",
    "hardware",
    "software",
    "database",
    "cloud",
    "access",
    "server",
    "Other"
]

EMPLOYEE_ACCOUNTS = {
    "employee1@example.com": {"name": "Employee 1"},
    "employee2@example.com": {"name": "Employee 2"},
    "employee3@example.com": {"name": "Employee 3"},
    "employee4@example.com": {"name": "Employee 4"},
    "employee5@example.com": {"name": "Employee 5"}
}

TEAM_ACCOUNTS = {
    "network@example.com": {"team": "Network Support"},
    "security@example.com": {"team": "Security Operations"},
    "desktop@example.com": {"team": "Desktop Support"},
    "devops@example.com": {"team": "DevOps"},
    "database@example.com": {"team": "Database Team"},
    "appsupport@example.com": {"team": "Application Support"},
    "cloudops@example.com": {"team": "Cloud Operations"}
}

ADMIN_ACCOUNT = {"admin@example.com": {"role": "admin"}}


def cognito_login(email, password):
    try:
        response = cognito.initiate_auth(
            ClientId=COGNITO_CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": email,
                "PASSWORD": password
            }
        )
        return response["AuthenticationResult"]
    except ClientError as e:
        raise ValueError(e.response["Error"]["Message"])


def employee_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "employee":
            return redirect(url_for("employee_login"))
        return f(*args, **kwargs)
    return wrapper


def team_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "team":
            return redirect(url_for("team_login"))
        return f(*args, **kwargs)
    return wrapper


def admin_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


def get_final_value(select_value, other_value):
    if select_value == "Other":
        return (other_value or "").strip()
    return (select_value or "").strip()


def build_manual_ist_iso(date_value, time_value):
    if not date_value or not time_value:
        return None
    dt = datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H:%M")
    return dt.isoformat() + "+05:30"


@app.context_processor
def inject_brand_target():
    role = session.get("role")
    if role == "admin":
        brand_endpoint = "admin_dashboard"
    elif role == "team":
        brand_endpoint = "team_dashboard"
    elif role == "employee":
        brand_endpoint = "create_page"
    else:
        brand_endpoint = "landing"
    return {"brand_endpoint": brand_endpoint}


@app.get("/")
def landing():
    return render_template("landing.html")


@app.get("/employee/login")
def employee_login():
    return render_template("employee_login.html")


@app.post("/employee/login")
def employee_login_submit():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()

    if email not in EMPLOYEE_ACCOUNTS:
        return render_template("employee_login.html", error="Invalid employee account")

    try:
        auth = cognito_login(email, password)
        session["role"] = "employee"
        session["email"] = email
        session["name"] = EMPLOYEE_ACCOUNTS[email]["name"]
        session["id_token"] = auth.get("IdToken", "")
        return redirect(url_for("create_page"))
    except ValueError as e:
        return render_template("employee_login.html", error=str(e))


@app.get("/report")
@employee_login_required
def create_page():
    return render_template(
        "create.html",
        team_options=TEAM_OPTIONS,
        category_options=CATEGORY_OPTIONS,
        reporter_name=session.get("name", ""),
        reporter_email=session.get("email", "")
    )


@app.post("/report")
@employee_login_required
def create_page_submit():
    reporter_name = session.get("name", "").strip()
    reporter_email = session.get("email", "").strip()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    severity = request.form.get("severity", "").strip()

    team = get_final_value(
        request.form.get("team", ""),
        request.form.get("team_other", "")
    )
    category = get_final_value(
        request.form.get("category", "general"),
        request.form.get("category_other", "")
    ) or "general"

    escalation_mode = request.form.get("escalation_mode", "default")
    manual_escalation_at = None

    if escalation_mode == "manual":
        manual_escalation_at = build_manual_ist_iso(
            request.form.get("manual_escalation_date", "").strip(),
            request.form.get("manual_escalation_time", "").strip()
        )

    if not reporter_name or not reporter_email or not title or not description or not severity or not team:
        return "Missing required fields", 400

    create_incident(
        title=title,
        description=description,
        severity=severity,
        team=team,
        source="manual",
        category=category,
        reporter_name=reporter_name,
        reporter_email=reporter_email,
        manual_escalation_at=manual_escalation_at
    )
    return redirect(url_for("create_page"))


@app.get("/team/login")
def team_login():
    return render_template("team_login.html")


@app.post("/team/login")
def team_login_submit():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()

    if email not in TEAM_ACCOUNTS:
        return render_template("team_login.html", error="Invalid team account")

    try:
        auth = cognito_login(email, password)
        session["role"] = "team"
        session["email"] = email
        session["team"] = TEAM_ACCOUNTS[email]["team"]
        session["id_token"] = auth.get("IdToken", "")
        return redirect(url_for("team_dashboard"))
    except ValueError as e:
        return render_template("team_login.html", error=str(e))


@app.get("/team/dashboard")
@team_login_required
def team_dashboard():
    all_incidents = get_all_incidents()
    team_name = session.get("team")
    incidents = [i for i in all_incidents if i.get("team") == team_name]
    incidents.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
    return render_template(
        "team_dashboard.html",
        incidents=incidents,
        team_name=team_name,
        user_email=session.get("email", "")
    )


@app.post("/team/update/<incident_id>")
@team_login_required
def team_update_status(incident_id):
    status = request.form.get("status", "").strip()
    if not status:
        return redirect(url_for("team_dashboard"))
    update_incident_status(incident_id, status)
    return redirect(url_for("team_dashboard"))


@app.get("/admin/login")
def admin_login():
    return render_template("admin_login.html")


@app.post("/admin/login")
def admin_login_submit():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()

    if email not in ADMIN_ACCOUNT:
        return render_template("admin_login.html", error="Invalid admin account")

    try:
        auth = cognito_login(email, password)
        session["role"] = "admin"
        session["email"] = email
        session["id_token"] = auth.get("IdToken", "")
        return redirect(url_for("admin_dashboard"))
    except ValueError as e:
        return render_template("admin_login.html", error=str(e))


@app.get("/admin/dashboard")
@admin_login_required
def admin_dashboard():
    incidents = get_all_incidents()
    incidents.sort(key=lambda x: x.get("createdAt", ""), reverse=True)

    team_counts = {}
    status_counts = {}
    severity_counts = {}

    for item in incidents:
        team = item.get("team", "Unknown")
        status = item.get("status", "Unknown")
        severity = item.get("severity", "Unknown")

        team_counts[team] = team_counts.get(team, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    return render_template(
        "admin_dashboard.html",
        incidents=incidents,
        team_counts=team_counts,
        status_counts=status_counts,
        severity_counts=severity_counts,
        user_email=session.get("email", "")
    )


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.post("/incidents")
def create_incident_api():
    data = request.get_json()

    reporter_name = data.get("reporter_name", "").strip()
    reporter_email = data.get("reporter_email", "").strip()
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    severity = data.get("severity", "").strip()
    team = data.get("team", "").strip()
    category = data.get("category", "general").strip() or "general"
    manual_escalation_at = data.get("manual_escalation_at")

    if not reporter_name or not reporter_email or not title or not description or not severity or not team:
        return jsonify({"error": "reporter_name, reporter_email, title, description, severity, team are required"}), 400

    item = create_incident(
        title=title,
        description=description,
        severity=severity,
        team=team,
        source="manual",
        category=category,
        reporter_name=reporter_name,
        reporter_email=reporter_email,
        manual_escalation_at=manual_escalation_at
    )
    return jsonify(item), 201


@app.put("/incidents/<incident_id>")
def update_incident_api(incident_id):
    data = request.get_json()
    new_status = data.get("status", "").strip()

    if not new_status:
        return jsonify({"error": "status is required"}), 400

    updated = update_incident_status(incident_id, new_status)
    if not updated:
        return jsonify({"error": "incident not found"}), 404

    return jsonify(updated), 200


@app.get("/incidents/<incident_id>")
def get_one_incident_api(incident_id):
    item = get_incident_by_id(incident_id)
    if not item:
        return jsonify({"error": "incident not found"}), 404

    return jsonify(item), 200


@app.get("/incidents")
def get_all_incidents_api():
    items = get_all_incidents()
    return jsonify(items), 200


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
