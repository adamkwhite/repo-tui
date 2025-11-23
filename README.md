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
git clone https://github.com/adamhl8/repo-tui.git
cd repo-tui

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install in development mode
pip install -e ".[dev]"
```

## Usage

```bash
# Run the TUI
repo-tui

# Or run directly
python -m repo_tui.app
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

Create `~/.config/repo-tui/config.toml`:

```toml
[github]
# Repos to exclude from list
excluded_repos = ["old-project", "fork-i-dont-care-about"]

[sonarcloud]
# Your SonarCloud organization
organization = "your-org"

[local]
# Where your repos are cloned locally
code_path = "/home/username/Code"
```

## License

MIT
