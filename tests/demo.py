#!/usr/bin/env python3
"""
Jira MCP Demo - Full CRUD operations demonstration.
Shows: List → Create → Assign → Complete → List → Delete → List

Usage:
    export JIRA_BASE_URL=https://your-domain.atlassian.net
    export JIRA_EMAIL=your-email@example.com
    export JIRA_API_TOKEN=your-api-token
    python demo.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jira_client import JiraClient, JiraConfig, format_issue


# Configuration from environment variables
JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "JIRAMCP")


def print_header(step: int, title: str):
    print(f"\n{'='*70}")
    print(f"STEP {step}: {title}")
    print(f"{'='*70}\n")


def print_issues(issues: list, label: str = ""):
    if label:
        print(f"📋 {label}")
    print(f"   Total: {len(issues)} issues\n")
    for issue in issues:
        status = issue.get("fields", {}).get("status", {}).get("name", "Unknown")
        summary = issue.get("fields", {}).get("summary", "No summary")
        assignee = issue.get("fields", {}).get("assignee")
        assignee_name = assignee.get("displayName") if assignee else "Unassigned"
        
        emoji = "✅" if status in ["Done", "Готово"] else "🔄" if status == "In Progress" else "📝"
        print(f"   {emoji} [{issue['key']}] {summary}")
        print(f"      Status: {status} | Assignee: {assignee_name}")
    print()


def main():
    if not all([JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN]):
        print("Error: Set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN environment variables")
        sys.exit(1)
    
    print("\n" + "🚀"*35)
    print("       JIRA MCP INTEGRATION DEMO")
    print("🚀"*35)
    
    config = JiraConfig(base_url=JIRA_BASE_URL, email=JIRA_EMAIL, api_token=JIRA_API_TOKEN)
    client = JiraClient(config)
    
    user = client.get_current_user()
    account_id = user.get("accountId")
    print(f"\n✅ Connected as: {user.get('displayName')} ({user.get('emailAddress')})")
    
    # Get project key
    projects = client.get_all_projects()
    project_key = PROJECT_KEY if any(p['key'] == PROJECT_KEY for p in projects) else projects[0]['key'] if projects else None
    
    if not project_key:
        print("No projects found!")
        return
    
    # ===== STEP 1: Show all current tasks =====
    print_header(1, "SHOW ALL CURRENT TASKS")
    issues = client.get_issues_by_project(project_key, max_results=20)
    print_issues(issues, f"Current issues in {project_key}:")
    initial_count = len(issues)
    
    # ===== STEP 2: Create a new task =====
    print_header(2, "CREATE A NEW TASK")
    new_issue = client.create_issue(
        project_key=project_key,
        summary="[DEMO] Test MCP Integration - Auto-created task",
        description="This task was created by the Jira MCP demo script.",
        issue_type="Task"
    )
    new_key = new_issue.get("key")
    print(f"✅ Created new issue: {new_key}")
    
    # ===== STEP 3: Assign the task to user =====
    print_header(3, "ASSIGN TASK TO ME")
    client.update_issue(new_key, {"assignee": {"accountId": account_id}})
    print(f"✅ Assigned {new_key} to: {user.get('displayName')}")
    
    # ===== STEP 4: Show updated list =====
    print_header(4, "SHOW ALL TASKS AFTER CREATION")
    issues = client.get_issues_by_project(project_key, max_results=20)
    print_issues(issues, f"Issues in {project_key} after changes:")
    
    # ===== STEP 5: Delete the task =====
    print_header(5, "DELETE THE DEMO TASK")
    print(f"🗑️  Deleting issue: {new_key}")
    client.delete_issue(new_key)
    print(f"✅ Deleted: {new_key}")
    
    # ===== STEP 6: Show final state =====
    print_header(6, "SHOW ALL TASKS AFTER DELETION")
    issues = client.get_issues_by_project(project_key, max_results=20)
    print_issues(issues, f"Final state of {project_key}:")
    
    print("\n" + "="*70)
    print("📊 DEMO COMPLETED SUCCESSFULLY!")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
