# Implementation Plan

[Overview]
Complete the agentbox workflow engine by creating the missing workflow/core.py, updating CLI commands, and adding Docker Compose support.

The agentbox CLI currently has working agent management (claude/codex/aider/goose/opencode), compose, team, compare, pipeline, sandbox, and session commands. The orchestrator (pipeline.py + engine.py) is complete. The `ag` CLI alias has been added to pyproject.toml. What's missing is: (1) workflow/core.py - the workflow engine that implements ask→sandbox→agent→diff→merge pipeline with AGENTS.md injection, git diff summary, merge/discard, and test running, (2) CLI integration for review/diff/merge/test commands, (3) Docker Compose multi-container orchestration.

[Types]
No new type definitions needed. WorkflowEngine uses existing dict-based config patterns.

[Files]
- NEW: agentbox/agentbox/workflow/core.py - WorkflowEngine class with AGENTS.md injection, git operations, test runner, ask workflow, review workflow
- MODIFY: agentbox/agentbox/cli.py - Add review/diff/merge/test commands, enhance ask command to use WorkflowEngine  
- MODIFY: agentbox/agentbox/workflow/__init__.py - Already exists, no changes needed
- NEW: agentbox/agentbox/compose/__init__.py - Docker Compose manager
- NEW: agentbox/agentbox/compose/manager.py - DockerComposeManager class

[Functions]
- NEW: WorkflowEngine.load_agents_md() - Load AGENTS.md from project
- NEW: WorkflowEngine.inject_agents_md() - Inject AGENTS.md into prompt
- NEW: WorkflowEngine.is_git_repo() - Check if project is git repo
- NEW: WorkflowEngine.get_git_diff() - Get git diff output
- NEW: WorkflowEngine.get_git_diff_stats() - Get diff statistics
- NEW: WorkflowEngine.print_diff_summary() - Print formatted diff
- NEW: WorkflowEngine.merge_changes() - git add -A + commit
- NEW: WorkflowEngine.discard_changes() - git checkout + clean
- NEW: WorkflowEngine.detect_test_command() - Auto-detect test framework
- NEW: WorkflowEngine.run_tests() - Execute tests
- NEW: WorkflowEngine.print_test_results() - Print test output
- NEW: WorkflowEngine.ask() - Full ask workflow
- NEW: WorkflowEngine.review() - Full review workflow (diff + test + merge/discard)
- NEW: DockerComposeManager.generate_compose() - Generate docker-compose.yml
- NEW: DockerComposeManager.up() - Start compose stack
- NEW: DockerComposeManager.down() - Stop compose stack
- MODIFY: cli.py ask command - Use WorkflowEngine.ask() with AGENTS.md injection
- ADD: cli.py review command - Call WorkflowEngine.review()
- ADD: cli.py diff command - Call WorkflowEngine.print_diff_summary()
- ADD: cli.py merge command - Call WorkflowEngine.merge_changes()
- ADD: cli.py test command - Call WorkflowEngine.run_tests()
- ADD: cli.py compose up/down commands - Call DockerComposeManager

[Classes]
- NEW: WorkflowEngine (agentbox/agentbox/workflow/core.py) - 15+ static/instance methods for complete workflow
- NEW: DockerComposeManager (agentbox/agentbox/compose/manager.py) - Docker Compose orchestration

[Dependencies]
No new dependencies needed. All functionality uses existing packages (rich, click, subprocess, json, pathlib).

[Testing]
- Verify `ag --help` works (ag alias)
- Verify `agentbox pipeline --help` works (existing)
- Verify `agentbox ask --help` shows enhanced options
- Verify `agentbox review --help` works
- Verify `agentbox diff --help` works
- Verify `agentbox test --help` works
- Verify `agentbox merge --help` works
- Verify `agentbox compose up --help` works (Docker Compose)

[Implementation Order]
1. Create workflow/core.py (CRITICAL - this is the file that keeps failing to create)
2. Update cli.py to add new commands and enhance ask
3. Create compose/manager.py for Docker Compose support
4. Reinstall and test all commands