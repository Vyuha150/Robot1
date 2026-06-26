import {
  AlertTriangle,
  Bot,
  BriefcaseBusiness,
  CalendarDays,
  CheckCircle2,
  ClipboardList,
  Database,
  FileText,
  Gauge,
  GraduationCap,
  Handshake,
  LayoutDashboard,
  Megaphone,
  Package
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { agents, leads, metrics, tasks } from "./data/mock";

const tabs = [
  ["founder", "Founder", LayoutDashboard],
  ["tasks", "Tasks", ClipboardList],
  ["sales", "Sales", BriefcaseBusiness],
  ["influencers", "Influencers", Megaphone],
  ["students", "Students", GraduationCap],
  ["products", "Products", Package],
  ["agents", "Agents", Bot],
  ["reports", "Reports", FileText]
] as const;

export function App() {
  const [tab, setTab] = useState("founder");
  const formatter = useMemo(() => new Intl.NumberFormat("en-IN"), []);

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="mark">JVK</div>
          <div>
            <strong>Founder Command</strong>
            <span>AI operating center</span>
          </div>
        </div>
        <nav>
          {tabs.map(([key, label, Icon]) => (
            <button className={tab === key ? "active" : ""} key={key} onClick={() => setTab(key)} title={label}>
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p>Daily command view</p>
            <h1>{tabs.find(([key]) => key === tab)?.[1]} Dashboard</h1>
          </div>
          <div className="approval">
            <CheckCircle2 size={18} />
            Human approval enabled
          </div>
        </header>

        {tab === "founder" && <Founder formatter={formatter} />}
        {tab === "tasks" && <Table title="Employee Task Manager" icon={<ClipboardList />} rows={tasks} headers={["Task", "Owner", "Priority", "Deadline"]} />}
        {tab === "sales" && <Table title="Lead Manager" icon={<Handshake />} rows={leads} headers={["Company", "Product", "Stage", "Value"]} />}
        {tab === "influencers" && <Influencers />}
        {tab === "students" && <Students />}
        {tab === "products" && <Products />}
        {tab === "agents" && <Agents />}
        {tab === "reports" && <Reports />}
      </section>
    </main>
  );
}

function Founder({ formatter }: { formatter: Intl.NumberFormat }) {
  const cards: Array<[string, string | number, LucideIcon]> = [
    ["Today's priorities", metrics.tasks, ClipboardList],
    ["Delayed tasks", metrics.delayed_tasks, AlertTriangle],
    ["Follow-ups due", metrics.followups_due, CalendarDays],
    ["Sales pipeline", `₹${formatter.format(metrics.sales_pipeline_value)}`, BriefcaseBusiness],
    ["Influencer network", metrics.influencers, Megaphone],
    ["Student members", metrics.student_members, GraduationCap],
    ["Robotics progress", `${metrics.robotics_progress}%`, Gauge],
    ["Political prep", `${metrics.political_preparation_progress}%`, Database]
  ];

  return (
    <>
      <section className="metric-grid">
        {cards.map(([label, value, Icon]) => (
          <article className="metric" key={String(label)}>
            <Icon size={20} />
            <span>{label}</span>
            <strong>{value}</strong>
          </article>
        ))}
      </section>
      <section className="band">
        <div>
          <h2>Alerts and Risks</h2>
          <p>3 delayed tasks need escalation. 8 sales follow-ups are due today. Influencer agreements need consent and disclosure review before campaign use.</p>
        </div>
        <div>
          <h2>Top Opportunities</h2>
          <p>Premium Hospital ERP demos, district influencer onboarding, student robotics clubs, and ethical political office ERP positioning are the highest-leverage lanes this week.</p>
        </div>
      </section>
    </>
  );
}

function Table({ title, icon, headers, rows }: { title: string; icon: ReactNode; headers: string[]; rows: string[][] }) {
  return (
    <section className="panel">
      <h2>{icon}{title}</h2>
      <table>
        <thead>
          <tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.join("-")}>{row.map((cell) => <td key={cell}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Influencers() {
  return <Table title="Influencer Database" icon={<Megaphone />} headers={["Segment", "Count", "Agreement", "Action"]} rows={[
    ["YouTube tech", "42", "18 signed", "Schedule district meetup"],
    ["Instagram local news", "55", "11 signed", "Brand safety review"],
    ["Student creators", "31", "8 signed", "Send onboarding form"]
  ]} />;
}

function Students() {
  return <Table title="Student Club Database" icon={<GraduationCap />} headers={["District", "Members", "Interest", "Next Move"]} rows={[
    ["Guntur", "120", "Robotics", "Workshop plan"],
    ["Vijayawada", "95", "Startups", "Campus permissions"],
    ["Hyderabad", "125", "Digital media", "Leadership shortlist"]
  ]} />;
}

function Products() {
  return <Table title="Product Database" icon={<Package />} headers={["Product", "Category", "Target", "Status"]} rows={[
    ["Hospital ERP", "ERP", "Hospitals", "Demo ready"],
    ["University ERP", "ERP", "Colleges", "Pitch ready"],
    ["Political Office ERP", "Political ERP", "Offices", "Ethics review"],
    ["Telemedicine Global Connect", "Digital health", "Doctors", "Discovery"]
  ]} />;
}

function Agents() {
  return (
    <section className="agent-grid">
      {agents.map((agent, index) => (
        <article className="agent" key={agent}>
          <Bot size={18} />
          <strong>{agent}</strong>
          <span>Agent {index + 1}</span>
        </article>
      ))}
    </section>
  );
}

function Reports() {
  return (
    <section className="band reports">
      <div>
        <h2>Morning Report</h2>
        <p>Founder priority brief, employee task list, follow-ups due, sales actions, influencer actions, student club actions, robotics actions, agri market actions, political intelligence actions, and risk alerts.</p>
      </div>
      <div>
        <h2>Weekly Review</h2>
        <p>Founder weekly review, employee scorecards, sales pipeline, influencer growth, student club growth, robotics progress, agri opportunity, political preparation, cashflow reminders, and strategic recommendations.</p>
      </div>
    </section>
  );
}
