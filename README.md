# Incident Escalation Console — Server (EC2 + Flask)

A cloud-based incident management system where the entire backend runs as a **Flask web application hosted on an EC2 instance**. Employees report incidents, support teams manage them, and admins monitor everything — all authenticated through AWS Cognito and backed by DynamoDB and SNS.

---

## Architecture Overview

```
Browser / User
     │
     ▼
EC2 Instance (Flask App — port 5000)
     │
     ├── AWS Cognito          ← Authentication (Employees, Teams, Admin)
     ├── DynamoDB             ← Incident storage
     ├── SNS                  ← Email alerts on incident creation / escalation
     └── Lambda (Scheduler)   ← Auto-escalation triggered by EventBridge
```

**No API Gateway or CloudFront.** The Flask app serves both the HTML UI (Jinja2 templates) and the REST API directly from the EC2 instance.

---

## AWS Services Used

| Service | Role |
|---|---|
| **EC2** | Hosts the Flask application (Python) |
| **AWS Cognito** | User authentication — employees, team members, admin all log in via Cognito User Pool |
| **DynamoDB** | Stores all incident records (NoSQL, single table) |
| **SNS** | Sends email notifications on new incidents and escalations |
| **Lambda** | Auto-escalation function — scans overdue incidents and updates status to `Escalated` |
| **EventBridge (Scheduler)** | Triggers the escalation Lambda on a schedule (e.g., every 5 minutes) |
| **IAM** | Role and policy management for EC2 → DynamoDB, SNS access |

---

## Project Structure

```
Server/
├── app/
│   ├── api.py                  # Flask app — all routes, login logic, dashboard
│   ├── incident_service.py     # DynamoDB CRUD operations
│   └── main.py                 # Entry point
├── templates/                  # Jinja2 HTML templates (server-rendered)
│   ├── base.html
│   ├── landing.html
│   ├── employee_login.html
│   ├── create.html             # Report incident form
│   ├── team_login.html
│   ├── team_dashboard.html
│   ├── admin_login.html
│   └── admin_dashboard.html
├── static/
│   └── style.css
├── requirements.txt
└── README.md
```

---

## User Roles

| Role | Login | What they can do |
|---|---|---|
| **Employee** | `/employee/login` | Log in with Cognito, report incidents |
| **Team Member** | `/team/login` | View their team's incidents, update status |
| **Admin** | `/admin/login` | View all incidents across all teams, search & filter |

All three roles authenticate using **AWS Cognito** (`USER_PASSWORD_AUTH` flow). Sessions are managed server-side by Flask.

---

## Incident Lifecycle

```
Open → In Progress → Resolved → Closed
                ↘
              Escalated  (auto-set by Lambda if SLA exceeded)
```

**SLA Escalation Thresholds:**
- `Low` severity → escalates after **24 hours**
- `Medium` severity → escalates after **4 hours**
- `High` severity → escalates after **15 minutes**

When an incident crosses its `escalationAt` timestamp without being resolved, the Lambda function marks it `Escalated` and SNS sends an email alert.

---

## Incident Data Model (DynamoDB)

| Field | Description |
|---|---|
| `incidentId` | Partition key — unique ID (e.g., `INC-A1B2C3D4`) |
| `title` | Short description of the incident |
| `description` | Full details |
| `severity` | `Low` / `Medium` / `High` |
| `team` | Assigned support team |
| `category` | `network`, `security`, `hardware`, `software`, etc. |
| `status` | `Open` / `In Progress` / `Resolved` / `Closed` / `Escalated` |
| `reporterName` | Name of employee who filed the incident |
| `reporterEmail` | Email of the reporter |
| `createdAt` | ISO timestamp (IST) |
| `escalationAt` | Deadline before auto-escalation |
| `resolvedAt` | ISO timestamp set when status → Resolved/Closed |
| `source` | `manual` (web form) or `api` (REST call) |

**Table name:** `incident-console-incidents`  
**Region:** `ap-south-1`

---

## API Endpoints (served directly from Flask on EC2)

| Method | Path | Description |
|---|---|---|
| `POST` | `/incidents` | Create a new incident |
| `GET` | `/incidents` | Get all incidents |
| `GET` | `/incidents/<id>` | Get a single incident |
| `PUT` | `/incidents/<id>` | Update incident status |
| `GET` | `/health` | Health check |

These REST endpoints are in addition to the server-rendered HTML routes.

---

## SNS Notifications

SNS sends email alerts in two situations:
1. **New incident created** — notifies the support team with full incident details
2. **Incident resolved or closed** — notifies the reporter by email
3. **Incident escalated** — notifies via the auto-escalation Lambda

**SNS Topic name:** `incident-console-alerts`  
Subscribe your support email to this topic.

---

## Auto-Escalation (Lambda + EventBridge)

A Lambda function (`lambda_auto_escalate.py`) runs on a schedule:
- Scans DynamoDB for all incidents where `status` is `Open` or `In Progress`
- Checks if current time has passed `escalationAt`
- If yes: updates `status` to `Escalated` and publishes an SNS escalation alert

**EventBridge schedule:** every 5 minutes (configurable).

---

## Cognito User Pool Setup

**User groups / accounts:**

| Email | Role | Team |
|---|---|---|
| `employee1@example.com` ... `employee5@example.com` | Employee | — |
| `network@example.com` | Team | Network Support |
| `security@example.com` | Team | Security Operations |
| `desktop@example.com` | Team | Desktop Support |
| `devops@example.com` | Team | DevOps |
| `database@example.com` | Team | Database Team |
| `appsupport@example.com` | Team | Application Support |
| `cloudops@example.com` | Team | Cloud Operations |
| `admin@example.com` | Admin | — |

**Cognito region:** `ap-south-1`  
**Auth flow:** `USER_PASSWORD_AUTH`

---

## Running Locally (for development)

```bash
# 1. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate       # Windows
source venv/bin/activate    # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# 3. Ensure AWS credentials are configured
aws configure

# 4. Run the Flask app
python -m app.api
```

App will be available at: `http://127.0.0.1:5000`

---

## Deploying on EC2

1. Launch an EC2 instance (Amazon Linux 2 or Ubuntu)
2. Install Python 3 and pip
3. Clone this repository
4. Install dependencies: `pip install -r requirements.txt`
5. Attach an IAM role to the EC2 instance with permissions for:
   - `dynamodb:*` on your incidents table
   - `sns:Publish`, `sns:CreateTopic`
   - `cognito-idp:InitiateAuth`
6. Run the app:
   ```bash
   python -m app.api
   ```
7. Open port `5000` in the EC2 security group (or use `nginx` as a reverse proxy on port 80)

> For production, use `gunicorn` instead of the Flask dev server:
> ```bash
> pip install gunicorn
> gunicorn -w 2 -b 0.0.0.0:5000 app.api:app
> ```

---

## Key Design Decisions

- **Server-rendered UI** with Jinja2 — no separate frontend deployment needed
- **Flask sessions** handle login state server-side (not localStorage)
- **Direct EC2 hosting** — simpler networking, no API Gateway overhead
- **Cognito for auth** — no passwords stored in the application
- **Lambda for escalation** — keeps the Flask app stateless; escalation runs independently on a schedule
