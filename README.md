# 🔌 Jira MCP Integration

**Cursor AI and other agents write amazing code.** In enterprises, tasks are given in instruments like Jira, GitHub Issues, Azure DevOps. AI needs access to such instruments.

This open-source solution helps AI agents work with Jira data.

## 🌐 Public Instance

**Available at https://jira-mcp.koveh.com**

Just provide your Jira credentials. We don't store any data.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   AI Agent      │────▶│   MCP Server    │────▶│   Jira Cloud    │
│  (Cursor/etc)   │◀────│   jira-mcp      │◀────│   REST API      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Features

- ✅ Get list of projects
- ✅ Get list of tasks with details
- ✅ Get specific task with descriptions
- ✅ Create new tickets
- ✅ Update existing tickets
- ✅ Delete tickets
- ✅ Search using JQL
- ✅ Assign tasks to users
- ✅ Transition task status

## Quick Start

### Option 1: Use Public Instance

Go to **https://jira-mcp.koveh.com** and connect with your Jira credentials.

### Option 2: Run with Docker

```bash
git clone https://github.com/Koveh/jira-mcp.git
cd jira-mcp
docker-compose up -d
```

Access at http://localhost:4200

### Option 3: Run Locally

```bash
git clone https://github.com/Koveh/jira-mcp.git
cd jira-mcp
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python http_server.py
```

## Get Jira API Token

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Copy the token

## Usage

### Add to Cursor IDE (Local MCP)

1. Clone this repo:
```bash
git clone https://github.com/Koveh/jira-mcp.git
cd jira-mcp
pip install -r requirements.txt
```

2. Get your Jira API token from: https://id.atlassian.com/manage-profile/security/api-tokens

3. Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "jira": {
      "command": "python",
      "args": ["/full/path/to/jira-mcp/mcp_server.py"],
      "env": {
        "JIRA_BASE_URL": "https://your-domain.atlassian.net",
        "JIRA_EMAIL": "your-email@example.com",
        "JIRA_API_TOKEN": "your-api-token-from-step-2"
      }
    }
  }
}
```

4. Restart Cursor (Cmd/Ctrl+Shift+P → "Developer: Reload Window")

You'll have these tools available:

| Tool | Description |
|------|-------------|
| `jira_connect` | Connect to Jira instance |
| `jira_get_projects` | List all projects |
| `jira_get_issues` | Get issues from project |
| `jira_get_issue` | Get specific issue details |
| `jira_create_issue` | Create new issue |
| `jira_update_issue` | Update existing issue |
| `jira_delete_issue` | Delete issue |
| `jira_search` | Search with JQL |
| `jira_get_current_user` | Get current user info |

### REST API Usage

```bash
# 1. Connect and get token
curl -X POST https://jira-mcp.koveh.com/api/connect \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "https://your-domain.atlassian.net",
    "email": "your-email@example.com",
    "api_token": "your-api-token"
  }'

# Response includes token for subsequent requests
# {"status": "connected", "token": "eyJ...", ...}

# 2. Use token for API calls
curl https://jira-mcp.koveh.com/api/projects \
  -H "Authorization: Bearer YOUR_TOKEN"

# 3. Create issue
curl -X POST https://jira-mcp.koveh.com/api/issues \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project": "PROJ", "summary": "New task"}'
```

### CLI Usage

```bash
export JIRA_BASE_URL=https://your-domain.atlassian.net
export JIRA_EMAIL=your-email@example.com
export JIRA_API_TOKEN=your-api-token

python cli.py whoami                    # Show current user
python cli.py projects                  # List projects
python cli.py list PROJ                 # List issues
python cli.py get PROJ-123              # Get issue details
python cli.py create PROJ "Summary"     # Create issue
python cli.py update PROJ-123 -s "New"  # Update issue
python cli.py delete PROJ-123           # Delete issue
python cli.py search "status='Done'"    # Search with JQL
```

### Python Client

```python
from jira_client import JiraClient, JiraConfig

config = JiraConfig(
    base_url="https://your-domain.atlassian.net",
    email="your-email@example.com",
    api_token="your-api-token"
)

client = JiraClient(config)

# Get projects
projects = client.get_all_projects()

# Create issue
issue = client.create_issue("PROJ", "Summary", "Description")

# Search
results = client.search_issues("status = 'In Progress'")
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/api/connect` | Connect and get token |
| GET | `/api/user` | Get current user |
| GET | `/api/projects` | List all projects |
| GET | `/api/issues?project=KEY` | Get project issues |
| GET | `/api/issue/KEY` | Get issue details |
| POST | `/api/issues` | Create issue |
| PUT | `/api/issue/KEY` | Update issue |
| DELETE | `/api/issue/KEY` | Delete issue |
| GET | `/api/search?jql=...` | Search with JQL |

## Project Structure

```
jira-mcp/
├── jira_client.py      # Core Jira API wrapper
├── mcp_server.py       # MCP server (stdio transport)
├── http_server.py      # HTTP/REST server
├── cli.py              # Command-line interface
├── Dockerfile          # Docker image
├── docker-compose.yml  # Docker Compose config
├── requirements.txt    # Python dependencies
├── examples/           # Usage examples
│   ├── cursor_mcp_config.json
│   └── api_usage.sh
└── tests/              # Test scripts
    ├── test_jira.py
    └── demo.py
```

## Self-Hosting with Docker

```bash
# Build and run
docker-compose up -d

# Or manually
docker build -t jira-mcp .
docker run -d -p 4200:4200 --name jira-mcp jira-mcp
```

### With nginx reverse proxy

```nginx
server {
    server_name jira-mcp.yourdomain.com;
    
    location / {
        proxy_pass http://127.0.0.1:4200;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### SSL with Certbot

```bash
certbot --nginx -d jira-mcp.yourdomain.com
```

## Security

- 🔒 We don't store any credentials or data
- 🔑 Credentials are only used for direct Jira API calls
- 📤 Use API tokens (not passwords)
- 🔄 Tokens can be revoked anytime at id.atlassian.com

## License

MIT

## Author

**DHW Team** - [koveh.com](https://koveh.com)

---

Made with ❤️ for the AI-powered development community
