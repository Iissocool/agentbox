# Agentbox 使用手册 — v0.3.0

> 🧊 一个命令搞定一切：`ag`

---

## 目录

1. [项目简介](#项目简介)
2. [工作原理](#工作原理)
3. [已实现功能](#已实现功能)
4. [快速上手](#快速上手)
5. [命令详解](#命令详解)
6. [架构详解](#架构详解)
7. [沙盒镜像缓存机制](#沙盒镜像缓存机制)
8. [数据安全保障](#数据安全保障)
9. [常见问题](#常见问题)

---

## 项目简介

**Agentbox** 是一个 AI Agent 编排 CLI 工具，让你在 Docker 沙盒中安全地运行多个 coding agent（Claude Code、Codex、Aider 等），通过 tmux 多窗口管理，一行命令启动。

**解决什么问题？**

- 🛡️ **安全隔离** — AI Agent 直接操作你的文件系统有风险，沙盒隔离后只能访问你挂载的项目目录
- 🤖 **多 Agent 协作** — 不同 Agent 各有所长，可以组合使用（架构师 + 编码者 + 审查者）
- 🔄 **会话管理** — Agent 运行在 tmux 中，断开后可随时重连
- ⚡ **一键启动** — 不需要手动 docker run / docker exec / tmux，`ag claude` 就够了

---

## 工作原理

### 整体流程

```
用户运行: ag claude
    │
    ▼
┌─────────────────────────────────────────────────┐
│  1. 创建 tmux 会话 (ag-<项目名>)                │
│  2. 创建/复用 Docker 容器 (agentbox-claude-<项目>) │
│  3. 在容器中安装 Agent（如需要）                  │
│  4. 在 tmux 窗口中执行:                          │
│     docker exec -it agentbox-claude-<项目> claude │
│  5. 自动 attach 到 tmux 会话                     │
└─────────────────────────────────────────────────┘
    │
    ▼
用户进入 tmux 窗口，看到 Claude Code 运行中
Ctrl+B 然后 D → 脱离（Agent 继续运行）
ag attach → 随时重连
```

### 三层架构

```
┌──────────────────────────────────────┐
│  tmux 会话层                         │
│  ├─ 窗口: sb-claude → Claude Code    │
│  ├─ 窗口: sb-codex  → Codex         │
│  └─ 窗口: shell     → 本地 shell     │
├──────────────────────────────────────┤
│  Docker 容器层                        │
│  ├─ agentbox-claude-glm              │
│  │   └─ ubuntu + node + claude       │
│  │   └─ /workspace → 挂载项目目录     │
│  └─ agentbox-codex-glm               │
│      └─ ubuntu + node + codex        │
│      └─ /workspace → 挂载项目目录     │
├──────────────────────────────────────┤
│  宿主机                               │
│  └─ ~/Desktop/glm (你的项目代码)       │
└──────────────────────────────────────┘
```

**关键点：**
- 容器通过 `-v` 挂载你的项目目录到 `/workspace`，Agent 可以读写项目文件
- 每个 Agent 一个独立容器，互不干扰
- tmux 窗口只是"显示器"，Agent 实际运行在容器中
- 脱离 tmux 后 Agent 继续运行，随时可重连

---

## 已实现功能

| 功能 | 命令 | 说明 |
|------|------|------|
| ✅ 单 Agent 沙盒运行 | `ag claude` | Docker 隔离，安全运行 |
| ✅ 多 Agent 快捷方式 | `ag codex` / `ag aider` | 一键启动不同 Agent |
| ✅ 交互式选择 | `ag` | 无需记命令，选就完事 |
| ✅ 会话管理 | `ag status` / `ag attach` / `ag kill` | 查看所有会话、重连、停止 |
| ✅ 数据保护 | `ag kill`（默认保留） | 停止不删除，下次自动恢复 |
| ✅ 镜像缓存 | 自动 docker commit | 首次安装后缓存，下次秒启动 |
| ✅ 坏缓存修复 | 自动验证 + 重装 | 缓存镜像中 Agent 丢失时自动重新安装 |
| ✅ 死进程重启 | 自动检测 + 重启 | Agent 崩溃后重新运行 `ag claude` 自动恢复 |
| ✅ 沙盒日志 | `ag logs` | 查看容器日志 |
| ✅ 会话历史 | `ag history` | 查看所有历史会话 |
| ✅ 多 Agent 组合 | `ag compose claude:coder codex:reviewer` | 分配角色协作 |
| ✅ 团队模式 | `ag team <team_id>` | YAML 定义的固定团队 |
| ✅ 对比模式 | `ag compare claude codex` | 同一 prompt 并排对比 |
| ✅ 快捷提问 | `ag ask "修复bug"` | 一键启动 Agent 并提问 |
| ✅ 工作流 | `ag diff` / `ag merge` / `ag review` / `ag test` | Git 操作 + 测试 |
| ✅ 流水线 | `ag pipeline dev "任务"` | 多步编排：规划→编码→审查 |
| ✅ 配置管理 | `ag config show/edit/reset` | 自定义 Agent、团队、沙盒参数 |
| ✅ 孤儿恢复 | `ag status` 自动恢复 | Docker 容器存在但状态丢失时自动重建 |
| ✅ 项目初始化 | `ag init` | 创建 AGENTS.md（可选） |

---

## 快速上手

### 安装

```bash
cd agentbox
pip install -e .
```

### 新项目使用（无需初始化）

```bash
cd my-project
ag claude          # 就这一步！自动创建沙盒、安装 Agent、挂载项目
```

### 日常使用

```bash
ag claude                    # 启动 Claude
# ... 在 Claude 中工作 ...
# Ctrl+B 然后 D → 脱离 tmux

ag attach                    # 随时重连
ag status                    # 查看所有会话状态
ag kill                      # 停止会话（数据保留）
```

---

## 命令详解

### 启动 Agent

```bash
ag                               # 交互式选择 Agent
ag claude                        # 在沙盒中运行 Claude Code
ag codex                         # 在沙盒中运行 Codex
ag aider                         # 在沙盒中运行 Aider
ag goose                         # 在沙盒中运行 Goose
ag opencode                      # 在沙盒中运行 OpenCode

# 带 prompt 启动
ag claude -p "修复认证 bug"

# 带角色启动（用于组合模式）
ag claude -r coder -p "实现功能 X"

# 后台启动（不进入 tmux）
ag claude --no-attach

# 运行任意已配置的 Agent
ag run <agent_id> -p "prompt"
```

### 会话管理

```bash
ag status                        # 仪表盘：所有会话、沙盒、Agent 状态一览
ag attach                        # 交互式选择会话并重连
ag attach ag-myproject           # 重连到指定会话
ag kill                          # 交互式选择会话并停止（沙盒数据保留！）
ag kill ag-myproject             # 停止指定会话（沙盒数据保留！）
ag kill --rm ag-myproject        # 停止并永久删除沙盒数据
ag kill --all                    # 停止所有会话（沙盒数据保留）
ag kill --all --rm               # 停止并删除所有会话和沙盒
ag history                       # 查看会话历史
```

> 💡 `ag kill` 和 `ag attach` 都可以**不加会话名**，会弹出交互式选择器。

### 沙盒日志

```bash
ag logs                          # 交互式选择沙盒查看日志
ag logs claude-myproject         # 查看指定沙盒日志
ag logs claude-myproject --tail 100
```

### 多 Agent 协作

```bash
# 组合多个 Agent 分配角色
ag compose claude:coder codex:reviewer
ag compose claude:architect aider:test-writer -p "构建认证模块"

# 运行预定义团队
ag team <team_id> -p "构建 API"

# 并排对比多个 Agent
ag compare claude codex -p "实现排序算法"
```

### 快捷提问

```bash
ag ask "为什么这么慢？"          # 向 Claude 提问（默认）
ag ask "修复这个" -a codex      # 向 Codex 提问
ag ask "修复 bug" --test        # 修复后自动运行测试
```

### 工作流快捷方式

```bash
ag diff                          # Git diff 摘要
ag diff --patch                  # 完整 diff
ag merge -m "添加功能 X"        # 暂存所有更改并提交
ag review                        # 审查更改、运行测试、合并或丢弃
ag test                          # 运行项目测试
ag test -c "pytest tests/"       # 指定测试命令
```

### 流水线

```bash
ag pipeline dev "添加用户认证"   # 规划 → 编码 → 审查
ag pipeline research "Rust vs Go" # 研究 → 总结 → 评审
ag pipeline compare "优化性能"   # 多 Agent 对比后综合
ag pipeline custom claude:plan codex:code claude:review -p "构建 API"
ag pipeline list                 # 查看流水线运行历史
ag pipeline show <run_id>        # 查看某次运行详情
```

### 配置

```bash
ag config show                   # 显示当前配置
ag config path                   # 配置文件路径（~/.agentbox/config.yaml）
ag config edit                   # 在编辑器中打开配置
ag config reset                  # 重置为默认配置
ag list                          # 列出可用的 Agent 和团队
```

### 高级命令

```bash
# 直接在沙盒中执行命令
ag sandbox exec claude-myproject bash -lic "ls /workspace"
ag sandbox exec -i claude-myproject bash   # 交互式 shell

# 预构建 Agent Docker 镜像（避免每次安装）
ag sandbox build claude

# Docker Compose 多 Agent 栈
ag stack up claude codex
ag stack down
ag stack logs
ag stack status
```

### 项目初始化（可选）

```bash
ag init                          # 创建 AGENTS.md + .agentbox/
```

`ag init` 不是必须的。它创建的 `AGENTS.md` 会被注入到 Agent 的上下文中，
帮助 Agent 更好理解你的项目结构。如果你不需要这个功能，可以跳过。

---

## 架构详解

### 目录结构

```
agentbox/
├── agentbox/
│   ├── __init__.py              # 版本号
│   ├── cli.py                   # CLI 入口（click 命令定义）
│   ├── config.py                # 配置管理（YAML 读写、Agent 检测）
│   ├── state.py                 # 会话状态管理（JSON 持久化）
│   ├── agents/
│   │   └── runner.py            # Agent 运行编排（核心逻辑）
│   ├── sandbox/
│   │   └── manager.py           # Docker 沙盒管理（创建/停止/删除/缓存）
│   ├── tmux_mgr/
│   │   └── manager.py           # tmux 会话管理（创建/窗口/attach）
│   ├── workflow/
│   │   └── core.py              # 工作流引擎（ask/diff/merge/review/test）
│   ├── orchestrator/
│   │   ├── engine.py            # 流水线执行引擎
│   │   └── pipeline.py          # 流水线定义（dev/research/compare）
│   ├── compose/
│   │   └── manager.py           # Docker Compose 多容器管理
│   └── templates/
│       └── docker/              # Dockerfile 模板
│           ├── Dockerfile.base
│           ├── Dockerfile.claude
│           ├── Dockerfile.codex
│           └── Dockerfile.aider
├── pyproject.toml               # Python 包配置
├── MANUAL.md                    # 本手册
└── README.md                    # 项目简介
```

### 数据流

```
用户 → ag claude → cli.py
                      │
                      ├→ AgentRunner.run_agent()
                      │     │
                      │     ├→ TmuxManager.create_session()     → 创建 tmux 会话
                      │     ├→ SandboxManager.create_sandbox()  → 创建/复用 Docker 容器
                      │     │     │
                      │     │     ├→ 检查运行中容器 → 复用
                      │     │     ├→ 检查停止容器 → 重启
                      │     │     ├→ 检查缓存镜像 → 从镜像创建
                      │     │     └→ 否则 → 从 ubuntu 创建 + 安装 Agent + commit 缓存
                      │     │
                      │     ├→ TmuxManager.add_agent_window()   → 在 tmux 中开窗口
                      │     │     └→ 执行 docker exec -it <容器> <Agent命令>
                      │     │
                      │     └→ register_window()                → 保存会话状态
                      │
                      └→ TmuxManager.attach_session()           → 连接到 tmux
```

---

## 沙盒镜像缓存机制

这是理解 Agentbox 性能的关键：

### 首次运行（慢，约 2-5 分钟）

```
ag claude
  │
  ├→ ubuntu:22.04 不存在？→ docker pull ubuntu:22.04
  ├→ 创建容器 agentbox-claude-glm
  ├→ apt-get install curl git build-essential
  ├→ 安装 Node.js 22
  ├→ npm install -g @anthropic-ai/claude-code
  ├→ 验证 claude 命令存在 ✅
  └→ docker commit → 保存为 agentbox-claude:latest 💾
```

### 再次运行（快，秒启动）

```
ag claude
  │
  ├→ 发现 agentbox-claude:latest 缓存镜像存在
  ├→ 从缓存镜像创建容器（已包含 Node.js + Claude）
  ├→ 验证 claude 命令存在 ✅
  └→ 跳过安装，直接启动！
```

### 容器复用（更快）

```
ag claude
  │
  ├→ 发现容器 agentbox-claude-glm 已在运行
  ├→ 验证 claude 命令存在 ✅
  └→ 直接复用！
```

### 缓存安全保障

- **commit 前验证** — 只有 Agent 确实安装成功才 `docker commit` 保存缓存
- **启动后验证** — 从缓存镜像创建容器后，检查 Agent 是否可用
- **坏缓存自动修复** — 如果缓存镜像中 Agent 丢失，自动重新安装
- **stop 时验证** — `ag kill` 停止容器前，只有 Agent 已安装才更新缓存

---

## 数据安全保障

### 容器停止 ≠ 数据丢失

| 操作 | 效果 | 数据 |
|------|------|------|
| `ag kill` | 停止容器 + 关闭 tmux | ✅ 保留 |
| `ag kill --rm` | 停止 + 删除容器 | ❌ 丢失 |
| `ag kill --all` | 停止所有容器 | ✅ 保留 |
| `ag kill --all --rm` | 停止 + 删除所有 | ❌ 丢失 |

### 双重保险

1. **容器保留** — `ag kill` 只停止不删除，`docker start` 即可恢复
2. **镜像缓存** — 停止前自动 `docker commit`，即使容器被删也能从镜像快速恢复

### 死进程自动重启

当你重新运行 `ag claude` 时：

```
检测到 tmux 窗口 sb-claude 已存在
  │
  ├→ 进程还活着？→ 直接 attach
  └→ 进程已死？→ 自动重启容器 + 重新发送命令
```

---

## 常见问题

### Q: 第一次运行 `ag claude` 很慢？

A: 首次需要下载 ubuntu 镜像 + 安装 Node.js + 安装 Claude Code，约 2-5 分钟。
安装成功后会自动缓存镜像，下次秒启动。

### Q: 看到 `⚠ Image 'agentbox-claude:latest' not found locally` 警告？

A: 正常！说明本地没有缓存镜像，会从 ubuntu 基础镜像创建并安装 Agent。
安装成功后下次就不会再有这个警告。

### Q: `ag claude` 直接跳到空窗口/报错？

A: 可能是之前的缓存镜像损坏（Agent 没装上就被缓存了）。
修复方法：
```bash
ag kill --all --rm                    # 清理所有
docker rmi agentbox-claude:latest     # 删除坏缓存
ag claude                             # 重新安装
```
v0.3.0 已自动修复此问题，安装后会验证 Agent 是否存在。

### Q: 如何彻底清理所有数据？

```bash
ag kill --all --rm                    # 停止并删除所有容器
docker rmi $(docker images -q agentbox-*)  # 删除所有缓存镜像
```

### Q: tmux 怎么用？

- `Ctrl+B` 然后 `D` — 脱离会话（Agent 继续运行）
- `Ctrl+B` 然后 `(` — 在 tmux 会话间切换
- `ag attach` — 重连到会话

### Q: Agent 怎么访问我的项目文件？

A: 容器启动时自动挂载当前目录到 `/workspace`。Agent 在 `/workspace` 中工作，
直接读写你的项目文件。这就是为什么需要 Docker 沙盒 — 限制 Agent 只能访问这个目录。

### Q: 支持哪些 Agent？

A: 内置支持：Claude Code、OpenAI Codex、Aider、Goose、OpenCode。
可通过 `~/.agentbox/config.yaml` 添加任意 Agent。

### Q: 需要先 `ag init` 吗？

A: **不需要！** 直接 `cd` 到项目目录运行 `ag claude` 就行。
`ag init` 只是创建 `AGENTS.md` 帮助 Agent 理解项目上下文，可选。

### Q: 环境变量怎么传递？

A: 在 `~/.agentbox/config.yaml` 中配置 Agent 的 `env_vars` 列表，
Agentbox 会从宿主机环境变量中读取并传递到容器。例如：

```yaml
agents:
  claude:
    env_vars:
      - ANTHROPIC_API_KEY    # 从宿主机 $ANTHROPIC_API_KEY 传入容器
```
