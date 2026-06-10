# Agentbox 使用手册

> 版本: 0.1.0 | 最后更新: 2026-06-11

## 目录

- [简介](#简介)
- [安装](#安装)
- [架构概览](#架构概览)
- [快速开始](#快速开始)
- [命令详解](#命令详解)
  - [Agent 命令](#agent-命令)
  - [工作流命令](#工作流命令)
  - [编排命令](#编排命令)
  - [Pipeline 命令](#pipeline-命令)
  - [Sandbox 命令](#sandbox-命令)
  - [Stack 命令](#stack-命令)
  - [Session 命令](#session-命令)
  - [配置命令](#配置命令)
  - [其他命令](#其他命令)
- [配置文件](#配置文件)
- [AGENTS.md 项目说明](#agentsmd-项目说明)
- [安全机制](#安全机制)
- [典型使用场景](#典型使用场景)

---

## 简介

Agentbox 是一个 AI Agent 编排 CLI 工具，让你在 tmux 中运行多个编码 Agent（Claude Code、Codex、Aider 等），支持 Docker 沙盒隔离、多 Agent 协作编排、自动化工作流。

**核心能力：**
- 🤖 一键启动 6 种 AI Agent
- 🧊 Docker 沙盒隔离运行
- 👥 多 Agent 角色编排（规划/编码/审查）
- 🔄 自动化工作流（ask → sandbox → diff → merge/discard）
- 🧠 Pipeline 顺序编排，上下文自动传递
- 🐳 Docker Compose 多容器栈

---

## 安装

```bash
cd agentbox
pip install -e .
```

安装后获得三个 CLI 入口：
- `agentbox` — 完整命令名
- `ag` — 短命令（推荐日常使用）
- `agx` — 备用短命令

---

## 架构概览

```
tmux 终端复用
   ↓
agentbox CLI (ag)
   ↓
Docker Sandboxes / Docker Compose
   ↓
Claude Code / Codex / OpenCode / Goose / Aider / Copilot
   ↓
API Provider (Anthropic / OpenAI / etc.)
```

---

## 快速开始

```bash
# 1. 在项目中初始化
cd my-project
ag init

# 2. 查看可用 Agent
ag list

# 3. 运行单个 Agent
ag claude
ag codex -p "帮我重构登录模块"

# 4. 一键 ask 工作流
ag ask "帮我重构登录模块，并写测试" --test

# 5. 查看修改 → 跑测试 → 合并/丢弃
ag review
```

---

## 命令详解

### Agent 命令

#### `ag claude` / `ag codex` / `ag aider` / `ag goose` / `ag opencode`

启动指定的 AI Agent。

```bash
# 直接启动（交互模式）
ag claude

# 带 prompt 启动
ag claude -p "帮我写一个 FastAPI 的 CRUD 模块"
ag codex -p "修复 issue #42 的 bug"

# 指定角色
ag codex -r planner
ag claude -r coder

# 在 Docker 沙盒中运行（默认）
ag claude

# 在本地运行（跳过沙盒）
ag claude --local

# 后台运行（不附加到 tmux）
ag codex --no-attach
```

**选项：**
| 选项 | 说明 |
|------|------|
| `-p, --prompt` | 发送给 Agent 的提示词 |
| `-r, --role` | 角色标签（如 planner、coder、reviewer） |
| `--local` | 在本地运行（默认使用 Docker 沙盒） |
| `--no-attach` | 不自动附加到 tmux 会话 |

#### `ag run`

运行任意已配置的 Agent（按 ID）。

```bash
ag run claude -p "hello"
ag run copilot
```

---

### 工作流命令

#### `ag ask` ⭐ 核心功能

一键式工作流：注入 AGENTS.md → 启动 Agent → 可选跑测试。

```bash
# 基本用法
ag ask "这个项目的主要功能是什么"

# 指定 Agent 和角色
ag ask "重构 auth 模块" -a codex -r coder

# 在沙盒中运行（默认）+ 自动跑测试
ag ask "帮我写单元测试" --test

# 后台运行
ag ask "优化性能" --no-attach
```

**选项：**
| 选项 | 说明 |
|------|------|
| `-a, --agent` | 使用的 Agent（默认: claude） |
| `-r, --role` | 角色标签 |
| `--local` | 在本地运行（默认使用 Docker 沙盒） |
| `--test` | 自动检测并运行测试命令，附加到 prompt 末尾 |
| `--no-attach` | 不附加到 tmux |

**`--test` 行为：**
自动检测项目测试框架，将测试命令注入 prompt：
- 检测到 `pytest` → `...run \`pytest\` and report the result`
- 检测到 `npm test` → `...run \`npm test\` and report the result`
- 未检测到 → `...identify and run the appropriate project tests`

#### `ag review` ⭐ 核心功能

交互式代码审查工作流：diff → 测试 → merge/discard。

```bash
# 完整审查流程
ag review

# 跳过自动测试
ag review --no-test

# 指定测试命令
ag review --test-cmd "pytest -x"
```

**流程：**
1. 显示 git diff 摘要
2. 自动运行项目测试
3. 交互选择：merge（合并）、discard（丢弃）、skip（跳过）

#### `ag diff`

显示项目的 git diff 摘要。

```bash
ag diff          # 仅摘要
ag diff --patch  # 摘要 + 完整 diff
```

#### `ag merge`

暂存所有更改并提交。

```bash
ag merge
ag merge -m "feat: add auth module"
```

#### `ag test`

运行项目测试。

```bash
ag test                # 自动检测测试命令
ag test -c "pytest -v" # 指定测试命令
```

**自动检测逻辑：**
| 文件 | 检测到的命令 |
|------|-------------|
| `pytest.ini` / `setup.cfg` + `[tool:pytest]` | `pytest` |
| `pyproject.toml` + `[tool.pytest]` | `pytest` |
| `package.json` + `scripts.test` | `npm test` |
| `Cargo.toml` | `cargo test` |
| `go.mod` | `go test ./...` |
| `Makefile` + `test` target | `make test` |

---

### 编排命令

#### `ag compose` ✨ 动态角色编排

用 `AGENT:ROLE` 语法动态组合多个 Agent。

```bash
# 规划 → 编码 → 审查
ag compose codex:planner claude:coder codex:reviewer

# 带 prompt 和本地运行
ag compose claude:architect aider:test-writer -p "Build auth module" --local

# 无角色时，agent ID 作为角色
ag compose claude codex
```

**效果：** 在同一 tmux 会话中创建多个窗口，每个 Agent 一个窗口，各自独立运行。

#### `ag team`

运行预配置的 Agent 团队。

```bash
ag team dev-team -p "Build a REST API"
ag team compare -p "Implement sorting algorithm"
```

**内置团队：**
| 团队 | 说明 | 成员 |
|------|------|------|
| `dev-team` | 完整开发团队 | claude:planner, codex:coder, claude:reviewer |
| `compare` | 对比多个 Agent | claude, codex |

#### `ag compare`

多个 Agent 并排对比，执行相同任务。

```bash
ag compare claude codex -p "实现快速排序"
ag compare claude aider goose -p "写一个 HTTP 服务器"
```

**效果：** 在同一 tmux 窗口中分割为多个 pane，每个 Agent 一个 pane。

---

### Pipeline 命令

Pipeline 编排 Agent 顺序执行，每步的输出自动传递给下一步。

#### `ag pipeline dev`

开发流水线：规划 → 编码 → 审查

```bash
ag pipeline dev "Build a user authentication system"
```

**流程：**
1. `codex:planner` — 分析任务，制定计划
2. `claude:coder` — 根据计划实现代码
3. `codex:reviewer` — 审查代码质量

#### `ag pipeline research`

研究流水线：研究 → 总结 → 评审

```bash
ag pipeline research "WebAssembly 性能优化策略"
```

#### `ag pipeline compare`

对比流水线：多 Agent 执行 → 综合分析

```bash
ag pipeline compare "实现 LRU 缓存" -a claude -a codex
```

#### `ag pipeline custom`

自定义流水线，用 `AGENT:ROLE` 定义步骤。

```bash
ag pipeline custom codex:planner claude:coder codex:reviewer -p "Build auth"
ag pipeline custom claude:researcher claude:writer
```

**上下文传递：** 每步自动接收前一步的输出 + 原始 prompt。

#### `ag pipeline list` / `ag pipeline show`

查看 Pipeline 运行历史和详情。

```bash
ag pipeline list           # 列出历史运行
ag pipeline show <run_id>  # 查看某次运行详情
```

---

### Sandbox 命令

管理 Docker 沙盒容器。

```bash
# 列出运行中的沙盒
ag sandbox list

# 创建沙盒
ag sandbox create claude

# 在沙盒中执行命令
ag sandbox exec agentbox-myproject-claude -- ls /workspace

# 交互式进入沙盒
ag sandbox exec agentbox-myproject-claude -i -- /bin/bash

# 查看沙盒日志
ag sandbox logs agentbox-myproject-claude --tail 100

# 停止沙盒
ag sandbox kill agentbox-myproject-claude
ag sandbox kill --all          # 停止所有沙盒

# 构建 Agent 镜像
ag sandbox build claude
```

**沙盒默认配置：**
| 参数 | 默认值 |
|------|--------|
| 基础镜像 | `ubuntu:22.04` |
| 挂载点 | `/workspace` |
| 网络 | `agentbox-net` |
| 内存限制 | 4GB |
| CPU 限制 | 2 核 |

---

### Stack 命令

Docker Compose 多容器栈管理。

```bash
# 启动多 Agent 栈
ag stack up claude codex aider

# 前台运行
ag stack up claude codex --foreground

# 查看状态
ag stack status

# 查看日志
ag stack logs --tail 50

# 停止栈
ag stack down
```

**生成的文件：**
- `.agentbox/docker-compose.yml` — Compose 配置
- `.agentbox/.env` — 环境变量（API 密钥等，权限 600）

---

### Session 命令

管理 tmux 会话。

```bash
# 列出所有 agentbox 会话
ag session list

# 附加到会话
ag session attach ag-myproject

# 查看会话中的窗口
ag session windows ag-myproject

# 终止会话
ag session kill ag-myproject
```

**会话命名规则：** `ag-<项目名>`

**tmux 嵌套环境：** 如果你的终端本身运行在 tmux 中（如 VS Code 集成终端、iTerm2 自动 tmux 等），`ag session attach` 会自动检测 `$TMUX` 环境变量并使用 `tmux switch-client` 切换会话，避免嵌套报错。切换后可用 `Ctrl+B` 然后 `(` 切回原会话。

如果仍然无法附加，可以手动操作：

```bash
# 查看所有会话
tmux list-sessions

# 切换到 agentbox 会话
tmux switch-client -t ag-myproject

# 或者不在 tmux 中时直接附加
tmux attach-session -t ag-myproject
```

---

### 配置命令

```bash
# 查看当前配置
ag config show

# 查看配置文件路径
ag config path

# 编辑配置
ag config edit

# 重置为默认配置
ag config reset
```

---

### Status 命令

#### `ag status` ⭐ 仪表盘

一键查看所有会话、沙盒和 Agent 的全景视图。

```bash
ag status
```

**展示内容：**
- 📊 摘要面板：活跃会话数、沙盒数、Agent 数
- 🖥️ 会话 & Agent 表：每个 tmux 会话下的 Agent、角色、运行模式、容器、状态、Prompt
- 🐳 Docker 沙盒表：容器 ID、名称、Agent、镜像、状态
- 💡 快捷操作提示

**示例输出：**
```
╭──────── 🧊 Agentbox Dashboard ────────╮
│ Sessions: 2   Sandboxes: 3   Agents: 4 │
╰────────────────────────────────────────╯

🖥️  Tmux Sessions & Agents
┌──────────┬─────────┬───────┬──────────┬────────────┬────────────────────────┬────────┬──────────────────────┐
│ Session  │ Project │ Agent │ Role     │ Mode       │ Container              │ Status │ Prompt               │
├──────────┼─────────┼───────┼──────────┼────────────┼────────────────────────┼────────┼──────────────────────┤
│ ag-myapp │ myapp   │ claude│ coder    │ 🐳 sandbox │ agentbox-claude-myapp │ 🟢     │ 重构认证模块          │
│          │         │ codex │ planner  │ 🐳 sandbox │ agentbox-codex-myapp  │ ⚪     │ 制定开发计划          │
└──────────┴─────────┴───────┴──────────┴────────────┴────────────────────────┴────────┴──────────────────────┘

🐳 Docker Sandboxes
┌──────────────┬──────────────────────────┬───────┬────────────────────────┬─────────┐
│ Container ID │ Name                     │ Agent │ Image                  │ Status  │
├──────────────┼──────────────────────────┼───────┼────────────────────────┼─────────┤
│ a1b2c3d4e5f6 │ agentbox-claude-myapp    │ claude│ agentbox-claude:latest │ Up 2h   │
│ f6e5d4c3b2a1 │ agentbox-codex-myapp     │ codex │ agentbox-codex:latest  │ Up 2h   │
└──────────────┴──────────────────────────┴───────┴────────────────────────┴─────────┘
```

---

### 其他命令

#### `ag init`

在当前项目中初始化 agentbox。

```bash
ag init
```

**会创建：**
- `AGENTS.md` — 项目说明文件（供 AI Agent 阅读）
- `.agentbox/` — 运行时目录
- 更新 `.gitignore` 添加 `.agentbox/`

#### `ag list`

列出可用 Agent、团队和本地检测结果。

```bash
ag list
ag list --all   # 显示所有详情
```

---

## 配置文件

配置文件位于 `~/.agentbox/config.yaml`，首次运行自动生成。

### 完整配置示例

```yaml
sandbox:
  base_image: ubuntu:22.04
  mount_point: /workspace
  network: agentbox-net
  auto_remove: true
  memory_limit: 4g
  cpu_limit: 2
  default_local: false      # 设为 true 则默认在本地运行（默认使用沙盒）
  compose_timeout: 120

tmux:
  session_prefix: ag-
  default_shell: /bin/bash

agents:
  claude:
    name: Claude Code
    cli: claude
    type: cli
    docker_image: agentbox-claude:latest
    env_vars:
      - ANTHROPIC_API_KEY
    install_cmd: npm install -g @anthropic-ai/claude-code
    run_cmd: claude

  codex:
    name: OpenAI Codex
    cli: codex
    type: cli
    docker_image: agentbox-codex:latest
    env_vars:
      - OPENAI_API_KEY
    install_cmd: npm install -g @openai/codex
    run_cmd: codex

  aider:
    name: Aider
    cli: aider
    type: cli
    docker_image: agentbox-aider:latest
    env_vars:
      - OPENAI_API_KEY
      - ANTHROPIC_API_KEY
    install_cmd: pip install aider-chat
    run_cmd: aider

  goose:
    name: Goose
    cli: goose
    type: cli
    docker_image: agentbox-goose:latest
    env_vars:
      - GOOSE_API_KEY
    install_cmd: curl -fsSL https://github.com/block/goose/releases/latest/download/install.sh | sh
    run_cmd: goose session

  opencode:
    name: OpenCode
    cli: opencode
    type: tui
    docker_image: agentbox-opencode:latest
    env_vars:
      - OPENAI_API_KEY
      - ANTHROPIC_API_KEY
    install_cmd: go install github.com/opencode-ai/opencode@latest
    run_cmd: opencode

  copilot:
    name: GitHub Copilot CLI
    cli: github-copilot-cli
    type: cli
    docker_image: agentbox-copilot:latest
    env_vars:
      - GITHUB_TOKEN
    install_cmd: npm install -g @githubnext/github-copilot-cli
    run_cmd: github-copilot-cli

teams:
  dev-team:
    description: Full development team
    agents:
      - role: planner
        agent: claude
        prompt: "You are the planner. Break down tasks into steps."
      - role: coder
        agent: codex
        prompt: "You are the coder. Write clean, tested code."
      - role: reviewer
        agent: claude
        prompt: "You are the reviewer. Check code quality and suggest fixes."

  compare:
    description: Run same task on multiple agents for comparison
    agents:
      - role: claude
        agent: claude
      - role: codex
        agent: codex
```

### 自定义 Agent

在 `config.yaml` 的 `agents` 下添加：

```yaml
agents:
  my-agent:
    name: My Custom Agent
    cli: my-agent
    type: cli
    docker_image: my-agent:latest
    env_vars:
      - MY_API_KEY
    install_cmd: pip install my-agent
    run_cmd: my-agent
```

### 自定义 Team

在 `teams` 下添加：

```yaml
teams:
  my-team:
    description: My custom team
    agents:
      - role: architect
        agent: claude
        prompt: "You are the architect. Design the system."
      - role: implementer
        agent: codex
        prompt: "You implement the design."
```

---

## AGENTS.md 项目说明

`AGENTS.md` 是项目级文件，帮助 AI Agent 理解你的项目。`ag ask` 和 `ag review` 会自动读取并注入到 prompt 中。

### 模板

```markdown
# My Project - Agent Guide

## Project Overview
<!-- 描述你的项目 -->

## Architecture
<!-- 关键目录和模块 -->

## Development
<!-- 构建、测试、运行方式 -->

## Conventions
<!-- 编码风格、提交规范等 -->
```

**建议填写：**
- 项目使用的主要语言和框架
- 目录结构说明
- 构建/测试/运行命令
- 代码规范和约定
- 已知的问题或注意事项

---

## 安全机制

| 措施 | 说明 |
|------|------|
| API 密钥隔离 | 密钥写入 `.agentbox/.env`（权限 600），不嵌入 YAML |
| `.gitignore` 保护 | `.agentbox/` 自动加入项目 `.gitignore` |
| Shell 注入防护 | 所有 prompt 通过 `shlex.quote()` 转义 |
| Tmux 注入防护 | 使用 `tmux send-keys -l` 字面发送命令 |
| 子进程超时 | Docker/Git/测试命令均有超时保护 |
| 沙盒隔离 | 默认在 Docker 容器中运行，与宿主隔离（`--local` 跳过） |

---

## 典型使用场景

### 场景 1：日常开发

```bash
cd my-project
ag ask "添加一个用户注册 API 端点" --test
# Agent 自动完成，注入 AGENTS.md，附带测试指令
ag review
# 查看修改 → 跑测试 → merge
```

### 场景 2：多 Agent 协作

```bash
ag compose codex:planner claude:coder codex:reviewer -p "重构数据库层"
# 三个 Agent 在同一 tmux 会话中各自运行
ag session list   # 查看会话
ag session attach ag-myproject  # 附加查看
```

### 场景 3：Agent 对比

```bash
ag compare claude codex aider -p "实现一个 LRU 缓存"
# 三个 Agent 并排执行相同任务
```

### 场景 4：Pipeline 自动化

```bash
ag pipeline dev "Build a REST API with authentication"
# codex 规划 → claude 编码 → codex 审查，输出自动传递
ag pipeline list   # 查看运行历史
```

### 场景 5：Docker 沙盒运行（默认行为）

```bash
# 默认就在 Docker 沙盒中运行
ag claude -p "帮我分析这段代码"
# 在隔离的 Docker 容器中运行，项目目录挂载到 /workspace
ag sandbox list    # 查看运行中的沙盒
ag sandbox logs agentbox-myproject-claude
```

### 场景 5b：临时在本地运行

```bash
# 使用 --local 跳过沙盒，直接在本地运行
ag claude --local -p "帮我分析这段代码"

# 也可以配置默认本地运行
ag config edit
# 在 ~/.agentbox/config.yaml 中设置：
#   sandbox:
#     default_local: true

# 之后所有 Agent 命令默认在本地运行
ag claude -p "帮我分析这段代码"
```

### 场景 6：Docker Compose 多容器栈

```bash
ag stack up claude codex aider
# 启动三个 Agent 的容器
ag stack status    # 查看状态
ag stack logs      # 查看日志
ag stack down      # 停止
```

---

## 命令速查表

| 命令 | 说明 |
|------|------|
| `ag claude` | 运行 Claude Code |
| `ag codex` | 运行 OpenAI Codex |
| `ag aider` | 运行 Aider |
| `ag goose` | 运行 Goose |
| `ag opencode` | 运行 OpenCode |
| `ag run <id>` | 运行指定 Agent |
| `ag ask "..."` | 一键 ask 工作流 |
| `ag review` | 审查修改 + 测试 + merge/discard |
| `ag diff` | 显示 git diff 摘要 |
| `ag merge` | 暂存并提交 |
| `ag test` | 运行项目测试 |
| `ag compose` | 动态角色编排 |
| `ag team <id>` | 运行预配置团队 |
| `ag compare` | Agent 对比 |
| `ag pipeline dev` | 开发流水线 |
| `ag pipeline research` | 研究流水线 |
| `ag pipeline custom` | 自定义流水线 |
| `ag sandbox list` | 列出沙盒 |
| `ag sandbox create` | 创建沙盒 |
| `ag sandbox kill` | 停止沙盒 |
| `ag stack up` | 启动 Compose 栈 |
| `ag stack down` | 停止 Compose 栈 |
| `ag session list` | 列出 tmux 会话 |
| `ag status` | 📊 仪表盘：查看所有会话/沙盒/Agent |
| `ag config show` | 查看配置 |
| `ag init` | 初始化项目 |
| `ag list` | 列出可用 Agent |