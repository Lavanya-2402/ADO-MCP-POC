import asyncio
import os
import sys
import json
import time
import logging
import argparse
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
import msal
import httpx
from google import genai
from google.genai import types

# Configure logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("azure-devops-agent-remote-cli")

# Load environment variables
load_dotenv()

class AppConfig:
    def __init__(self) -> None:
        self.gemini_api_key: str = self._get_required_env("GEMINI_API_KEY")
        self.azure_devops_organization: str = os.getenv("AZURE_DEVOPS_ORGANIZATION", "Rapid-AI-Team")
        self.default_project: str = os.getenv("AZURE_DEVOPS_PROJECT", "Pulse")
        self.default_repo: str = os.getenv("AZURE_DEVOPS_REPOSITORY", "Pulse")
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
        # Fix 12: Validate Entra credentials at startup so CLI fails fast
        # rather than crashing mid-run on the first API call.
        self.entra_tenant_id: str = self._get_required_env("ENTRA_TENANT_ID")
        self.entra_client_id: str = self._get_required_env("ENTRA_CLIENT_ID")
        self.entra_client_secret: str = self._get_required_env("ENTRA_CLIENT_SECRET")

    def _get_required_env(self, key: str) -> str:
        val = os.getenv(key)
        if not val or "here" in val:
            logger.critical(f"Missing required environment variable: {key}")
            raise RuntimeError(f"Configuration Error: {key} must be defined in your .env file.")
        return val

try:
    config = AppConfig()
except RuntimeError as err:
    logger.critical(f"CLI startup failed due to config errors: {err}")
    sys.exit(1)

@dataclass
class Tool:
    name: str
    description: str
    inputSchema: dict

@dataclass
class ToolsResponse:
    tools: List[Tool]

@dataclass
class Content:
    text: str

@dataclass
class CallToolResponse:
    content: List[Content]

# Fix 13: Use msal.SerializableTokenCache + asyncio.Lock instead of a plain
# global dict to prevent concurrent duplicate token fetches.
_msal_token_cache = msal.SerializableTokenCache()
_token_lock = asyncio.Lock()
_token_expiry: float = 0.0

def format_auth_header(token: str) -> str:
    token_str = token.strip()
    if token_str.startswith("Bearer "):
        return token_str
    return f"Bearer {token_str}"

async def get_auth_token() -> str:
    global _token_expiry
    current_time = time.time()

    async with _token_lock:
        cached = _msal_token_cache.find(msal.TokenCache.CredentialType.ACCESS_TOKEN)
        if cached and current_time < _token_expiry - 60:
            return cached[0]["secret"]

        authority = f"https://login.microsoftonline.com/{config.entra_tenant_id}"
        scope = ["https://mcp.dev.azure.com/.default"]

        logger.info(f"[MSAL] Acquiring new token for Entra tenant {config.entra_tenant_id}...")
        try:
            msal_app = msal.ConfidentialClientApplication(
                config.entra_client_id,
                authority=authority,
                client_credential=config.entra_client_secret,
                token_cache=_msal_token_cache
            )
            result = msal_app.acquire_token_for_client(scopes=scope)

            if "access_token" not in result:
                err_msg = result.get("error_description") or result.get("error") or "Unknown OAuth error"
                raise RuntimeError(err_msg)

            _token_expiry = current_time + result.get("expires_in", 3600)
            logger.info("[MSAL] Token successfully acquired via Client Credentials.")
            return result["access_token"]
        except Exception as e:
            logger.error(f"[MSAL ERROR] Failed to fetch token: {e}", exc_info=True)
            raise RuntimeError(f"OAuth Token Acquisition failed: {str(e)}")

class RemoteMCPClient:
    def __init__(self, remote_url: str, token: Optional[str] = None, default_headers: Optional[Dict[str, str]] = None) -> None:
        if not remote_url.startswith("http"):
            self.url = f"https://mcp.dev.azure.com/{remote_url}"
        else:
            self.url = remote_url
        self.token = token
        self.default_headers = default_headers or {}

    async def get_headers(self) -> Dict[str, str]:
        token = self.token or await get_auth_token()
        auth_header = format_auth_header(token)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": auth_header
        }
        headers.update(self.default_headers)
        return headers

    async def list_tools(self) -> ToolsResponse:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }
        headers = await self.get_headers()
        async with httpx.AsyncClient() as client:
            response = await client.post(self.url, json=payload, headers=headers, timeout=60.0)
            if response.status_code != 200:
                logger.error(f"Failed to list tools from remote server: HTTP {response.status_code}")
                raise RuntimeError(f"Remote server error: {response.text}")
            
            data = response.text.strip()
            if data.startswith("event:"):
                lines = data.split("\n")
                data_line = next((l for l in lines if l.startswith("data: ")), None)
                if data_line:
                    data = data_line[6:]
            
            res_json = json.loads(data)
            if "error" in res_json:
                raise RuntimeError(f"RPC Error: {res_json['error']}")
            
            tools_list = []
            for t in res_json.get("result", {}).get("tools", []):
                tools_list.append(Tool(t.get("name", ""), t.get("description", ""), t.get("inputSchema", {})))
            return ToolsResponse(tools_list)

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> CallToolResponse:
        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments
            }
        }
        headers = await self.get_headers()
        async with httpx.AsyncClient() as client:
            response = await client.post(self.url, json=payload, headers=headers, timeout=60.0)
            if response.status_code != 200:
                logger.error(f"Failed to call tool '{name}' on remote server: HTTP {response.status_code}")
                raise RuntimeError(f"Remote server call_tool failed: {response.text}")
            
            data = response.text.strip()
            if data.startswith("event:"):
                lines = data.split("\n")
                data_line = next((l for l in lines if l.startswith("data: ")), None)
                if data_line:
                    data = data_line[6:]
            
            res_json = json.loads(data)
            if "error" in res_json:
                raise RuntimeError(f"RPC Error on call_tool '{name}': {res_json['error']}")
            
            content_list = []
            for c in res_json.get("result", {}).get("content", []):
                content_list.append(Content(c.get("text", "")))
            return CallToolResponse(content_list)

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

def determine_subagent_role(prompt: str) -> dict:
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

def filter_tools_for_role(role_name: str, mcp_tools: list) -> list:
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
    tools: list,
    mcp_session: RemoteMCPClient,
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
            logger.info(f"TOOL CALL -> {call.name}")
            logger.debug(f"Arguments: {json.dumps(call.args, indent=2)}")
            try:
                tool_result = await mcp_session.call_tool(call.name, call.args)
                result_text = "\n".join(
                    c.text for c in tool_result.content if getattr(c, "text", None)
                ) if tool_result.content else ""

                logger.debug(f"Tool result (length={len(result_text)}): {result_text[:200]}...")
                tool_responses.append(types.Part.from_function_response(
                    name=call.name, response={"result": result_text}
                ))
            except Exception as tool_err:
                logger.error(f"Tool Error ({call.name}): {tool_err}")
                tool_responses.append(types.Part.from_function_response(
                    name=call.name, response={"error": str(tool_err)}
                ))

        contents.append(types.Content(role="tool", parts=tool_responses))
        loop_count += 1

    if loop_count >= max_loops and not final_text:
        final_text = "Reached maximum tool execution steps without a final response."

def get_remote_mcp_config() -> str:
    local_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(local_dir, "mcp_config.json")
    
    if not os.path.exists(config_path):
        logger.error(f"Remote mcp_config.json configuration file not found at {config_path}")
        raise FileNotFoundError(f"Configuration file 'mcp_config.json' not found at {local_dir}")
        
    with open(config_path, "r", encoding="utf-8") as f:
        mcp_data = json.load(f)
        
    servers = mcp_data.get("mcpServers", {})
    if "azure-devops" not in servers:
        logger.error("Configuration block 'azure-devops' is missing from remote mcp_config.json")
        raise KeyError("Invalid config: 'azure-devops' server block is required in mcp_config.json")
        
    server_info = servers["azure-devops"]
    url = server_info.get("url")
    if not url:
        raise KeyError("Invalid config: 'url' must be specified in the azure-devops block of mcp_config.json")
    return url

async def main():
    parser = argparse.ArgumentParser(description="Azure DevOps Agent Remote Command Line Interface")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-p", "--prompt", type=str, help="Prompt describing DevOps automation requests.")
    group.add_argument("-f", "--file", type=str, help="Path to a text file containing the prompt / tasks.")
    
    args = parser.parse_args()

    prompt_content = ""
    if args.prompt:
        prompt_content = args.prompt
    elif args.file:
        if not os.path.exists(args.file):
            logger.error(f"File '{args.file}' not found.")
            sys.exit(1)
        with open(args.file, "r", encoding="utf-8") as f:
            prompt_content = f.read().strip()
            
    if not prompt_content:
        logger.error("Empty prompt or file content.")
        sys.exit(1)

    logger.info("Initializing Remote MCP Session via CLI...")
    try:
        remote_url = get_remote_mcp_config()
        # Initialize token (this will authenticate using client credentials or cached tokens)
        token = await get_auth_token()
        mcp_session = RemoteMCPClient(remote_url=remote_url, token=token)
        
        mcp_tools_resp = await mcp_session.list_tools()
        mcp_tools = mcp_tools_resp.tools
        logger.info(f"Remote Session initialized. Loaded {len(mcp_tools)} tools.\n")
        
        subagent = determine_subagent_role(prompt_content)
        gemini_tools = filter_tools_for_role(subagent["name"], mcp_tools)
        subagent_name = subagent["name"]
        
        logger.info(f"Active Profile: {subagent_name}")
        system_instruction = (
            f"You are the {subagent['name']} subagent. {subagent['instruction']}\n"
            "To conserve API quota, you MUST follow these constraints:\n"
            f"1. The default project is '{config.azure_devops_organization}' and the default repository is '{config.default_repo}'. ALWAYS assume these defaults. Do NOT query projects or repository list unless the user explicitly asks to list them or specifies a different project/repository.\n"
            "2. Minimize tool calls. Only call tools that are absolutely necessary to answer the prompt.\n"
            "3. If a tool call returns empty or fails, DO NOT retry it. Report the failure/empty state immediately to the user.\n"
            "4. Call tools in parallel in a single turn whenever possible instead of running them sequentially across multiple turns.\n"
            "5. Do not perform redundant queries (e.g. if you already listed branches, do not list them again).\n"
            "6. Act fully autonomously. Never ask the user for confirmation, permission, or approval before executing writing or mutating actions (like creating/updating work items, updating team capacity, assigning iterations, creating branches, or writing wiki pages). Execute them immediately."
        )
        
        logger.info("Running remote agent task...")
        final_text = await execute_agent_run(
            prompt=prompt_content,
            system_instruction=system_instruction,
            tools=gemini_tools,
            mcp_session=mcp_session
        )
        
        logger.info("=== FINAL AGENT RESPONSE ===")
        logger.info(final_text)
        logger.info("============================")
        
    except Exception as err:
        logger.critical(f"CLI execution failed: {err}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())
