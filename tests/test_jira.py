"""
Test script for Jira integration.
Tests connection and basic operations.

Usage:
    export JIRA_BASE_URL=https://your-domain.atlassian.net
    export JIRA_EMAIL=your-email@example.com
    export JIRA_API_TOKEN=your-api-token
    python test_jira.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jira_client import JiraClient, JiraConfig, format_issue, format_issue_detailed


# Configuration from environment variables
JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "JIRAMCP")


def main():
    if not all([JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN]):
        print("Error: Set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN environment variables")
        sys.exit(1)
    
    config = JiraConfig(
        base_url=JIRA_BASE_URL,
        email=JIRA_EMAIL,
        api_token=JIRA_API_TOKEN
    )
    client = JiraClient(config)
    
    # 1. Test connection - get current user
    print("=" * 60)
    print("1. Testing connection...")
    print("=" * 60)
    user = client.get_current_user()
    print(f"Connected as: {user.get('displayName')} ({user.get('emailAddress')})")
    print(f"Account ID: {user.get('accountId')}")
    
    # 2. Get all projects
    print("\n" + "=" * 60)
    print("2. Getting all projects...")
    print("=" * 60)
    projects = client.get_all_projects()
    for p in projects:
        print(f"  - {p['key']}: {p['name']}")
    
    if not projects:
        print("No projects found.")
        return
    
    # 3. Get issues from first project or specified project
    project_key = PROJECT_KEY if any(p['key'] == PROJECT_KEY for p in projects) else projects[0]['key']
    
    print(f"\n" + "=" * 60)
    print(f"3. Getting issues from {project_key}...")
    print("=" * 60)
    issues = client.get_issues_by_project(project_key, max_results=10)
    for issue in issues:
        print(f"  {format_issue(issue)}")
    
    if issues:
        # 4. Get detailed view of first issue
        print("\n" + "=" * 60)
        print("4. Getting detailed view of first issue...")
        print("=" * 60)
        detailed = client.get_issue(issues[0]['key'])
        print(format_issue_detailed(detailed))
    
    print("\n" + "=" * 60)
    print("All tests completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
