# 🧊 Agentbox

**AI Agent 编排 CLI** — 在 Docker 沙盒中通过 tmux 运行多个 coding agent。

```
tmux / zellij
   ↓
agentbox CLI (ag)
   ↓
Docker Sandboxes / 本地运行
   ↓
Claude Code / Codex / OpenCode / Goose / Aider / ...
   ↓
API Provider (OpenAI / Anthropic / Ollama / ...)
```

## ✨ 特性

- 🤖 **多 Agent 支持** — Claude Code、OpenAI Codex、Aider、Goose、OpenCode 等
- 📦 **Docker 沙盒隔离** — 每个 agent 运行在独立容器中，不污染宿主机
- 🖥️ **tmux 多窗口** — 自动管理 tmux session，每个 agent 一个 window
- 👥 **团队编排** — 用 YAML 定义多 agent 团队协作
- ⚡ **对比模式** — 同一个 prompt 在多个 agent 中并排运行对比
- 💬 **快捷提问** — `ag ask "帮我重构登录模块"` 一键启动

## 🚀 安装

```bash
cd agentbox
pip install -e .
```

安装后 `agentbox` 或 `agx` 命令即可使用。

## 📋 使用

### 查看可用 Agent

```bash
ag list
```

### 运行单个 Agent

```bash
# 本地运行 Claude Code
ag claude

# 本地运行 Codex
ag codex

# 带 prompt 运行
ag claude -p "帮我重构这个模块"

# 默认在 Docker 沙盒中运行
ag claude
# 在本地运行（跳过沙盒）
ag claude --local

# 运行任意已配置的 agent
ag run aider
```

### 团队模式

```bash
# 运行预定义的 dev-team
ag team dev-team

# 带 prompt
ag team dev-team -p "实现用户注册功能"

# 默认在沙盒中运行团队
ag team dev-team
# 在本地运行
ag team dev-team --local
```

### 对比模式

```bash
# 两个 agent 并排对比
ag compare claude codex -p "写一个快排算法"

# 多个 agent 对比
ag compare claude codex aider -p "优化这个函数"
```

### 快捷提问

```bash
ag ask "帮我写单元测试"
ag ask "这个 bug 怎么修" -a codex
ag ask "实现缓存层" --test
ag ask "重构认证模块"           # 默认沙盒
ag ask "重构认证模块" --local   # 本地运行
```

### 工作流命令

```bash
# 查看当前项目改动摘要
ag diff

# 查看完整 patch
ag diff --patch

# 自动检测并运行测试
ag test
ag test -c "pytest tests/unit"

# 审查改动，运行测试，并选择 merge/discard/skip
ag review

# stage 全部改动并提交
ag merge -m "Implement auth workflow"
```

### 沙盒管理

```bash
# 列出运行中的沙盒
ag sandbox list

# 创建沙盒
ag sandbox create claude

# 查看沙盒日志
ag sandbox logs claude-myproject

# 在沙盒中执行命令
ag sandbox exec claude-myproject -- ls /workspace

# 构建 agent 镜像
ag sandbox build claude

# 删除沙盒
ag sandbox kill claude-myproject
ag sandbox kill --all
```

### Docker Compose 栈

```bash
# 为多个 agent 启动 compose 栈
ag stack up claude codex aider

# 查看状态和日志
ag stack status
ag stack logs --tail 200

# 停止栈
ag stack down
```

### Session 管理

```bash
# 列出 agentbox tmux sessions
ag session list

# 连接到 session
ag session attach ag-myproject

# 查看 session 窗口
ag session windows ag-myproject

# 关闭 session
ag session kill ag-myproject
```

### 配置

```bash
# 查看配置
ag config show

# 配置文件路径
ag config path

# 编辑配置
ag config edit

# 重置为默认
ag config reset
```

### 项目初始化

```bash
cd my-project
ag init
```

会创建 `AGENTS.md` 和 `.agentbox/` 目录。

## ⚙️ 配置

配置文件位于 `~/.agentbox/config.yaml`，可自定义：

- **sandbox** — Docker 沙盒设置（镜像、内存、CPU）
- **tmux** — tmux session 设置
- **agents** — 定义新 agent（CLI 命令、Docker 镜像、环境变量）
- **teams** — 定义 agent 团队编排

### 添加自定义 Agent

编辑 `~/.agentbox/config.yaml`：

```yaml
agents:
  my-agent:
    name: My Custom Agent
    cli: my-agent-cli
    type: cli
    docker_image: agentbox-my-agent:latest
    env_vars:
      - MY_API_KEY
    install_cmd: "npm install -g my-agent-cli"
    run_cmd: "my-agent-cli"
```

### 定义团队

```yaml
teams:
  full-stack:
    description: "Full stack development team"
    agents:
      - role: architect
        agent: claude
        prompt: "You design the architecture"
      - role: coder
        agent: codex
        prompt: "You write the code"
      - role: tester
        agent: aider
        prompt: "You write tests"
```

## 🏗️ 架构

```
agentbox/
├── agentbox/
│   ├── __init__.py
│   ├── cli.py              # CLI 入口（click）
│   ├── config.py           # 配置管理（YAML）
│   ├── agents/
│   │   ├── __init__.py
│   │   └── runner.py       # Agent 运行编排
│   ├── sandbox/
│   │   ├── __init__.py
│   │   └── manager.py      # Docker 沙盒管理
│   ├── tmux_mgr/
│   │   ├── __init__.py
│   │   └── manager.py      # tmux session 管理
│   ├── workflow/
│   │   ├── __init__.py
│   │   └── core.py         # AGENTS.md 注入、git diff/test/merge 工作流
│   ├── compose/
│   │   ├── __init__.py
│   │   └── manager.py      # Docker Compose 多容器栈
│   └── templates/
│       └── docker/         # Dockerfile 模板
├── config/                 # 示例配置
├── pyproject.toml
└── README.md
```

## 🔧 依赖

- Python 3.10+
- Docker（沙盒模式需要）
- tmux（多窗口管理）
- 至少一个 AI Agent CLI（Claude Code、Codex 等）

## 📝 License

MIT
