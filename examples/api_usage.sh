#!/bin/bash
# Jira MCP API Usage Examples
# Available at: https://jira-mcp.koveh.com

BASE_URL="https://jira-mcp.koveh.com"

# 1. Connect and get auth token
echo "=== Connect to Jira ==="
RESPONSE=$(curl -s -X POST "$BASE_URL/api/connect" \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "https://your-domain.atlassian.net",
    "email": "your-email@example.com",
    "api_token": "your-api-token"
  }')

echo "$RESPONSE"
TOKEN=$(echo "$RESPONSE" | grep -o '"token": "[^"]*"' | cut -d'"' -f4)

# 2. Get all projects
echo -e "\n=== Get Projects ==="
curl -s "$BASE_URL/api/projects" -H "Authorization: Bearer $TOKEN"

# 3. Get issues from a project
echo -e "\n\n=== Get Issues ==="
curl -s "$BASE_URL/api/issues?project=YOUR_PROJECT_KEY" -H "Authorization: Bearer $TOKEN"

# 4. Create a new issue
echo -e "\n\n=== Create Issue ==="
curl -s -X POST "$BASE_URL/api/issues" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project": "YOUR_PROJECT_KEY",
    "summary": "New task created via API",
    "description": "Task description"
  }'

# 5. Update an issue
echo -e "\n\n=== Update Issue ==="
curl -s -X PUT "$BASE_URL/api/issue/YOUR_ISSUE_KEY" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"summary": "Updated summary"}'

# 6. Delete an issue
echo -e "\n\n=== Delete Issue ==="
curl -s -X DELETE "$BASE_URL/api/issue/YOUR_ISSUE_KEY" \
  -H "Authorization: Bearer $TOKEN"

# 7. Search with JQL
echo -e "\n\n=== Search Issues ==="
curl -s "$BASE_URL/api/search?jql=status%20%3D%20%27In%20Progress%27" \
  -H "Authorization: Bearer $TOKEN"

