# Agentbox 开发进度 & 待办事项

> 最后更新: 2026-06-10

## 已完成的功能

### 核心框架
- agentbox/agentbox/__init__.py - 包初始化，版本号
- agentbox/agentbox/config.py - 配置管理
- agentbox/agentbox/state.py - 会话状态追踪
- agentbox/pyproject.toml - 项目配置，已添加 ag CLI 别名

### Agent 运行器
- agentbox/agentbox/agents/runner.py - AgentRunner (单agent/compose/team/compare/sandbox)

### Tmux / Sandbox / Pipeline
- agentbox/agentbox/tmux_mgr/manager.py - TmuxManager
- agentbox/agentbox/sandbox/manager.py - SandboxManager
- agentbox/agentbox/orchestrator/pipeline.py - Pipeline/PipelineStep/StepType + dev/research/compare pipeline
- agentbox/agentbox/orchestrator/engine.py - Orchestrator (顺序/并行执行, 上下文传递, 状态持久化)

### CLI 命令 (全部在 cli.py)
claude/codex/aider/goose/opencode, run, compose, team, compare, ask, pipeline, sandbox, session, config, init, list

### Docker 模板
Dockerfile.base, Dockerfile.claude, Dockerfile.codex, Dockerfile.aider

---

## 未完成的功能

### 1. [关键] workflow/core.py - 工作流引擎

workflow/__init__.py 已创建(导出WorkflowEngine)，但 core.py 一直未能成功创建

需要实现的 WorkflowEngine 类方法:
- load_agents_md(project_path) - 加载AGENTS.md
- inject_agents_md(prompt, project_path) - 注入AGENTS.md到prompt
- is_git_repo(project_path) - 检查是否git仓库
- get_git_diff(project_path) - 获取git diff
- get_git_diff_stats(project_path) - 获取diff统计
- print_diff_summary(project_path) - 打印格式化diff摘要
- merge_changes(project_path, message) - git add -A + commit
- discard_changes(project_path) - git checkout + clean
- detect_test_command(project_path) - 自动检测测试命令(pytest/npm test/go test/cargo test)
- run_tests(project_path, command) - 执行测试
- print_test_results(results) - 格式化输出测试结果
- ask(prompt, agent_id, project_path, use_sandbox) - 完整ask工作流(注入AGENTS.md->创建session->启动agent)
- review(project_path, auto_test, test_cmd) - 审查工作流(diff+test+merge/discard)

导入依赖:
from ..config import get_agent_config
from ..sandbox import SandboxManager
from ..state import register_window
from ..tmux_mgr import TmuxManager

### 2. [中等] 更新 cli.py - 新增命令

需要添加:
- 修改ask命令: 使用WorkflowEngine.ask()替代AgentRunner.run_agent()，添加--sandbox,--test选项
- review命令: diff + test + merge/discard交互
- diff命令: 显示git diff摘要
- merge命令: git add -A + commit
- test命令: 运行项目测试
- 添加导入: from .workflow import WorkflowEngine

### 3. [低] Docker Compose多容器编排

新建文件:
- agentbox/agentbox/compose/__init__.py
- agentbox/agentbox/compose/manager.py - DockerComposeManager(generate_compose/up/down/logs/status)

CLI命令组(用stack避免与compose命令冲突):
- agentbox stack up AGENTS... - 启动多agent compose栈
- agentbox stack down - 停止compose栈

---

## 已知问题

1. workflow/__init__.py导入了WorkflowEngine但core.py不存在，会导致import错误
   临时修复: 改为 try/except ImportError

2. ask命令目前用AgentRunner.run_agent()，增强后应改为WorkflowEngine.ask()

3. Docker Compose命令组不能命名compose(已被占用)，用stack

---

## 安装测试

cd /Users/wenbeijiu/Desktop/glm/agentbox
pip3 install -e .
ag --help
agentbox review --help
agentbox diff --help
agentbox test --help
agentbox stack --help
