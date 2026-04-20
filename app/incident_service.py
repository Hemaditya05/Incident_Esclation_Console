import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

from bootstrap.config import (
    REGION,
    DYNAMODB_TABLE,
    SNS_TOPIC_NAME,
    SEVERITY_ESCALATION_MINUTES
)

IST = timezone(timedelta(hours=5, minutes=30))

dynamodb = boto3.resource("dynamodb", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)

table = dynamodb.Table(DYNAMODB_TABLE)


def to_json_safe(value):
    if isinstance(value, list):
        return [to_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: to_json_safe(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return value


def get_sns_topic_arn():
    response = sns.create_topic(Name=SNS_TOPIC_NAME)
    return response["TopicArn"]


def now_ist():
    return datetime.now(IST)


def now_ist_iso():
    return now_ist().isoformat()


def parse_iso_ist(value):
    return datetime.fromisoformat(value)


def calculate_escalation_at(severity, manual_escalation_at=None):
    if manual_escalation_at:
        return manual_escalation_at
    minutes = SEVERITY_ESCALATION_MINUTES.get(severity, 60)
    return (now_ist() + timedelta(minutes=minutes)).isoformat()


def notify_team_open(incident_id, title, severity, team, category, escalation_at):
    topic_arn = get_sns_topic_arn()
    sns.publish(
        TopicArn=topic_arn,
        Subject=f"New Incident: {incident_id}",
        Message=(
            f"New incident created\n\n"
            f"Incident ID: {incident_id}\n"
            f"Title: {title}\n"
            f"Severity: {severity}\n"
            f"Team: {team}\n"
            f"Category: {category}\n"
            f"Status: Open\n"
            f"Escalation At: {escalation_at}\n"
        )
    )


def notify_team_progress(incident_id, title, severity, team):
    topic_arn = get_sns_topic_arn()
    sns.publish(
        TopicArn=topic_arn,
        Subject=f"Incident In Progress: {incident_id}",
        Message=(
            f"Incident moved to In Progress\n\n"
            f"Incident ID: {incident_id}\n"
            f"Title: {title}\n"
            f"Severity: {severity}\n"
            f"Team: {team}\n"
        )
    )


def notify_reporter_status(incident_id, title, reporter_email, status):
    if not reporter_email:
        return

    topic_arn = get_sns_topic_arn()

    if status == "Resolved":
        subject = f"Incident Resolved: {incident_id}"
        message = (
            f"Your reported incident has been resolved.\n\n"
            f"Incident ID: {incident_id}\n"
            f"Title: {title}\n"
            f"Status: Resolved\n"
            f"Please verify the fix.\n"
            f"Reporter Email: {reporter_email}\n"
        )
    elif status == "Closed":
        subject = f"Incident Closed: {incident_id}"
        message = (
            f"Your reported incident has been closed.\n\n"
            f"Incident ID: {incident_id}\n"
            f"Title: {title}\n"
            f"Status: Closed\n"
            f"The case is now formally completed.\n"
            f"Reporter Email: {reporter_email}\n"
        )
    else:
        return

    sns.publish(
        TopicArn=topic_arn,
        Subject=subject,
        Message=message
    )


def notify_escalation(incident):
    topic_arn = get_sns_topic_arn()
    sns.publish(
        TopicArn=topic_arn,
        Subject=f"Incident Escalated: {incident['incidentId']}",
        Message=(
            f"Incident crossed SLA and has been escalated.\n\n"
            f"Incident ID: {incident['incidentId']}\n"
            f"Title: {incident['title']}\n"
            f"Severity: {incident['severity']}\n"
            f"Team: {incident['team']}\n"
            f"Category: {incident['category']}\n"
            f"Current Status: Escalated\n"
            f"Escalation Time: {incident['escalationAt']}\n"
            f"Reporter: {incident.get('reporterName', '')}\n"
            f"Reporter Email: {incident.get('reporterEmail', '')}\n"
        )
    )


def create_incident(
    title,
    description,
    severity,
    team,
    source="manual",
    category="general",
    reporter_name="",
    reporter_email="",
    manual_escalation_at=None
):
    if severity not in SEVERITY_ESCALATION_MINUTES:
        raise ValueError("Severity must be one of: Low, Medium, High")

    incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
    created_at = now_ist_iso()
    escalation_at = calculate_escalation_at(severity, manual_escalation_at)

    item = {
        "incidentId": incident_id,
        "title": title,
        "description": description,
        "severity": severity,
        "team": team,
        "status": "Open",
        "source": source,
        "category": category,
        "reporterName": reporter_name,
        "reporterEmail": reporter_email,
        "createdAt": created_at,
        "escalationAt": escalation_at
    }

    table.put_item(Item=item)
    notify_team_open(incident_id, title, severity, team, category, escalation_at)

    return to_json_safe(item)


def update_incident_status(incident_id, new_status):
    allowed = {"Open", "In Progress", "Resolved", "Closed", "Escalated"}

    if new_status not in allowed:
        raise ValueError("Status must be one of: Open, In Progress, Resolved, Closed, Escalated")

    existing = table.get_item(Key={"incidentId": incident_id}).get("Item")
    if not existing:
        return {}

    update_expr = "SET #s = :s"
    expr_names = {"#s": "status"}
    expr_values = {":s": new_status}

    if new_status in {"Resolved", "Closed"}:
        update_expr += ", resolvedAt = :r"
        expr_values[":r"] = now_ist_iso()

    response = table.update_item(
        Key={"incidentId": incident_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
        ReturnValues="ALL_NEW"
    )

    updated = response.get("Attributes", {})

    if new_status == "In Progress":
        notify_team_progress(
            incident_id=updated["incidentId"],
            title=updated["title"],
            severity=updated["severity"],
            team=updated["team"]
        )

    if new_status in {"Resolved", "Closed"}:
        notify_reporter_status(
            incident_id=updated["incidentId"],
            title=updated["title"],
            reporter_email=updated.get("reporterEmail", ""),
            status=new_status
        )

    return to_json_safe(updated)


def get_incident_by_id(incident_id):
    response = table.get_item(Key={"incidentId": incident_id})
    return to_json_safe(response.get("Item"))


def get_all_incidents():
    response = table.scan()
    items = response.get("Items", [])
    items.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
    return to_json_safe(items)


def auto_escalate_overdue_incidents():
    response = table.scan()
    items = response.get("Items", [])
    escalated_items = []

    for item in items:
        status = item.get("status", "")
        escalation_at = item.get("escalationAt")

        if status in {"Resolved", "Closed", "Escalated"}:
            continue
        if not escalation_at:
            continue

        if parse_iso_ist(escalation_at) <= now_ist():
            update_response = table.update_item(
                Key={"incidentId": item["incidentId"]},
                UpdateExpression="SET #s = :s, escalatedAt = :e",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":s": "Escalated",
                    ":e": now_ist_iso()
                },
                ReturnValues="ALL_NEW"
            )

            updated = update_response.get("Attributes", {})
            notify_escalation(updated)
            escalated_items.append(to_json_safe(updated))

    return escalated_items
