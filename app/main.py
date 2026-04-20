from app.incident_service import create_incident, update_incident_status


def menu():
    print("\nIncident Escalation Console")
    print("1. Create Incident")
    print("2. Update Incident Status")
    print("3. Exit")


def handle_create():
    title = input("Title: ").strip()
    description = input("Description: ").strip()
    severity = input("Severity (Low/Medium/High): ").strip()
    team = input("Team: ").strip()
    source = input("Source [manual]: ").strip() or "manual"
    category = input("Category [general]: ").strip() or "general"

    item = create_incident(title, description, severity, team, source, category)
    print("\n[SUCCESS] Incident created")
    for k, v in item.items():
        print(f"{k}: {v}")


def handle_update():
    incident_id = input("Incident ID: ").strip()
    new_status = input("New Status (Open/In Progress/Resolved/Closed/Escalated): ").strip()

    updated = update_incident_status(incident_id, new_status)
    print("\n[SUCCESS] Incident updated")
    for k, v in updated.items():
        print(f"{k}: {v}")


def main():
    while True:
        menu()
        choice = input("Choose: ").strip()

        if choice == "1":
            handle_create()
        elif choice == "2":
            handle_update()
        elif choice == "3":
            print("Bye")
            break
        else:
            print("Invalid choice")


if __name__ == "__main__":
    main()
