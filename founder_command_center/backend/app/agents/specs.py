from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    role: str
    inputs: list[str]
    outputs: list[str]
    memory: list[str]
    tools: list[str]
    escalation_logic: str


AGENT_SPECS: list[AgentSpec] = [
    AgentSpec(
        "chief_of_staff",
        "Founder Chief of Staff Agent",
        "Converts founder goals into plans, coordinates all agents, and escalates risks.",
        ["goals", "tasks", "risks", "reports"],
        ["daily brief", "weekly command report", "escalations"],
        ["founder priorities", "agent outputs", "decision history"],
        ["task planner", "report generator", "dashboard metrics"],
        "Escalate delayed high-priority work, compliance risk, or decisions needing founder approval.",
    ),
    AgentSpec(
        "employee_manager",
        "Task Planner and Employee Manager Agent",
        "Assigns tasks, tracks deadlines, and creates performance reports.",
        ["employees", "tasks", "deadlines"],
        ["daily task sheets", "workload redistribution", "scorecards"],
        ["employee skills", "task outcomes"],
        ["task API", "employee dashboard"],
        "Escalate blocked tasks, overloaded employees, and repeated missed deadlines.",
    ),
    AgentSpec(
        "opportunity",
        "Strategy and Opportunity Agent",
        "Tracks schemes, tenders, events, trade fairs, CSR, and public issues.",
        ["market signals", "products", "regions"],
        ["opportunity report", "new scopes", "recommended action"],
        ["opportunity backlog", "source history"],
        ["web research queue", "report generator"],
        "Escalate time-sensitive opportunities or high-value strategic openings.",
    ),
    AgentSpec(
        "erp_sales",
        "ERP/CRM Product Sales Agent",
        "Builds prospect lists, sales assets, follow-ups, and objection handling.",
        ["products", "leads", "industries"],
        ["prospect list", "pitch scripts", "follow-up plan"],
        ["lead stages", "objection library"],
        ["CRM", "CSV import", "email drafts"],
        "Escalate premium prospects, stale high-value deals, and pricing decisions.",
    ),
    AgentSpec(
        "premium_client",
        "Premium Client Acquisition Agent",
        "Focuses on founder-level high-value client meetings and positioning.",
        ["premium leads", "products", "relationship notes"],
        ["meeting brief", "priority list", "follow-up note"],
        ["premium account history"],
        ["CRM", "briefing generator"],
        "Escalate any deal above the configured premium value threshold.",
    ),
    AgentSpec(
        "robotics",
        "Robotics Market and Partnership Agent",
        "Tracks service robot markets, pilots, outsourcing progress, and demos.",
        ["robotics tasks", "pilot leads", "hardware status"],
        ["roadmap", "pilot list", "demo script"],
        ["robotics milestones", "partner notes"],
        ["task API", "lead API"],
        "Escalate demo blockers, hardware issues, and pilot customer commitments.",
    ),
    AgentSpec(
        "agri",
        "Agri Market Intelligence Agent",
        "Maps AP agri products to domestic/export buyers, certifications, logistics, and margins.",
        ["products", "markets", "buyers"],
        ["product-country-buyer report", "buyer outreach plan"],
        ["buyer records", "market notes"],
        ["agri database", "CSV export"],
        "Escalate verified buyer demand, certification gaps, or risky margin assumptions.",
    ),
    AgentSpec(
        "influencer_builder",
        "Influencer Network Builder Agent",
        "Builds and scores the 10,000 influencer database.",
        ["influencers", "districts", "platforms"],
        ["outreach plan", "scorecard", "meeting plan"],
        ["influencer profiles", "engagement scores"],
        ["influencer CRM", "CSV import"],
        "Escalate high-reach influencers, brand-safety risk, and consent gaps.",
    ),
    AgentSpec(
        "influencer_legal",
        "Influencer Legal and Agreement Agent",
        "Creates lawyer-reviewable, fair influencer agreement drafts and disclosure reminders.",
        ["campaign terms", "influencer data", "payment model"],
        ["MOU draft", "approval checklist", "disclosure note"],
        ["agreement versions", "legal review status"],
        ["template generator", "audit log"],
        "Require human approval for every agreement, mass campaign, or payment structure.",
    ),
    AgentSpec(
        "student_clubs",
        "Student Clubs and Youth Pipeline Agent",
        "Builds district/college club structures, volunteer roles, and leadership pipelines.",
        ["student members", "colleges", "events"],
        ["club plan", "activity calendar", "leadership pipeline"],
        ["club member history", "college permissions"],
        ["student database", "event planner"],
        "Escalate college permission blockers, inactive coordinators, or safety concerns.",
    ),
    AgentSpec(
        "events",
        "Events and Grand Meetings Agent",
        "Plans meetings, launches, demos, budgets, guest lists, scripts, and follow-ups.",
        ["events", "guest lists", "budgets"],
        ["agenda", "invitation", "sponsor proposal", "follow-up plan"],
        ["event playbooks", "attendance history"],
        ["event database", "CSV export"],
        "Escalate budget overruns, VIP confirmations, and public-content approvals.",
    ),
    AgentSpec(
        "political_intelligence",
        "Political Intelligence and Stakeholder Mapping Agent",
        "Builds ethical district, constituency, stakeholder, and public issue intelligence.",
        ["constituency data", "public issues", "stakeholders"],
        ["issue brief", "constituency profile", "risk note"],
        ["stakeholder maps", "public issue history"],
        ["political database", "report generator"],
        "Escalate misinformation risk, illegal manipulation risk, or sensitive messaging.",
    ),
    AgentSpec(
        "political_operations",
        "Political Campaign Operations Agent",
        "Creates ethical political office SOPs, volunteer workflows, grievance systems, and ERP requirements.",
        ["office tasks", "volunteers", "grievances", "schedules"],
        ["SOP", "workflow", "manifesto issue note", "ERP requirements"],
        ["operation playbooks", "approval logs"],
        ["task API", "political ERP"],
        "Require human approval for political messaging and public campaign content.",
    ),
    AgentSpec(
        "data_compliance",
        "Data, CRM and Compliance Agent",
        "Maintains data quality, deduplication, consent, source tracking, and privacy-by-design.",
        ["people", "leads", "influencers", "student members"],
        ["duplicate report", "consent gaps", "data quality report"],
        ["audit logs", "source records", "consent status"],
        ["dedupe engine", "audit log", "CSV validator"],
        "Escalate missing consent, risky source, duplicate premium records, and mass outreach requests.",
    ),
]


AGENT_BY_KEY = {agent.key: agent for agent in AGENT_SPECS}
