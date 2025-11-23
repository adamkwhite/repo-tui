# repo-tui

A Textual-based TUI for viewing GitHub repositories with SonarCloud integration.

## Project Structure

```
src/repo_tui/
├── app.py          # Main Textual app, screens, keybindings
├── config.py       # Configuration loading from TOML
├── data.py         # GitHub and SonarCloud API clients
├── launcher.py     # Windows Terminal / Claude Code launcher
├── models.py       # Dataclasses (Issue, SonarStatus, RepoOverview)
└── widgets/
    ├── repo_list.py   # Repository list with expand/collapse
    └── issue_list.py  # Issue list with selection tracking
```

## Key Patterns

- Uses `gh` CLI for GitHub API (must be authenticated)
- SonarCloud API is public, no auth needed
- Windows Terminal launched via `wt.exe` from WSL
- Claude Code path: `/home/adam/.claude/local/claude`
