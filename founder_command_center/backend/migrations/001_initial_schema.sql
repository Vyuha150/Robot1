CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  username VARCHAR(120) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(40) NOT NULL DEFAULT 'employee',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS people (
  id SERIAL PRIMARY KEY,
  name VARCHAR(180) NOT NULL,
  phone VARCHAR(40),
  email VARCHAR(180),
  district VARCHAR(120),
  mandal_or_city VARCHAR(120),
  state VARCHAR(120),
  category VARCHAR(80),
  organization VARCHAR(180),
  role VARCHAR(120),
  influence_level VARCHAR(40),
  relationship_strength INTEGER DEFAULT 0,
  source VARCHAR(120),
  consent_status VARCHAR(40) DEFAULT 'unknown',
  assigned_employee VARCHAR(120),
  last_contacted_at TIMESTAMP,
  next_followup_at TIMESTAMP,
  notes TEXT,
  tags JSONB DEFAULT '[]',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employees (
  id SERIAL PRIMARY KEY,
  name VARCHAR(180) NOT NULL,
  role VARCHAR(120) NOT NULL,
  skills JSONB DEFAULT '[]',
  workload_score INTEGER DEFAULT 0,
  active_tasks_count INTEGER DEFAULT 0,
  performance_score INTEGER DEFAULT 70,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
  id SERIAL PRIMARY KEY,
  title VARCHAR(220) NOT NULL,
  description TEXT,
  goal VARCHAR(220),
  assigned_to_employee_id INTEGER REFERENCES employees(id),
  assigned_by_agent VARCHAR(120),
  priority VARCHAR(40) DEFAULT 'medium',
  status VARCHAR(40) DEFAULT 'todo',
  deadline TIMESTAMP,
  dependencies JSONB DEFAULT '[]',
  expected_output TEXT,
  review_notes TEXT,
  risk_level VARCHAR(40) DEFAULT 'low',
  escalation_required BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
  id SERIAL PRIMARY KEY,
  name VARCHAR(180) UNIQUE NOT NULL,
  category VARCHAR(120) NOT NULL,
  target_customer TEXT,
  pain_points JSONB DEFAULT '[]',
  features JSONB DEFAULT '[]',
  pricing VARCHAR(180),
  demo_link VARCHAR(255),
  pitch_script TEXT,
  competitors JSONB DEFAULT '[]',
  objections JSONB DEFAULT '[]',
  required_documents JSONB DEFAULT '[]',
  status VARCHAR(40) DEFAULT 'active',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS leads (
  id SERIAL PRIMARY KEY,
  company_name VARCHAR(180) NOT NULL,
  contact_person VARCHAR(180),
  phone VARCHAR(40),
  email VARCHAR(180),
  industry VARCHAR(120) NOT NULL,
  district VARCHAR(120),
  lead_source VARCHAR(120),
  product_interest VARCHAR(180),
  deal_value_estimate FLOAT DEFAULT 0,
  stage VARCHAR(60) DEFAULT 'new',
  next_followup_at TIMESTAMP,
  assigned_employee VARCHAR(120),
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS influencers (
  id SERIAL PRIMARY KEY,
  name VARCHAR(180) NOT NULL,
  platform VARCHAR(80) NOT NULL,
  profile_url VARCHAR(255) UNIQUE,
  district VARCHAR(120),
  state VARCHAR(120),
  niche VARCHAR(120),
  followers INTEGER DEFAULT 0,
  average_views INTEGER DEFAULT 0,
  engagement_rate FLOAT DEFAULT 0,
  audience_type VARCHAR(120),
  contact_details TEXT,
  collaboration_interest VARCHAR(80),
  expected_payment VARCHAR(120),
  legal_agreement_status VARCHAR(60) DEFAULT 'not_started',
  event_attended BOOLEAN DEFAULT FALSE,
  content_quality_score INTEGER DEFAULT 0,
  brand_safety_score INTEGER DEFAULT 0,
  relationship_score INTEGER DEFAULT 0,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS student_club_members (
  id SERIAL PRIMARY KEY,
  name VARCHAR(180) NOT NULL,
  college VARCHAR(220) NOT NULL,
  district VARCHAR(120) NOT NULL,
  state VARCHAR(120) NOT NULL,
  interest_group VARCHAR(120) NOT NULL,
  skill VARCHAR(180),
  phone VARCHAR(40),
  email VARCHAR(180),
  club_role VARCHAR(120),
  weekly_activity_status VARCHAR(80) DEFAULT 'pending',
  leadership_potential INTEGER DEFAULT 0,
  volunteer_status VARCHAR(80) DEFAULT 'new',
  assigned_coordinator VARCHAR(120),
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
