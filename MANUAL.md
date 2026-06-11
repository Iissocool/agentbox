# Agentbox Manual — v0.3.0

> 🧊 One command to rule them all: `ag`

## Quick Reference

| Command | Description |
|---------|-------------|
| `ag` | Interactive: pick an agent |
| `ag claude` | Run Claude in sandbox |
| `ag codex` | Run Codex in sandbox |
| `ag aider` | Run Aider in sandbox |
| `ag status` | Dashboard: sessions & sandboxes |
| `ag attach` | Reconnect to a session |
| `ag kill` | Kill session + sandbox |
| `ag logs` | View sandbox logs |
| `ag history` | Session history |

## Command Details

### Starting Agents

```bash
# Interactive picker
ag

# Direct agent shortcuts
ag claude                        # Claude Code in sandbox
ag codex                         # OpenAI Codex in sandbox
ag aider                         # Aider in sandbox
ag goose                         # Goose in sandbox

# With prompt
ag claude -p "Fix the auth bug"

# With role
ag claude -r coder -p "Implement feature X"

# Any configured agent
ag run <agent_id> -p "prompt"
```

### Session Management

```bash
ag status                        # Dashboard: all sessions, sandboxes, agents
ag attach                        # Pick a session to attach to
ag attach ag-myproject           # Attach to specific session
ag kill                          # Pick a session to kill (also kills sandbox)
ag kill ag-myproject             # Kill specific session + sandbox
ag kill --all                    # Kill everything
ag history                       # View session history
```

### Sandbox Logs

```bash
ag logs                          # Pick a sandbox to view logs
ag logs claude-myproject         # View specific sandbox logs
ag logs claude-myproject --tail 100
```

### Multi-Agent

```bash
# Compose agents with roles
ag compose claude:coder codex:reviewer
ag compose claude:architect aider:test-writer -p "Build auth module"

# Run a team
ag team <team_id> -p "Build the API"

# Compare agents side by side
ag compare claude codex -p "Implement sorting"
```

### Workflow Shortcuts

```bash
ag ask "Why is this slow?"       # Ask an agent about your project
ag ask --test "Fix the bug"      # Ask agent to fix and run tests
ag diff                          # Git diff summary
ag diff --patch                  # Full diff
ag merge -m "Add feature X"     # Stage all and commit
ag review                        # Review changes, test, merge/discard
ag test                          # Run project tests
```

### Pipelines

```bash
ag pipeline dev "Add user auth"  # Plan → Code → Review
ag pipeline research "Rust vs Go" # Research → Summarize → Critique
ag pipeline compare "Optimize"   # Compare across agents
ag pipeline custom claude:plan codex:code claude:review -p "Build API"
```

### Configuration

```bash
ag config show                   # Show current config
ag config path                   # Config file location
ag config edit                   # Open in editor
ag config reset                  # Reset to defaults
ag list                          # List available agents & teams
ag init                          # Initialize agentbox in project
```

### Advanced

```bash
# Direct sandbox commands
ag sandbox exec claude-myproject bash -lic "ls /workspace"
ag sandbox exec -i claude-myproject bash   # Interactive shell
ag sandbox build claude          # Pre-build agent Docker image

# Docker Compose stacks
ag stack up claude codex
ag stack down
ag stack logs
ag stack status
```

## Architecture

```
ag (CLI entry point)
├── tmux session (ag-<project>)
│   ├── window: sb-claude → docker exec -it agentbox-claude-<project> claude
│   ├── window: sb-codex  → docker exec -it agentbox-codex-<project> codex
│   └── window: shell     → local shell
└── Docker containers
    ├── agentbox-claude-<project>  (ubuntu + claude + /workspace mount)
    └── agentbox-codex-<project>  (ubuntu + codex + /workspace mount)
```

## Sandbox Image Caching

1. First run: `ubuntu:22.04` → install agent → `docker commit` → `agentbox-claude:latest`
2. Second run: Reuse cached `agentbox-claude:latest` (instant start)
3. Container reuse: If same project container is running, reuse directly

## Session Recovery

If state is lost (e.g. `state.json` deleted), running `ag status` or `ag history`
will auto-recover sessions from Docker container labels.

## Tips

- `Ctrl+B` then `D` to detach from tmux (session keeps running)
- `ag attach` to reconnect
- `ag kill --all` to clean up everything
- Use `--no-attach` flag to start agents without entering tmux