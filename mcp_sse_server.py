#!/usr/bin/env python3
"""
Jira MCP SSE Server - Remote MCP protocol over Server-Sent Events.
Allows Cursor to connect remotely via @anthropic/mcp-remote.

Usage in Cursor mcp.json:
{
  "mcpServers": {
    "jira": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-remote", "https://jira-mcp.koveh.com/mcp/SESSION_TOKEN"]
    }
  }
}
"""
import json
import uuid
import base64
import threading
import queue
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import time

from jira_client import JiraClient, JiraConfig


# Store active sessions: {session_id: {"client": JiraClient, "queue": Queue}}
SESSIONS = {}
SESSION_LOCK = threading.Lock()


def create_session(base_url: str, email: str, api_token: str) -> str:
    """Create a new session and return session ID."""
    session_id = str(uuid.uuid4())
    config = JiraConfig(base_url=base_url, email=email, api_token=api_token)
    client = JiraClient(config)
    
    # Test connection
    client.get_current_user()
    
    with SESSION_LOCK:
        SESSIONS[session_id] = {
            "client": client,
            "config": config,
            "queue": queue.Queue(),
            "created": time.time()
        }
    
    return session_id


def get_session(session_id: str) -> dict:
    """Get session by ID."""
    with SESSION_LOCK:
        return SESSIONS.get(session_id)


def decode_credentials_from_token(token: str) -> dict:
    """Decode base64 credentials token."""
    try:
        decoded = base64.b64decode(token).decode()
        return json.loads(decoded)
    except:
        return None


def extract_description(desc: dict) -> str:
    """Extract text from ADF description."""
    if not desc or not isinstance(desc, dict):
        return ""
    texts = []
    for content in desc.get("content", []):
        for item in content.get("content", []):
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
    return " ".join(texts)


class MCPSSEHandler(BaseHTTPRequestHandler):
    """Handler for MCP SSE protocol."""
    
    protocol_version = 'HTTP/1.1'
    
    def _get_session_from_path(self) -> dict:
        """Extract session from URL path."""
        parsed = urlparse(self.path)
        parts = parsed.path.strip('/').split('/')
        
        if len(parts) >= 2 and parts[0] == 'mcp':
            token = parts[1]
            
            # Try as session ID first
            session = get_session(token)
            if session:
                return session
            
            # Try as base64 encoded credentials
            creds = decode_credentials_from_token(token)
            if creds:
                session_id = create_session(
                    creds.get("base_url"),
                    creds.get("email"),
                    creds.get("api_token")
                )
                return get_session(session_id)
        
        return None
    
    def _send_json(self, data: dict, status: int = 200):
        """Send JSON response."""
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.end_headers()
        self.wfile.write(body)
    
    def _send_sse_event(self, event: str, data: dict):
        """Send SSE event."""
        self.wfile.write(f"event: {event}\n".encode())
        self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()
    
    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.end_headers()
    
    def do_GET(self):
        """Handle GET - SSE endpoint for receiving messages."""
        parsed = urlparse(self.path)
        
        if parsed.path == '/health':
            self._send_json({"status": "ok", "service": "jira-mcp-sse"})
            return
        
        if parsed.path.startswith('/mcp/'):
            self._handle_sse()
            return
        
        self._send_json({"error": "Not found"}, 404)
    
    def do_POST(self):
        """Handle POST - receive MCP messages."""
        parsed = urlparse(self.path)
        
        if parsed.path == '/api/session':
            self._create_session()
            return
        
        if parsed.path.startswith('/mcp/'):
            self._handle_mcp_message()
            return
        
        self._send_json({"error": "Not found"}, 404)
    
    def _create_session(self):
        """Create a new session from credentials."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}
        
        try:
            session_id = create_session(
                body.get("base_url"),
                body.get("email"),
                body.get("api_token")
            )
            
            # Also create a token that can be used directly
            creds = json.dumps({
                "base_url": body.get("base_url"),
                "email": body.get("email"),
                "api_token": body.get("api_token")
            })
            token = base64.b64encode(creds.encode()).decode()
            
            self._send_json({
                "session_id": session_id,
                "token": token,
                "mcp_url": f"https://jira-mcp.koveh.com/mcp/{token}",
                "cursor_config": {
                    "mcpServers": {
                        "jira": {
                            "command": "npx",
                            "args": ["-y", "@anthropic/mcp-remote", f"https://jira-mcp.koveh.com/mcp/{token}"]
                        }
                    }
                }
            })
        except Exception as e:
            self._send_json({"error": str(e)}, 400)
    
    def _handle_sse(self):
        """Handle SSE connection."""
        session = self._get_session_from_path()
        if not session:
            self._send_json({"error": "Invalid session"}, 401)
            return
        
        # Send SSE headers
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        
        # Send endpoint event (required by mcp-remote)
        self._send_sse_event("endpoint", f"/mcp/{urlparse(self.path).path.split('/')[-1]}")
        
        # Keep connection alive and process queue
        try:
            while True:
                try:
                    msg = session["queue"].get(timeout=30)
                    self._send_sse_event("message", msg)
                except queue.Empty:
                    # Send keepalive
                    self.wfile.write(": keepalive\n\n".encode())
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
    
    def _handle_mcp_message(self):
        """Handle incoming MCP message."""
        session = self._get_session_from_path()
        if not session:
            self._send_json({"error": "Invalid session"}, 401)
            return
        
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}
        
        response = self._process_mcp_request(session, body)
        
        # Put response in queue for SSE
        session["queue"].put(response)
        
        # Also return directly
        self._send_json(response)
    
    def _process_mcp_request(self, session: dict, request: dict) -> dict:
        """Process MCP request and return response."""
        method = request.get("method")
        params = request.get("params", {})
        req_id = request.get("id")
        
        result = None
        error = None
        
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "jira-mcp", "version": "1.0.0"}
                }
            
            elif method == "tools/list":
                result = {"tools": self._get_tools_list()}
            
            elif method == "tools/call":
                result = self._call_tool(session, params)
            
            elif method == "notifications/initialized":
                result = {}
            
            else:
                error = {"code": -32601, "message": f"Unknown method: {method}"}
        
        except Exception as e:
            error = {"code": -32603, "message": str(e)}
        
        response = {"jsonrpc": "2.0", "id": req_id}
        if error:
            response["error"] = error
        else:
            response["result"] = result
        
        return response
    
    def _get_tools_list(self) -> list:
        """Return list of available tools."""
        return [
            {
                "name": "jira_get_projects",
                "description": "Get list of all accessible Jira projects",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "jira_get_issues",
                "description": "Get all issues for a specific project",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_key": {"type": "string", "description": "Project key (e.g., PROJ)"},
                        "max_results": {"type": "integer", "description": "Maximum results", "default": 50}
                    },
                    "required": ["project_key"]
                }
            },
            {
                "name": "jira_get_issue",
                "description": "Get detailed information about a specific issue",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "issue_key": {"type": "string", "description": "Issue key (e.g., PROJ-123)"}
                    },
                    "required": ["issue_key"]
                }
            },
            {
                "name": "jira_create_issue",
                "description": "Create a new issue/task in Jira",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_key": {"type": "string", "description": "Project key"},
                        "summary": {"type": "string", "description": "Issue title"},
                        "description": {"type": "string", "description": "Issue description"},
                        "issue_type": {"type": "string", "description": "Issue type", "default": "Task"}
                    },
                    "required": ["project_key", "summary"]
                }
            },
            {
                "name": "jira_update_issue",
                "description": "Update an existing issue",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "issue_key": {"type": "string", "description": "Issue key"},
                        "summary": {"type": "string", "description": "New summary"},
                        "description": {"type": "string", "description": "New description"}
                    },
                    "required": ["issue_key"]
                }
            },
            {
                "name": "jira_delete_issue",
                "description": "Delete an issue from Jira",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "issue_key": {"type": "string", "description": "Issue key"}
                    },
                    "required": ["issue_key"]
                }
            },
            {
                "name": "jira_search",
                "description": "Search issues using JQL",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "jql": {"type": "string", "description": "JQL query"},
                        "max_results": {"type": "integer", "description": "Max results", "default": 50}
                    },
                    "required": ["jql"]
                }
            },
            {
                "name": "jira_get_current_user",
                "description": "Get current authenticated user info",
                "inputSchema": {"type": "object", "properties": {}}
            }
        ]
    
    def _call_tool(self, session: dict, params: dict) -> dict:
        """Execute a tool call."""
        client = session["client"]
        tool_name = params.get("name")
        args = params.get("arguments", {})
        
        result = None
        
        if tool_name == "jira_get_projects":
            projects = client.get_all_projects()
            result = [{"key": p["key"], "name": p["name"], "id": p["id"]} for p in projects]
        
        elif tool_name == "jira_get_issues":
            issues = client.get_issues_by_project(args["project_key"], args.get("max_results", 50))
            result = []
            for i in issues:
                if i.get("fields"):
                    fields = i["fields"]
                    result.append({
                        "key": i["key"],
                        "summary": fields.get("summary"),
                        "status": fields.get("status", {}).get("name"),
                        "assignee": fields.get("assignee", {}).get("displayName") if fields.get("assignee") else None
                    })
        
        elif tool_name == "jira_get_issue":
            issue = client.get_issue(args["issue_key"])
            fields = issue["fields"]
            result = {
                "key": issue["key"],
                "summary": fields.get("summary"),
                "status": fields.get("status", {}).get("name"),
                "priority": fields.get("priority", {}).get("name"),
                "assignee": fields.get("assignee", {}).get("displayName") if fields.get("assignee") else None,
                "description": extract_description(fields.get("description")),
                "created": fields.get("created"),
                "updated": fields.get("updated")
            }
        
        elif tool_name == "jira_create_issue":
            issue = client.create_issue(
                args["project_key"],
                args["summary"],
                args.get("description", ""),
                args.get("issue_type", "Task")
            )
            result = {"key": issue.get("key"), "id": issue.get("id")}
        
        elif tool_name == "jira_update_issue":
            fields = {}
            if args.get("summary"):
                fields["summary"] = args["summary"]
            if args.get("description"):
                fields["description"] = {
                    "type": "doc", "version": 1,
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": args["description"]}]}]
                }
            client.update_issue(args["issue_key"], fields)
            result = {"status": "updated", "key": args["issue_key"]}
        
        elif tool_name == "jira_delete_issue":
            client.delete_issue(args["issue_key"])
            result = {"status": "deleted", "key": args["issue_key"]}
        
        elif tool_name == "jira_search":
            issues = client.search_issues(args["jql"], args.get("max_results", 50))
            result = []
            for i in issues:
                if i.get("fields"):
                    fields = i["fields"]
                    result.append({
                        "key": i["key"],
                        "summary": fields.get("summary"),
                        "status": fields.get("status", {}).get("name")
                    })
        
        elif tool_name == "jira_get_current_user":
            result = client.get_current_user()
        
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
    
    def log_message(self, format, *args):
        print(f"[MCP-SSE] {args[0]}")


def run_sse_server(port: int = 4201):
    """Run the SSE MCP server."""
    server = HTTPServer(("0.0.0.0", port), MCPSSEHandler)
    print(f"MCP SSE Server running on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    run_sse_server()

