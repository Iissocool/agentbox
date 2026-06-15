# 🧊 Agentbox 架构分层说明

> 版本: 0.3.0 | 最后更新: 2025-06-15

## 目录

- [整体架构](#整体架构)
- [分层设计](#分层设计)
- [核心模块详解](#核心模块详解)
- [数据流](#数据流)
- [配置体系](#配置体系)
- [状态管理](#状态管理)
- [Docker 镜像体系](#docker-镜像体系)
- [命令路由](#命令路由)

---

## 整体架构

Agentbox 是一个 AI Agent 编排沙盒系统，核心设计理念：**所有 Agent 都运行在 Docker 容器中，通过 tmux 会话管理交互**。

```
┌─────────────────────────────────────────────────────────────┐
│                        用户入口                              │
│                  ag (CLI) / REPL 交互式                       │
├─────────────────────────────────────────────────────────────┤
│                     命令调度层 (CLI)                         │
│            cli.py — Click 命令组 + 命令面板                   │
├──────┬──────┬──────┬──────┬──────┬──────┬──────┬───────────┤
│Agent │Multi │Chat  │Work  │Pipe  │Shell │Config│ Manage    │
│Runner│Agent │Engine│flow  │Orch  │      │      │ (status/  │
│      │Compose│     │Engine│estr. │      │      │  kill/    │
│      │Team  │      │      │      │      │      │  logs)    │
│      │Compare│     │      │      │      │      │           │
├──────┴──────┴──────┴──────┴──────┴──────┴──────┴───────────┤
│                    基础设施层                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Sandbox  │  │  Tmux    │  │  State   │  │  Config  │   │
│  │ Manager  │  │  Manager │  │ Tracker  │  │  Loader  │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
├─────────────────────────────────────────────────────────────┤
│                    运行环境层                                │
│         Docker Containers + Tmux Sessions                   │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐           │
│  │ agentbox-  │  │ agentbox-  │  │ agentbox-  │  ...      │
│  │ claude-glm │  │ codex-glm  │  │ aider-glm  │           │
│  └────────────┘  └────────────┘  └────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

---

## 分层设计

### 第一层：用户入口层

| 入口 | 文件 | 说明 |
|------|------|------|
| `ag` 命令 | `cli.py` | Click 命令组，支持 `ag claude`、`ag status` 等子命令 |
| `ag`（无参数）| `repl.py` | 交互式 REPL，Sovereign Terminal 主题，`/` 命令补全 |

### 第二层：业务逻辑层

| 模块 | 文件 | 职责 |
|------|------|------|
| **AgentRunner** | `agents/runner.py` | 单 Agent 启动、重启、Shell 附加 |
| **WorkflowEngine** | `workflow/core.py` | `/ask` 提问、`/diff`/`/merge`/`/review` Git 工作流、`/test` 测试 |
| **Orchestrator** | `orchestrator/engine.py` | 多步 Pipeline 编排（顺序/并行），步骤间上下文传递 |
| **Pipeline** | `orchestrator/pipeline.py` | Pipeline 数据结构定义 + 预置流水线（dev/research/compare） |
| **DockerComposeManager** | `compose/manager.py` | Docker Compose 多 Agent 栈管理 |

### 第三层：基础设施层

| 模块 | 文件 | 职责 |
|------|------|------|
| **SandboxManager** | `sandbox/manager.py` | Docker 容器生命周期（创建/启动/停止/删除/镜像构建） |
| **TmuxManager** | `tmux_mgr/manager.py` | tmux 会话/窗口/面板管理，终端 attach/detach |
| **StateTracker** | `state.py` | 会话状态持久化（JSON），窗口注册/清理/恢复 |
| **ConfigLoader** | `config.py` | YAML 配置加载/合并/迁移，Agent 检测 |

### 第四层：工具层

| 模块 | 文件 | 职责 |
|------|------|------|
| **commands** | `utils/commands.py` | Agent 命令构建（`build_agent_command` + `build_docker_exec`） |
| **Dockerfiles** | `templates/docker/` | Docker 镜像构建模板 |

### 第五层：运行环境

```
Docker Container (agentbox-{agent}-{project})
  └── Agent CLI (claude / codex / aider / ...)
      └── 工作目录: /workspace (挂载宿主机项目)

Tmux Session (ag-{project})
  ├── Window: shell (默认)
  ├── Window: sb-{agent} (Agent 运行窗口)
  └── Window: shell-{agent} (可选的伴随 Shell)
```

---

## 核心模块详解

### 1. `cli.py` — 命令调度中心

**所有用户命令的入口**，基于 Click 框架。

```python
# 命令注册方式
main = click.Group()  # 顶层组
main.add_command(claude)   # Agent 快捷命令
main.add_command(status)   # 管理命令
main.add_command(pipeline) # 子组
```

**关键设计**：
- 无子命令时自动启动 REPL（`run_repl(ctx)`）
- `_interactive_command_palette()` 提供 26 个命令的交互式选择
- `_interactive_agent_select()` 自动检测本地已安装的 Agent

**命令分类**：

| 分类 | 命令 | 路由目标 |
|------|------|---------|
| Agent 快捷 | `ag claude/codex/aider/goose/opencode` | `AgentRunner.run_agent()` |
| 多 Agent | `ag compose/team/compare` | `AgentRunner.run_compose/team/compare()` |
| 对话 | `ag ask` | `WorkflowEngine.ask()` |
| 工作流 | `ag diff/merge/review/test` | `WorkflowEngine.*()` |
| 流水线 | `ag pipeline dev/research/compare` | `Orchestrator.execute()` |
| 管理 | `ag status/attach/kill/logs/history` | 直接调用基础设施层 |
| Shell | `ag shell` | `AgentRunner.run_shell()` |
| 配置 | `ag config show/edit/reset` | 配置管理 |

---

### 2. `repl.py` — 交互式终端

**Sovereign Terminal 主题 REPL**，基于 prompt_toolkit。

```
◈ glm › /claude        ← 金色提示符 + 自动补全
  ↑↓ 选择  ↵ 执行     ← 底部工具栏
```

**核心组件**：
- `_CMDS`: 26 个命令定义（名称、描述、分类、用法）
- `_Completer`: 命令自动补全（`/` 触发）
- `_exec()`: 命令调度器，路由到 `AgentRunner` / `WorkflowEngine` / `Orchestrator`
- `_splash()`: ASCII Art Banner + 版本号

**非命令输入处理**：
- 输入 `claude 帮我写代码` → 自动识别 `claude` 为 Agent ID → `run_agent("claude", prompt="帮我写代码")`
- 输入 `帮我写代码` → 默认走 `WorkflowEngine.ask()` 使用 Claude

---

### 3. `agents/runner.py` — Agent 运行器

**最核心的业务模块**，负责将 Agent 运行在 Docker 沙盒中。

**启动流程**（`run_agent()`）：

```
1. 检查 Docker 可用性
2. 创建/获取 tmux 会话
3. 检查窗口是否已存在且进程存活
   ├── 已存在且存活 → 直接 attach
   ├── 已存在但进程死 → 重启（_restart_window）
   └── 不存在 → 创建新沙盒
4. SandboxManager.create_sandbox() → Docker 容器
5. 构建 docker exec 命令
6. TmuxManager.add_agent_window() → tmux 窗口
7. register_window() → 状态持久化
8. 可选: 添加伴随 Shell（--with-shell）
9. attach 到 tmux 会话
```

**五种运行模式**：

| 方法 | 用途 | 命令 |
|------|------|------|
| `run_agent()` | 单 Agent 启动 | `ag claude` |
| `run_compose()` | 动态角色组合 | `ag compose claude:coder codex:reviewer` |
| `run_team()` | 预定义团队 | `ag team dev-team` |
| `run_compare()` | 并排对比 | `ag compare claude codex` |
| `run_shell()` | 容器 Shell | `ag shell claude` |

---

### 4. `sandbox/manager.py` — Docker 沙盒管理

**容器生命周期管理**，核心是 `create_sandbox()` 的四级回退策略：

```
Strategy 1: 容器正在运行 → 直接复用
                ↓ 不存在
Strategy 2: 容器已停止 → docker start 重启
                ↓ 不存在
Strategy 3: Agent 镜像存在 → docker run 从镜像创建（快）
                ↓ 镜像不存在
Strategy 4: 优先 Dockerfile 构建 → docker build（可靠，有层缓存）
            回退: base 镜像 + install + docker commit（不推荐）
```

**镜像构建优先级**：
1. `Dockerfile.{agent}`（如 `Dockerfile.claude`）— Docker 层缓存，最可靠
2. `_generate_agent_image()` — 动态生成临时 Dockerfile
3. 容器内安装 + `docker commit` — 最后手段

**命名规则**：
- 容器: `agentbox-{agent_id}-{project_name}`
- 镜像: `agentbox-{agent_id}:latest`
- 网络: `agentbox-net`

---

### 5. `tmux_mgr/manager.py` — Tmux 会话管理

**终端会话编排**，每个项目对应一个 tmux 会话。

```
tmux session: ag-{project_name}
  ├── Window 0: shell (默认 Shell)
  ├── Window 1: sb-claude (Claude Agent)
  ├── Window 2: shell-claude (伴随 Shell)
  └── Window 3: sb-codex (Codex Agent)
```

**关键方法**：

| 方法 | 说明 |
|------|------|
| `create_session()` | 创建 tmux 会话，默认窗口命名为 `shell` |
| `add_agent_window()` | 添加 Agent 运行窗口，发送命令 |
| `add_agent_pane()` | 水平分屏（compare 模式） |
| `attach_session()` | attach 到会话，处理终端状态恢复 |
| `capture_pane()` | 捕获窗口内容（用于进程存活检测） |
| `list_sessions/windows()` | 枚举会话和窗口 |

**终端状态恢复**：`attach_session()` 在 attach 前后执行 `stty sane`，防止 prompt_toolkit 的 raw mode 残留导致卡住。

---

### 6. `orchestrator/` — Pipeline 编排引擎

**多步骤 Agent 编排**，支持顺序执行和并行执行。

**数据结构**：

```python
@dataclass
class PipelineStep:
    agent: str          # Agent ID
    role: str           # 角色标签
    prompt: str         # 提示词模板（支持 {key} 占位符）
    step_type: StepType # SEQUENTIAL 或 PARALLEL
    timeout: int        # 超时秒数

@dataclass
class Pipeline:
    name: str
    steps: list[PipelineStep]
    shared_context: dict  # 步骤间共享上下文
```

**执行流程**：

```
Orchestrator.execute(pipeline)
  ├── 创建 tmux 会话
  ├── 遍历 steps:
  │   ├── SEQUENTIAL → _execute_step()
  │   │   ├── create_sandbox()
  │   │   ├── build_agent_command() + build_docker_exec()
  │   │   ├── add_agent_window()
  │   │   ├── _wait_for_output() (轮询 tmux 窗口)
  │   │   └── 将输出写入 shared_context
  │   └── PARALLEL → 收集到 parallel_group
  │       └── _execute_parallel_group() (同时启动多个)
  └── 保存运行结果到 ~/.agentbox/pipelines/
```

**预置流水线**：

| 流水线 | 步骤 | 说明 |
|--------|------|------|
| `dev_pipeline` | planner → coder → reviewer | 软件开发 |
| `research_pipeline` | researcher → summarizer → critic | 研究分析 |
| `compare_pipeline` | 多 Agent 并行 → synthesizer | 对比综合 |

---

### 7. `workflow/core.py` — 工作流引擎

**项目感知的 Agent 任务协调**。

**核心功能**：

| 功能 | 方法 | 说明 |
|------|------|------|
| AGENTS.md 注入 | `inject_agents_md()` | 自动将项目说明注入 Agent 提示词 |
| Git Diff | `get_git_diff_stats()` | 查看 Git 改动（兼容无 commit 的新仓库） |
| Git Merge | `merge_changes()` | `git add -A && git commit` |
| Git Discard | `discard_changes()` | 丢弃所有改动 |
| 测试检测 | `detect_test_command()` | 自动识别 pytest/npm test/go test/cargo test |
| Ask 工作流 | `ask()` | 提问 → 注入 AGENTS.md → 沙盒启动 Agent |
| Review 工作流 | `review()` | diff → test → merge/discard/skip |

---

### 8. `state.py` — 状态持久化

**JSON 文件存储**，位于 `~/.agentbox/state.json`。

```json
{
  "sessions": {
    "ag-glm": {
      "created_at": "2025-06-13T01:03:18",
      "project_name": "glm",
      "project_path": "/Users/.../glm",
      "windows": {
        "sb-claude": {
          "agent": "claude",
          "role": "claude",
          "sandbox": true,
          "prompt": ""
        }
      }
    }
  }
}
```

**关键操作**：

| 操作 | 方法 | 说明 |
|------|------|------|
| 注册窗口 | `register_window()` | 记录 Agent 窗口信息 |
| 注销会话 | `unregister_session()` | 删除整个会话记录 |
| 清理失效 | `cleanup_stale_sessions()` | 删除 tmux 中已不存在的会话 |
| 清理窗口 | `cleanup_stale_windows()` | 删除已关闭的窗口记录 |
| 恢复孤立 | `recover_orphaned_sessions()` | 从 Docker 容器标签重建状态 |

---

### 9. `config.py` — 配置管理

**YAML 配置**，位于 `~/.agentbox/config.yaml`。

**配置结构**：

```yaml
sandbox:
  base_image: agentbox-base:latest  # 基础镜像
  mount_point: /workspace           # 项目挂载点
  network: agentbox-net             # Docker 网络
  memory_limit: 4g
  cpu_limit: 2

agents:
  claude:
    name: Claude Code
    docker_image: agentbox-claude:latest
    run_cmd: claude
    env_vars: [ANTHROPIC_API_KEY]
    install_cmd: npm install -g @anthropic-ai/claude-code

teams:
  dev-team:
    agents:
      - {role: planner, agent: claude, prompt: "..."}
```

**加载机制**：`load_config()` → 读取 YAML → `deep_merge(DEFAULT_CONFIG, user_config)` → 迁移旧值（如 `ubuntu:22.04` → `agentbox-base:latest`）

---

### 10. `utils/commands.py` — 命令构建器

**单一真相源**，所有模块统一调用：

```python
# Agent 命令构建
build_agent_command("claude", "claude", "hello")  → "claude -p 'hello'"
build_agent_command("aider", "aider", "hello")    → "aider --message 'hello'"
build_agent_command("codex", "codex", "hello")    → "codex 'hello'"

# Docker 包裹
build_docker_exec("agentbox-claude-glm", "claude -p 'hello'")
  → "docker exec -it agentbox-claude-glm claude -p 'hello'"
```

---

## 数据流

### 单 Agent 启动流程

```
用户: ag claude -p "修复bug"
  │
  ├─ cli.py: claude 命令 → AgentRunner.run_agent("claude", prompt="修复bug")
  │
  ├─ runner.py:
  │   ├─ TmuxManager.create_session("glm") → ag-glm
  │   ├─ SandboxManager.create_sandbox("claude-glm")
  │   │   ├─ 检查容器 agentbox-claude-glm 是否运行
  │   │   ├─ 检查镜像 agentbox-claude:latest 是否存在
  │   │   ├─ 不存在 → build_agent_image("claude") → docker build
  │   │   └─ docker run -d --name agentbox-claude-glm ...
  │   ├─ build_agent_command("claude", "claude", "修复bug") → "claude -p '修复bug'"
  │   ├─ build_docker_exec("agentbox-claude-glm", ...) → "docker exec -it ..."
  │   ├─ TmuxManager.add_agent_window("ag-glm", "sb-claude", cmd)
  │   ├─ register_window(...)
  │   └─ TmuxManager.attach_session("ag-glm")
  │
  └─ 用户看到 tmux 中的 Claude Code 界面
```

### Pipeline 执行流程

```
用户: ag pipeline dev "实现登录功能"
  │
  ├─ cli.py → Orchestrator.execute(dev_pipeline("实现登录功能"))
  │
  ├─ Step 1: planner (codex)
  │   ├─ create_sandbox("codex-glm")
  │   ├─ prompt: "You are the planner... Task: {original_prompt}"
  │   ├─ docker exec → codex 运行
  │   └─ 捕获输出 → context["plan"] = "1. 创建路由 2. ..."
  │
  ├─ Step 2: coder (claude)
  │   ├─ prompt: "Implement: {plan}"
  │   ├─ docker exec → claude 运行
  │   └─ context["code"] = "实现代码..."
  │
  ├─ Step 3: reviewer (codex)
  │   ├─ prompt: "Review: {code}"
  │   └─ context["review"] = "审查意见..."
  │
  └─ 保存结果到 ~/.agentbox/pipelines/dev-pipeline-*.json
```

---

## Docker 镜像体系

```
agentbox-base:latest          ← 基础镜像 (Ubuntu + Node + Python + Go + git)
  ├── agentbox-claude:latest  ← + npm install -g @anthropic-ai/claude-code
  ├── agentbox-codex:latest   ← + npm install -g @openai/codex
  └── agentbox-aider:latest   ← + pip install aider-chat
```

**构建优先级**：
1. `Dockerfile.base` → `agentbox-base:latest`（含开发工具）
2. `Dockerfile.{agent}` → `FROM agentbox-base` + 安装 Agent（Docker 层缓存）
3. `docker commit` → 运行时快照（不可靠，仅作回退）

---

## 命令路由速查

| 命令 | 模块 | 核心方法 |
|------|------|---------|
| `ag claude` | runner.py | `AgentRunner.run_agent("claude")` |
| `ag codex` | runner.py | `AgentRunner.run_agent("codex")` |
| `ag run <id>` | runner.py | `AgentRunner.run_agent(id)` |
| `ag compose` | runner.py | `AgentRunner.run_compose()` |
| `ag team` | runner.py | `AgentRunner.run_team()` |
| `ag compare` | runner.py | `AgentRunner.run_compare()` |
| `ag ask "问题"` | core.py | `WorkflowEngine.ask()` |
| `ag diff` | core.py | `WorkflowEngine.print_diff_summary()` |
| `ag merge` | core.py | `WorkflowEngine.merge_changes()` |
| `ag review` | core.py | `WorkflowEngine.review()` |
| `ag test` | core.py | `WorkflowEngine.run_tests()` |
| `ag pipeline dev` | engine.py | `Orchestrator.execute(dev_pipeline())` |
| `ag shell` | runner.py | `AgentRunner.run_shell()` |
| `ag status` | cli.py | `status()` — Dashboard |
| `ag attach` | cli.py | `TmuxManager.attach_session()` |
| `ag kill` | cli.py | `TmuxManager.kill_session()` + `SandboxManager.stop/kill_sandbox()` |
| `ag logs` | cli.py | `SandboxManager.get_sandbox_logs()` |
| `ag history` | cli.py | `state.load_state()` |
| `ag list` | runner.py | `AgentRunner.list_available_agents()` |
| `ag config` | cli.py | `config.save_config/load_config()` |
| `ag init` | cli.py | 创建 `AGENTS.md` + `.agentbox/` |
| `ag sandbox build` | manager.py | `SandboxManager.build_agent_image()` |
| `ag stack up` | compose/ | `DockerComposeManager.up()` |

---

## 文件系统布局

```
~/.agentbox/
  ├── config.yaml          ← 用户配置
  ├── state.json           ← 会话状态
  └── pipelines/
      └── dev-pipeline-*.json  ← Pipeline 运行记录

agentbox/agentbox/templates/docker/
  ├── Dockerfile.base      ← 基础镜像 (Ubuntu + dev tools)
  ├── Dockerfile.claude    ← Claude Code
  ├── Dockerfile.codex     ← OpenAI Codex
  └── Dockerfile.aider     ← Aider