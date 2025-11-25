# repo-tui

Terminal UI for GitHub repository overview with SonarCloud integration.

## Features

- **Repository List** - View all your GitHub repos with status indicators
  - Red: Failed SonarCloud quality gate or 10+ open issues
  - Yellow: Warning quality gate or 5+ issues
  - Blue: 1-4 open issues
  - Green: No issues
- **Expandable Issues** - Press `Space` to expand inline issues under a repo
- **Issue Details** - Press `e` to view full issue details in a modal
- **Claude Code Integration** - Press `c` to launch Claude Code in a new Windows Terminal tab
- **Quick Links** - Press `o` to open repo/issue in browser

## Requirements

- Python 3.12+
- `gh` CLI (authenticated)
- Windows Terminal (for Claude Code launcher)
- WSL/Ubuntu environment

## Installation

```bash
# Clone the repo
git clone https://github.com/adamkwhite/repo-tui.git
cd repo-tui

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Authenticate with GitHub
gh auth login
```

## Usage

```bash
# Run the TUI
./run.sh

# Or run directly
python -m repo_tui.app

# Development mode with hot reload
./dev.sh
```

## Keybindings

| Key | Action |
|-----|--------|
| `j/↓` | Move down |
| `k/↑` | Move up |
| `Tab` | Switch between repo list and issue list |
| `Space` | Expand/collapse repo issues |
| `e` | View issue details |
| `h/l` | Navigate issues in modal |
| `o` | Open in browser |
| `c` | Launch Claude Code |
| `r` | Refresh data |
| `s` | Toggle SonarCloud check |
| `?` | Help |
| `q` | Quit |

## Configuration

Create `~/.repo-overview.yaml` in your home directory (YAML format recommended for comments):

```yaml
# Repos to include (whitelist mode - if set, ONLY these repos are shown)
included_repos: []

# Repos to exclude (blacklist mode - only used if included_repos is empty)
excluded_repos: []

# SonarCloud organization (optional)
sonarcloud_org: null

# GitHub organization to fetch repos from (instead of personal repos)
github_org: null

# Local directory where repos are cloned
local_code_path: ~/Code
```

Or use JSON format (`~/.repo-overview.json`):

```json
{
  "included_repos": [],
  "excluded_repos": [],
  "sonarcloud_org": null,
  "github_org": null,
  "local_code_path": "~/Code"
}
```

### Configuration Options

- **`included_repos`**: Whitelist mode - if set, ONLY show these repos (useful for large organizations with 100+ repos)
  - Example: `["repo1", "repo2", "repo3"]`
  - Leave empty `[]` to show all repos (except those in `excluded_repos`)

- **`excluded_repos`**: Blacklist mode - hide specific repos (only used when `included_repos` is empty)
  - Example: `["archived-project", "test-repo"]`

- **`github_org`**: Fetch repos from a specific GitHub organization instead of personal repos
  - Example: `"my-company"`
  - Leave as `null` to fetch your personal repos

- **`sonarcloud_org`**: SonarCloud organization name (optional, only needed with `-s` flag)
  - Example: `"my-org"`

- **`local_code_path`**: Where your repos are cloned locally (used for git status checks)
  - Example: `"~/code"` or `"~/workspace"`

### Example Configurations

**Personal repos:**
```yaml
included_repos: []
excluded_repos:
  - old-fork
  - archived-project
sonarcloud_org: null
github_org: null
local_code_path: ~/Code
```

**Organization repos (grouped by feature with comments):**
```yaml
included_repos:
  # Authentication & Security
  - auth-service
  - user-management

  # API Services
  - api-gateway
  - customer-api
  - inventory-api

  # Frontend Applications
  - web-app
  - mobile-app
  - admin-portal

  # Infrastructure
  - terraform-configs
  - k8s-manifests

excluded_repos: []
sonarcloud_org: my-company
github_org: my-company
local_code_path: ~/work/projects
```

## License

MIT
