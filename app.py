import os
import uuid
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps

import boto3
from botocore.exceptions import ClientError
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from dotenv import load_dotenv

load_dotenv()

REGION = os.getenv("REGION", "ap-south-1")
DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE")
SNS_TOPIC_NAME = os.getenv("SNS_TOPIC_NAME")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID")
FLASK_SECRET = os.getenv("FLASK_SECRET", "incident-secret")

SEVERITY_ESCALATION_MINUTES = json.loads(os.getenv("SEVERITY_ESCALATION_MINUTES", "{}"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)

app.secret_key = FLASK_SECRET

IST = timezone(timedelta(hours=5, minutes=30))

dynamodb = boto3.resource("dynamodb", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)
cognito = boto3.client("cognito-idp", region_name=REGION)

table = dynamodb.Table(DYNAMODB_TABLE)


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

def now_ist_iso():
    return datetime.now(IST).isoformat()

def calculate_escalation_at(severity):
    minutes = SEVERITY_ESCALATION_MINUTES.get(severity, 60)
    return (datetime.now(IST) + timedelta(minutes=minutes)).isoformat()

def create_incident(title, description, severity, team, category,
                    reporter_email, reporter_name):

    incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"

    item = {
        "incidentId": incident_id,
        "title": title,
        "description": description,
        "severity": severity,
        "team": team,
        "category": category,
        "status": "Open",
        "reporterEmail": reporter_email,
        "reporterName": reporter_name,
        "createdAt": now_ist_iso(),
        "escalationAt": calculate_escalation_at(severity)
    }

    table.put_item(Item=item)

    sns.publish(
        TopicArn=sns.create_topic(Name=SNS_TOPIC_NAME)["TopicArn"],
        Subject=f"New Incident {incident_id}",
        Message=f"{title} | Severity: {severity} | Team: {team}"
    )

    return item

def update_incident_status(incident_id, new_status):

    allowed = {"Open", "In Progress", "Resolved", "Closed", "Escalated"}

    if new_status not in allowed:
        raise ValueError("Invalid status")

    existing = table.get_item(Key={"incidentId": incident_id}).get("Item")
    if not existing:
        return {}

    update_expr = "SET #s=:s"
    expr_names = {"#s": "status"}
    expr_values = {":s": new_status}

    if new_status in {"Resolved", "Closed"}:
        update_expr += ", resolvedAt=:r"
        expr_values[":r"] = now_ist_iso()

    response = table.update_item(
        Key={"incidentId": incident_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
        ReturnValues="ALL_NEW"
    )

    updated = response.get("Attributes", {})

    topic_arn = sns.create_topic(Name=SNS_TOPIC_NAME)["TopicArn"]

    if new_status == "In Progress":
        sns.publish(
            TopicArn=topic_arn,
            Subject=f"Incident In Progress: {updated['incidentId']}",
            Message=f"""
Incident moved to In Progress

Incident ID: {updated['incidentId']}
Title: {updated['title']}
Severity: {updated['severity']}
Team: {updated['team']}
"""
        )

    if new_status == "Resolved":
        sns.publish(
            TopicArn=topic_arn,
            Subject=f"Incident Resolved: {updated['incidentId']}",
            Message=f"""
Your reported incident has been resolved.

Incident ID: {updated['incidentId']}
Title: {updated['title']}
Status: Resolved
"""
        )

    if new_status == "Closed":
        sns.publish(
            TopicArn=topic_arn,
            Subject=f"Incident Closed: {updated['incidentId']}",
            Message=f"""
Your reported incident has been closed.

Incident ID: {updated['incidentId']}
Title: {updated['title']}
Status: Closed
"""
        )

    return updated

def get_all_incidents():
    response = table.scan()
    return response.get("Items", [])

def get_incident_by_id(incident_id):
    response = table.get_item(Key={"incidentId": incident_id})
    return response.get("Item")

def cognito_login(email, password):
    response = cognito.initiate_auth(
        ClientId=COGNITO_CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": email, "PASSWORD": password}
    )
    return response["AuthenticationResult"]



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


@app.route("/")
def landing():
    return render_template("landing.html")

@app.route("/employee/login")
def employee_login():
    return render_template("employee_login.html")

@app.post("/employee/login")
def employee_login_submit():
    email = request.form["email"]
    password = request.form["password"]

    try:
        cognito_login(email, password)
        session["role"] = "employee"
        session["email"] = email
        session["name"] = EMPLOYEE_ACCOUNTS[email]["name"]
        return redirect(url_for("create_page"))
    except Exception:
        return render_template("employee_login.html", error="Login failed")

@app.route("/report")
@employee_login_required
def create_page():
    return render_template(
        "create.html",
        team_options=TEAM_OPTIONS,
        category_options=CATEGORY_OPTIONS,
        reporter_name=session.get("name"),
        reporter_email=session.get("email")
    )

@app.post("/report")
@employee_login_required
def create_page_submit():
    create_incident(
        title=request.form["title"],
        description=request.form["description"],
        severity=request.form["severity"],
        team=request.form["team"],
        category=request.form["category"],
        reporter_email=session["email"],
        reporter_name=session["name"]
    )
    return redirect(url_for("create_page"))

@app.route("/team/login")
def team_login():
    return render_template("team_login.html")

@app.post("/team/login")
def team_login_submit():
    email = request.form["email"]
    password = request.form["password"]

    cognito_login(email, password)

    session["role"] = "team"
    session["email"] = email
    session["team"] = TEAM_ACCOUNTS[email]["team"]

    return redirect(url_for("team_dashboard"))

@app.route("/team/dashboard")
@team_login_required
def team_dashboard():
    team = session["team"]
    incidents = [i for i in get_all_incidents() if i["team"] == team]
    return render_template("team_dashboard.html", incidents=incidents)

@app.post("/team/update/<incident_id>")
@team_login_required
def team_update_status(incident_id):
    update_incident_status(incident_id, request.form["status"])
    return redirect(url_for("team_dashboard"))

@app.route("/admin/login")
def admin_login():
    return render_template("admin_login.html")

@app.post("/admin/login")
def admin_login_submit():
    email = request.form["email"]
    password = request.form["password"]

    cognito_login(email, password)

    session["role"] = "admin"
    session["email"] = email

    return redirect(url_for("admin_dashboard"))

@app.route("/admin/dashboard")
@admin_login_required
def admin_dashboard():
    incidents = get_all_incidents()
    return render_template("admin_dashboard.html", incidents=incidents)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))

@app.get("/health")
def health():
    return jsonify({"status": "ok"})

@app.get("/api/incidents")
def api_incidents():
    return jsonify(get_all_incidents())

@app.get("/api/incidents/<incident_id>")
def api_get_incident(incident_id):
    return jsonify(get_incident_by_id(incident_id))

@app.post("/api/incidents")
def api_create_incident():
    data = request.json
    item = create_incident(
        data["title"],
        data["description"],
        data["severity"],
        data["team"],
        data["category"],
        data["reporter_email"],
        data["reporter_name"]
    )
    return jsonify(item)

@app.put("/api/incidents/<incident_id>")
def api_update_incident(incident_id):
    updated = update_incident_status(incident_id, request.json["status"])
    return jsonify(updated)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)