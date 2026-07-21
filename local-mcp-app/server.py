import asyncio
import os
import sys
import json
import logging
from typing import Dict, List, Any, AsyncGenerator, Optional, Callable, Awaitable
from contextlib import asynccontextmanager, AsyncExitStack
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("azure-devops-agent-local")

# Load environment variables
load_dotenv()

# Configuration Validation Class
class AppConfig:
    def __init__(self) -> None:
        self.gemini_api_key: str = self._get_required_env("GEMINI_API_KEY")
        self.azure_devops_pat: str = self._get_required_env("AZURE_DEVOPS_PAT")
        self.organization: str = os.getenv("AZURE_DEVOPS_ORGANIZATION", "Rapid-AI-Team")
        self.default_project: str = os.getenv("AZURE_DEVOPS_PROJECT", "Pulse")
        self.default_repo: str = os.getenv("AZURE_DEVOPS_REPOSITORY", "Pulse")
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
        self.port: int = int(os.getenv("PORT", "8180"))

    def _get_required_env(self, key: str) -> str:
        val = os.getenv(key)
        if not val:
            logger.critical(f"Missing required environment variable: {key}")
            raise RuntimeError(f"Configuration Error: {key} must be defined in your .env file.")
        return val

try:
    config = AppConfig()
except RuntimeError as err:
    logger.critical(f"Server startup failed due to config errors: {err}")
    sys.exit(1)

# Global subagent role mapping configurations
SUBAGENT_ROLES = {
    "DevOps Engineer": {
        "keywords": ["pipeline", "build", "run", "deploy", "release", "migration"],
        "prefixes": ["core_", "pipelines_", "advsec_", "search_"],
        "instruction": (
            "You are the DevOps Engineer subagent. Your focus is CI/CD, builds, pipelines, and releases. "
            "You only call tools related to build pipelines, log files, and migrations. "
            "Ensure build failures are diagnosed using log files."
        )
    },
    "QA Analyst": {
        "keywords": ["test", "suite", "qa", "plan", "case"],
        "prefixes": ["core_", "testplan_", "pipelines_", "search_"],
        "instruction": (
            "You are the QA Analyst subagent. Your focus is testing, test cases, test suites, and test plans. "
            "You verify requirements and report test results. Minimize all other tool usage."
        )
    },
    "Technical Writer": {
        "keywords": ["wiki", "documentation", "page"],
        "prefixes": ["core_", "wiki_", "search_"],
        "instruction": (
            "You are the Technical Writer subagent. Your focus is documenting features, searching wikis, "
            "and writing high-quality Markdown documentation in wiki pages."
        )
    },
    "Product Manager": {
        "keywords": ["work item", "task", "bug", "story", "epic", "issue", "backlog", "query", "discussion", "comment", "link", "capacity", "sprint", "iteration", "board", "velocity", "assign", "create item", "add item", "new item", "feature"],
        "prefixes": ["core_", "wit_", "work_", "search_"],
        "instruction": (
            "You are the Product Manager subagent. Your focus is backlogs, iteration sprints, capacity, work items, and descriptions. "
            "You coordinate requirements and update work items on the Azure Board."
        )
    },
    "Software Developer": {
        "keywords": ["repo", "repository", "branch", "commit", "pull request", "pr", "merge", "file", "diff", "code review", "clone", "push", "git"],
        "prefixes": ["core_", "repo_", "wit_", "search_"],
        "instruction": (
            "You are the Software Developer subagent. Your focus is code repositories, branches, pull requests, files, and git commits. "
            "You review diffs, browse files, and check branch statuses."
        )
    },
    "General Assistant": {
        "keywords": [],
        "prefixes": ["core_", "wit_", "work_", "repo_", "pipelines_", "wiki_", "testplan_", "advsec_", "search_"],
        "instruction": (
            "You are a general Azure DevOps assistant. You have access to all available tools across "
            "work items, repositories, pipelines, wikis, test plans, and project management. "
            "Choose the most appropriate tools to answer the user's request accurately."
        )
    }
}

def get_local_stdio_params() -> StdioServerParameters:
    local_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(local_dir, "mcp_config.json")
    
    if not os.path.exists(config_path):
        logger.error(f"Local mcp_config.json configuration file not found at {config_path}")
        raise FileNotFoundError(f"Configuration file 'mcp_config.json' not found locally in {local_dir}")
        
    with open(config_path, "r", encoding="utf-8") as f:
        mcp_data = json.load(f)
        
    servers = mcp_data.get("mcpServers", {})
    if "azure-devops" not in servers:
        logger.error("Configuration block 'azure-devops' is missing from local mcp_config.json")
        raise KeyError("Invalid config: 'azure-devops' server block is required in mcp_config.json")
        
    server_info = servers["azure-devops"]
    command = server_info.get("command", "npx")
    args = server_info.get("args", [])
    
    env_vars = dict(os.environ)
    env_vars["ADO_MCP_AUTH_TOKEN"] = config.azure_devops_pat
    
    logger.info(f"Loaded local Stdio connection from config. Command: {command}, Args: {args}")
    return StdioServerParameters(
        command=command,
        args=args,
        env=env_vars
    )

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    App Lifespan Manager: Initializes a Persistent Stdio Subprocess session 
    and list tools once at startup, caching them for sub-second route access.
    Cleanly exits the stack on app shutdown.
    """
    logger.info("Initializing persistent Local MCP Session...")
    exit_stack = AsyncExitStack()
    try:
        server_params = get_local_stdio_params()
        
        # Enter stdio client subprocess context
        read_stream, write_stream = await exit_stack.enter_async_context(stdio_client(server_params))
        # Enter ClientSession context
        mcp_session = await exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
        
        await mcp_session.initialize()
        mcp_tools_resp = await mcp_session.list_tools()
        
        # Cache active session objects in app state
        app.state.mcp_session = mcp_session
        app.state.mcp_tools = mcp_tools_resp.tools
        app.state.exit_stack = exit_stack
        
        logger.info(f"Persistent Local MCP Session initialized successfully. Cached {len(app.state.mcp_tools)} tools.")
    except Exception as err:
        logger.critical(f"Failed to start local MCP subprocess: {err}", exc_info=True)
        await exit_stack.aclose()
        sys.exit(1)
        
    yield
    
    logger.info("Shutting down persistent Local MCP Session...")
    await exit_stack.aclose()
    logger.info("Local MCP Session shutdown completed.")

# Initialize app with lifespan manager
app = FastAPI(title="Azure DevOps Agent Local Server", lifespan=lifespan)

# Allow CORS for static HTML file queries
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    prompt: str = Field(..., description="The query sent by the user describing DevOps automation requests.")

def get_tool_reason(tool_name: str, args: Optional[Dict[str, Any]] = None) -> str:
    args = args or {}
    project = args.get("project") or args.get("projectId") or config.default_project
    repo = args.get("repositoryId") or args.get("repositoryName") or config.default_repo
    
    templates = {
        "core_list_orgs": "Listing all Azure DevOps organizations you have access to.",
        "core_list_projects": "Querying your Azure DevOps organization to list all active projects.",
        "core_list_project_teams": f"Listing all development teams in project '{project}'.",
        "repo_repository": f"Retrieving main details for repository '{repo}'.",
        "repo_repository_list": f"Querying project '{project}' to discover code repositories.",
        "repo_list_repos_by_project": f"Listing all code repositories registered under project '{project}'.",
        "repo_branch": f"Fetching details of branch '{args.get('branchName') or args.get('name') or 'target branch'}' in repository '{repo}'.",
        "repo_branch_list": f"Retrieving all active git branches inside repository '{repo}'.",
        "repo_list_branches_by_repo": f"Listing git branches inside repository '{repo}'.",
        "repo_file": f"Reading contents of file '{args.get('path') or 'target file'}' in repository '{repo}'.",
        "repo_file_get_content": f"Fetching text content of '{args.get('path')}' from repository '{repo}'.",
        "repo_search_commits": f"Searching commit history of repository '{repo}' for matches.",
        "search_code": f"Performing full-text search across codebase files for keyword '{args.get('searchText') or 'query'}'.",
        "wit_work_item": f"Retrieving details for work item #{args.get('id')}.",
        "wit_work_item_get": f"Fetching work item #{args.get('id')} fields and values.",
        "wit_work_item_my": "Retrieving work items assigned to your profile.",
        "wit_work_item_write": f"Creating/modifying work item in project '{project}' ({args.get('workItemType') or 'Item'}).",
        "wit_work_item_write_create": f"Creating new {args.get('workItemType') or 'Work Item'} under project '{project}'.",
        "wit_work_item_write_update": f"Updating fields and status of work item #{args.get('id')}.",
        "wit_work_item_write_add_child": f"Adding a new child task under parent work item #{args.get('parentId')}.",
        "wit_work_item_comment_write_add": f"Adding discussion comment to work item #{args.get('workItemId')}.",
        "wit_work_item_link_write_link": f"Linking work items together as relationships.",
        "pipelines_build_list": f"Listing build history runs in project '{project}'.",
        "pipelines_build_get_status": f"Querying build execution status of pipeline run.",
        "pipelines_run_list": f"Retrieving execution runs history of pipeline.",
        "pipelines_run_get": f"Fetching build details of pipeline execution run.",
        "pipelines_write_run_pipeline": f"Queueing and triggering a new build for pipeline ID {args.get('pipelineId')} on project '{project}'.",
        "pipelines_write_create_pipeline": f"Creating a new YAML pipeline '{args.get('name')}' pointing to '{args.get('yamlPath')}'."
    }
    
    if tool_name in templates:
        return templates[tool_name]
    
    for key, val in templates.items():
        if key in tool_name:
            return val
            
    readable_name = tool_name.replace("_", " ").title()
    return f"Querying DevOps API for {readable_name} details."

def determine_subagent_role(prompt: str) -> Dict[str, str]:
    prompt_lower = prompt.lower()
    matched_roles = []
    
    for role_name, config_data in SUBAGENT_ROLES.items():
        if role_name == "General Assistant":
            continue
        if any(k in prompt_lower for k in config_data["keywords"]):
            matched_roles.append({
                "name": role_name,
                "instruction": config_data["instruction"]
            })
            
    if len(matched_roles) == 1:
        return matched_roles[0]
    else:
        general = SUBAGENT_ROLES["General Assistant"]
        return {
            "name": "General Assistant",
            "instruction": general["instruction"]
        }

def filter_tools_for_role(role_name: str, mcp_tools: List[Any]) -> List[types.Tool]:
    gemini_declarations = []
    role_config = SUBAGENT_ROLES.get(role_name, SUBAGENT_ROLES["General Assistant"])
    allowed = role_config["prefixes"]
    
    for tool in mcp_tools:
        name = tool.name
        include = False
        
        for prefix in allowed:
            if name.startswith(prefix) or name == prefix:
                include = True
                break
                
        if include:
            schema = tool.inputSchema or {"type": "object", "properties": {}}
            decl = types.FunctionDeclaration(
                name=tool.name,
                description=tool.description or f"Executes {tool.name}",
                parameters_json_schema=schema
            )
            gemini_declarations.append(decl)
            
    return [types.Tool(function_declarations=gemini_declarations)]

async def execute_agent_run(
    prompt: str,
    system_instruction: str,
    tools: List[types.Tool],
    mcp_session: ClientSession,
    max_loops: int = 40,
    event_handler: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
) -> str:
    gemini_client = genai.Client()
    contents = [
        types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    ]
    loop_count = 0
    final_text = ""

    while loop_count < max_loops:
        if loop_count > 0:
            await asyncio.sleep(4.5)

        gen_config = types.GenerateContentConfig(
            tools=tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            system_instruction=system_instruction
        )

        response = gemini_client.models.generate_content(
            model=config.gemini_model,
            contents=contents,
            config=gen_config
        )

        thought_desc = ""
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if getattr(part, "text", None):
                    thought_desc += part.text

        if thought_desc.strip() and event_handler:
            await event_handler({"type": "thought", "message": thought_desc.strip()})

        if not response.function_calls:
            if thought_desc.strip():
                final_text = thought_desc.strip()
            break

        contents.append(response.candidates[0].content)
        tool_responses = []

        for call in response.function_calls:
            reason_msg = get_tool_reason(call.name, call.args)
            logger.info(f" -> CALLING TOOL: {call.name} with args: {call.args}")
            if event_handler:
                await event_handler({
                    "type": "tool_start",
                    "tool": call.name,
                    "arguments": call.args or {},
                    "message": f"Invoking {call.name}",
                    "reason": reason_msg
                })

            try:
                tool_result = await mcp_session.call_tool(call.name, call.args)
                result_text = ""
                if tool_result.content:
                    result_text = "\n".join(
                        c.text for c in tool_result.content if getattr(c, "text", None)
                    )
                
                if event_handler:
                    await event_handler({
                        "type": "tool_complete",
                        "tool": call.name,
                        "status": "success",
                        "message": f"Successfully ran {call.name}."
                    })

                truncated_result = result_text
                if len(truncated_result) > 3000:
                    truncated_result = truncated_result[:3000] + "\n\n... [Truncated by server to conserve Gemini API free tier token quota] ..."

                tool_responses.append(
                    types.Part.from_function_response(
                        name=call.name,
                        response={"result": truncated_result}
                    )
                )
            except Exception as tool_err:
                logger.error(f" [ERROR] ({call.name}): {tool_err}")
                if event_handler:
                    await event_handler({
                        "type": "tool_complete",
                        "tool": call.name,
                        "status": "failed",
                        "message": f"Error running {call.name}: {str(tool_err)}"
                    })
                tool_responses.append(
                    types.Part.from_function_response(
                        name=call.name,
                        response={"error": str(tool_err)}
                    )
                )

        contents.append(types.Content(role="tool", parts=tool_responses))
        loop_count += 1

    if loop_count >= max_loops and not final_text:
        final_text = "Reached maximum tool execution steps without a final response."

    return final_text

@app.post("/api/chat/stream")
async def chat_stream_endpoint(request: ChatRequest, req: Request) -> StreamingResponse:
    # Pull persistent session directly from FastAPI state context
    mcp_session = req.app.state.mcp_session
    mcp_tools = req.app.state.mcp_tools

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            logger.info(f"Reusing persistent session for local query: '{request.prompt[:50]}...'")
            yield f"data: {json.dumps({'type': 'status', 'message': 'Established connection to Azure DevOps MCP server.'})}\n\n"

            subagent = determine_subagent_role(request.prompt)
            gemini_tools = filter_tools_for_role(subagent["name"], mcp_tools)
            subagent_name = subagent["name"]
            
            yield f"data: {json.dumps({'type': 'subagent', 'name': subagent_name})}\n\n"
            yield f"data: {json.dumps({'type': 'status', 'message': f'Active Profile: Summoned {subagent_name} to analyze your request.'})}\n\n"

            queue = asyncio.Queue()

            async def handle_progress(event: Dict[str, Any]) -> None:
                await queue.put(event)

            system_instruction = (
                f"You are the {subagent['name']} subagent. {subagent['instruction']}\n"
                "To conserve API quota, you MUST follow these constraints:\n"
                f"1. The default project is '{config.default_project}' and the default repository is '{config.default_repo}'. ALWAYS assume these defaults. Do NOT query projects or repository list unless the user explicitly asks to list them or specifies a different project/repository.\n"
                "2. Minimize tool calls. Only call tools that are absolutely necessary to answer the prompt.\n"
                "3. If a tool call returns empty or fails, DO NOT retry it. Report the failure/empty state immediately to the user.\n"
                "4. Call tools in parallel in a single turn whenever possible instead of running them sequentially across multiple turns.\n"
                "5. Do not perform redundant queries (e.g. if you already listed branches, do not list them again).\n"
                "6. Act fully autonomously. Never ask the user for confirmation, permission, or approval before executing writing or mutating actions (like creating/updating work items, updating team capacity, assigning iterations, creating branches, or writing wiki pages). Execute them immediately."
            )

            agent_task = asyncio.create_task(
                execute_agent_run(
                    prompt=request.prompt,
                    system_instruction=system_instruction,
                    tools=gemini_tools,
                    mcp_session=mcp_session,
                    event_handler=handle_progress
                )
            )

            while not agent_task.done() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield f"data: {json.dumps(event)}\n\n"
                    queue.task_done()
                except asyncio.TimeoutError:
                    continue

            final_text = await agent_task
            yield f"data: {json.dumps({'type': 'final', 'message': final_text})}\n\n"

        except Exception as err:
            logger.error(f"Execution failed: {err}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': f'Error during execution: {str(err)}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

async def run_build_doctor(build_id: str, project_name: str, pipeline_id: str, mcp_session: ClientSession, mcp_tools: List[Any]) -> None:
    logger.info(f"[Build Doctor] Commencing build diagnosis for build #{build_id} under pipeline {pipeline_id}...")
    try:
        prompt = (
            f"Build #{build_id} in pipeline {pipeline_id} under project '{project_name}' has failed.\n"
            "Your job as the Build Doctor is to:\n"
            f"1. Query the build logs for build ID '{build_id}' (using pipelines_build_log list and get_content) "
            "to extract the exact compiler error, syntax failure, or failing test case.\n"
            "2. Once you find the root cause, automatically create a new BUG Work Item in project "
            f"'{project_name}' with a detailed description of the traceback error and the recommended fix."
        )
        
        tools = filter_tools_for_role("DevOps Engineer", mcp_tools) + filter_tools_for_role("Product Manager", mcp_tools)
        
        async def handle_progress(event: Dict[str, Any]) -> None:
            if event["type"] == "thought":
                logger.info(f"[Build Doctor thought]: {event['message']}")
            elif event["type"] == "tool_start":
                logger.info(f"[Build Doctor calling {event['tool']}]: {event['reason']}")

        system_instruction = (
            "You are a DevOps Engineer and Product Manager. Diagnose build failures and report bugs autonomously."
        )

        await execute_agent_run(
            prompt=prompt,
            system_instruction=system_instruction,
            tools=tools,
            mcp_session=mcp_session,
            max_loops=10,
            event_handler=handle_progress
        )
        logger.info(f"[Build Doctor] Diagnostic completed for build #{build_id}.")
    except Exception as e:
        logger.error(f"[Build Doctor] Error during build diagnosis: {e}", exc_info=True)

@app.post("/api/webhooks/ado")
async def azure_devops_webhook(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = payload.get("eventType")
    resource = payload.get("resource", {})
    
    logger.info(f"[Webhook Received] Event Type: {event_type}")
    
    if event_type == "build.complete":
        result = resource.get("result")
        build_id = resource.get("id")
        project_name = resource.get("project", {}).get("name") or config.default_project
        pipeline_id = resource.get("definition", {}).get("id")
        
        if result == "failed":
            logger.info(f"[Build Doctor] Triggering auto-healing diagnostics for Build #{build_id} in project '{project_name}'...")
            mcp_session = request.app.state.mcp_session
            mcp_tools = request.app.state.mcp_tools
            asyncio.create_task(run_build_doctor(str(build_id), project_name, str(pipeline_id), mcp_session, mcp_tools))
            return {"status": "triggered_build_doctor", "build_id": build_id}
            
    return {"status": "ignored", "event_type": event_type}

# Serve static HTML/JS frontend from the current directory
current_dir = os.path.dirname(os.path.abspath(__file__))
app.mount("/", StaticFiles(directory=current_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting Local Uvicorn server on port {config.port}...")
    uvicorn.run(app, host="127.0.0.1", port=config.port)
