# Detailed Line-by-Line Explanation of Local `server.py`

This document provides a line-by-line breakdown of [server.py](file:///c:/Users/2862390/Desktop/Azure%20Devops%20MCP/local-mcp-app/server.py) in the **local-mcp-app** directory. It explains **what** each line of code does, **why** it was written, and how it differs from the remote version (specifically using `stdio` local subprocesses and Personal Access Tokens instead of HTTP JSON-RPC and MSAL Entra ID OAuth).

---

## Table of Contents
1. [Imports & Dependencies (Lines 1–18)](#1-imports--dependencies-lines-118)
2. [Structured Logging & Dotenv Loading (Lines 19–29)](#2-structured-logging--dotenv-loading-lines-1929)
3. [Configuration & Environment Validation (Lines 30–53)](#3-configuration--environment-validation-lines-3053)
4. [Subagent Role Persona Definitions (Lines 54–106)](#4-subagent-role-persona-definitions-lines-54106)
5. [Local Stdio Subprocess Configuration (Lines 107–137)](#5-local-stdio-subprocess-configuration-lines-107137)
6. [FastAPI Lifespan Manager & CORS Setup (Lines 138–186)](#6-fastapi-lifespan-manager--cors-setup-lines-138186)
7. [Subagent Persona Routing & Tool Filtering (Lines 187–225)](#7-subagent-persona-routing--tool-filtering-lines-187225)
8. [Autonomous Agent Execution Loop (Lines 226–291)](#8-autonomous-agent-execution-loop-lines-226291)
9. [Chat Streaming Endpoint with SSE (Lines 292–333)](#9-chat-streaming-endpoint-with-sse-lines-292333)
10. [Build Doctor Diagnostics & Webhook Listener (Lines 334–386)](#10-build-doctor-diagnostics--webhook-listener-lines-334386)
11. [Static File Hosting & Local Server Launcher (Lines 387–395)](#11-static-file-hosting--local-server-launcher-lines-387395)

---

## 1. Imports & Dependencies (Lines 1–18)

```python
1: import asyncio
2: import os
3: import sys
4: import json
5: import logging
6: from typing import Dict, List, Any, AsyncGenerator, Optional
7: from contextlib import asynccontextmanager, AsyncExitStack
8: from dotenv import load_dotenv
9: from fastapi import FastAPI, HTTPException, Request
10: from fastapi.middleware.cors import CORSMiddleware
11: from fastapi.staticfiles import StaticFiles
12: from fastapi.responses import StreamingResponse
13: from pydantic import BaseModel, Field
14: from google import genai
15: from google.genai import types
16: from mcp import ClientSession, StdioServerParameters
17: from mcp.client.stdio import stdio_client
```

### Explanation & Rationale
* **`import asyncio` (Line 1):** Provides asynchronous primitives for handling background tasks and non-blocking I/O operations.
* **`import os` (Line 2):** Performs operating system operations (reading environment variables and building absolute directory paths).
* **`import sys` (Line 3):** Accesses system-level parameters (e.g., standard output stream for logging and terminating process startup on invalid configurations via `sys.exit(1)`).
* **`import json` (Line 4):** Standard JSON parsing and serialization utility for formatting output messages.
* **`import logging` (Line 5):** Handles structured logging across the application.
* **`from typing import ...` (Line 6):** Type annotations (`Dict`, `List`, `AsyncGenerator`, etc.) for static type checking.
* **`from contextlib import asynccontextmanager, AsyncExitStack` (Line 7):**
  * `asynccontextmanager`: Decorator used for FastAPI application lifecycle management (`lifespan`).
  * `AsyncExitStack`: Manages multiple asynchronous context managers (such as sub-processes, streams, and sessions) to ensure clean initialization and tear-down.
* **`from dotenv import load_dotenv` (Line 8):** Reads local environment variables from `.env`.
* **`from fastapi import ...` (Lines 9–13):** Core web application framework (`FastAPI`, web request handlers, CORS settings, static file hosting, and SSE streaming responses).
* **`from google import genai`, `from google.genai import types` (Lines 14–15):** Official Google Gemini AI SDK for LLM interactions and function calling.
* **`from mcp import ClientSession, StdioServerParameters` & `from mcp.client.stdio import stdio_client` (Lines 16–17):** Python MCP SDK tools for launching and managing a **local stdio (Standard Input/Output) child process**. **Why:** In contrast to the remote server which calls HTTP JSON-RPC endpoints over HTTPS, the local server spawns a local MCP server process (e.g., via `npx @azure-devops/mcp`) and communicates using standard input/output streams.

---

## 2. Structured Logging & Dotenv Loading (Lines 19–29)

```python
19: # Configure structured logging
20: logging.basicConfig(
21:     level=logging.INFO,
22:     format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
23:     handlers=[logging.StreamHandler(sys.stdout)]
24: )
25: logger = logging.getLogger("azure-devops-agent-local")
26: 
27: # Load environment variables
28: load_dotenv()
```

### Explanation & Rationale
* **Lines 20–25:** Sets up global structured logging to output formatted entries (`TIMESTAMP [LEVEL] LOGGER: MESSAGE`) to standard output. Creates a dedicated logger named `"azure-devops-agent-local"`.
* **Line 28:** Calls `load_dotenv()` to populate `os.environ` from `.env`.

---

## 3. Configuration & Environment Validation (Lines 30–53)

```python
30: # Configuration Validation Class
31: class AppConfig:
32:     def __init__(self) -> None:
33:         self.gemini_api_key: str = self._get_required_env("GEMINI_API_KEY")
34:         self.azure_devops_pat: str = self._get_required_env("AZURE_DEVOPS_PAT")
35:         self.organization: str = os.getenv("AZURE_DEVOPS_ORGANIZATION", "Rapid-AI-Team")
36:         self.default_project: str = os.getenv("AZURE_DEVOPS_PROJECT", "Pulse")
37:         self.default_repo: str = os.getenv("AZURE_DEVOPS_REPOSITORY", "Pulse")
38:         self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
39:         self.port: int = int(os.getenv("PORT", "8180"))
40: 
41:     def _get_required_env(self, key: str) -> str:
42:         val = os.getenv(key)
43:         if not val:
44:             logger.critical(f"Missing required environment variable: {key}")
45:             raise RuntimeError(f"Configuration Error: {key} must be defined in your .env file.")
46:         return val
47: 
48: try:
49:     config = AppConfig()
50: except RuntimeError as err:
51:     logger.critical(f"Server startup failed due to config errors: {err}")
52:     sys.exit(1)
```

### Explanation & Rationale
* **`AppConfig` (Lines 31–46):** Reads environment variables specifically tailored for local operation:
  * `gemini_api_key`: Reads `GEMINI_API_KEY`.
  * `azure_devops_pat`: Reads `AZURE_DEVOPS_PAT` (Personal Access Token). **Why:** Local MCP servers authenticate against Azure DevOps using PATs passed down through environment variables.
  * Default organization, project, repository, Gemini model, and local port (`8180`).
* **Fail-Fast Mechanics (Lines 48–52):** Validates required keys immediately at file evaluation. Halts process execution if configuration parameters are missing.

---

## 4. Subagent Role Persona Definitions (Lines 54–106)

```python
54: # Global subagent role mapping configurations
55: SUBAGENT_ROLES = {
56:     "DevOps Engineer": {
57:         "keywords": ["pipeline", "build", "run", "deploy", "release", "migration"],
58:         "prefixes": ["core_", "pipelines_", "advsec_", "search_"],
59:         "instruction": ( ... )
60:     },
61:     "QA Analyst": { ... },
62:     "Technical Writer": { ... },
63:     "Product Manager": { ... },
64:     "Software Developer": { ... },
65:     "General Assistant": { ... }
66: }
```

### Explanation & Rationale
* **Lines 54–106:** Defines role configurations for specialized personas (`DevOps Engineer`, `QA Analyst`, `Technical Writer`, `Product Manager`, `Software Developer`, `General Assistant`).
* **Why:** Limits tool declarations sent to Gemini based on the user request, preserving LLM prompt context windows and improving tool accuracy.

---

## 5. Local Stdio Subprocess Configuration (Lines 107–137)

```python
108: def get_local_stdio_params() -> StdioServerParameters:
109:     local_dir = os.path.dirname(os.path.abspath(__file__))
110:     config_path = os.path.join(local_dir, "mcp_config.json")
111:     
112:     if not os.path.exists(config_path):
113:         logger.error(f"Local mcp_config.json configuration file not found at {config_path}")
114:         raise FileNotFoundError(f"Configuration file 'mcp_config.json' not found locally in {local_dir}")
115:         
116:     with open(config_path, "r", encoding="utf-8") as f:
117:         mcp_data = json.load(f)
118:         
119:     servers = mcp_data.get("mcpServers", {})
120:     if "azure-devops" not in servers:
121:         logger.error("Configuration block 'azure-devops' is missing from local mcp_config.json")
122:         raise KeyError("Invalid config: 'azure-devops' server block is required in mcp_config.json")
123:         
124:     server_info = servers["azure-devops"]
125:     command = server_info.get("command", "npx")
126:     args = server_info.get("args", [])
127:     
128:     env_vars = dict(os.environ)
129:     env_vars["ADO_MCP_AUTH_TOKEN"] = config.azure_devops_pat
130:     
131:     logger.info(f"Loaded local Stdio connection from config. Command: {command}, Args: {args}")
132:     return StdioServerParameters(
133:         command=command,
134:         args=args,
135:         env=env_vars
136:     )
```

### Explanation & Rationale
* **`get_local_stdio_params()` (Lines 108–136):** Reads the local `mcp_config.json` configuration file, extracts the command (e.g., `npx`), command-line arguments (e.g., `-y @azure-devops/mcp`), and constructs `StdioServerParameters`.
* **Injecting PAT (Line 129):** Copies current system environment variables and sets `ADO_MCP_AUTH_TOKEN = config.azure_devops_pat`. **Why:** Passes the Personal Access Token to the child node process for authenticating API operations.

---

## 6. FastAPI Lifespan Manager & CORS Setup (Lines 138–186)

```python
138: @asynccontextmanager
139: async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
140:     """
141:     App Lifespan Manager: Initializes a Persistent Stdio Subprocess session 
142:     and list tools once at startup, caching them for sub-second route access.
143:     Cleanly exits the stack on app shutdown.
144:     """
145:     logger.info("Initializing persistent Local MCP Session...")
146:     exit_stack = AsyncExitStack()
147:     try:
148:         server_params = get_local_stdio_params()
149:         
150:         # Enter stdio client subprocess context
151:         read_stream, write_stream = await exit_stack.enter_async_context(stdio_client(server_params))
152:         # Enter ClientSession context
153:         mcp_session = await exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
154:         
155:         await mcp_session.initialize()
156:         mcp_tools_resp = await mcp_session.list_tools()
157:         
158:         # Cache active session objects in app state
159:         app.state.mcp_session = mcp_session
160:         app.state.mcp_tools = mcp_tools_resp.tools
161:         app.state.exit_stack = exit_stack
162:         
163:         logger.info(f"Persistent Local MCP Session initialized successfully. Cached {len(app.state.mcp_tools)} tools.")
164:     except Exception as err:
165:         logger.critical(f"Failed to start local MCP subprocess: {err}", exc_info=True)
166:         await exit_stack.aclose()
167:         sys.exit(1)
168:         
169:     yield
170:     
171:     logger.info("Shutting down persistent Local MCP Session...")
172:     await exit_stack.aclose()
173:     logger.info("Local MCP Session shutdown completed.")
```

### Explanation & Rationale
* **`AsyncExitStack` & `stdio_client` (Lines 146–154):** Spawns the MCP subprocess using `stdio_client` and binds input/output read-write streams into an active `ClientSession`.
* **Persistent Subprocess Lifecycle:** Keeps the child process running continuously during the server's lifecycle, pre-caching tool definitions in `app.state.mcp_tools`. **Why:** Spawning node/npx sub-processes on every chat request adds high latency. Running a single persistent stdio session provides fast response times.
* **Tear-Down (`await exit_stack.aclose()`):** Automatically terminates the subprocess gracefully when the FastAPI web server shuts down.

---

## 7. Subagent Persona Routing & Tool Filtering (Lines 187–225)

```python
187: class ChatRequest(BaseModel):
188:     prompt: str = Field(..., description="The query sent by the user describing DevOps automation requests.")
189: 
190: 
191: def determine_subagent_role(prompt: str) -> Dict[str, str]:
192:     prompt_lower = prompt.lower()
193:     matched_roles = []
194: 
195:     for role_name, config_data in SUBAGENT_ROLES.items():
196:         if role_name == "General Assistant":
197:             continue
198:         if any(k in prompt_lower for k in config_data["keywords"]):
199:             matched_roles.append({
200:                 "name": role_name,
201:                 "instruction": config_data["instruction"]
202:             })
203: 
204:     if len(matched_roles) == 1:
205:         return matched_roles[0]
206:     general = SUBAGENT_ROLES["General Assistant"]
207:     return {"name": "General Assistant", "instruction": general["instruction"]}
208: 
209: 
210: def filter_tools_for_role(role_name: str, mcp_tools: List[Any]) -> List[types.Tool]:
211:     gemini_declarations = []
212:     role_config = SUBAGENT_ROLES.get(role_name, SUBAGENT_ROLES["General Assistant"])
213:     allowed = role_config["prefixes"]
214: 
215:     for tool in mcp_tools:
216:         if any(tool.name.startswith(p) or tool.name == p for p in allowed):
217:             schema = tool.inputSchema or {"type": "object", "properties": {}}
218:             gemini_declarations.append(types.FunctionDeclaration(
219:                 name=tool.name,
220:                 description=tool.description or f"Executes {tool.name}",
221:                 parameters_json_schema=schema
222:             ))
223: 
224:     return [types.Tool(function_declarations=gemini_declarations)]
```

### Explanation & Rationale
* **`determine_subagent_role()` (Lines 191–207):** Evaluates the user prompt keywords against subagent definitions to select the matching subagent persona.
* **`filter_tools_for_role()` (Lines 210–224):** Filters tools retrieved from the local MCP stdio server to match the chosen subagent's allowed prefixes, wrapping them into Gemini SDK function declarations.

---

## 8. Autonomous Agent Execution Loop (Lines 226–291)

```python
227: async def execute_agent_run(
228:     prompt: str,
229:     system_instruction: str,
230:     tools: List[types.Tool],
231:     mcp_session: ClientSession,
232:     max_loops: int = 40
233: ) -> str:
234:     gemini_client = genai.Client()
235:     contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
236:     loop_count = 0
237:     final_text = ""
238: 
239:     while loop_count < max_loops:
240:         if loop_count > 0:
241:             await asyncio.sleep(1)
242: 
243:         gen_config = types.GenerateContentConfig(
244:             tools=tools,
245:             automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
246:             system_instruction=system_instruction
247:         )
248: 
249:         response = gemini_client.models.generate_content(
250:             model=config.gemini_model,
251:             contents=contents,
252:             config=gen_config
253:         )
254: 
255:         final_text = ""
256:         if response.candidates and response.candidates[0].content.parts:
257:             for part in response.candidates[0].content.parts:
258:                 if getattr(part, "text", None):
259:                     final_text += part.text
260: 
261:         if not response.function_calls:
262:             break
263: 
264:         contents.append(response.candidates[0].content)
265:         tool_responses = []
266: 
267:         for call in response.function_calls:
268:             logger.info(f" -> TOOL: {call.name} | args: {call.args}")
269:             try:
270:                 tool_result = await mcp_session.call_tool(call.name, call.args)
271:                 result_text = "\n".join(
272:                     c.text for c in tool_result.content if getattr(c, "text", None)
273:                 ) if tool_result.content else ""
274: 
275:                 tool_responses.append(types.Part.from_function_response(
276:                     name=call.name, response={"result": result_text}
277:                 ))
278:             except Exception as tool_err:
279:                 logger.error(f" -> TOOL ERROR ({call.name}): {tool_err}")
280:                 tool_responses.append(types.Part.from_function_response(
281:                     name=call.name, response={"error": str(tool_err)}
282:                 ))
283: 
284:         contents.append(types.Content(role="tool", parts=tool_responses))
285:         loop_count += 1
286: 
287:     if loop_count >= max_loops and not final_text:
288:         final_text = "Reached maximum tool execution steps without a final response."
289: 
290:     return final_text
```

### Explanation & Rationale
* **`execute_agent_run()` (Lines 227–290):** Autonomous loop that manages interaction between Gemini and the local MCP stdio session:
  1. Requests completions from Gemini while disabling SDK automatic function calling (`disable=True`).
  2. Intercepts requested function calls (`response.function_calls`).
  3. Executes functions over the local stdio channel using `await mcp_session.call_tool(call.name, call.args)`.
  4. Returns tool execution outputs back to Gemini until Gemini outputs a text answer without tool requests.

---

## 9. Chat Streaming Endpoint with SSE (Lines 292–333)

```python
292: @app.post("/api/chat/stream")
293: async def chat_stream_endpoint(request: ChatRequest, req: Request) -> StreamingResponse:
294:     mcp_session = req.app.state.mcp_session
295:     mcp_tools = req.app.state.mcp_tools
296: 
297:     async def event_generator() -> AsyncGenerator[str, None]:
298:         try:
299:             logger.info(f"Incoming query: '{request.prompt[:80]}...'")
300:             yield f"data: {json.dumps({'type': 'status', 'message': 'Connected to Azure DevOps MCP server.'})}\n\n"
301: 
302:             subagent = determine_subagent_role(request.prompt)
303:             gemini_tools = filter_tools_for_role(subagent["name"], mcp_tools)
304:             subagent_name = subagent["name"]
305: 
306:             yield f"data: {json.dumps({'type': 'subagent', 'name': subagent_name})}\n\n"
307:             yield f"data: {json.dumps({'type': 'status', 'message': f'Active Profile: {subagent_name}'})}\n\n"
308: 
309:             system_instruction = ( ... )
310: 
311:             final_text = await execute_agent_run(
312:                 prompt=request.prompt,
313:                 system_instruction=system_instruction,
314:                 tools=gemini_tools,
315:                 mcp_session=mcp_session
316:             )
317:             yield f"data: {json.dumps({'type': 'final', 'message': final_text})}\n\n"
318: 
319:         except Exception as err:
320:             logger.error(f"Execution failed: {err}", exc_info=True)
321:             yield f"data: {json.dumps({'type': 'error', 'message': f'Error during execution: {str(err)}'})}\n\n"
322: 
323:     return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### Explanation & Rationale
* **`chat_stream_endpoint` (Lines 292–333):** HTTP POST endpoint returning Server-Sent Events (`text/event-stream`).
* **Real-Time Feeds:** Yields connection status messages, active subagent profile notifications, and the final response text back to the browser user interface.

---

## 10. Static File Hosting & Local Server Launcher (Lines 387–395)

```python
387: # Serve static HTML/JS frontend from the current directory
388: current_dir = os.path.dirname(os.path.abspath(__file__))
389: app.mount("/", StaticFiles(directory=current_dir, html=True), name="static")
390: 
391: if __name__ == "__main__":
392:     import uvicorn
393:     logger.info(f"Starting Local Uvicorn server on port {config.port}...")
394:     uvicorn.run(app, host="127.0.0.1", port=config.port)
```

### Explanation & Rationale
* **`app.mount("/", ...)` (Lines 388–389):** Serves local frontend assets (`index.html`, `script.js`, `styles.css`) directly from the local directory.
* **`uvicorn.run(...)` (Lines 391–394):** Launches Uvicorn listening locally on `127.0.0.1` at port `8180`.
