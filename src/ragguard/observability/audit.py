from datetime import datetime, timezone

def audit_event(event_type, payload):
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "payload": payload,
    }
