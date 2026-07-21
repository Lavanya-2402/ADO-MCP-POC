# High-Detail Technical Reference: Local Azure DevOps MCP Application

This documentation provides an exhaustive, production-grade technical breakdown of the **Local Azure DevOps MCP Application**. It covers the architecture, lifecycle management, classification logic, LLM integration loop, asynchronous background tasks, and details of all components.

---

## 1. System Architecture

The local application is a self-contained AI-powered agent bridging a local LLM with the Azure DevOps REST API via the Model Context Protocol (MCP).

```
   ┌─────────────────────────────────────────────────────────────┐
   │                       Web Browser Client                    │
   │            (index.html & script.js - Professional UI)        │
   └──────────────────────────────┬──────────────────────────────┘
                                  │
                                  │ HTTP / SSE (Event Stream)
                                  ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                    FastAPI Backend Server                   │
   │                         (server.py)                         │
   └──────────────────────────────┬──────────────────────────────┘
                                  │
                                  │ Stdio Pipes (stdin / stdout)
                                  ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                Stdio Client (MCP Node Process)              │
   │               npx @azure-devops/mcp <org_name>              │
   └──────────────────────────────┬──────────────────────────────┘
                                  │
                                  │ HTTPS REST Calls (using PAT)
                                  ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                       Azure DevOps Cloud                    │
   │                     (dev.azure.com/<org>)                   │
   └─────────────────────────────────────────────────────────────┘
```

---

## 2. Lifespan Lifecycle & Persistent Sessions

To maximize performance, resource efficiency, and sub-second tool discovery, the FastAPI backend uses the **Lifespan Context Manager** (`@asynccontextmanager`) in conjunction with Python's standard `contextlib.AsyncExitStack`.

### Startup & Setup Phase
1. **Config Loading**: Reads the environment variables from `.env` (validated via `AppConfig`) and extracts command settings from `mcp_config.json`.
2. **Process Spawn & Session Bind**: 
   * It calls the standard `stdio_client(server_params)` context manager from the Python `mcp` SDK.
   * This spawns the Node.js MCP server (`npx -y @azure-devops/mcp <org> --authentication envvar`) as a background subprocess, mapping input/output streams.
   * The server context establishes a persistent `ClientSession(read, write)` and calls `await mcp_session.initialize()`.
3. **Pre-caching Definitions**:
   * Calls `mcp_session.list_tools()` at startup.
   * Caches all **90 available tool schemas** and definitions in the FastAPI application state (`app.state.mcp_tools`).
   * Caches the active session on `app.state.mcp_session`.
   * This pre-caching ensures that subsequent API queries do not incur subprocess startup latency.

### Shutdown & Cleanup Phase
* When the FastAPI application terminates, the lifespan manager triggers `await exit_stack.aclose()`.
* This closes the stdio client session, terminates the Node.js subprocess, and cleans up open pipes, preventing dangling processes or orphaned port/handle bindings.

---

## 3. Subagent Routing & Classification Engine

The system uses a **Subagent Routing Classifier** to segment incoming requests into specific functional roles, narrowing the tools exposed to the LLM to conserve context window token usage and minimize hallucinations.

### The Classification Matrix

| Subagent Role | Target Keywords | Allowed Tool Prefix Filters | Focus Area / Description |
| :--- | :--- | :--- | :--- |
| **DevOps Engineer** | `pipeline`, `build`, `run`, `deploy`, `release`, `migration` | `core_`, `pipelines_`, `advsec_`, `search_` | CI/CD processes, pipeline configurations, builds, logs, security alerts. |
| **QA Analyst** | `test`, `suite`, `qa`, `plan`, `case` | `core_`, `testplan_`, `pipelines_`, `search_` | Test planning, suites, runs, cases, reporting quality stats. |
| **Technical Writer** | `wiki`, `documentation`, `page` | `core_`, `wiki_`, `search_` | Documenting features, managing wikis, writing markdown pages. |
| **Product Manager** | `work item`, `task`, `bug`, `story`, `epic`, `issue`, `backlog`, `query`, `discussion`, `comment`, `link`, `capacity`, `sprint`, `iteration`, `board`, `velocity`, `assign`, `create item`, `add item`, `new item`, `feature` | `core_`, `wit_`, `work_`, `search_` | Iterations, sprints, team settings, creating and updating work items. |
| **Software Developer** | `repo`, `repository`, `branch`, `commit`, `pull request`, `pr`, `merge`, `file`, `diff`, `code review`, `clone`, `push`, `git` | `core_`, `repo_`, `wit_`, `search_` | Source control, branch management, pull requests, commits. |
| **General Assistant** | *Fallback when multiple/no keywords match* | *All Prefixes* | Full-featured fallback assistant with access to all 90 tools. |

### Helper Functions

* `determine_subagent_role(prompt)`: Scans the user prompt in lowercase. Matches keywords and selects the role. If multiple roles or no roles match, it defaults to the `"General Assistant"`.
* `filter_tools_for_role(role_name, mcp_tools)`: Filter the cached 90 tools. Only tools starting with prefixes mapped to the role are converted to Gemini `FunctionDeclaration` structures and registered under the LLM config.

---

## 4. Gemini Function-Calling Loop (`execute_agent_run`)

The application overrides Gemini's automatic function-calling mechanism to run in manual execution mode. This allows the backend server to intercept, log, and throttle tool calls before execution.

```
                  ┌──────────────────────────────┐
                  │   Start execute_agent_run    │
                  └──────────────┬───────────────┘
                                 │
                                 ▼
                   ┌────────────────────────────┐
                   │ Generate Content from Model│◄────────────────┐
                   └─────────────┬──────────────┘                 │
                                 │                                │
                                 ▼                                │
                      /                      \                    │
                     <   Has Function Calls?  >                   │
                      \                      /                    │
                        /                  \                      │
                  Yes  /                    \  No                 │
                      /                      \                    │
                     ▼                        ▼                   │
             ┌───────────────┐        ┌───────────────┐           │
             │ Loop Calls:   │        │ Return Model  │           │
             │ Exec tool and │        │ Text Output   │           │
             │ collect output│        └───────────────┘           │
             └───────┬───────┘                                    │
                     │                                            │
                     ▼                                            │
             ┌───────────────┐                                    │
             │ Append results│                                    │
             │ to history    │                                    │
             └───────┬───────┘                                    │
                     │                                            │
                     ▼                                            │
             ┌───────────────┐                                    │
             │ Sleep 4.5s    ├────────────────────────────────────┘
             │ (Rate Limit)  │
             └───────────────┘
```

### Core Execution Safeguards
1. **Manual Function Resolution**: Configured with `automatic_function_calling=False`. The server parses response candidates for tool arguments, executes them in standard code, and appends the result to the conversation history.
2. **Rate Limit Throttling**: Implements `await asyncio.sleep(4.5)` between successive tool execution turns to avoid hitting the Gemini API free tier rate limits (RPM constraints).
3. **Data Truncation Guard**: The output of each tool call is joined and truncated to a maximum of **3,000 characters**:
   ```python
   if len(result_text) > 3000:
       result_text = result_text[:3000] + "\n\n... [Truncated] ..."
   ```
   This prevents token overflow, conserves the context window, and reduces free-tier quota exhaustion.

---

## 5. Detailed API Endpoints & Background Processes

### `POST /api/chat/stream`
* **Protocol**: Server-Sent Events (SSE).
* **Execution Flow**:
  1. Accepts `ChatRequest` schema (`prompt`).
  2. Resolves the subagent role.
  3. Yields status events to inform the frontend UI of the state:
     `data: {"type": "status", "message": "Connected to Azure DevOps MCP server."}`
     `data: {"type": "subagent", "name": "DevOps Engineer"}`
  4. Triggers `execute_agent_run` in the current thread and awaits the final response.
  5. Yields the final accumulated answer block:
     `data: {"type": "final", "message": "The pipeline runs are..."}`

### `POST /api/webhooks/ado` (Webhook Receiver)
* **Trigger**: Listens for HTTP POST webhook events from Azure DevOps Services.
* **Filter Rule**: Matches `"eventType": "build.complete"` with `"result": "failed"`.
* **Action**: If a build fails, it spins up the **Build Doctor** utility running in the background as an asynchronous non-blocking task:
  ```python
  asyncio.create_task(run_build_doctor(build_id, project_name, pipeline_id, mcp_session, mcp_tools))
  ```

---

## 6. Build Doctor & Auto-Healing Mechanics

The **Build Doctor** is a specialized background automation workflow designed to automatically diagnose build failures and open tracking items for developers.

### Diagnostic Flow
1. **Trigger**: Fired when a build fails in a monitored pipeline.
2. **Log Retrieval**: Using the combined capabilities of `DevOps Engineer` and `Product Manager` profiles, it invokes:
   * `pipelines_get_build_log` to fetch available build log descriptors.
   * `pipelines_get_build_log_by_id` to download the specific failing log chunks.
3. **Reasoning Step**: Feeds the logs to the Gemini model to parse syntax errors, compilation tracebacks, or failing unit test assertions.
4. **Auto-Healing Bug Creation**: Once the root cause is diagnosed, the subagent calls `wit_create_work_item` to automatically create a new **BUG Work Item** on the Azure Board.
   * **Project**: Mapped to the failing build project.
   * **Title**: `[Build Doctor] Build #{build_id} Failed in Pipeline {pipeline_id}`
   * **Description**: Includes the extracted log traceback and a step-by-step description of the recommended changes required to fix it.

---

## 7. Frontend UI Integration

The frontend consists of a clean, single-page, highly responsive user interface:
* **Styles**: Blue-and-white professional layout built with standard CSS. Fully responsive design with flex columns.
* **Initials Avatar Badge**: When the subagent role is resolved, `script.js` updates the user's avatar icon to reflect the persona (e.g., `D` for DevOps Engineer, `QA` for QA Analyst, `A` for Agent, `U` for User).
* **SSE Event Handler**: Reads the SSE chunk data:
  * `type: status` -> Displays subtle connection status info.
  * `type: subagent` -> Dynamically updates avatar initials and border highlight color.
  * `type: final` -> Appends the markdown response in the chat bubble.
  * `type: error` -> Displays a professional validation warning banner.
