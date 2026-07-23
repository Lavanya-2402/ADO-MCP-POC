import asyncio
import os
import sys
import json
import logging
from typing import Dict, List, Any, AsyncGenerator, Optional
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
    general = SUBAGENT_ROLES["General Assistant"]
    return {"name": "General Assistant", "instruction": general["instruction"]}


def filter_tools_for_role(role_name: str, mcp_tools: List[Any]) -> List[types.Tool]:
    gemini_declarations = []
    role_config = SUBAGENT_ROLES.get(role_name, SUBAGENT_ROLES["General Assistant"])
    allowed = role_config["prefixes"]

    for tool in mcp_tools:
        if any(tool.name.startswith(p) or tool.name == p for p in allowed):
            schema = tool.inputSchema or {"type": "object", "properties": {}}
            gemini_declarations.append(types.FunctionDeclaration(
                name=tool.name,
                description=tool.description or f"Executes {tool.name}",
                parameters_json_schema=schema
            ))

    return [types.Tool(function_declarations=gemini_declarations)]


async def execute_agent_run(
    prompt: str,
    system_instruction: str,
    tools: List[types.Tool],
    mcp_session: ClientSession,
    max_loops: int = 40
) -> str:
    gemini_client = genai.Client()
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
    loop_count = 0
    final_text = ""

    while loop_count < max_loops:
        if loop_count > 0:
            await asyncio.sleep(1)

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

        final_text = ""
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if getattr(part, "text", None):
                    final_text += part.text

        if not response.function_calls:
            break

        contents.append(response.candidates[0].content)
        tool_responses = []

        for call in response.function_calls:
            logger.info(f" -> TOOL: {call.name} | args: {call.args}")
            try:
                tool_result = await mcp_session.call_tool(call.name, call.args)
                result_text = "\n".join(
                    c.text for c in tool_result.content if getattr(c, "text", None)
                ) if tool_result.content else ""

                tool_responses.append(types.Part.from_function_response(
                    name=call.name, response={"result": result_text}
                ))
            except Exception as tool_err:
                logger.error(f" -> TOOL ERROR ({call.name}): {tool_err}")
                tool_responses.append(types.Part.from_function_response(
                    name=call.name, response={"error": str(tool_err)}
                ))

        contents.append(types.Content(role="tool", parts=tool_responses))
        loop_count += 1

    if loop_count >= max_loops and not final_text:
        final_text = "Reached maximum tool execution steps without a final response."

    return final_text

@app.post("/api/chat/stream")
async def chat_stream_endpoint(request: ChatRequest, req: Request) -> StreamingResponse:
    mcp_session = req.app.state.mcp_session
    mcp_tools = req.app.state.mcp_tools

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            logger.info(f"Incoming query: '{request.prompt[:80]}...'")
            yield f"data: {json.dumps({'type': 'status', 'message': 'Connected to Azure DevOps MCP server.'})}\n\n"

            subagent = determine_subagent_role(request.prompt)
            gemini_tools = filter_tools_for_role(subagent["name"], mcp_tools)
            subagent_name = subagent["name"]

            yield f"data: {json.dumps({'type': 'subagent', 'name': subagent_name})}\n\n"
            yield f"data: {json.dumps({'type': 'status', 'message': f'Active Profile: {subagent_name}'})}\n\n"

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

            final_text = await execute_agent_run(
                prompt=request.prompt,
                system_instruction=system_instruction,
                tools=gemini_tools,
                mcp_session=mcp_session
            )
            yield f"data: {json.dumps({'type': 'final', 'message': final_text})}\n\n"

        except Exception as err:
            logger.error(f"Execution failed: {err}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': f'Error during execution: {str(err)}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")



# Serve static HTML/JS frontend from the current directory
current_dir = os.path.dirname(os.path.abspath(__file__))
app.mount("/", StaticFiles(directory=current_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting Local Uvicorn server on port {config.port}...")
    uvicorn.run(app, host="127.0.0.1", port=config.port)
