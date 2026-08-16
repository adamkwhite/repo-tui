# repo-tui

Terminal UI for GitHub repository overview with SonarCloud integration.

## Features

- **Repository List** - View all your GitHub repos with status indicators
  - Red: Failed SonarCloud quality gate (ERROR) or 5+ critical issues
  - Yellow: Warning quality gate, uncommitted changes, or 1-4 critical issues
  - Blue: Open pull requests
  - Green: Clean
- **Two Views** - List view (`1`) and 3-column grid view (`2`)
- **Expandable Issues** - Press `Space` to expand inline issues under a repo
- **Issue Details** - Press `e` to view full issue details in a modal
- **Claude Code Integration** - Press `c` to launch Claude Code in a new Windows Terminal tab
- **Dependabot Bulk Merge** - Press `D` to merge Dependabot PRs across all repos
- **Quick Links** - Press `o` to open repo/issue in browser
- **Privacy Mode** - Press `p` (or pass `--privacy`) to mask private repo names, descriptions, and issue/PR titles for screen-shares and demos (public repos are never masked)

Critical issue labels: `bug`, `security`, `breaking-change`, `ci-failure`, `priority-high`, `status-blocked`.

## Requirements

- Python 3.13+ (the version CI tests against)
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

# Safe mode - guaranteed terminal cleanup on exit (see Troubleshooting)
./run-safe.sh
```

### CLI Flags

| Flag | Description |
|------|-------------|
| `-s`, `--sonar` | Check SonarCloud/SonarQube status on startup |
| `-p`, `--privacy` | Start with privacy mode enabled |

## Keybindings

| Key | Action |
|-----|--------|
| `j/↓` `k/↑` | Move down / up |
| `h/←` `l/→` | Move left / right (grid view) |
| `1` / `2` | Switch to list view / grid view |
| `Space` | Expand/collapse repo issues |
| `e` | View issue details |
| `o` | Open in browser |
| `c` | Launch Claude Code |
| `r` / `R` | Refresh current repo / all repos |
| `s` / `S` | Check SonarCloud for current repo / all repos |
| `p` | Toggle privacy mode (mask private repo details) |
| `D` | Bulk-merge Dependabot PRs across all repos |
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

# Self-hosted SonarQube (optional)
sonar_url: null  # e.g., https://sonar.company.com
sonar_token: null  # Direct token (not recommended for security)
sonar_token_pass: null  # Pass path (e.g., work/sonarqube) - recommended

# Claude Code launcher
claude_command: claude  # Claude CLI command or full path

# Privacy mode (mask private repo details on startup; toggle at runtime with `p`)
privacy_mode: false

# Debug settings
debug: false  # Enable debug logging to ~/.cache/repo-tui/logs/
```

Or use JSON format (`~/.repo-overview.json`):

```json
{
  "included_repos": [],
  "excluded_repos": [],
  "sonarcloud_org": null,
  "github_org": null,
  "local_code_path": "~/Code",
  "sonar_url": null,
  "sonar_token": null,
  "sonar_token_pass": null,
  "claude_command": "claude",
  "debug": false
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

- **`sonar_url`**: Self-hosted SonarQube URL (leave as `null` for public SonarCloud)
  - Example: `"https://sonar.company.com"`

- **`sonar_token`**: SonarQube authentication token (not recommended - use `sonar_token_pass` instead)

- **`sonar_token_pass`**: Path to token in `pass` password manager (recommended for security)
  - Example: `"work/sonarqube"`
  - Token will be retrieved via `pass work/sonarqube` command

- **`claude_command`**: Command to launch Claude Code (used when pressing `c` key)
  - Example: `"claude"` (if in PATH) or `"/home/user/.claude/local/claude"` (full path)
  - Useful for machines with different Claude aliases or non-standard installations

- **`debug`**: Enable debug logging for troubleshooting
  - Set to `true` to enable detailed logging:
  - Logs are written to `~/.cache/repo-tui/logs/`, one file per subsystem:

    | File | Contents |
    |------|----------|
    | `pr-fetch.log` | `gh pr list` calls and their results |
    | `sonar-check.log` | which project keys were tried for each repo |
    | `sonar-fetch.log` | raw SonarQube API requests and responses |
    | `claude-launch.log` | the `wt.exe` command line and launch errors |

  - Names follow `<subsystem>-<action>.log`. They are declared in the
    `DebugLog` enum in `src/repo_tui/config.py` and written only through
    `Config.debug_log()` — adding a log means adding an enum member, which
    the test suite checks against the convention.
  - Default: `false`

### Example Configurations

**Personal repos, no SonarCloud:**
```yaml
included_repos: []
excluded_repos:
  - old-fork
  - archived-project
sonarcloud_org: null
github_org: null
local_code_path: ~/Code
```

**Personal repos with SonarCloud:**

When you sign into SonarCloud with GitHub, your personal organization key is your
GitHub username. Both values below are the same string for that reason. Run with
`./run.sh -s` to actually check quality gates.

```yaml
included_repos:
  - invoice-parser
  - trailhead-api
  - dotfiles
excluded_repos: []

# SonarCloud org key — https://sonarcloud.io/organizations/jrivera-dev
sonarcloud_org: jrivera-dev

# Leave null for personal repos; `gh repo list` already scopes to your account.
github_org: null

local_code_path: ~/Code
```

**Organization repos with self-hosted SonarQube:**

```yaml
included_repos:
  - billing-service
  - customer-api
excluded_repos: []

# Bound to the GitHub org, so the keys match.
github_org: northwind-labs
sonarcloud_org: northwind-labs

# Self-hosted instance instead of sonarcloud.io. `sonar_token_pass` is a path
# in the `pass` password store, not the token itself: `pass insert work/sonarqube`
sonar_url: https://sonarqube.northwind-labs.io
sonar_token_pass: work/sonarqube

local_code_path: ~/work/northwind
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

## Development

```bash
pip install -r requirements-dev.txt

./test.sh                       # Run all tests
./test.sh tests/test_app.py -v  # Run a single test file
make lint                       # ruff + mypy (see Makefile for all targets)
```

## Troubleshooting

**Mouse codes appear in the terminal after exit** (e.g. `?2048;0$y`) - Textual's mouse
tracking escape codes can outlive the process. Use `./run-safe.sh`, which traps exit and
resets the terminal. To fix an already-corrupted session:

```bash
printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?25h'
```

## License

MIT
