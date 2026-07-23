# Detailed Line-by-Line Explanation of `server.py`

This document provides a line-by-line explanation of [server.py](file:///c:/Users/2862390/Desktop/Azure%20Devops%20MCP/remote-mcp-app/server.py). It covers **what** each section of code does, **why** it was implemented, and how the components interact to provide a remote Model Context Protocol (MCP) agent for Azure DevOps.

---

## Table of Contents
1. [Imports & Setup (Lines 1–20)](#1-imports--setup-lines-120)
2. [Logging & Environment Configuration (Lines 21–31)](#2-logging--environment-configuration-lines-2131)
3. [Startup Configuration Validation (Lines 32–60)](#3-startup-configuration-validation-lines-3260)
4. [MCP Data Models (Lines 61–78)](#4-mcp-data-models-lines-6178)
5. [Microsoft Entra ID OAuth Authentication (Lines 79–135)](#5-microsoft-entra-id-oauth-authentication-lines-79135)
6. [Remote MCP Client (Lines 136–226)](#6-remote-mcp-client-lines-136226)
7. [Subagent Role Definitions (Lines 227–280)](#7-subagent-role-definitions-lines-227280)
8. [Configuration Reader (Lines 281–306)](#8-configuration-reader-lines-281306)
9. [FastAPI Lifespan Manager & CORS Setup (Lines 307–344)](#9-fastapi-lifespan-manager--cors-setup-lines-307344)
10. [Subagent Routing & Tool Filtering (Lines 345–383)](#10-subagent-routing--tool-filtering-lines-345383)
11. [Autonomous Agent Loop (Lines 384–448)](#11-autonomous-agent-loop-lines-384448)
12. [Chat Streaming Endpoint (Lines 449–490)](#12-chat-streaming-endpoint-lines-449490)
13. [Build Doctor & Azure DevOps Webhook (Lines 491–549)](#13-build-doctor--azure-devops-webhook-lines-491549)
14. [Static File Hosting & Server Entry Point (Lines 550–557)](#14-static-file-hosting--server-entry-point-lines-550557)

---

## 1. Imports & Setup (Lines 1–20)

```python
1: import asyncio
2: import os
3: import sys
4: import json
5: import time
6: import logging
7: from dataclasses import dataclass
8: from typing import Dict, List, Any, AsyncGenerator, Optional, Tuple
9: from contextlib import asynccontextmanager
10: from dotenv import load_dotenv
11: from fastapi import FastAPI, HTTPException, Request
12: from fastapi.middleware.cors import CORSMiddleware
13: from fastapi.staticfiles import StaticFiles
14: from fastapi.responses import StreamingResponse
15: from pydantic import BaseModel, Field
16: import msal
17: import httpx
18: from google import genai
19: from google.genai import types
```

### Explanation & Rationale
* **`import asyncio` (Line 1):** Python's standard library for asynchronous programming. **Why:** Used for concurrency, background tasks (like Build Doctor), and async locking (`asyncio.Lock`).
* **`import os` (Line 2):** Operating system interactions. **Why:** Accesses environment variables from `.env` files and builds file system paths.
* **`import sys` (Line 3):** System parameters and functions. **Why:** Used to log to `sys.stdout` and terminate server startup (`sys.exit(1)`) if required configuration settings are missing.
* **`import json` (Line 4):** Standard JSON parsing. **Why:** Serializes and deserializes JSON-RPC 2.0 payloads for MCP communication and Server-Sent Events (SSE).
* **`import time` (Line 5):** Time functions. **Why:** Tracks token expiration timestamps to prevent unnecessary OAuth refresh requests.
* **`import logging` (Line 6):** Standard logging library. **Why:** Outputs structured logs to monitor incoming web requests, tool executions, and system errors.
* **`from dataclasses import dataclass` (Line 7):** Data container classes. **Why:** Simplifies data structure definitions (`Tool`, `CallToolResponse`) without writing verbose `__init__` boilerplate.
* **`from typing import ...` (Line 8):** Type hint annotations. **Why:** Ensures static type safety and improves code readability.
* **`from contextlib import asynccontextmanager` (Line 9):** Async context management utility. **Why:** Manages FastAPI lifespan initialization and cleanup tasks.
* **`from dotenv import load_dotenv` (Line 10):** Dotenv variable loader. **Why:** Loads configuration parameters from local `.env` files into environment variables.
* **`from fastapi import ...` (Lines 11–14):** Core web framework tools. **Why:** Hosts HTTP endpoints, handles CORS, streams real-time responses to the UI via `StreamingResponse`, and serves static HTML/JS files.
* **`from pydantic import BaseModel, Field` (Line 15):** Data validation library. **Why:** Validates incoming JSON payloads sent to the chat API endpoint.
* **`import msal` (Line 16):** Microsoft Authentication Library. **Why:** Handles OAuth 2.0 Client Credentials flow with Azure Entra ID to authenticate requests to Azure DevOps.
* **`import httpx` (Line 17):** Async HTTP client. **Why:** Makes asynchronous HTTP requests to remote MCP servers.
* **`from google import genai`, `from google.genai import types` (Lines 18–19):** Google Gemini AI SDK. **Why:** Drives agent reasoning, function calling, tool execution loops, and prompt processing.

---

## 2. Logging & Environment Configuration (Lines 21–31)

```python
21: # Configure structured logging
22: logging.basicConfig(
23:     level=logging.INFO,
24:     format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
25:     handlers=[logging.StreamHandler(sys.stdout)]
26: )
27: logger = logging.getLogger("azure-devops-agent-remote")
28: 
29: # Load environment variables
30: load_dotenv()
```

### Explanation & Rationale
* **Lines 22–26:** Configures global logger settings to print timestamps, log levels, logger names, and log messages directly to standard output.
* **Line 27:** Instantiates a dedicated logger instance named `"azure-devops-agent-remote"`.
* **Line 30:** Executes `load_dotenv()` to read key-value pairs from `.env` into environment memory before validating settings.

---

## 3. Startup Configuration Validation (Lines 32–60)

```python
32: # Configuration Validation Class
33: class AppConfig:
34:     def __init__(self) -> None:
35:         self.gemini_api_key: str = self._get_required_env("GEMINI_API_KEY")
36:         self.azure_devops_organization: str = os.getenv("AZURE_DEVOPS_ORGANIZATION", "Rapid-AI-Team")
37:         self.default_project: str = os.getenv("AZURE_DEVOPS_PROJECT", "Pulse")
38:         self.default_repo: str = os.getenv("AZURE_DEVOPS_REPOSITORY", "Pulse")
39:         self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
40:         self.port: int = int(os.getenv("PORT", "8199"))
41:         # Fix 12: Validate Entra credentials at startup so the server fails fast
42:         # rather than crashing mid-request when the first API call is made.
43:         self.entra_tenant_id: str = self._get_required_env("ENTRA_TENANT_ID")
44:         self.entra_client_id: str = self._get_required_env("ENTRA_CLIENT_ID")
45:         self.entra_client_secret: str = self._get_required_env("ENTRA_CLIENT_SECRET")
46: 
47:     def _get_required_env(self, key: str) -> str:
48:         val = os.getenv(key)
49:         if not val or "here" in val:
50:             logger.critical(f"Missing required environment variable: {key}")
51:             raise RuntimeError(f"Configuration Error: {key} must be defined in your .env file.")
52:         return val
53: 
54: try:
55:     config = AppConfig()
56: except RuntimeError as err:
57:     logger.critical(f"Server startup failed due to config errors: {err}")
58:     sys.exit(1)
```

### Explanation & Rationale
* **`AppConfig` (Lines 33–46):** Reads environment variables and stores application configuration settings (Gemini key, model, Azure organization defaults, port, and Entra ID credentials).
* **`_get_required_env` (Lines 47–52):** Helper function that checks if a required key exists and does not contain dummy placeholder text like `"here"`.
* **Fail-Fast Error Handling (Lines 54–58):** Instantiates `config` at file load time. If required credentials are missing, it prints a critical error log and halts execution via `sys.exit(1)`. **Why:** Ensures the server immediately stops at startup if misconfigured, preventing runtime crashes during user requests.

---

## 4. MCP Data Models (Lines 61–78)

```python
61: @dataclass
62: class Tool:
63:     name: str
64:     description: str
65:     inputSchema: dict
66: 
67: @dataclass
68: class ToolsResponse:
69:     tools: List[Tool]
70: 
71: @dataclass
72: class Content:
73:     text: str
74: 
75: @dataclass
76: class CallToolResponse:
77:     content: List[Content]
```

### Explanation & Rationale
* **`Tool` (Lines 61–65):** Holds tool metadata (`name`, `description`, `inputSchema`) fetched from the remote MCP server.
* **`ToolsResponse` (Lines 67–69):** Container wrapper for a list of available tools.
* **`Content` (Lines 71–73):** Represents text output blocks returned by tool executions.
* **`CallToolResponse` (Lines 75–78):** Wrapper containing tool output content objects. **Why:** Strongly types MCP objects for internal handling.

---

## 5. Microsoft Entra ID OAuth Authentication (Lines 79–135)

```python
79: # Fix 13: Use msal.SerializableTokenCache + asyncio.Lock instead of a plain
80: # global dict. The lock prevents concurrent requests from triggering duplicate
81: # token fetches when the cache is cold or the token has just expired.
82: _msal_token_cache = msal.SerializableTokenCache()
83: _token_lock = asyncio.Lock()
84: _token_expiry: float = 0.0
85: 
86: def format_auth_header(token: str) -> str:
87:     """
88:     Formats the token correctly as a Bearer token.
89:     """
90:     token_str = token.strip()
91:     if token_str.startswith("Bearer "):
92:         return token_str
93:     return f"Bearer {token_str}"
94: 
95: async def get_auth_token() -> str:
96:     """
97:     Acquires an authentication token for Azure DevOps using MSAL Client Credentials Flow.
98:     """
99:     global _token_expiry
100:     current_time = time.time()
101: 
102:     async with _token_lock:
103:         # Return cached token if still valid (with 60s buffer)
104:         cached = _msal_token_cache.find(msal.TokenCache.CredentialType.ACCESS_TOKEN)
105:         if cached and current_time < _token_expiry - 60:
106:             return cached[0]["secret"]
107: 
108:         authority = f"https://login.microsoftonline.com/{config.entra_tenant_id}"
109:         scope = ["https://mcp.dev.azure.com/.default"]
110: 
111:         logger.info(f"[MSAL] Acquiring new token for Entra tenant {config.entra_tenant_id}...")
112:         try:
113:             msal_app = msal.ConfidentialClientApplication(
114:                 config.entra_client_id,
115:                 authority=authority,
116:                 client_credential=config.entra_client_secret,
117:                 token_cache=_msal_token_cache
118:             )
119:             result = msal_app.acquire_token_for_client(scopes=scope)
120: 
121:             if "access_token" not in result:
122:                 err_msg = result.get("error_description") or result.get("error") or "Unknown OAuth error"
123:                 raise RuntimeError(err_msg)
124: 
125:             _token_expiry = current_time + result.get("expires_in", 3600)
126:             logger.info("[MSAL] Token successfully acquired via Client Credentials.")
127:             return result["access_token"]
128:         except Exception as e:
129:             logger.error(f"[MSAL ERROR] Failed to fetch token: {e}", exc_info=True)
130:             raise HTTPException(status_code=500, detail=f"OAuth Token Acquisition failed: {str(e)}")
```

### Explanation & Rationale
* **Token Caching & Mutex (Lines 82–84):** Initializes `_msal_token_cache` and an `asyncio.Lock()`. **Why:** Prevents race conditions where simultaneous HTTP requests trigger duplicate authentication calls to Azure Entra ID when tokens expire.
* **`format_auth_header` (Lines 86–93):** Ensures token headers strictly follow the `"Bearer <token>"` scheme required by Microsoft endpoints.
* **`get_auth_token` (Lines 95–134):** Performs OAuth 2.0 client credential token acquisition against `https://login.microsoftonline.com/<tenant_id>` requesting scope `https://mcp.dev.azure.com/.default`. Reuses cached tokens if valid for >60 seconds.

---

## 6. Remote MCP Client (Lines 136–226)

```python
136: class RemoteMCPClient:
137:     """
138:     Client class that implements JSON-RPC communication over HTTPS
139:     with dynamic OAuth Bearer token injection and error handling.
140:     """
141:     def __init__(self, remote_url: str, token: Optional[str] = None, default_headers: Optional[Dict[str, str]] = None) -> None:
142:         if not remote_url.startswith("http"):
143:             self.url = f"https://mcp.dev.azure.com/{remote_url}"
144:         else:
145:             self.url = remote_url
146: 
147:         self.token = token
148:         self.default_headers = default_headers or {}
149: 
150:     async def get_headers(self) -> Dict[str, str]:
151:         token = self.token or await get_auth_token()
152:         auth_header = format_auth_header(token)
153:             
154:         headers = {
155:             "Content-Type": "application/json",
156:             "Accept": "application/json, text/event-stream",
157:             "Authorization": auth_header
158:         }
159:         headers.update(self.default_headers)
160:         return headers
161: 
162:     async def list_tools(self) -> ToolsResponse:
163:         payload = {
164:             "jsonrpc": "2.0",
165:             "id": 1,
166:             "method": "tools/list",
167:             "params": {}
168:         }
169:         headers = await self.get_headers()
170:         async with httpx.AsyncClient() as client:
171:             response = await client.post(self.url, json=payload, headers=headers, timeout=60.0)
172:             if response.status_code != 200:
173:                 logger.error(f"Failed to list tools from remote server: HTTP {response.status_code}")
174:                 raise HTTPException(status_code=response.status_code, detail=f"Remote server error: {response.text}")
175:             
176:             data = response.text.strip()
177:             if data.startswith("event:"):
178:                 lines = data.split("\n")
179:                 data_line = next((l for l in lines if l.startswith("data: ")), None)
180:                 if data_line:
181:                     data = data_line[6:]
182:             
183:             res_json = json.loads(data)
184:             if "error" in res_json:
185:                 raise RuntimeError(f"RPC Error: {res_json['error']}")
186:             
187:             tools_list = []
188:             for t in res_json.get("result", {}).get("tools", []):
189:                 tools_list.append(Tool(t.get("name", ""), t.get("description", ""), t.get("inputSchema", {})))
190:             
191:             return ToolsResponse(tools_list)
192: 
193:     async def call_tool(self, name: str, arguments: Dict[str, Any]) -> CallToolResponse:
194:         payload = {
195:             "jsonrpc": "2.0",
196:             "id": 2,
197:             "method": "tools/call",
198:             "params": {
199:                 "name": name,
200:                 "arguments": arguments
201:             }
202:         }
203:         headers = await self.get_headers()
204:         async with httpx.AsyncClient() as client:
205:             response = await client.post(self.url, json=payload, headers=headers, timeout=60.0)
206:             if response.status_code != 200:
207:                 logger.error(f"Failed to execute tool '{name}': HTTP {response.status_code}")
208:                 raise HTTPException(status_code=response.status_code, detail=f"Remote execution error: {response.text}")
209:             
210:             data = response.text.strip()
211:             if data.startswith("event:"):
212:                 lines = data.split("\n")
213:                 data_line = next((l for l in lines if l.startswith("data: ")), None)
214:                 if data_line:
215:                     data = data_line[6:]
216:             
217:             res_json = json.loads(data)
218:             if "error" in res_json:
219:                 raise RuntimeError(f"RPC Error: {res_json['error']}")
220:             
221:             contents = []
222:             for item in res_json.get("result", {}).get("content", []):
223:                 contents.append(Content(item.get("text", "")))
224:             
225:             return CallToolResponse(contents)
```

### Explanation & Rationale
* **`RemoteMCPClient` (Lines 136–160):** Manages HTTPS connections to the remote Azure DevOps MCP server, dynamically attaching authentication headers.
* **`list_tools()` (Lines 162–191):** Constructs a JSON-RPC 2.0 `tools/list` payload, dispatches the HTTP POST request, handles SSE `data:` formatting if returned, parses the JSON response, and extracts tool definitions.
* **`call_tool()` (Lines 193–225):** Constructs a JSON-RPC 2.0 `tools/call` payload with specific arguments, calls the remote endpoint, extracts the content response, and returns a structured `CallToolResponse`.

---

## 7. Subagent Role Definitions (Lines 227–280)

```python
227: # Global subagent role mapping configurations
228: SUBAGENT_ROLES = {
229:     "DevOps Engineer": {
230:         "keywords": ["pipeline", "build", "run", "deploy", "release", "migration"],
231:         "prefixes": ["core_", "pipelines_", "advsec_", "search_"],
232:         "instruction": (
233:             "You are the DevOps Engineer subagent. Your focus is CI/CD, builds, pipelines, and releases. "
234:             "You only call tools related to build pipelines, log files, and migrations. "
235:             "Ensure build failures are diagnosed using log files."
236:         )
237:     },
238:     "QA Analyst": {
239:         "keywords": ["test", "suite", "qa", "plan", "case"],
240:         "prefixes": ["core_", "testplan_", "pipelines_", "search_"],
241:         "instruction": ( ... )
242:     },
243:     "Technical Writer": { ... },
244:     "Product Manager": { ... },
245:     "Software Developer": { ... },
246:     "General Assistant": { ... }
247: }
```

### Explanation & Rationale
* **Role Specialization (`SUBAGENT_ROLES`):** Categorizes tools into domain-specific persona profiles (`DevOps Engineer`, `QA Analyst`, `Technical Writer`, `Product Manager`, `Software Developer`, and `General Assistant`).
* **Why:** Passing dozens of tools to Gemini for every request consumes token quota and can degrade model reasoning. Categorizing tools into distinct roles filters the available tool list to only those necessary for the current task.

---

## 8. Configuration Reader (Lines 281–306)

```python
281: def get_remote_config() -> Tuple[str, Dict[str, str]]:
282:     local_dir = os.path.dirname(os.path.abspath(__file__))
283:     config_path = os.path.join(local_dir, "mcp_config.json")
284:     
285:     if not os.path.exists(config_path):
286:         logger.error(f"Local mcp_config.json configuration file not found at {config_path}")
287:         raise FileNotFoundError(f"Configuration file 'mcp_config.json' not found locally in {local_dir}")
288:         
289:     with open(config_path, "r", encoding="utf-8") as f:
290:         mcp_data = json.load(f)
291:         
292:     servers = mcp_data.get("mcpServers", {})
293:     if "azure-devops-remote" not in servers:
294:         logger.error("Configuration block 'azure-devops-remote' is missing from local mcp_config.json")
295:         raise KeyError("Invalid config: 'azure-devops-remote' block is required in mcp_config.json")
296:         
297:     remote_srv = servers["azure-devops-remote"]
298:     url = remote_srv.get("url")
299:     if not url:
300:         raise KeyError("Remote server configuration URL is missing from mcp_config.json")
301:         
302:     headers = remote_srv.get("headers", {})
303:     str_headers = {k: str(v) for k, v in headers.items()}
304:     
305:     return url, str_headers
```

### Explanation & Rationale
* **`get_remote_config()`:** Locates, parses, and validates `mcp_config.json`.
* **Why:** Dynamically sets up target remote endpoints and custom headers without hardcoding URLs directly inside python modules.

---

## 9. FastAPI Lifespan Manager & CORS Setup (Lines 307–344)

```python
307: @asynccontextmanager
308: async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
309:     """
310:     App Lifespan Manager: Pre-caches remote tool definitions at startup.
311:     """
312:     logger.info("Initializing persistent Remote MCP Client...")
313:     try:
314:         remote_url, mcp_headers = get_remote_config()
315:         
316:         # Instantiate remote client once and fetch all tool definitions
317:         mcp_session = RemoteMCPClient(remote_url, default_headers=mcp_headers)
318:         mcp_tools_resp = await mcp_session.list_tools()
319:         
320:         # Cache active session objects in app state
321:         app.state.mcp_session = mcp_session
322:         app.state.mcp_tools = mcp_tools_resp.tools
323:         
324:         logger.info(f"Persistent Remote MCP Client initialized successfully. Cached {len(app.state.mcp_tools)} tools.")
325:     except Exception as err:
326:         logger.critical(f"Failed to start remote MCP connection: {err}", exc_info=True)
327:         sys.exit(1)
328:         
329:     yield
330:     
331:     logger.info("Shutting down persistent Remote MCP Session...")
332: 
333: # Initialize app with lifespan manager
334: app = FastAPI(title="Azure DevOps Remote Agent Server", lifespan=lifespan)
335: 
336: # Allow CORS so our static HTML file can query the backend
337: app.add_middleware(
338:     CORSMiddleware,
339:     allow_origins=["*"],
340:     allow_credentials=True,
341:     allow_methods=["*"],
342:     allow_headers=["*"],
343: )
```

### Explanation & Rationale
* **`lifespan()` (Lines 307–332):** Initializes the `RemoteMCPClient` session when the server starts and fetches tool schemas via `list_tools()`. Stores the session and tools list in `app.state`. **Why:** Pre-caches tool definitions at startup so incoming user requests don't need to re-query the remote server for tool schemas on every chat turn.
* **CORS Middleware (Lines 336–343):** Enables Cross-Origin Resource Sharing (`CORSMiddleware`). **Why:** Allows browser-based UI frontends running on different origins/ports to interact with the backend API.

---

## 10. Subagent Routing & Tool Filtering (Lines 345–383)

```python
345: class ChatRequest(BaseModel):
346:     prompt: str = Field(..., description="The query sent by the user describing DevOps automation requests.")
347: 
348: 
349: def determine_subagent_role(prompt: str) -> Dict[str, str]:
350:     prompt_lower = prompt.lower()
351:     matched_roles = []
352: 
353:     for role_name, config_data in SUBAGENT_ROLES.items():
354:         if role_name == "General Assistant":
355:             continue
356:         if any(k in prompt_lower for k in config_data["keywords"]):
357:             matched_roles.append({
358:                 "name": role_name,
359:                 "instruction": config_data["instruction"]
360:             })
361: 
362:     if len(matched_roles) == 1:
363:         return matched_roles[0]
364:     general = SUBAGENT_ROLES["General Assistant"]
365:     return {"name": "General Assistant", "instruction": general["instruction"]}
366: 
367: 
368: def filter_tools_for_role(role_name: str, mcp_tools: List[Any]) -> List[types.Tool]:
369:     gemini_declarations = []
370:     role_config = SUBAGENT_ROLES.get(role_name, SUBAGENT_ROLES["General Assistant"])
371:     allowed = role_config["prefixes"]
372: 
373:     for tool in mcp_tools:
374:         if any(tool.name.startswith(p) or tool.name == p for p in allowed):
375:             schema = tool.inputSchema or {"type": "object", "properties": {}}
376:             gemini_declarations.append(types.FunctionDeclaration(
377:                 name=tool.name,
378:                 description=tool.description or f"Executes {tool.name}",
379:                 parameters_json_schema=schema
380:             ))
381: 
382:     return [types.Tool(function_declarations=gemini_declarations)]
```

### Explanation & Rationale
* **`ChatRequest` (Lines 345–346):** Pydantic input model validating user requests.
* **`determine_subagent_role()` (Lines 349–365):** Scans the prompt text for keywords (e.g., `"build"`, `"test"`, `"wiki"`, `"repo"`, `"story"`). If a single role matches, it routes to that specialized subagent; otherwise, it defaults to `"General Assistant"`.
* **`filter_tools_for_role()` (Lines 368–382):** Filters the tool list to match the subagent's allowed prefixes and maps them into Gemini SDK `types.FunctionDeclaration` schemas.

---

## 11. Autonomous Agent Loop (Lines 384–448)

```python
384: async def execute_agent_run(
385:     prompt: str,
386:     system_instruction: str,
387:     tools: List[types.Tool],
388:     mcp_session: RemoteMCPClient,
389:     max_loops: int = 40
390: ) -> str:
391:     gemini_client = genai.Client()
392:     contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
393:     loop_count = 0
394:     final_text = ""
395: 
396:     while loop_count < max_loops:
397:         if loop_count > 0:
398:             await asyncio.sleep(1)
399: 
400:         gen_config = types.GenerateContentConfig(
401:             tools=tools,
402:             automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
403:             system_instruction=system_instruction
404:         )
405: 
406:         response = gemini_client.models.generate_content(
407:             model=config.gemini_model,
408:             contents=contents,
409:             config=gen_config
410:         )
411: 
412:         final_text = ""
413:         if response.candidates and response.candidates[0].content.parts:
414:             for part in response.candidates[0].content.parts:
415:                 if getattr(part, "text", None):
416:                     final_text += part.text
417: 
418:         if not response.function_calls:
419:             break
420: 
421:         contents.append(response.candidates[0].content)
422:         tool_responses = []
423: 
424:         for call in response.function_calls:
425:             logger.info(f" -> TOOL: {call.name} | args: {call.args}")
426:             try:
427:                 tool_result = await mcp_session.call_tool(call.name, call.args)
428:                 result_text = "\n".join(
429:                     c.text for c in tool_result.content if getattr(c, "text", None)
430:                 ) if tool_result.content else ""
431: 
432:                 tool_responses.append(types.Part.from_function_response(
433:                     name=call.name, response={"result": result_text}
434:                 ))
435:             except Exception as tool_err:
436:                 logger.error(f" -> TOOL ERROR ({call.name}): {tool_err}")
437:                 tool_responses.append(types.Part.from_function_response(
438:                     name=call.name, response={"error": str(tool_err)}
439:                 ))
440: 
441:         contents.append(types.Content(role="tool", parts=tool_responses))
442:         loop_count += 1
443: 
444:     if loop_count >= max_loops and not final_text:
445:         final_text = "Reached maximum tool execution steps without a final response."
446: 
447:     return final_text
```

### Explanation & Rationale
* **`execute_agent_run()`:** Implements the agent execution loop:
  1. Sends prompt, history, system instructions, and filtered tool schemas to Gemini.
  2. Disables Gemini's default client-side automatic function calling (`disable=True`) so tool execution can be handled asynchronously through the remote MCP client.
  3. If Gemini emits function calls (`response.function_calls`), it executes those tools remotely using `mcp_session.call_tool()`.
  4. Appends tool results (`from_function_response`) to the conversation history and loops back to Gemini.
  5. Terminates when Gemini returns a text answer without requesting function calls, or when `max_loops` is reached.

---

## 12. Chat Streaming Endpoint (Lines 449–490)

```python
449: @app.post("/api/chat/stream")
450: async def chat_stream_endpoint(request: ChatRequest, req: Request) -> StreamingResponse:
451:     mcp_session = req.app.state.mcp_session
452:     mcp_tools = req.app.state.mcp_tools
453: 
454:     async def event_generator() -> AsyncGenerator[str, None]:
455:         try:
456:             logger.info(f"Incoming query: '{request.prompt[:80]}...'")
457:             yield f"data: {json.dumps({'type': 'status', 'message': 'Connected to Azure DevOps Remote MCP server.'})}\n\n"
458: 
459:             subagent = determine_subagent_role(request.prompt)
460:             gemini_tools = filter_tools_for_role(subagent["name"], mcp_tools)
461:             subagent_name = subagent["name"]
462: 
463:             yield f"data: {json.dumps({'type': 'subagent', 'name': subagent_name})}\n\n"
464:             yield f"data: {json.dumps({'type': 'status', 'message': f'Active Profile: {subagent_name}'})}\n\n"
465: 
466:             system_instruction = (
467:                 f"You are the {subagent['name']} subagent. {subagent['instruction']}\n"
468:                 "To conserve API quota, you MUST follow these constraints:\n"
469:                 f"1. The default project is '{config.default_project}' and the default repository is '{config.default_repo}'. ALWAYS assume these defaults. Do NOT query projects or repository list unless the user explicitly asks to list them or specifies a different project/repository.\n"
470:                 "2. Minimize tool calls. Only call tools that are absolutely necessary to answer the prompt.\n"
471:                 "3. If a tool call returns empty or fails, DO NOT retry it. Report the failure/empty state immediately to the user.\n"
472:                 "4. Call tools in parallel in a single turn whenever possible instead of running them sequentially across multiple turns.\n"
473:                 "5. Do not perform redundant queries (e.g. if you already listed branches, do not list them again).\n"
474:                 "6. Act fully autonomously. Never ask the user for confirmation, permission, or approval before executing writing or mutating actions (like creating/updating work items, updating team capacity, assigning iterations, creating branches, or writing wiki pages). Execute them immediately."
475:             )
476: 
477:             final_text = await execute_agent_run(
478:                 prompt=request.prompt,
479:                 system_instruction=system_instruction,
480:                 tools=gemini_tools,
481:                 mcp_session=mcp_session
482:             )
483:             yield f"data: {json.dumps({'type': 'final', 'message': final_text})}\n\n"
484: 
485:         except Exception as err:
486:             logger.error(f"Execution failed: {err}", exc_info=True)
487:             yield f"data: {json.dumps({'type': 'error', 'message': f'Error during execution: {str(err)}'})}\n\n"
488: 
489:     return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### Explanation & Rationale
* **`chat_stream_endpoint`:** The main HTTP endpoint for chat requests (`/api/chat/stream`).
* **Server-Sent Events (SSE):** Returns a `StreamingResponse` using `media_type="text/event-stream"`.
* **Flow:**
  1. Emits connection confirmation status event.
  2. Selects subagent role and streams active profile notification event.
  3. Prepares default parameters (project, repository, efficiency constraints) in the system instruction prompt.
  4. Runs `execute_agent_run()`.
  5. Emits final output text to the web frontend.

---

## 13. Static File Hosting & Server Entry Point (Lines 491–498)

```python
491: # Serve static HTML/JS frontend from the current directory
492: current_dir = os.path.dirname(os.path.abspath(__file__))
493: app.mount("/", StaticFiles(directory=current_dir, html=True), name="static")
494: 
495: if __name__ == "__main__":
496:     import uvicorn
497:     logger.info(f"Starting Remote Uvicorn server on port {config.port}...")
498:     uvicorn.run(app, host="127.0.0.1", port=config.port)
```

### Explanation & Rationale
* **`app.mount("/", ...)` (Lines 491–493):** Serves static web frontend files (`index.html`, `script.js`, `styles.css`) directly from the server directory.
* **`uvicorn.run(...)` (Lines 495–498):** Starts the Uvicorn ASGI web server on `127.0.0.1` at the configured port (default `8199`).

