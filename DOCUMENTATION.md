# Azure DevOps MCP Integration Gateway — Detailed Technical Reference Index

Welcome! This index document provides a comprehensive, production-grade guide to understanding, configuring, and maintaining the Azure DevOps Model Context Protocol (MCP) integration workspace. It coordinates the architecture of both the **Local** and **Remote** application services.

---

## 1. Core Architectural Concepts

### What is the Model Context Protocol (MCP)?
The standard Model Context Protocol allows Large Language Models (like Gemini) to securely communicate with external system REST APIs through intermediate server-hosted tools. This app binds tool definitions with Gemini's content generation loops, allowing users to interact with Azure DevOps repositories, work item boards, test runs, wikis, and pipelines using natural language.

### Dual-Architecture Model

```
                                  ┌────────────────────────┐
                                  │       USER CHAT        │
                                  └───────────┬────────────┘
                                              │ (HTTP POST Stream)
                                              ▼
                                 ┌─────────────────────────┐
                                 │     FastAPI Server      │
                                 │   (Local: Port 8180)    │
                                 │   (Remote: Port 8199)   │
                                 └────────────┬────────────┘
                                              │ (JSON-RPC)
                                              ▼
                    ┌─────────────────────────┴─────────────────────────┐
                    │                                                   │
                    ▼                                                   ▼
       ┌─────────────────────────┐                         ┌─────────────────────────┐
       │   Local Stdio Gateway   │                         │  Remote Gateway Server  │
       │  (npx subprocess app)   │                         │ (mcp.dev.azure.com/org) │
       ├─────────────────────────┤                         ├─────────────────────────┤
       │ Auth: PAT (Base64)      │                         │ Auth: Entra ID Token    │
       │ Tools: 90 available     │                         │ Tools: 40 available     │
       └─────────────────────────┘                         └─────────────────────────┘
```

1. **Local MCP App (`local-mcp-app/`)**:
   * **Authentication**: Uses a **Personal Access Token (PAT)** generated in the Azure DevOps user profile settings.
   * **Connection**: Launches the local Node-based `@azure-devops/mcp` server as a persistent stdio subprocess.
   * **Scope**: Evaluates and exposes all **90 local tools** available on the npm module, including Iterations, Capacities, WIQL Query execution, and Test Plans.
   * **Technical Documentation**: See details in [local-mcp-app/DOCUMENTATION.md](file:///c:/Users/2862390/Desktop/Azure%20Devops%20MCP/local-mcp-app/DOCUMENTATION.md).

2. **Remote MCP App (`remote-mcp-app/`)**:
   * **Authentication**: Uses an **Entra ID App Registration (Client Credentials Flow)** with Tenant ID, Client ID, and Client Secret.
   * **Connection**: Communicates directly over HTTPS with the official Azure DevOps Remote MCP Gateway (`https://mcp.dev.azure.com/{org}`).
   * **Scope**: Exposes a consolidated set of **40 remote tools** optimized for secure pipelines, repository branch/file checkouts, wikis, and work items.
   * **Technical Documentation**: See details in [remote-mcp-app/DOCUMENTATION.md](file:///c:/Users/2862390/Desktop/Azure%20Devops%20MCP/remote-mcp-app/DOCUMENTATION.md).

---

## 2. Directory & Workspace Map

The workspace contains the following layout and reference sheets:

* **[local_mcp_tools.txt](file:///c:/Users/2862390/Desktop/Azure%20Devops%20MCP/local_mcp_tools.txt)**: A flat reference file listing the exact names of all 90 tools loaded by the local stdio server.
* **[remote_mcp_tools.txt](file:///c:/Users/2862390/Desktop/Azure%20Devops%20MCP/remote_mcp_tools.txt)**: A flat reference file listing all 40 tools and descriptions exposed by the remote gateway.
* **[local-mcp-app/](file:///c:/Users/2862390/Desktop/Azure%20Devops%20MCP/local-mcp-app/)**:
  * `server.py`: Python FastAPI backend. Uses standard `ClientSession` and `stdio_client` to communicate with the subprocess.
  * `mcp_config.json`: Standard schema defining local stdio startup commands.
  * `index.html` & `styles.css`: Emoji-free professional blue/white chat frontend page.
* **[remote-mcp-app/](file:///c:/Users/2862390/Desktop/Azure%20Devops%20MCP/remote-mcp-app/)**:
  * `server.py`: Python FastAPI backend. Houses the MSAL Client Credentials flow, token caching dict (`_token_cache`), and custom JSON-RPC `RemoteMCPClient`.
  * `mcp_config.json`: Configuration defining remote HTTPS organization URL.
  * `index.html` & `styles.css`: High-end corporate chat panel.

---

## 3. Operational Lifespan & Subagent Logic

Both backends share core execution modules for handling user queries safely:

1. **FastAPI Lifespan Caching**: Pre-caches tool schema definitions at server start. This keeps subsequent chat stream request-to-token latencies under 100ms.
2. **Subagent Role Routing**: Dynamically categorizes prompts into 6 distinct profiles:
   * *DevOps Engineer*: Pipelines and releases.
   * *QA Analyst*: Testing suites and plans.
   * *Technical Writer*: Wikis and documentation.
   * *Product Manager*: Work items and boards.
   * *Software Developer*: Repositories and branches.
   * *General Assistant*: Fallback with all tools.
3. **Manual Tool Execution Loop**: Forces manual loop tracking on Gemini with automatic throttling sleep (`4.5 seconds` per turn) to respect API quota boundaries.
4. **Data Truncation Guard**: Automatically intercepts all tool output payloads and truncates content to **3,000 characters** to protect LLM context length limit.

---

## 4. Launch Instructions

To launch the servers on your host machine:

### 1. Local App Server
```powershell
# Navigate to workspace
cd "c:\Users\2862390\Desktop\Azure Devops MCP"
# Launch local server (Default port: 8180)
python local-mcp-app/server.py
```
Open **[http://127.0.0.1:8180](http://127.0.0.1:8180)** in your web browser.

### 2. Remote App Server
```powershell
# Navigate to workspace
cd "c:\Users\2862390\Desktop\Azure Devops MCP"
# Launch remote server (Default port: 8199)
python remote-mcp-app/server.py
```
Open **[http://127.0.0.1:8199](http://127.0.0.1:8199)** (or the port specified in `.env`) in your web browser.
