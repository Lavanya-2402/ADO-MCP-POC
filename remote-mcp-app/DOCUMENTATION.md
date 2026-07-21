# High-Detail Technical Reference: Remote Azure DevOps MCP Application

This documentation provides an exhaustive, production-grade technical breakdown of the **Remote Azure DevOps MCP Application**. It covers the architecture, OAuth credentials validation, MSAL token caching, JSON-RPC schema parsing, classification logic, LLM integration loop, asynchronous background tasks, and all components.

---

## 1. System Architecture

The remote application is a secure gateway bridge connecting a local LLM with the cloud-hosted Azure DevOps Remote MCP Gateway using Microsoft Entra ID authentication.

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
   └──────────────┬──────────────────────────────┬───────────────┘
                  │                              │
                  │ OAuth Request (MSAL client)  │ HTTP / JSON-RPC
                  ▼                              ▼
   ┌──────────────────────────────┐    ┌─────────────────────────┐
   │      Microsoft Entra ID      │    │   Remote MCP Gateway    │
   │  (login.microsoftonline.com) │    │ (mcp.dev.azure.com)     │
   └──────────────────────────────┘    └─────────┬───────────────┘
                                                 │
                                                 │ HTTPS REST Calls
                                                 ▼
                                       ┌─────────────────────────┐
                                       │    Azure DevOps Cloud   │
                                       └─────────────────────────┘
```

---

## 2. Lifespan Lifecycle & Persistent Sessions

To optimize performance and avoid recreating HTTP connection pools for every user query, the FastAPI backend uses the **Lifespan Context Manager** (`@asynccontextmanager`).

### Startup & Setup Phase
1. **Config Loading**: Reads the environment variables from `.env` (validated via `AppConfig`) and extracts gateway parameters from `mcp_config.json`.
2. **Pre-caching Definitions**:
   * Initializes a persistent `RemoteMCPClient` with the gateway URL (`https://mcp.dev.azure.com/Rapid-AI-Team`) and headers.
   * Acquires a new Entra ID token using MSAL client credentials flow.
   * Sends a JSON-RPC request (`method: tools/list`) to the remote gateway.
   * Parses and caches all **40 remote tool schemas** and definitions in the FastAPI application state (`app.state.mcp_tools`).
   * Caches the active client session on `app.state.mcp_session`.
   * This caching mechanism ensures subsequent chats run immediately without querying tool schemas repeatedly.

### Shutdown Phase
* When FastAPI shuts down, it logs the session teardown and closes active client handles cleanly.

---

## 3. Entra ID Client Credentials Flow & Token Rotation

The backend implements silent, background authentication to Azure DevOps using **Entra ID Application Registrations**.

### Credentials Validation
The server reads three variables from `.env` to configure MSAL:
* `ENTRA_TENANT_ID`: The UUID of your Microsoft Entra Tenant.
* `ENTRA_CLIENT_ID`: The App Registration (Client) ID.
* `ENTRA_CLIENT_SECRET`: The secret key generated for the Application.

If any of these fields are missing or contain placeholder values, the backend triggers a critical configuration error and exits immediately during startup.

### Token Rotation Logic (`get_auth_token`)
* **Scope**: Requests the Azure DevOps resource scope `["https://mcp.dev.azure.com/.default"]`.
* **Caching & Expiry**: To avoid calling Entra ID on every request, tokens are cached in memory:
  `_token_cache = {"token": None, "expires_at": 0}`
* **Condition (Cache Hit)**:
  ```python
  if _token_cache["token"] and current_time < _token_cache["expires_at"] - 60:
      return _token_cache["token"]
  ```
  If a token is in cache and is valid for at least 60 more seconds, it is returned immediately.
* **Condition (Cache Miss)**:
  If the token is expired or missing, the server uses MSAL's `ConfidentialClientApplication` to request a new token from `https://login.microsoftonline.com/{tenant_id}` and updates the cache.

---

## 4. RemoteMCPClient Implementation (JSON-RPC)

The `RemoteMCPClient` class interacts with the remote gateway over standard HTTPS. Since the gateway is exposed via JSON-RPC, the client translates method names and payloads:

1. **Header Assembly**: Attaches the Entra ID access token as a standard Bearer authorization header:
   `Authorization: Bearer eyJ...`
2. **List Tools**: Issues a JSON-RPC `tools/list` POST request.
3. **Call Tool**: Issues a JSON-RPC `tools/call` POST request with `name` and `arguments` parameters.
4. **SSE Response Handling**: The remote gateway may return payloads wrapped as Server-Sent Events (`event: data`). The client intercepts the raw HTTP stream, extracts lines starting with `data: `, and parses the inner JSON block.

---

## 5. Subagent Routing & Classification Engine

The system uses a **Subagent Routing Classifier** to segment incoming requests into specific functional roles, narrowing the tools exposed to the LLM to conserve context window token usage and minimize hallucinations.

### The Classification Matrix

| Subagent Role | Target Keywords | Allowed Tool Prefix Filters | Focus Area / Description |
| :--- | :--- | :--- | :--- |
| **DevOps Engineer** | `pipeline`, `build`, `run`, `deploy`, `release`, `migration` | `core_`, `pipelines_`, `advsec_`, `search_` | CI/CD processes, pipeline configurations, builds, logs, security alerts. |
| **QA Analyst** | `test`, `suite`, `qa`, `plan`, `case` | `core_`, `testplan_`, `pipelines_`, `search_` | Test planning, suites, runs, cases, reporting quality stats. |
| **Technical Writer** | `wiki`, `documentation`, `page` | `core_`, `wiki_`, `search_` | Documenting features, managing wikis, writing markdown pages. |
| **Product Manager** | `work item`, `task`, `bug`, `story`, `epic`, `issue`, `backlog`, `query`, `discussion`, `comment`, `link`, `capacity`, `sprint`, `iteration`, `board`, `velocity`, `assign`, `create item`, `add item`, `new item`, `feature` | `core_`, `wit_`, `work_`, `search_` | Iterations, sprints, team settings, creating and updating work items. |
| **Software Developer** | `repo`, `repository`, `branch`, `commit`, `pull request`, `pr`, `merge`, `file`, `diff`, `code review`, `clone`, `push`, `git` | `core_`, `repo_`, `wit_`, `search_` | Source control, branch management, pull requests, commits. |
| **General Assistant** | *Fallback when multiple/no keywords match* | *All Prefixes* | Full-featured fallback assistant with access to all 40 tools. |

### Helper Functions
* `determine_subagent_role(prompt)`: Scans the user prompt in lowercase. Matches keywords and selects the role. If multiple roles or no roles match, it defaults to the `"General Assistant"`.
* `filter_tools_for_role(role_name, mcp_tools)`: Filter the cached 40 tools. Only tools starting with prefixes mapped to the role are converted to Gemini `FunctionDeclaration` structures and registered under the LLM config.

---

## 6. Gemini Function-Calling Loop (`execute_agent_run`)

The application overrides Gemini's automatic function-calling mechanism to run in manual execution mode. This allows the backend server to intercept, log, and throttle tool calls before execution.

### Core Execution Safeguards
1. **Manual Function Resolution**: Configured with `automatic_function_calling=False`. The server parses response candidates for tool arguments, executes them in standard code, and appends the result to the conversation history.
2. **Rate Limit Throttling**: Implements `await asyncio.sleep(4.5)` between successive tool execution turns to avoid hitting the Gemini API free tier rate limits (RPM constraints).
3. **Data Truncation Guard**: The output of each tool call is joined and truncated to a maximum of **3,000 characters** to protect free-tier token usage:
   ```python
   if len(result_text) > 3000:
       result_text = result_text[:3000] + "\n\n... [Truncated] ..."
   ```

---

## 7. Detailed API Endpoints & Webhooks

### `POST /api/chat/stream`
* **Protocol**: Server-Sent Events (SSE).
* **Execution Flow**:
  1. Accepts `ChatRequest` schema (`prompt`).
  2. Resolves the subagent role.
  3. Yields status events to inform the frontend UI of the state:
     `data: {"type": "status", "message": "Connected to Azure DevOps Remote MCP server."}`
     `data: {"type": "subagent", "name": "DevOps Engineer"}`
  4. Triggers `execute_agent_run` in the current thread and awaits the final response.
  5. Yields the final accumulated answer block:
     `data: {"type": "final", "message": "The pipeline runs are..."}`

### `POST /api/webhooks/ado` (Webhook Receiver)
* **Trigger**: Listens for HTTP POST webhook events from Azure DevOps Services.
* **Filter Rule**: Matches `"eventType": "build.complete"` with `"result": "failed"`.
* **Action**: Spins up the **Build Doctor** utility running in the background as an asynchronous non-blocking task:
  ```python
  asyncio.create_task(run_build_doctor(build_id, project_name, pipeline_id, mcp_session, mcp_tools))
  ```

---

## 8. Build Doctor & Auto-Healing Mechanics

The **Build Doctor** is a specialized background automation workflow designed to automatically diagnose build failures and print the diagnostic summary in the server logs for system administrators.

### Diagnostic Flow
1. **Trigger**: Fired when a build fails in a monitored pipeline.
2. **Log Retrieval**: Using the `DevOps Engineer` profile, it invokes:
   * `pipelines_build_log` list to fetch available build log descriptors.
   * `pipelines_build_log` content to fetch failing tracebacks.
3. **Reasoning Step**: Feeds the logs to the Gemini model to parse syntax errors, compilation tracebacks, or failing unit test assertions.
4. **Diagnostic Report**: Outputs a formatted diagnostic report directly to the uvicorn stdout logger:
   ```
   ================ BUILD DOCTOR REPORT ================
   Build ID: 123 | Project: Pulse v1 | Pipeline: 5
   Compilation failed in main.py line 42: IndentationError.
   =====================================================
   ```

---

## 9. Frontend UI Integration

The frontend consists of a clean, single-page, highly responsive user interface:
* **Styles**: Blue-and-white professional layout built with standard CSS. Fully responsive design with flex columns.
* **Initials Avatar Badge**: When the subagent role is resolved, `script.js` updates the user's avatar icon to reflect the persona (e.g., `D` for DevOps Engineer, `QA` for QA Analyst, `A` for Agent, `U` for User).
* **SSE Event Handler**: Reads the SSE chunk data:
  * `type: status` -> Displays subtle connection status info.
  * `type: subagent` -> Dynamically updates avatar initials and border highlight color.
  * `type: final` -> Appends the markdown response in the chat bubble.
  * `type: error` -> Displays a professional validation warning banner.
