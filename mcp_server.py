#!/usr/bin/env python3
"""
Jira MCP Server - Model Context Protocol server for AI agents to interact with Jira.
Fast and well-structured Python implementation.

Usage:
    python mcp_server.py
"""
import asyncio
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from jira_client import JiraClient, JiraConfig


# Global client instance
_client: JiraClient | None = None


def get_client() -> JiraClient:
    """Get the Jira client, raise if not connected."""
    if _client is None:
        raise ValueError("Not connected to Jira. Call jira_connect first.")
    return _client


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


# Create server instance
server = Server("jira-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Jira tools."""
    return [
        Tool(
            name="jira_connect",
            description="Connect to a Jira instance using email and API token",
            inputSchema={
                "type": "object",
                "properties": {
                    "base_url": {"type": "string", "description": "Jira instance URL (e.g., https://your-domain.atlassian.net)"},
                    "email": {"type": "string", "description": "Your Jira email"},
                    "api_token": {"type": "string", "description": "Your Jira API token"}
                },
                "required": ["base_url", "email", "api_token"]
            }
        ),
        Tool(
            name="jira_get_projects",
            description="Get list of all accessible Jira projects",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="jira_get_issues",
            description="Get all issues for a specific project",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_key": {"type": "string", "description": "Project key (e.g., PROJ)"},
                    "max_results": {"type": "integer", "description": "Maximum results to return", "default": 50}
                },
                "required": ["project_key"]
            }
        ),
        Tool(
            name="jira_get_issue",
            description="Get detailed information about a specific issue",
            inputSchema={
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string", "description": "Issue key (e.g., PROJ-123)"}
                },
                "required": ["issue_key"]
            }
        ),
        Tool(
            name="jira_create_issue",
            description="Create a new issue/task in Jira",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_key": {"type": "string", "description": "Project key"},
                    "summary": {"type": "string", "description": "Issue title/summary"},
                    "description": {"type": "string", "description": "Issue description"},
                    "issue_type": {"type": "string", "description": "Issue type", "default": "Task"}
                },
                "required": ["project_key", "summary"]
            }
        ),
        Tool(
            name="jira_update_issue",
            description="Update an existing issue",
            inputSchema={
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string", "description": "Issue key to update"},
                    "summary": {"type": "string", "description": "New summary"},
                    "description": {"type": "string", "description": "New description"}
                },
                "required": ["issue_key"]
            }
        ),
        Tool(
            name="jira_delete_issue",
            description="Delete an issue from Jira",
            inputSchema={
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string", "description": "Issue key to delete"}
                },
                "required": ["issue_key"]
            }
        ),
        Tool(
            name="jira_search",
            description="Search issues using JQL (Jira Query Language)",
            inputSchema={
                "type": "object",
                "properties": {
                    "jql": {"type": "string", "description": "JQL query string"},
                    "max_results": {"type": "integer", "description": "Maximum results", "default": 50}
                },
                "required": ["jql"]
            }
        ),
        Tool(
            name="jira_get_current_user",
            description="Get information about the currently authenticated user",
            inputSchema={"type": "object", "properties": {}}
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    global _client
    
    result = {}
    
    if name == "jira_connect":
        config = JiraConfig(
            base_url=arguments["base_url"],
            email=arguments["email"],
            api_token=arguments["api_token"]
        )
        _client = JiraClient(config)
        user = _client.get_current_user()
        result = {
            "status": "connected",
            "user": user.get("displayName"),
            "email": user.get("emailAddress")
        }
    
    elif name == "jira_get_projects":
        client = get_client()
        projects = client.get_all_projects()
        result = [{"key": p["key"], "name": p["name"], "id": p["id"]} for p in projects]
    
    elif name == "jira_get_issues":
        client = get_client()
        issues = client.get_issues_by_project(
            arguments["project_key"],
            arguments.get("max_results", 50)
        )
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
    
    elif name == "jira_get_issue":
        client = get_client()
        issue = client.get_issue(arguments["issue_key"])
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
    
    elif name == "jira_create_issue":
        client = get_client()
        issue = client.create_issue(
            arguments["project_key"],
            arguments["summary"],
            arguments.get("description", ""),
            arguments.get("issue_type", "Task")
        )
        result = {"key": issue.get("key"), "id": issue.get("id"), "self": issue.get("self")}
    
    elif name == "jira_update_issue":
        client = get_client()
        fields = {}
        if arguments.get("summary"):
            fields["summary"] = arguments["summary"]
        if arguments.get("description"):
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": arguments["description"]}]}]
            }
        client.update_issue(arguments["issue_key"], fields)
        result = {"status": "updated", "key": arguments["issue_key"]}
    
    elif name == "jira_delete_issue":
        client = get_client()
        client.delete_issue(arguments["issue_key"])
        result = {"status": "deleted", "key": arguments["issue_key"]}
    
    elif name == "jira_search":
        client = get_client()
        issues = client.search_issues(
            arguments["jql"],
            arguments.get("max_results", 50)
        )
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
    
    elif name == "jira_get_current_user":
        client = get_client()
        result = client.get_current_user()
    
    else:
        result = {"error": f"Unknown tool: {name}"}
    
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
