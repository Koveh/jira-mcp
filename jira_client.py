"""
Jira API Client - Fast and well-structured Python client for Jira operations.
Available at jira.koveh.com as MCP.
"""
import requests
from dataclasses import dataclass
from typing import Optional


@dataclass
class JiraConfig:
    """Configuration for Jira API connection."""
    base_url: str
    email: str
    api_token: str
    
    @property
    def auth(self) -> tuple:
        return (self.email, self.api_token)
    
    @property
    def headers(self) -> dict:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }


class JiraClient:
    """Client for interacting with Jira REST API."""
    
    def __init__(self, config: JiraConfig):
        self.config = config
        self.session = requests.Session()
        self.session.auth = config.auth
        self.session.headers.update(config.headers)
    
    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make HTTP request to Jira API."""
        url = f"{self.config.base_url}/rest/api/3/{endpoint}"
        response = self.session.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json() if response.text else {}
    
    # ==================== Board Operations ====================
    
    def create_project(self, key: str, name: str, project_type: str = "software", lead_account_id: str = None) -> dict:
        """Create a new Jira project."""
        payload = {
            "key": key,
            "name": name,
            "projectTypeKey": project_type,
            "projectTemplateKey": "com.pyxis.greenhopper.jira:gh-simplified-kanban-classic"
        }
        if lead_account_id:
            payload["leadAccountId"] = lead_account_id
        return self._request("POST", "project", json=payload)
    
    def get_all_projects(self) -> list:
        """Get list of all projects."""
        result = self._request("GET", "project/search")
        return result.get("values", [])
    
    def get_boards(self) -> list:
        """Get all boards."""
        url = f"{self.config.base_url}/rest/agile/1.0/board"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json().get("values", [])
    
    # ==================== Issue Operations ====================
    
    def create_issue(self, project_key: str, summary: str, description: str = "", issue_type: str = "Task") -> dict:
        """Create a new issue/task."""
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [{
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}]
                    }]
                },
                "issuetype": {"name": issue_type}
            }
        }
        return self._request("POST", "issue", json=payload)
    
    def delete_issue(self, issue_key: str) -> dict:
        """Delete an issue."""
        return self._request("DELETE", f"issue/{issue_key}")
    
    def get_issue(self, issue_key: str, expand: str = "") -> dict:
        """Get a specific issue with full details."""
        params = {"expand": expand} if expand else {}
        return self._request("GET", f"issue/{issue_key}", params=params)
    
    def get_issues_by_project(self, project_key: str, max_results: int = 50) -> list:
        """Get all issues for a project."""
        jql = f"project = {project_key}"
        return self.search_issues(jql, max_results)
    
    def search_issues(self, jql: str, max_results: int = 50) -> list:
        """Search issues using JQL."""
        import urllib.parse
        encoded_jql = urllib.parse.quote(jql)
        fields = "summary,status,assignee,priority,description,created,updated"
        endpoint = f"search/jql?jql={encoded_jql}&maxResults={max_results}&fields={fields}"
        result = self._request("GET", endpoint)
        return result.get("issues", [])
    
    def update_issue(self, issue_key: str, fields: dict) -> dict:
        """Update an existing issue."""
        payload = {"fields": fields}
        return self._request("PUT", f"issue/{issue_key}", json=payload)
    
    # ==================== User Operations ====================
    
    def get_current_user(self) -> dict:
        """Get current authenticated user info."""
        return self._request("GET", "myself")
    
    def get_users_assignable_to_project(self, project_key: str) -> list:
        """Get users assignable to a project."""
        return self._request("GET", f"user/assignable/search?project={project_key}")


def format_issue(issue: dict) -> str:
    """Format issue for display."""
    fields = issue.get("fields", {})
    status = fields.get("status", {}).get("name", "Unknown")
    summary = fields.get("summary", "No summary")
    assignee = fields.get("assignee", {})
    assignee_name = assignee.get("displayName", "Unassigned") if assignee else "Unassigned"
    
    return f"[{issue['key']}] {summary} | Status: {status} | Assignee: {assignee_name}"


def format_issue_detailed(issue: dict) -> str:
    """Format issue with full details."""
    fields = issue.get("fields", {})
    lines = [
        f"Key: {issue['key']}",
        f"Summary: {fields.get('summary', 'N/A')}",
        f"Status: {fields.get('status', {}).get('name', 'N/A')}",
        f"Priority: {fields.get('priority', {}).get('name', 'N/A')}",
        f"Created: {fields.get('created', 'N/A')}",
        f"Updated: {fields.get('updated', 'N/A')}",
    ]
    
    desc = fields.get("description")
    if desc:
        desc_text = extract_text_from_adf(desc)
        lines.append(f"Description: {desc_text}")
    
    return "\n".join(lines)


def extract_text_from_adf(adf: dict) -> str:
    """Extract plain text from Atlassian Document Format."""
    if not adf or not isinstance(adf, dict):
        return ""
    
    texts = []
    for content in adf.get("content", []):
        for item in content.get("content", []):
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
    return " ".join(texts)

