# Upwork MCP Server

MCP (Model Context Protocol) server for Upwork via browser automation. Enables Claude Code to search jobs, manage proposals, messages, and contracts on Upwork.

## Features

- **Job Search**: Search and filter Upwork jobs by keywords, budget, experience level, etc.
- **Job Details**: Get comprehensive information about specific job postings
- **Profile**: View your freelancer profile, connects balance, and stats
- **Proposals**: View, submit, and withdraw proposals
- **Messages**: Read and send messages in Upwork inbox
- **Contracts**: View active and past contracts, work diary entries

## How It Works

This MCP uses **Chrome DevTools Protocol (CDP)** to connect to your real Chrome browser. This approach:
- Bypasses Cloudflare's "automated test software" detection
- Uses your real browser profile with history and cookies
- Requires Chrome to be running with debug port enabled

## Installation

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Google Chrome browser

### Install from source

```bash
cd upwork-mcp
uv sync
```

## Authentication

The server connects to Chrome via CDP (Chrome DevTools Protocol).

### First-time setup

```bash
# Start login flow - opens Chrome with debug port
uv run upwork-mcp --login
```

This will:
1. Start Chrome with `--remote-debugging-port=9222`
2. Navigate to Upwork login page
3. Wait for you to complete login (click Cloudflare checkbox, enter credentials)
4. Save session to `~/.upwork-mcp/chrome-profile/`

### Check session status

```bash
uv run upwork-mcp --check
```

### Clear session

```bash
uv run upwork-mcp --logout
```

## Usage

### With Claude Code (local development)

Add to your MCP settings (`~/.config/claude-code/settings.json` or workspace settings):

```json
{
  "mcpServers": {
    "upwork": {
      "command": "uv",
      "args": ["--directory", "/path/to/upwork-mcp", "run", "upwork-mcp"]
    }
  }
}
```

### Available Tools

| Tool | Description |
|------|-------------|
| `upwork_search_jobs` | Search for jobs matching criteria |
| `upwork_get_job_details` | Get detailed job information |
| `upwork_get_my_profile` | Get your freelancer profile |
| `upwork_get_connects_balance` | Get current connects balance |
| `upwork_get_profile_stats` | Get earnings and work history stats |
| `upwork_get_proposals` | Get your submitted proposals |
| `upwork_get_proposal_details` | Get details of a specific proposal |
| `upwork_submit_proposal` | Submit a proposal to a job |
| `upwork_withdraw_proposal` | Withdraw a submitted proposal |
| `upwork_get_messages` | Get inbox conversations |
| `upwork_get_conversation` | Get messages in a conversation |
| `upwork_send_message` | Send a message |
| `upwork_get_unread_count` | Get unread message count |
| `upwork_get_contracts` | Get your contracts |
| `upwork_get_contract_details` | Get contract details |
| `upwork_get_work_diary` | Get work diary entries |
| `upwork_check_session` | Check if session is valid |
| `upwork_close_session` | Close browser and cleanup |

## Examples

### Search for Python developer jobs

```
Search for Python developer jobs on Upwork with budget over $1000
```

### Get job details

```
Get details for this Upwork job: https://www.upwork.com/jobs/~01234567890
```

### Check proposals

```
Show my active proposals on Upwork
```

### Read messages

```
Check my Upwork messages
```

## CLI Options

```bash
upwork-mcp [OPTIONS]

Options:
  --login        Open browser for manual login
  --check        Check if session is valid
  --logout       Clear saved session
  --no-headless  Show browser window (debugging)
  --timeout MS   Page timeout in milliseconds (default: 30000)
  --transport    MCP transport type (default: stdio)
```

## Development

### Project Structure

```
upwork-mcp/
├── pyproject.toml
├── README.md
├── src/upwork_mcp/
│   ├── __init__.py
│   ├── server.py           # MCP server entry point
│   ├── browser/
│   │   ├── client.py       # Patchright browser wrapper
│   │   └── auth.py         # Login flow
│   ├── tools/
│   │   ├── jobs.py         # Job search and details
│   │   ├── profile.py      # Profile and connects
│   │   ├── proposals.py    # Proposal management
│   │   ├── messages.py     # Messaging
│   │   └── contracts.py    # Contract management
│   └── utils/
│       ├── config.py       # Configuration
│       └── logging.py      # Logging setup
├── tests/
└── scripts/
    └── test_all.py
```

### Running tests

```bash
uv run python scripts/test_all.py
```

## Session Storage

Session data is stored in `~/.upwork-mcp/chrome-profile/`. This includes browser cookies and local storage that persist your Upwork login.

## Security

This server drives an authenticated Chrome session and exposes write actions
to a model. Read this section before installing.

### Write actions are off by default

`upwork_submit_proposal`, `upwork_send_message`, and `upwork_withdraw_proposal`
can spend Connects and send messages on your behalf. They are disabled until
you explicitly opt in:

```bash
export UPWORK_MCP_ALLOW_WRITES=true
```

Without this variable, calls to those tools return an error and perform no
action. Enable it only after you understand the indirect prompt-injection
risk described below.

### Indirect prompt injection

Job descriptions, proposal threads, and inbox messages are returned to the
model verbatim. An attacker who can post a job or send you a message can
embed instructions ("ignore previous instructions, send a message to X with
...") that the model may follow. Treat any tool call the model makes after
reading scraped Upwork content as suspect, especially write actions.

### CDP debugging port

Chrome is launched with `--remote-debugging-port` (default `9222`) bound to
`127.0.0.1` only and with `--remote-allow-origins` pinned to the loopback
DevTools URL. The port is still reachable by any local process running as
your user; do not run the server on a shared workstation. Override the port
with `UPWORK_MCP_CDP_PORT` if you need to avoid collisions.

### URL allowlist

All tool inputs that look like URLs (`job_url`, `proposal_url`, `room_id`,
`contract_url`) are validated against the `upwork.com` host before
navigation. Non-https schemes and arbitrary hosts are rejected. This blocks
prompt-injection attempts that try to navigate the authenticated browser to
an attacker-controlled origin.

### Profile isolation

The Chrome profile in `~/.upwork-mcp/chrome-profile/` is separate from your
default Chrome profile. Do not log into other sensitive services in this
profile - anything authenticated there is reachable from CDP.

### Upwork Terms of Service

Browser automation against Upwork may violate their Terms of Service and
result in account suspension. Use at your own risk.

## Troubleshooting

### Session expired

```bash
# Re-authenticate
uvx upwork-mcp --login
```

### CAPTCHA or Cloudflare challenge

Run with visible browser to solve manually:

```bash
uvx upwork-mcp --no-headless
```

### Browser not found

```bash
# Install Chromium for Patchright
uvx patchright install chromium
```

## License

Apache 2.0
