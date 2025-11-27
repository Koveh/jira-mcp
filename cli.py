#!/usr/bin/env python3
"""
Jira CLI - Command-line interface for Jira operations.
"""
import argparse
import json
import os
import sys

from jira_client import JiraClient, JiraConfig, format_issue, format_issue_detailed


def get_client_from_env() -> JiraClient:
    """Create Jira client from environment variables."""
    config = JiraConfig(
        base_url=os.environ.get("JIRA_BASE_URL", ""),
        email=os.environ.get("JIRA_EMAIL", ""),
        api_token=os.environ.get("JIRA_API_TOKEN", "")
    )
    if not all([config.base_url, config.email, config.api_token]):
        print("Error: Set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN environment variables")
        sys.exit(1)
    return JiraClient(config)


def cmd_create(args):
    """Create a new issue."""
    client = get_client_from_env()
    result = client.create_issue(args.project, args.summary, args.description or "", args.type)
    print(f"Created: {result.get('key')}")


def cmd_delete(args):
    """Delete an issue."""
    client = get_client_from_env()
    client.delete_issue(args.issue)
    print(f"Deleted: {args.issue}")


def cmd_get(args):
    """Get issue details."""
    client = get_client_from_env()
    issue = client.get_issue(args.issue)
    print(format_issue_detailed(issue))


def cmd_list(args):
    """List issues in a project."""
    client = get_client_from_env()
    issues = client.get_issues_by_project(args.project, args.max)
    for issue in issues:
        print(format_issue(issue))


def cmd_projects(args):
    """List all projects."""
    client = get_client_from_env()
    projects = client.get_all_projects()
    for p in projects:
        print(f"{p['key']}: {p['name']}")


def cmd_search(args):
    """Search issues using JQL."""
    client = get_client_from_env()
    issues = client.search_issues(args.jql, args.max)
    for issue in issues:
        print(format_issue(issue))


def cmd_update(args):
    """Update an issue."""
    client = get_client_from_env()
    fields = {}
    if args.summary:
        fields["summary"] = args.summary
    client.update_issue(args.issue, fields)
    print(f"Updated: {args.issue}")


def cmd_whoami(args):
    """Show current user."""
    client = get_client_from_env()
    user = client.get_current_user()
    print(f"User: {user.get('displayName')} ({user.get('emailAddress')})")


def main():
    parser = argparse.ArgumentParser(description="Jira CLI")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # create
    p = subparsers.add_parser("create", help="Create a new issue")
    p.add_argument("project", help="Project key")
    p.add_argument("summary", help="Issue summary")
    p.add_argument("-d", "--description", help="Issue description")
    p.add_argument("-t", "--type", default="Task", help="Issue type (default: Task)")
    p.set_defaults(func=cmd_create)
    
    # delete
    p = subparsers.add_parser("delete", help="Delete an issue")
    p.add_argument("issue", help="Issue key")
    p.set_defaults(func=cmd_delete)
    
    # get
    p = subparsers.add_parser("get", help="Get issue details")
    p.add_argument("issue", help="Issue key")
    p.set_defaults(func=cmd_get)
    
    # list
    p = subparsers.add_parser("list", help="List issues in a project")
    p.add_argument("project", help="Project key")
    p.add_argument("-m", "--max", type=int, default=50, help="Max results")
    p.set_defaults(func=cmd_list)
    
    # projects
    p = subparsers.add_parser("projects", help="List all projects")
    p.set_defaults(func=cmd_projects)
    
    # search
    p = subparsers.add_parser("search", help="Search issues using JQL")
    p.add_argument("jql", help="JQL query")
    p.add_argument("-m", "--max", type=int, default=50, help="Max results")
    p.set_defaults(func=cmd_search)
    
    # update
    p = subparsers.add_parser("update", help="Update an issue")
    p.add_argument("issue", help="Issue key")
    p.add_argument("-s", "--summary", help="New summary")
    p.set_defaults(func=cmd_update)
    
    # whoami
    p = subparsers.add_parser("whoami", help="Show current user")
    p.set_defaults(func=cmd_whoami)
    
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    
    args.func(args)


if __name__ == "__main__":
    main()

