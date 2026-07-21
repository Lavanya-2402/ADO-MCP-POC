# Azure DevOps MCP Action-Oriented Agent Prompts Sheet

This file contains action-oriented prompts designed for automated SDLC agents to execute write, create, and configuration tasks against the Azure DevOps MCP server. 

These prompts do not ask the agent to "list" or "verify" information; instead, they instruct the agent to directly execute writes, updates, linkages, and runs using the available MCP write tools.

---

## 🚀 Set 1: Environment & Scrum Board Setup
*Tasks for an automated Project/Scrum Agent to initialize iterations, populate the backlog, and configure team settings.*

### 1. Create Sprints / Iterations
* **MCP Tools Used:** `work_create_iterations` & `work_assign_iterations`
* **Prompt:**
  > "Create two Sprints under the 'Pulse' project root: 'Sprint 1' (Start: 2026-07-01, End: 2026-07-20) and 'Sprint 2' (Start: 2026-07-21, End: 2026-08-10). Assign both Sprints to the 'Pulse v1 Team' backlog settings."

### 2. Batch-Create Backlog Epics and Features
* **MCP Tools Used:** `wit_create_work_item`
* **Prompt:**
  > "Create three Epics and four Features in the 'Pulse' project backlog:
  > - Epic 1: 'AI Ingestion & Curation Engine'
  > - Epic 2: 'Unified Developer Portal & UI'
  > - Epic 3: 'DevOps & Infrastructure automation'
  > - Feature 1: 'Feeds Ingestion Layer' (Assigned to 'steja3351', State: 'Done')
  > - Feature 2: 'Gemini Curation Brain' (Assigned to 'Lavanya Tetakali', State: 'In Progress')
  > - Feature 3: 'Monochrome Dashboard UI' (Assigned to 'supriyadaita439', State: 'In Progress')
  > - Feature 4: 'Continuous Integration (CI) Automation' (Assigned to 'Lavanya Tetakali', State: 'In Progress')"

### 3. Create User Stories and Establish Parent-Child Links
* **MCP Tools Used:** `wit_create_work_item` & `wit_add_child_work_items`
* **Prompt:**
  > "Create the following User Stories, link them as child items under their respective parent Features, and assign them to the specified iteration:
  > - User Story: 'Implement Contextual Vault Lookup' (Assignee: 'Lavanya Tetakali', Iteration: 'Sprint 1', Parent: 'Gemini Curation Brain')
  > - User Story: 'Implement Monochrome Dark Theme' (Assignee: 'supriyadaita439', Iteration: 'Sprint 1', Parent: 'Monochrome Dashboard UI')
  > - User Story: 'Core Ingestion Orchestrator' (Assignee: 'steja3351', Iteration: 'Sprint 1', Parent: 'Feeds Ingestion Layer')
  > - User Story: 'Hot Topics UI Grid' (Assignee: 'supriyadaita439', Iteration: 'Sprint 2', Parent: 'Monochrome Dashboard UI')
  > - User Story: 'Reddit RSS parsing parser' (Assignee: 'steja3351', Iteration: 'Sprint 2', Parent: 'Feeds Ingestion Layer')
  > - User Story: 'CI Pipeline Test Execution' (Assignee: 'Lavanya Tetakali', Iteration: 'Sprint 1', Parent: 'Continuous Integration (CI) Automation')
  > - User Story: 'Containerize Web App' (Assignee: 'Lavanya Tetakali', Iteration: 'Sprint 2', Parent: 'Continuous Integration (CI) Automation')"

### 4. Configure Team Capacities
* **MCP Tools Used:** `work_update_team_capacity`
* **Prompt:**
  > "Set the daily development capacities for the team 'Pulse v1 Team' in 'Sprint 1' to: Lavanya Tetakali = 8 hours, steja3351 = 6 hours, and supriyadaita439 = 8 hours."

---

## 🛠️ Set 2: Developer Git & Pull Request Actions
*Tasks for Developer agents to create branches, open Pull Requests, link work items, and write reviews.*

### 1. Create a Feature Branch
* **MCP Tools Used:** `repo_create_branch`
* **Prompt:**
  > "Create a new branch in the 'Pulse' repository named 'feature/gemini-fallback' branching from the head of the 'main' branch."

### 2. Create a Pull Request for Code Review
* **MCP Tools Used:** `repo_create_pull_request`
* **Prompt:**
  > "Create a Pull Request to merge the branch 'feature/reddit-parser' into 'main' in the 'Pulse' repository. Set the title to 'feat(ingest): implement reddit RSS feed parser' and set the description to 'Adds SQLite db schemas, feeds collector agents, and API endpoints for Reddit feed parsing'."

### 3. Link Pull Request to Backlog User Story
* **MCP Tools Used:** `wit_link_work_item_to_pull_request`
* **Prompt:**
  > "Link Pull Request ID [Insert PR ID] in the 'Pulse' repository to the User Story work item titled 'Reddit RSS parsing parser' to update its traceability."

### 4. Post Review Comments and Feedback on a PR
* **MCP Tools Used:** `repo_create_pull_request_thread` & `repo_reply_to_comment`
* **Prompt:**
  > "Create a comment thread on Pull Request ID [Insert PR ID] at a file level with the comment: 'Please ensure that the feed parser handles malformed XML payloads safely without raising an unhandled exception.' If there is an existing thread regarding unit tests, reply to it stating: 'The unit tests have been fixed in the latest commit on this branch.'"

---

## 🐛 Set 3: DevOps, Pipelines & Defect Management Actions
*Tasks for DevOps and QA agents to manage pipelines, file bugs, and link failures.*

### 1. Create CI/CD Pipeline
* **MCP Tools Used:** `pipelines_create_pipeline`
* **Prompt:**
  > "Create a build pipeline definition in the 'Pulse' project. Name it 'Pulse CI Pipeline', point it to the 'Pulse' repository, and configure it to use the `azure-pipelines.yml` file from the main branch."

### 2. Run Pipeline against Feature Branches
* **MCP Tools Used:** `pipelines_run_pipeline`
* **Prompt:**
  > "Run the pipeline 'Pulse CI Pipeline' for the branch 'feature/reddit-parser' to validate the ingestion test execution suite."

### 3. Log a Bug for a Failed Build
* **MCP Tools Used:** `wit_create_work_item` & `wit_add_child_work_items`
* **Prompt:**
  > "Create a Bug work item in the 'Pulse' project with the title 'CI Build Failure: test_api.py on feature/reddit-parser'. Set the Description to 'The build failed during the pytest execution step. Traceback shows an XML parsing error in backend/sources/reddit.py.' Set the Severity to '1 - Critical' and link this Bug as a child of the 'Reddit RSS parsing parser' User Story."

---

## 📝 Set 4: Wiki Documentation Actions
*Tasks for Documentation and Knowledge Management agents to create and update project wikis.*

### 1. Create Developer Wiki
* **MCP Tools Used:** `wiki_create_or_update_page` (or `wiki_upsert_page`)
* **Prompt:**
  > "Create a project wiki named 'Pulse Wiki' if it does not exist. Then, create a wiki page at the path '/Developer-Setup/Database-Seeder' with the Markdown content:
  > '# Database Seeding Instructions\nTo seed the SQLite database with the 17 AI timeline milestones, run:\n`python -m backend.db.database --seed`'"

### 2. Update Sprint Review Notes
* **MCP Tools Used:** `wiki_create_or_update_page`
* **Prompt:**
  > "Add or update the wiki page at path '/Sprint-Reviews/Sprint-1' with a table summarizing the Sprint 1 deliverables:
  > | Work Item | Owner | Status |
  > | :--- | :--- | :--- |
  > | Contextual Vault Lookup | Lavanya Tetakali | Completed |
  > | Monochrome Dark Theme | supriyadaita439 | Completed |
  > | Core Ingestion Orchestrator | steja3351 | Completed |"
