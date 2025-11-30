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

## Configuration

Config file: `~/.repo-overview.json`

```json
{
  "included_repos": [],
  "excluded_repos": [],
  "sonarcloud_org": null,
  "github_org": null,
  "local_code_path": "~/Code"
}
```

**Filtering Logic:**
- **`included_repos`**: If set (non-empty), ONLY show these repos (whitelist mode)
  - Use this when you have many repos but only want to monitor a specific subset
  - Example: `["repo-tui", "job-agent", "ip-project"]`
- **`excluded_repos`**: If `included_repos` is empty, show all repos EXCEPT these (blacklist mode)
  - Use this when you want to see most repos but hide a few
  - Example: `["archived-project", "test-repo"]`
- **`local_code_path`**: Where your repos are checked out locally (used for git status checks)
- **`sonarcloud_org`**: Optional, only needed if using `-s` flag for SonarCloud integration
- **`github_org`**: Optional, filter to repos from a specific GitHub organization

**Porting to another machine:**
1. Copy the repo-tui directory
2. Update `local_code_path` to match the new machine
3. Set `included_repos` if you only want a subset of your 150+ repos
4. Ensure `gh` CLI is authenticated: `gh auth login`

## View Modes

The app supports two view modes (switch with `1` and `2` keys):
- **List View** (default) - Traditional list with expand/collapse
- **Grid View** - 3-column card-based grid layout

Both views share the same data model and support all actions (refresh, open, launch Claude, etc.).

## Development & Testing

### Running the App

- **Production**: `./run.sh`
- **Development (hot reload)**: `./dev.sh` (uses watchdog to auto-restart on file changes)
- **Safe mode (guaranteed cleanup)**: `./run-safe.sh` (uses bash trap for terminal cleanup)

### Running Tests

```bash
./test.sh              # Run all tests
./test.sh tests/test_app.py -v  # Run specific test file
```

Test structure:
- `tests/test_app.py` - Unit tests for initialization and basic attributes
- `tests/test_app_integration.py` - Integration tests using Textual's Pilot API

### Development Dependencies

The project uses `requirements-dev.txt` for development and CI dependencies:
- `pytest>=7.4.0`, `pytest-cov>=4.1.0`, `pytest-html>=4.1.0` - Testing framework
- `pytest-asyncio>=0.21.0` - **Required** for async Textual tests
- `mypy>=1.5.0` - Type checking
- `types-PyYAML>=6.0.0` - **Required** for mypy to type-check YAML imports
- `ruff>=0.3.0` - Linting and formatting

Install with:
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Testing Patterns

**Always mock data fetching to prevent real API calls:**
```python
from unittest.mock import AsyncMock, patch

with patch('repo_tui.app.fetch_all_repos', new_callable=AsyncMock) as mock_fetch:
    mock_fetch.return_value = sample_repos
    app = RepoOverviewApp()
    async with app.run_test() as pilot:
        # Your test code
```

**Using Pilot API for user simulation:**
```python
await pilot.press("2")  # Simulate key press
await pilot.pause()     # Wait for messages to process
await pilot.click("#widget-id")  # Simulate clicks
```

**Testing view switches:**
```python
# Set repos before testing
app.repos = sample_repos
current_widget = app._get_current_widget()
if current_widget:
    current_widget.set_repos(sample_repos)

# Switch views
await pilot.press("2")  # Switch to grid
await pilot.pause()
assert app.view_mode == "grid"
```

## Critical Issues & Solutions

### Mouse Tracking Leak

**Problem:** Textual enables mouse tracking with escape codes (`\x1b[?1000h`, `\x1b[?1003h`) that persist after app exit, corrupting terminal sessions.

**Symptoms:** After running the app, mouse movements appear as codes like `?2048;0$y` in your terminal.

**Solutions:**
1. Use `./run-safe.sh` which includes bash `trap` for guaranteed cleanup
2. `./test.sh` also includes cleanup trap
3. If terminal gets corrupted: `printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?25h'`

**Why this happens:**
- Python's `atexit` runs too late (after Textual re-enables mouse)
- Textual's lifecycle methods (`_on_exit_app`, `_shutdown`) aren't sufficient
- Shell-level `trap` is the most reliable solution

### Git Status Tracking

**Implementation:** Only tracks uncommitted changes to **tracked files**, ignoring untracked files.

```python
# Check for uncommitted changes (ignoring untracked files)
status_lines = stdout.decode().strip().split('\n')
has_changes = any(
    line and not line.startswith('??')  # Ignore untracked files
    for line in status_lines
)
```

This prevents false positives for repos with untracked files (like `.claude/` directories).

## Common Gotchas

### 1. `self.mouse_over` Must Not Be Boolean

**Wrong:**
```python
self.mouse_over = False  # BREAKS - AttributeError when Textual calls .post_message()
```

**Correct:**
```python
# Don't set it at all, or set to None
# Textual manages this as a Widget reference
```

### 2. Grid View Needs Explicit Data Setting

When switching to grid view, you must call `set_repos()`:

```python
self.view_mode = "grid"
await self.recompose()
new_widget = self._get_current_widget()
if new_widget:
    new_widget.set_repos(self.repos)  # REQUIRED
```

### 3. Virtual Environments Required (Ubuntu 24.04+)

Always use descriptively named virtual environments:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Textual Testing Requires pytest-asyncio

All Textual tests must be async:
```python
@pytest.mark.asyncio
async def test_something():
    async with app.run_test() as pilot:
        # Test code
```

## Architecture Notes

### Widget Lifecycle

1. **Mount** - Widget added to DOM, `on_mount()` fires
2. **Compose** - `compose()` yields child widgets (using `yield`, not context managers)
3. **Unmount** - Widget removed from DOM, cleanup happens
4. **Recompose** - Rebuilds widget tree (used for view switching)

### View Switching Flow

1. Store selected repo (if any)
2. Change `self.view_mode`
3. Call `await self.recompose()` to rebuild widget tree
4. Get new widget and call `set_repos()`
5. Optionally restore selection (list view only)

### Data Flow

1. `fetch_all_repos()` loads basic repo info in batches
2. Lazy loading: issue/PR details loaded on expand
3. Git status checked per repo if local path exists
4. SonarCloud checked only if enabled (`-s` flag)

### Null Safety in Widget Operations

**Critical Pattern:** Always check if widget exists before calling methods on it:

```python
# BAD - Can crash if widget is None
current_widget = self._get_current_widget()
current_widget.set_repos(self.repos)  # May crash!

# GOOD - Safe null check
current_widget = self._get_current_widget()
if current_widget:
    current_widget.set_repos(self.repos)
```

This pattern is especially important in:
- `action_sonar_all()` (src/repo_tui/app.py:838-840)
- View switching operations
- Any operation that calls `_get_current_widget()`

## Current Status

**Branch:** main (all PRs merged as of 2025-11-29)

**Recent Changes:**
- Fixed CI/CD pipeline by adding `requirements-dev.txt` with all dev dependencies
- Added null safety check in Sonar All display update to prevent crashes
- Applied ruff formatting across all Python files
- All linting, type checking, and test checks now pass in CI

**Technology Stack:**
- Python 3.13+ (specified in pyproject.toml)
- Textual 0.40.0+ - Terminal UI framework
- Rich 13.0.0+ - Terminal formatting
- PyYAML 6.0+ - YAML config support
- pytest-asyncio - Async test support (critical for Textual tests)

**Known Issues:**
- None currently - all CI checks passing

**Next Steps:**
- Monitor SonarCloud integration for any edge cases
- Consider adding more comprehensive test coverage for widget operations
- Potential future enhancement: Support both SonarCloud.io and self-hosted SonarQube simultaneously
