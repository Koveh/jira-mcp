#!/usr/bin/env python3
"""
Jira MCP HTTP Server - REST API + MCP SSE for remote connections.
Users provide their own Jira credentials.

Usage:
    python http_server.py
    
Available at: https://jira-mcp.koveh.com

MCP Remote Config:
    {
      "mcpServers": {
        "jira": {
          "command": "npx",
          "args": ["-y", "@anthropic/mcp-remote", "https://jira-mcp.koveh.com/mcp/YOUR_TOKEN"]
        }
      }
    }
"""
import json
import uuid
import queue
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import base64

from jira_client import JiraClient, JiraConfig


# Store active MCP sessions
MCP_SESSIONS = {}
MCP_SESSION_LOCK = threading.Lock()


def create_mcp_session(base_url: str, email: str, api_token: str) -> str:
    """Create a new MCP session."""
    config = JiraConfig(base_url=base_url, email=email, api_token=api_token)
    client = JiraClient(config)
    client.get_current_user()  # Test connection
    
    session_id = str(uuid.uuid4())[:8]
    with MCP_SESSION_LOCK:
        MCP_SESSIONS[session_id] = {
            "client": client,
            "config": config,
            "queue": queue.Queue(),
            "created": time.time()
        }
    return session_id


def get_mcp_session(session_id: str) -> dict:
    """Get MCP session by ID."""
    with MCP_SESSION_LOCK:
        return MCP_SESSIONS.get(session_id)


def decode_token(token: str) -> dict:
    """Decode base64 credentials token."""
    try:
        return json.loads(base64.b64decode(token).decode())
    except:
        return None


def extract_description(desc: dict) -> str:
    """Extract text from ADF."""
    if not desc or not isinstance(desc, dict):
        return ""
    texts = []
    for content in desc.get("content", []):
        for item in content.get("content", []):
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
    return " ".join(texts)


class JiraHTTPHandler(BaseHTTPRequestHandler):
    
    def _get_client(self) -> JiraClient:
        """Get Jira client from Authorization header or query params."""
        # Try Authorization header first (Base64 encoded JSON)
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            creds = json.loads(base64.b64decode(token))
            config = JiraConfig(
                base_url=creds.get("base_url"),
                email=creds.get("email"),
                api_token=creds.get("api_token")
            )
            return JiraClient(config)
        
        # Try query params
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        
        base_url = params.get("base_url", [None])[0]
        email = params.get("email", [None])[0]
        api_token = params.get("api_token", [None])[0]
        
        if all([base_url, email, api_token]):
            config = JiraConfig(base_url=base_url, email=email, api_token=api_token)
            return JiraClient(config)
        
        return None
    
    def _send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode())
    
    def _send_html(self, html: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())
    
    def _require_auth(self):
        """Check if client is authenticated."""
        client = self._get_client()
        if not client:
            self._send_json({
                "error": "Authentication required",
                "help": "Provide credentials via Authorization header (Bearer base64(JSON)) or query params (base_url, email, api_token)"
            }, 401)
            return None
        return client
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        
        if path == "/" or path == "":
            self._serve_dashboard()
        elif path == "/health":
            self._send_json({"status": "ok", "service": "jira-mcp"})
        elif path == "/api/user":
            client = self._require_auth()
            if client:
                self._get_user(client)
        elif path == "/api/projects":
            client = self._require_auth()
            if client:
                self._get_projects(client)
        elif path == "/api/issues":
            client = self._require_auth()
            if client:
                project = params.get("project", [""])[0]
                if not project:
                    self._send_json({"error": "project parameter required"}, 400)
                else:
                    self._get_issues(client, project)
        elif path.startswith("/api/issue/"):
            client = self._require_auth()
            if client:
                issue_key = path.split("/")[-1]
                self._get_issue(client, issue_key)
        elif path == "/api/search":
            client = self._require_auth()
            if client:
                jql = params.get("jql", [""])[0]
                if not jql:
                    self._send_json({"error": "jql parameter required"}, 400)
                else:
                    self._search_issues(client, jql)
        elif path.startswith("/mcp/"):
            self._handle_mcp_sse()
        elif path == "/sse":
            # SSE endpoint for mcp-remote
            self._handle_mcp_sse()
        else:
            self._send_json({"error": "Not found"}, 404)
    
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}
        
        # For POST, also check body for credentials
        client = self._get_client()
        if not client and all([body.get("base_url"), body.get("email"), body.get("api_token")]):
            config = JiraConfig(
                base_url=body.get("base_url"),
                email=body.get("email"),
                api_token=body.get("api_token")
            )
            client = JiraClient(config)
        
        if path == "/api/connect":
            # Test connection endpoint
            if not all([body.get("base_url"), body.get("email"), body.get("api_token")]):
                self._send_json({"error": "base_url, email, api_token required"}, 400)
                return
            config = JiraConfig(
                base_url=body.get("base_url"),
                email=body.get("email"),
                api_token=body.get("api_token")
            )
            test_client = JiraClient(config)
            user = test_client.get_current_user()
            # Generate auth token for subsequent requests
            creds = json.dumps({"base_url": body["base_url"], "email": body["email"], "api_token": body["api_token"]})
            token = base64.b64encode(creds.encode()).decode()
            # Create MCP URL for remote connections
            mcp_url = f"https://jira-mcp.koveh.com/mcp/{token}"
            
            self._send_json({
                "status": "connected",
                "user": user.get("displayName"),
                "email": user.get("emailAddress"),
                "accountId": user.get("accountId"),
                "token": token,
                "mcp_url": mcp_url,
                "cursor_config": {
                    "mcpServers": {
                        "jira": {
                            "command": "npx",
                            "args": ["-y", "@anthropic/mcp-remote", mcp_url]
                        }
                    }
                },
                "help": "Use token in Authorization header OR use mcp_url in Cursor"
            })
        elif path == "/api/issues":
            if not client:
                self._send_json({"error": "Authentication required"}, 401)
                return
            self._create_issue(client, body)
        elif path.startswith("/api/issue/") and path.endswith("/transition"):
            if not client:
                self._send_json({"error": "Authentication required"}, 401)
                return
            issue_key = path.split("/")[-2]
            self._transition_issue(client, issue_key, body)
        elif path.startswith("/mcp/") or path == "/message":
            self._handle_mcp_message(body)
        else:
            self._send_json({"error": "Not found"}, 404)
    
    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}
        
        client = self._require_auth()
        if not client:
            return
        
        if path.startswith("/api/issue/"):
            issue_key = path.split("/")[-1]
            self._update_issue(client, issue_key, body)
        else:
            self._send_json({"error": "Not found"}, 404)
    
    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        client = self._require_auth()
        if not client:
            return
        
        if path.startswith("/api/issue/"):
            issue_key = path.split("/")[-1]
            self._delete_issue(client, issue_key)
        else:
            self._send_json({"error": "Not found"}, 404)
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
    
    # ===== API Methods =====
    
    def _create_issue(self, client: JiraClient, body: dict):
        if not body.get("project") or not body.get("summary"):
            self._send_json({"error": "project and summary required"}, 400)
            return
        result = client.create_issue(
            body.get("project"),
            body.get("summary"),
            body.get("description", ""),
            body.get("type", "Task")
        )
        self._send_json({"success": True, "key": result.get("key"), "id": result.get("id")})
    
    def _delete_issue(self, client: JiraClient, issue_key: str):
        client.delete_issue(issue_key)
        self._send_json({"success": True, "deleted": issue_key})
    
    def _get_issue(self, client: JiraClient, issue_key: str):
        issue = client.get_issue(issue_key)
        self._send_json(self._format_issue(issue))
    
    def _get_issues(self, client: JiraClient, project: str):
        issues = client.get_issues_by_project(project)
        self._send_json({"project": project, "count": len(issues), "issues": [self._format_issue(i) for i in issues]})
    
    def _get_projects(self, client: JiraClient):
        projects = client.get_all_projects()
        self._send_json({"count": len(projects), "projects": [{"key": p["key"], "name": p["name"]} for p in projects]})
    
    def _get_user(self, client: JiraClient):
        user = client.get_current_user()
        self._send_json({"name": user.get("displayName"), "email": user.get("emailAddress"), "accountId": user.get("accountId")})
    
    def _search_issues(self, client: JiraClient, jql: str):
        issues = client.search_issues(jql)
        self._send_json({"jql": jql, "count": len(issues), "issues": [self._format_issue(i) for i in issues]})
    
    def _transition_issue(self, client: JiraClient, issue_key: str, body: dict):
        import requests
        session = requests.Session()
        session.auth = client.config.auth
        session.headers.update(client.config.headers)
        
        url = f"{client.config.base_url}/rest/api/3/issue/{issue_key}/transitions"
        
        if not body.get("transitionId"):
            # Return available transitions
            response = session.get(url)
            transitions = response.json().get("transitions", [])
            self._send_json({"issue": issue_key, "transitions": [{"id": t["id"], "name": t["name"]} for t in transitions]})
            return
        
        payload = {"transition": {"id": body.get("transitionId")}}
        response = session.post(url, json=payload)
        self._send_json({"success": response.status_code in [200, 204], "issue": issue_key})
    
    def _update_issue(self, client: JiraClient, issue_key: str, body: dict):
        fields = {}
        if body.get("summary"):
            fields["summary"] = body["summary"]
        if body.get("assignee"):
            fields["assignee"] = {"accountId": body["assignee"]}
        if body.get("description"):
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": body["description"]}]}]
            }
        client.update_issue(issue_key, fields)
        self._send_json({"success": True, "updated": issue_key})
    
    def _format_issue(self, issue: dict) -> dict:
        fields = issue.get("fields", {})
        return {
            "key": issue.get("key"),
            "summary": fields.get("summary"),
            "status": fields.get("status", {}).get("name"),
            "assignee": fields.get("assignee", {}).get("displayName") if fields.get("assignee") else None,
            "priority": fields.get("priority", {}).get("name") if fields.get("priority") else None,
        }
    
    # ===== MCP SSE Methods =====
    
    def _get_mcp_client_from_path(self) -> JiraClient:
        """Get Jira client from MCP path token."""
        parsed = urlparse(self.path)
        parts = parsed.path.strip('/').split('/')
        
        if len(parts) >= 2:
            token = parts[-1]
            creds = decode_token(token)
            if creds:
                config = JiraConfig(
                    base_url=creds.get("base_url"),
                    email=creds.get("email"),
                    api_token=creds.get("api_token")
                )
                return JiraClient(config)
        return None
    
    def _get_token_from_path(self) -> str:
        """Extract token from URL path."""
        parsed = urlparse(self.path)
        parts = parsed.path.strip('/').split('/')
        if len(parts) >= 2:
            return parts[-1]
        return None
    
    def _handle_mcp_sse(self):
        """Handle MCP SSE connection for mcp-remote."""
        token = self._get_token_from_path()
        if not token:
            self._send_json({"error": "Token required in URL"}, 401)
            return
        
        # Validate token format (don't validate Jira creds yet)
        creds = decode_token(token)
        if not creds:
            self._send_json({"error": "Invalid token format"}, 401)
            return
        
        # Build complete HTTP response manually and send via raw socket
        endpoint_url = f"https://jira-mcp.koveh.com/mcp/{token}"
        sse_data = f"event: endpoint\ndata: {endpoint_url}\n\n"
        
        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/event-stream\r\n"
            "Cache-Control: no-cache\r\n"
            "Connection: keep-alive\r\n"
            "X-Accel-Buffering: no\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "\r\n"
            f"{sse_data}"
        )
        
        # Send directly to socket (bypass buffered wfile)
        try:
            self.connection.sendall(response.encode('utf-8'))
            print(f"[MCP-SSE] Sent endpoint: {endpoint_url[:50]}...", flush=True)
            
            # Keep connection alive
            while True:
                time.sleep(15)
                self.connection.sendall(b":ping\n\n")
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            print(f"[MCP-SSE] Connection closed: {type(e).__name__}", flush=True)
    
    def _handle_mcp_message(self, body: dict):
        """Handle incoming MCP message."""
        client = self._get_mcp_client_from_path()
        if not client:
            self._send_json({"error": "Invalid token"}, 401)
            return
        
        response = self._process_mcp_request(client, body)
        self._send_json(response)
    
    def _process_mcp_request(self, client: JiraClient, request: dict) -> dict:
        """Process MCP request."""
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
                result = {"tools": self._get_mcp_tools()}
            elif method == "tools/call":
                result = self._call_mcp_tool(client, params)
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
    
    def _get_mcp_tools(self) -> list:
        """Get MCP tools list."""
        return [
            {"name": "jira_get_projects", "description": "Get all Jira projects", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "jira_get_issues", "description": "Get issues from project", "inputSchema": {"type": "object", "properties": {"project_key": {"type": "string"}, "max_results": {"type": "integer", "default": 50}}, "required": ["project_key"]}},
            {"name": "jira_get_issue", "description": "Get issue details", "inputSchema": {"type": "object", "properties": {"issue_key": {"type": "string"}}, "required": ["issue_key"]}},
            {"name": "jira_create_issue", "description": "Create new issue", "inputSchema": {"type": "object", "properties": {"project_key": {"type": "string"}, "summary": {"type": "string"}, "description": {"type": "string"}, "issue_type": {"type": "string", "default": "Task"}}, "required": ["project_key", "summary"]}},
            {"name": "jira_update_issue", "description": "Update issue", "inputSchema": {"type": "object", "properties": {"issue_key": {"type": "string"}, "summary": {"type": "string"}, "description": {"type": "string"}}, "required": ["issue_key"]}},
            {"name": "jira_delete_issue", "description": "Delete issue", "inputSchema": {"type": "object", "properties": {"issue_key": {"type": "string"}}, "required": ["issue_key"]}},
            {"name": "jira_search", "description": "Search with JQL", "inputSchema": {"type": "object", "properties": {"jql": {"type": "string"}, "max_results": {"type": "integer", "default": 50}}, "required": ["jql"]}},
            {"name": "jira_get_current_user", "description": "Get current user", "inputSchema": {"type": "object", "properties": {}}}
        ]
    
    def _call_mcp_tool(self, client: JiraClient, params: dict) -> dict:
        """Execute MCP tool."""
        name = params.get("name")
        args = params.get("arguments", {})
        result = None
        
        if name == "jira_get_projects":
            projects = client.get_all_projects()
            result = [{"key": p["key"], "name": p["name"]} for p in projects]
        elif name == "jira_get_issues":
            issues = client.get_issues_by_project(args["project_key"], args.get("max_results", 50))
            result = [{"key": i["key"], "summary": i.get("fields", {}).get("summary"), "status": i.get("fields", {}).get("status", {}).get("name")} for i in issues if i.get("fields")]
        elif name == "jira_get_issue":
            issue = client.get_issue(args["issue_key"])
            fields = issue["fields"]
            result = {"key": issue["key"], "summary": fields.get("summary"), "status": fields.get("status", {}).get("name"), "description": extract_description(fields.get("description"))}
        elif name == "jira_create_issue":
            issue = client.create_issue(args["project_key"], args["summary"], args.get("description", ""), args.get("issue_type", "Task"))
            result = {"key": issue.get("key"), "id": issue.get("id")}
        elif name == "jira_update_issue":
            fields = {}
            if args.get("summary"): fields["summary"] = args["summary"]
            if args.get("description"): fields["description"] = {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": args["description"]}]}]}
            client.update_issue(args["issue_key"], fields)
            result = {"status": "updated", "key": args["issue_key"]}
        elif name == "jira_delete_issue":
            client.delete_issue(args["issue_key"])
            result = {"status": "deleted", "key": args["issue_key"]}
        elif name == "jira_search":
            issues = client.search_issues(args["jql"], args.get("max_results", 50))
            result = [{"key": i["key"], "summary": i.get("fields", {}).get("summary")} for i in issues if i.get("fields")]
        elif name == "jira_get_current_user":
            result = client.get_current_user()
        else:
            raise ValueError(f"Unknown tool: {name}")
        
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
    
    def _serve_dashboard(self):
        html = """<!DOCTYPE html>
<html>
<head>
    <title>Jira MCP - koveh.com</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'JetBrains Mono', 'SF Mono', monospace; background: linear-gradient(135deg, #0f0f23 0%, #1a1a2e 50%, #16213e 100%); color: #e0e0e0; min-height: 100vh; }
        .container { max-width: 900px; margin: 0 auto; padding: 40px 20px; }
        h1 { font-size: 2.5rem; background: linear-gradient(90deg, #00d4ff, #7c3aed, #f472b6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 8px; }
        .subtitle { color: #8b949e; margin-bottom: 40px; }
        .card { background: rgba(22, 27, 34, 0.8); backdrop-filter: blur(10px); border: 1px solid #30363d; border-radius: 12px; padding: 24px; margin-bottom: 24px; }
        .card h2 { color: #58a6ff; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
        .card h2::before { content: ''; width: 4px; height: 16px; background: linear-gradient(180deg, #00d4ff, #7c3aed); border-radius: 2px; }
        input, button { font-family: inherit; font-size: 14px; }
        input { background: #0d1117; border: 1px solid #30363d; color: #e0e0e0; padding: 12px 16px; border-radius: 8px; width: 100%; margin-bottom: 12px; }
        input:focus { outline: none; border-color: #58a6ff; box-shadow: 0 0 0 3px rgba(88, 166, 255, 0.1); }
        input::placeholder { color: #6e7681; }
        .btn { background: linear-gradient(90deg, #238636, #2ea043); color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-weight: 600; transition: all 0.2s; }
        .btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(35, 134, 54, 0.4); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-secondary { background: linear-gradient(90deg, #30363d, #3d444d); }
        .btn-danger { background: linear-gradient(90deg, #da3633, #f85149); }
        .hidden { display: none; }
        .issue { display: flex; align-items: center; padding: 16px; border-bottom: 1px solid #21262d; transition: background 0.2s; }
        .issue:hover { background: rgba(88, 166, 255, 0.05); }
        .issue:last-child { border-bottom: none; }
        .issue-key { background: linear-gradient(90deg, #238636, #2ea043); color: white; padding: 4px 10px; border-radius: 6px; font-weight: 600; font-size: 12px; margin-right: 16px; }
        .issue-summary { flex: 1; }
        .issue-status { background: #21262d; padding: 4px 10px; border-radius: 6px; font-size: 12px; color: #8b949e; }
        .status-done { background: rgba(35, 134, 54, 0.2); color: #3fb950; }
        .status-progress { background: rgba(31, 111, 235, 0.2); color: #58a6ff; }
        .api-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
        .api-item { background: #21262d; padding: 12px 16px; border-radius: 8px; display: flex; align-items: center; gap: 12px; }
        .method { padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
        .get { background: #238636; color: white; }
        .post { background: #1f6feb; color: white; }
        .put { background: #9e6a03; color: white; }
        .delete { background: #da3633; color: white; }
        code { background: #30363d; padding: 2px 8px; border-radius: 4px; font-size: 13px; }
        #output { background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 16px; font-family: 'JetBrains Mono', monospace; font-size: 13px; white-space: pre-wrap; max-height: 300px; overflow-y: auto; color: #7ee787; }
        .connected { color: #3fb950; }
        .error { color: #f85149; }
        .flex { display: flex; gap: 12px; }
        .flex-1 { flex: 1; }
        .actions { display: flex; gap: 8px; margin-top: 16px; }
        .info-box { background: rgba(88, 166, 255, 0.1); border: 1px solid rgba(88, 166, 255, 0.3); border-radius: 8px; padding: 16px; margin-bottom: 24px; }
        .info-box p { color: #8b949e; font-size: 14px; line-height: 1.6; }
        .info-box a { color: #58a6ff; }
        .logo { font-size: 3rem; margin-bottom: 16px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">🔌</div>
        <h1>Jira MCP Integration</h1>
        <p class="subtitle">Connect AI agents to Jira • Open Source • koveh.com</p>
        
        <div class="info-box">
            <p>Cursor AI and other agents write amazing code. In enterprises, tasks are given in Jira, GitHub Issues, Azure DevOps. AI needs access to such instruments.</p>
            <p style="margin-top: 8px;"><strong>We don't store any data.</strong> Your credentials are used only for API requests.</p>
        </div>
        
        <div class="card" id="auth-card">
            <h2>Connect to Jira</h2>
            <input type="text" id="base_url" placeholder="Jira URL (e.g., https://your-domain.atlassian.net)">
            <input type="email" id="email" placeholder="Your Jira email">
            <input type="password" id="api_token" placeholder="API Token (from id.atlassian.com/manage-profile/security/api-tokens)">
            <button class="btn" onclick="connect()">Connect</button>
            <p id="auth-status" style="margin-top: 12px; font-size: 13px;"></p>
        </div>
        
        <div class="card hidden" id="user-card">
            <h2>Connected</h2>
            <p>👤 <span id="user-name"></span> (<span id="user-email"></span>)</p>
            <p style="margin-top: 8px; font-size: 12px; color: #6e7681;">Account ID: <code id="user-account"></code></p>
            <button class="btn btn-secondary" onclick="disconnect()" style="margin-top: 12px;">Disconnect</button>
        </div>
        
        <div class="card hidden" id="projects-card">
            <h2>Projects</h2>
            <div id="projects">Loading...</div>
        </div>
        
        <div class="card hidden" id="issues-card">
            <h2>Issues</h2>
            <div class="flex" style="margin-bottom: 16px;">
                <input type="text" id="project-key" placeholder="Project key (e.g., PROJ)" class="flex-1" style="margin-bottom: 0;">
                <button class="btn btn-secondary" onclick="loadIssues()">Load</button>
            </div>
            <div id="issues"></div>
            <div class="actions">
                <button class="btn" onclick="createIssue()">➕ Create Issue</button>
            </div>
        </div>
        
        <div class="card">
            <h2>API Endpoints</h2>
            <div class="api-grid">
                <div class="api-item"><span class="method post">POST</span><code>/api/connect</code></div>
                <div class="api-item"><span class="method get">GET</span><code>/api/user</code></div>
                <div class="api-item"><span class="method get">GET</span><code>/api/projects</code></div>
                <div class="api-item"><span class="method get">GET</span><code>/api/issues?project=KEY</code></div>
                <div class="api-item"><span class="method get">GET</span><code>/api/issue/KEY</code></div>
                <div class="api-item"><span class="method post">POST</span><code>/api/issues</code></div>
                <div class="api-item"><span class="method put">PUT</span><code>/api/issue/KEY</code></div>
                <div class="api-item"><span class="method delete">DELETE</span><code>/api/issue/KEY</code></div>
                <div class="api-item"><span class="method get">GET</span><code>/api/search?jql=...</code></div>
            </div>
        </div>
        
        <div class="card">
            <h2>Output</h2>
            <pre id="output">Ready to connect...</pre>
        </div>
        
        <div class="card hidden" id="mcp-config-card">
            <h2>🎉 Your Cursor MCP Config</h2>
            <p style="color: #3fb950; font-size: 13px; margin-bottom: 12px;">Copy this to <code>~/.cursor/mcp.json</code> and restart Cursor:</p>
            <pre id="mcp-config" style="background: #0d1117; padding: 16px; border-radius: 8px; font-size: 12px; color: #e0e0e0; overflow-x: auto; border: 1px solid #238636;"></pre>
            <button class="btn" onclick="copyMcpConfig()" style="margin-top: 12px;">📋 Copy Config</button>
        </div>
        
        <div class="card">
            <h2>How to Use</h2>
            
            <h3 style="color: #58a6ff; font-size: 13px; margin: 16px 0 8px;">Option 1: Remote MCP in Cursor ⭐ Recommended</h3>
            <p style="color: #8b949e; font-size: 13px; margin-bottom: 8px;">Connect above to get your personal MCP config. No installation needed!</p>
            
            <h3 style="color: #58a6ff; font-size: 13px; margin: 16px 0 8px;">Option 2: Web Dashboard</h3>
            <p style="color: #8b949e; font-size: 13px; margin-bottom: 16px;">Manage Jira tasks directly from this page.</p>
            
            <h3 style="color: #58a6ff; font-size: 13px; margin: 16px 0 8px;">Option 3: Local MCP</h3>
            <pre style="background: #0d1117; padding: 12px; border-radius: 6px; font-size: 12px; color: #e0e0e0; overflow-x: auto;">git clone https://github.com/Koveh/jira-mcp.git
pip install -r requirements.txt
# Then add to ~/.cursor/mcp.json with local path</pre>
            
            <p style="color: #6e7681; font-size: 12px; margin-top: 16px;">Get API token: <a href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank" style="color: #58a6ff;">id.atlassian.com/manage-profile/security/api-tokens</a></p>
        </div>
    </div>

    <script>
        let authToken = localStorage.getItem('jira_token');
        let currentProject = '';
        
        async function api(method, path, body) {
            const opts = { 
                method, 
                headers: { 'Content-Type': 'application/json' }
            };
            if (authToken) opts.headers['Authorization'] = 'Bearer ' + authToken;
            if (body) opts.body = JSON.stringify(body);
            const res = await fetch(path, opts);
            return res.json();
        }
        
        async function connect() {
            const base_url = document.getElementById('base_url').value;
            const email = document.getElementById('email').value;
            const api_token = document.getElementById('api_token').value;
            
            if (!base_url || !email || !api_token) {
                document.getElementById('auth-status').innerHTML = '<span class="error">All fields required</span>';
                return;
            }
            
            document.getElementById('auth-status').textContent = 'Connecting...';
            
            try {
                const data = await api('POST', '/api/connect', { base_url, email, api_token });
                if (data.error) {
                    document.getElementById('auth-status').innerHTML = '<span class="error">' + data.error + '</span>';
                    return;
                }
                
                authToken = data.token;
                localStorage.setItem('jira_token', authToken);
                if (data.cursor_config) {
                    localStorage.setItem('cursor_config', JSON.stringify(data.cursor_config));
                }
                
                document.getElementById('user-name').textContent = data.user;
                document.getElementById('user-email').textContent = data.email;
                document.getElementById('user-account').textContent = data.accountId;
                
                document.getElementById('auth-card').classList.add('hidden');
                document.getElementById('user-card').classList.remove('hidden');
                document.getElementById('projects-card').classList.remove('hidden');
                document.getElementById('issues-card').classList.remove('hidden');
                
                // Show MCP config
                if (data.cursor_config) {
                    document.getElementById('mcp-config').textContent = JSON.stringify(data.cursor_config, null, 2);
                    document.getElementById('mcp-config-card').classList.remove('hidden');
                }
                
                log(data);
                loadProjects();
            } catch (e) {
                document.getElementById('auth-status').innerHTML = '<span class="error">Connection failed: ' + e.message + '</span>';
            }
        }
        
        function disconnect() {
            authToken = null;
            localStorage.removeItem('jira_token');
            localStorage.removeItem('cursor_config');
            document.getElementById('auth-card').classList.remove('hidden');
            document.getElementById('user-card').classList.add('hidden');
            document.getElementById('projects-card').classList.add('hidden');
            document.getElementById('issues-card').classList.add('hidden');
            document.getElementById('mcp-config-card').classList.add('hidden');
            log({status: 'disconnected'});
        }
        
        function copyMcpConfig() {
            const config = document.getElementById('mcp-config').textContent;
            navigator.clipboard.writeText(config).then(() => {
                alert('Copied! Paste to ~/.cursor/mcp.json and restart Cursor');
            });
        }
        
        async function loadProjects() {
            const data = await api('GET', '/api/projects');
            document.getElementById('projects').innerHTML = data.projects ? data.projects.map(p => 
                `<div class="issue" onclick="selectProject('${p.key}')"><span class="issue-key">${p.key}</span><span class="issue-summary">${p.name}</span></div>`
            ).join('') : '<span class="error">' + (data.error || 'Failed to load') + '</span>';
            log(data);
        }
        
        function selectProject(key) {
            document.getElementById('project-key').value = key;
            currentProject = key;
            loadIssues();
        }
        
        async function loadIssues() {
            const project = document.getElementById('project-key').value;
            if (!project) return;
            currentProject = project;
            
            const data = await api('GET', '/api/issues?project=' + project);
            document.getElementById('issues').innerHTML = data.issues ? data.issues.map(i => {
                const statusClass = i.status === 'Done' || i.status === 'Готово' ? 'status-done' : i.status === 'In Progress' || i.status === 'В работе' ? 'status-progress' : '';
                return `<div class="issue">
                    <span class="issue-key">${i.key}</span>
                    <span class="issue-summary">${i.summary}</span>
                    <span class="issue-status ${statusClass}">${i.status}</span>
                    <button class="btn btn-danger" style="margin-left:8px;padding:6px 12px;font-size:12px;" onclick="deleteIssue('${i.key}')">🗑️</button>
                </div>`;
            }).join('') : '<span class="error">' + (data.error || 'No issues') + '</span>';
            log(data);
        }
        
        async function createIssue() {
            const summary = prompt('Issue summary:');
            if (!summary || !currentProject) return;
            const data = await api('POST', '/api/issues', { project: currentProject, summary });
            log(data);
            loadIssues();
        }
        
        async function deleteIssue(key) {
            if (!confirm('Delete ' + key + '?')) return;
            const data = await api('DELETE', '/api/issue/' + key);
            log(data);
            loadIssues();
        }
        
        function log(data) {
            document.getElementById('output').textContent = JSON.stringify(data, null, 2);
        }
        
        // Auto-reconnect if token exists
        if (authToken) {
            api('GET', '/api/user').then(data => {
                if (!data.error) {
                    document.getElementById('user-name').textContent = data.name;
                    document.getElementById('user-email').textContent = data.email;
                    document.getElementById('user-account').textContent = data.accountId;
                    document.getElementById('auth-card').classList.add('hidden');
                    document.getElementById('user-card').classList.remove('hidden');
                    document.getElementById('projects-card').classList.remove('hidden');
                    document.getElementById('issues-card').classList.remove('hidden');
                    
                    // Show saved MCP config
                    const savedConfig = localStorage.getItem('cursor_config');
                    if (savedConfig) {
                        document.getElementById('mcp-config').textContent = savedConfig;
                        document.getElementById('mcp-config-card').classList.remove('hidden');
                    }
                    
                    loadProjects();
                } else {
                    disconnect();
                }
            });
        }
    </script>
</body>
</html>"""
        self._send_html(html)
    
    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {args[0]}")


def main():
    port = 4200
    server = HTTPServer(("0.0.0.0", port), JiraHTTPHandler)
    print(f"""
╔═══════════════════════════════════════════════════════════════╗
║           JIRA MCP HTTP SERVER                                ║
║           https://jira-mcp.koveh.com                          ║
╠═══════════════════════════════════════════════════════════════╣
║  🌐 Dashboard:  http://localhost:{port}                        ║
║  📡 API Base:   http://localhost:{port}/api                    ║
║  ❤️  Health:    http://localhost:{port}/health                 ║
╠═══════════════════════════════════════════════════════════════╣
║  Users provide their own Jira credentials.                    ║
║  We don't store any data.                                     ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    server.serve_forever()


if __name__ == "__main__":
    main()
