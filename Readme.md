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

### Create project root and enter it
New-Item -ItemType Directory -Path "D:\Agent" -Force
Set-Location "D:\Agent"

### Core framework
New-Item -ItemType Directory -Path "app\core","app\registry","app\models" -Force

### Plugin domains (empty for now, filled in M7+)
New-Item -ItemType Directory -Path "plugins\excel","plugins\pdf","plugins\word","plugins\google","plugins\telegram" -Force

### Secrets, data, logs, tests
New-Item -ItemType Directory -Path "config","data","logs","tests" -Force

### __init__.py so every package is importable (recursive discovery needs real packages)
New-Item -ItemType File -Path "app\__init__.py","app\core\__init__.py","app\registry\__init__.py","app\models\__init__.py" -Force
New-Item -ItemType File -Path "plugins\__init__.py","plugins\excel\__init__.py","plugins\pdf\__init__.py","plugins\word\__init__.py","plugins\google\__init__.py","plugins\telegram\__init__.py" -Force
New-Item -ItemType File -Path "tests\__init__.py" -Force

### .gitkeep so empty runtime dirs still exist in git (contents themselves are ignored)
New-Item -ItemType File -Path "data\.gitkeep","logs\.gitkeep" -Force

### Git init
git init

### To check Folder tree 
Get-ChildItem -Recurse -Directory | Select-Object FullName

### Git recognizes the repo and .gitignore is working (should NOT list data/logs/.env)
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

#===========================================================================

## M2 — Step 1: The call_tool Pipeline
Build app/core/call_tool.py — the single shared execution path every tier (Tier 1 regex, Tier 3 LLM, Tier 4 LangGraph, everything) routes through to actually invoke a tool. This is where:

the tool_name-not-name parameter-collision fix (Section 5) is applied structurally,
input is validated against the tool's input_schema before the function ever runs,
every call — success or failure — writes a row to execution_history automatically, with no tool ever having to remember to log itself,
call_tool is structurally guaranteed to never silently return None on success (the documented prior bug), because its return type is ToolResult, not Optional[ToolResult], and every code path either returns a populated ToolResult or raises.

## M2 — Step 2: Permission Profiles + ApprovalHandler
Wire the PermissionLevel enum (already declared per-tool since M1-S4) into an actual approval-gating policy inside call_tool. Build a pluggable ApprovalHandler interface per Section 2, with two safe concrete implementations for now (CLIApprovalHandler for manual dev testing, AutoApproveHandler/AutoDenyHandler strictly for automated tests) — the real Telegram-based handler arrives in M6. Also stub the "one batch approval per run" behavior: multiple call_tool invocations sharing a run_id only prompt once.

## M2 — Step 3: Milestone Wrap-up (pytest suite + tag)
Write a real pytest suite covering call_tool and approval gating with a properly isolated test database (the fixture calls init_db() itself, per the documented "test fixtures must call init_db() themselves" lesson — never assume a shared DB state). Run it, confirm green, then tag v0.2-m2-tool-framework.

# ===============================================================
## M3 — Step 1: Event Bus Core (pub/sub)
Build app/core/event_bus.py: a simple, synchronous, in-process publish/subscribe mechanism that tools and call_tool can publish events to, and that future subsystems (Notification Framework in M5, Job Queue in M10, Scheduler in M11) can subscribe to — without those tools or call_tool ever knowing who's listening. This step builds the bus itself and wires call_tool to publish two events (tool.succeeded, tool.failed) on every invocation

## M3 — Step 2: Approval Events + Milestone Wrap-up
Add three more event types specifically around the approval-gating flow — tool.approval_requested, tool.approval_granted, tool.approval_denied — since the Notification Framework (M5) will want to notify the person about pending approvals, not just completed calls. Then close out M3: a dedicated tests/test_event_bus.py, full pytest run, and tag v0.3-m3-event-bus.

# =======================================================================
## M4 — Step 1: Central Knowledge Base Schema
Build app/core/knowledge_base.py: the SQLite-backed store for notes, contacts, preferences, and long-term memory (Section 4, item 1). This step focuses on the schema and basic CRUD operations — a knowledge_items table designed so embeddings can be added in a later phase (likely alongside LangGraph/semantic search work) without a schema rewrite.

## M4 — Step 2: Knowledge Base as Tools + Milestone Wrap-up
Expose the knowledge base to the agent itself via real @tool-decorated plugins in plugins/knowledge/ — add_note, search_knowledge, get_knowledge_item, update_knowledge_item, delete_knowledge_item — so future tiers (regex, LLM, LangGraph) can actually let the agent read/write its own memory, not just internal code. Then close out M4: pytest suite, full run, tag v0.4-m4-knowledge-base.

# =====================================================================

## M5 — Step 1: Notification Framework Core
Build app/core/notifications.py: the channel-abstracted notification system from Section 4, item 5. This step defines the NotificationChannel interface, a NotificationManager that can hold and broadcast to multiple channels at once, and one concrete starter implementation — ConsoleNotificationChannel.

## M5 — Step 2: Wire Notifications to Events + Milestone Wrap-up
Connect the Notification Framework to the Event Bus: subscribe notification-sending handlers to tool.approval_requested and tool.failed, register the console channel in main.py's boot sequence, then close out M5 with a pytest suite and the v0.5-m5-notifications tag.

# ==========================================================================
## M6 — Step 1: Telegram Bot Scaffolding + Notification Channel
Get a real, running Telegram bot connected to your actual bot token, restricted to your own Telegram user ID, with concurrent_updates=True set from the very first version (per Section 5 — never add this as an afterthought once a deadlock has already happened). This step delivers: the Application builder wrapper, a /start command handler, and TelegramNotificationChannel — the second real NotificationChannel implementation, proving the abstraction from M5 genuinely works across two very different delivery mechanisms.

## M6 — Step 2: Telegram Approval Handler (inline buttons)
Build TelegramApprovalHandler — a real ApprovalHandler (from M2) backed by Telegram inline-keyboard buttons. A MODIFY/DELETE/ADMIN tool call routed through this handler sends you an "Approve / Deny" message in Telegram; tapping a button resolves a threading.Event that the (blocking, synchronous) request_approval() call is waiting on.

## M6 — Step 3: Wire main.py + Testable Pytest Suite + Milestone Wrap-up
Replace main.py's NotImplementedError placeholder with the real agent loop — register both notification channels (console + Telegram) and call start_bot() as the final, blocking step. Then build a pytest suite for everything in M6 that can be tested without a live Telegram connection (the callback-resolution logic and timeout behavior, using a real background-thread event loop but a fake Application/bot.send_message — no actual network calls). Close out with the tag.

# ======================================================================

## M7 — Step 1: Excel Read Tools (streaming)
Build plugins/excel/ — tools to list sheets, read a range/whole sheet, and search for values in an Excel workbook, using openpyxl in streaming read-only mode (read_only=True) per the 8GB RAM discipline in Section 2. This step is read-only tools only (PermissionLevel.READ — no approval gate needed); write/modify tools (Step 2) come next since they're higher-risk and deserve their own focused step.