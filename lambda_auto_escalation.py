#Copy and paste this in the Lambda function code editor in AWS Lambda
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3

REGION = os.environ["REGION"]
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]
SNS_TOPIC_NAME = os.environ["SNS_TOPIC_NAME"]

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


def now_ist():
    return datetime.now(IST)


def now_ist_iso():
    return now_ist().isoformat()


def parse_iso(value):
    return datetime.fromisoformat(value)


def get_sns_topic_arn():
    response = sns.create_topic(Name=SNS_TOPIC_NAME)
    return response["TopicArn"]


def notify_escalation(incident):
    topic_arn = get_sns_topic_arn()
    sns.publish(
        TopicArn=topic_arn,
        Subject=f"Incident Escalated: {incident['incidentId']}",
        Message=(
            f"Incident crossed SLA and was escalated.\n\n"
            f"Incident ID: {incident['incidentId']}\n"
            f"Title: {incident['title']}\n"
            f"Severity: {incident['severity']}\n"
            f"Team: {incident['team']}\n"
            f"Category: {incident['category']}\n"
            f"Status: Escalated\n"
            f"Escalation Time: {incident['escalationAt']}\n"
            f"Reporter: {incident.get('reporterName', '')}\n"
            f"Reporter Email: {incident.get('reporterEmail', '')}\n"
        )
    )


def lambda_handler(event, context):
    print("[START] Auto escalation Lambda started")

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

        try:
            if parse_iso(escalation_at) <= now_ist():
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
                print(f"[ESCALATED] {item['incidentId']}")

        except Exception as e:
            print(f"[ERROR] Failed for {item.get('incidentId', 'UNKNOWN')}: {str(e)}")

    print(f"[DONE] Total escalated: {len(escalated_items)}")

    return {
        "statusCode": 200,
        "message": "Auto escalation completed",
        "escalatedCount": len(escalated_items),
        "items": escalated_items
    }
