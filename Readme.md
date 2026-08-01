# Personal AI Agent

Local, sovereign Personal & Professional AI Agent Ecosystem.
Rebuild started: 2026-08-01.

See project memory / architecture notes for full design.
Do not commit `.env`, `config/credentials.json`, or `config/token.json`.

#======================================================================
D:\Agent\
├── app\                    # Core framework code (never touched by plugin authors)
│   ├── core\                # config, logging, exceptions, db connection — the "spine"
│   ├── registry\             # plugin discovery + tool registry (recursive, walk_packages)
│   └── models\               # shared Pydantic models (ToolResult, base schemas, etc.)
│
├── plugins\                 # ALL tools live here, one subfolder per domain — never in app\
│   ├── excel\
│   ├── pdf\
│   ├── word\
│   ├── google\               # gmail/, drive\, calendar\, sheets\ subpackages later
│   └── telegram\
│
├── config\                  # secrets & credentials ONLY — never source code
│   ├── credentials.json      # (you supply; gitignored)
│   └── token.json            # (generated after OAuth; gitignored)
│
├── data\                    # SQLite DB files, runtime state — never source code
├── logs\                    # rotating Loguru log files
├── tests\                   # pytest suite — full-suite, run only at milestones
│
├── main.py                  # real entry point (Telegram bot / agent loop)
├── main_test.py             # your fast per-step manual verification script
├── requirements.txt
├── .env.example              # documents required env vars, safe to commit
├── .env                       # actual secrets, gitignored, you fill this in
├── .gitignore
└── README.md

#==============================================================
## M1 — Step 1: Project Scaffolding
Lay down the full directory skeleton on disk, with plugins kept structurally separate from core framework code, config/secrets separated from code, and data/logs separated from source — so every later milestone has an obvious, uncontested home. This step creates structure and placeholder files only

# Create project root and enter it
New-Item -ItemType Directory -Path "D:\Agent" -Force
Set-Location "D:\Agent"

# Core framework
New-Item -ItemType Directory -Path "app\core","app\registry","app\models" -Force

# Plugin domains (empty for now, filled in M7+)
New-Item -ItemType Directory -Path "plugins\excel","plugins\pdf","plugins\word","plugins\google","plugins\telegram" -Force

# Secrets, data, logs, tests
New-Item -ItemType Directory -Path "config","data","logs","tests" -Force

# __init__.py so every package is importable (recursive discovery needs real packages)
New-Item -ItemType File -Path "app\__init__.py","app\core\__init__.py","app\registry\__init__.py","app\models\__init__.py" -Force
New-Item -ItemType File -Path "plugins\__init__.py","plugins\excel\__init__.py","plugins\pdf\__init__.py","plugins\word\__init__.py","plugins\google\__init__.py","plugins\telegram\__init__.py" -Force
New-Item -ItemType File -Path "tests\__init__.py" -Force

# .gitkeep so empty runtime dirs still exist in git (contents themselves are ignored)
New-Item -ItemType File -Path "data\.gitkeep","logs\.gitkeep" -Force

# Git init
git init

# To check Folder tree 
Get-ChildItem -Recurse -Directory | Select-Object FullName

# Git recognizes the repo and .gitignore is working (should NOT list data/logs/.env)
git status

#==============================================
## M1 — Step 2: Config + Logging
Build the two lowest-level "spine" modules that everything else depends on:

app/core/config.py — a single Pydantic Settings object that loads .env, validates required keys exist, and exposes typed config to the whole app (no module anywhere else reads os.environ directly — always through this).
app/core/logging_setup.py — Loguru configured once, rotating file logs in logs/, console output for dev, called once at startup and imported everywhere else as an already-configured logger.
app/core/exceptions.py — the base exception hierarchy now, since Step 5 lessons (wrapped re-raises) require it to exist before any tool code is written.

## M1 — Step 3: Database Layer
Build app/core/database.py: a single SQLite connection helper plus init_db() that creates all foundational tables — most importantly execution_history, the audit table every tool call writes to automatically (per Section 2's "full audit trail" requirement), so it exists before the tool registry (M1 Step 4 / M2) needs to write to it.

## M1 — Step 4: Plugin Registry (recursive tool discovery)
Build the centerpiece of M1: app/registry/, containing

tool_contract.py — the @tool decorator + ToolResult shape every plugin must use.
discovery.py — recursive plugin discovery using pkgutil.walk_packages (never iter_modules, per the documented lesson), scanning plugins/ and registering every @tool-decorated function it finds, including ones nested in subpackages like plugins/google/gmail/.

## M1 — Step 5: Boot Sequence + Milestone Close
Wire up the real main.py startup sequence — configure_logging() → init_db() → discover_tools(), in that order, with each step's failure being loud and fatal (no silent partial-startup) — and tag the milestone.