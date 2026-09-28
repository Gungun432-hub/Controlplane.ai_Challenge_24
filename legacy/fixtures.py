from .engine import Application, Detector, Tool


APPLICATIONS = [
    Application("customer-support", "Customer support", ["read_customer", "write_ticket"], {"ticketing": ["read_customer", "write_ticket"]}),
    Application("recruitment", "Recruitment", ["read_candidate", "schedule_interview"], {"recruiting": ["read_candidate"]}),
    Application("finance-decision", "Finance decision", ["read_credit", "approve_credit"], {"credit": ["read_credit", "approve_credit"]}),
    Application("it-operations", "IT operations", ["read_logs", "restart_service"], {"ops": ["read_logs", "restart_service"]}),
    Application("marketing", "Marketing", ["read_segment", "send_campaign"], {"campaigns": ["read_segment", "send_campaign"]}),
]

TOOLS = [
    Tool("ticketing", "Ticketing", ["read_customer", "write_ticket"]),
    Tool("recruiting", "Recruiting", ["read_candidate", "schedule_interview"]),
    Tool("credit", "Credit decision", ["read_credit", "approve_credit"]),
    Tool("ops", "Operations", ["read_logs", "restart_service"]),
    Tool("campaigns", "Campaigns", ["read_segment", "send_campaign"]),
]


def scenario_detectors(application_id: str) -> list[Detector]:
    if application_id == "finance-decision":
        return [Detector("credit-policy", .95, reason="policy score 0.95"), Detector("human-review", .9)]
    if application_id == "recruitment":
        return [Detector("candidate-consent", .9), Detector("deadline-check", .7, status="failed", reason="consent deadline missing")]
    if application_id == "it-operations":
        return [Detector("incident-window", .99), Detector("change-ticket", .95)]
    return [Detector("policy", .92), Detector("data-boundary", .94)]
