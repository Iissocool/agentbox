# Agentbox 手册 — v0.3.0

> 🧊 一个命令搞定一切：`ag`

## 快速参考

| 命令 | 说明 |
|------|------|
| `ag` | 交互式选择 Agent |
| `ag claude` | 在沙盒中运行 Claude |
| `ag codex` | 在沙盒中运行 Codex |
| `ag aider` | 在沙盒中运行 Aider |
| `ag status` | 仪表盘：查看所有会话和沙盒 |
| `ag attach` | 重连到会话 |
| `ag kill` | 停止会话（沙盒数据保留） |
| `ag logs` | 查看沙盒日志 |
| `ag history` | 查看会话历史 |

## 命令详解

### 启动 Agent

```bash
ag                               # 交互式选择 Agent
ag claude                        # 在沙盒中运行 Claude Code
ag codex                         # 在沙盒中运行 Codex
ag aider                         # 在沙盒中运行 Aider
ag goose                         # 在沙盒中运行 Goose

# 带 prompt 启动
ag claude -p "修复认证 bug"

# 带角色启动
ag claude -r coder -p "实现功能 X"

# 运行任意已配置的 Agent
ag run <agent_id> -p "prompt"
```

### 会话管理

```bash
ag status                        # 仪表盘：所有会话、沙盒、Agent 状态
ag attach                        # 交互式选择会话并重连
ag attach ag-myproject           # 重连到指定会话
ag kill                          # 交互式选择会话并停止（沙盒数据保留）
ag kill ag-myproject             # 停止指定会话（沙盒数据保留）
ag kill --rm ag-myproject        # 停止并永久删除沙盒数据
ag kill --all                    # 停止所有会话（沙盒数据保留）
ag kill --all --rm               # 停止并删除所有会话和沙盒
ag history                       # 查看会话历史
```

> 💡 `ag kill` 和 `ag attach` 都可以**不加会话名**，会弹出交互式选择器让你选择。

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

### 工作流快捷方式

```bash
ag ask "为什么这么慢？"          # 向 Agent 提问
ag ask --test "修复这个 bug"     # 让 Agent 修复并运行测试
ag diff                          # Git diff 摘要
ag diff --patch                  # 完整 diff
ag merge -m "添加功能 X"        # 暂存所有更改并提交
ag review                        # 审查更改、运行测试、合并或丢弃
ag test                          # 运行项目测试
```

### 流水线

```bash
ag pipeline dev "添加用户认证"   # 规划 → 编码 → 审查
ag pipeline research "Rust vs Go" # 研究 → 总结 → 评审
ag pipeline compare "优化性能"   # 多 Agent 对比
ag pipeline custom claude:plan codex:code claude:review -p "构建 API"
```

### 配置

```bash
ag config show                   # 显示当前配置
ag config path                   # 配置文件路径
ag config edit                   # 在编辑器中打开配置
ag config reset                  # 重置为默认配置
ag list                          # 列出可用的 Agent 和团队
ag init                          # 在项目中初始化 agentbox
```

### 高级命令

```bash
# 直接在沙盒中执行命令
ag sandbox exec claude-myproject bash -lic "ls /workspace"
ag sandbox exec -i claude-myproject bash   # 交互式 shell
ag sandbox build claude          # 预构建 Agent Docker 镜像

# Docker Compose 多 Agent 栈
ag stack up claude codex
ag stack down
ag stack logs
ag stack status
```

## 架构

```
ag（CLI 入口）
├── tmux 会话（ag-<项目名>）
│   ├── 窗口: sb-claude → docker exec -it agentbox-claude-<项目名> claude
│   ├── 窗口: sb-codex  → docker exec -it agentbox-codex-<项目名> codex
│   └── 窗口: shell     → 本地 shell
└── Docker 容器
    ├── agentbox-claude-<项目名>  (ubuntu + claude + /workspace 挂载)
    └── agentbox-codex-<项目名>  (ubuntu + codex + /workspace 挂载)
```

## 沙盒镜像缓存

1. 首次运行：`ubuntu:22.04` → 安装 Agent → `docker commit` → `agentbox-claude:latest`
2. 再次运行：直接使用缓存的 `agentbox-claude:latest`（秒启动）
3. 容器复用：如果同一项目的容器已在运行，直接复用

## 会话恢复

如果状态丢失（如 `state.json` 被删除），运行 `ag status` 或 `ag history`
会自动从 Docker 容器标签中恢复会话信息。

## 数据安全

- `ag kill` 默认**只停止容器，不删除**，数据完整保留
- 下次运行 `ag claude` 会自动重启已有容器（无需重新安装 Agent）
- 停止前自动 `docker commit` 保存到缓存镜像，双重保险
- 只有 `ag kill --rm` 才会永久删除容器数据

## 小技巧

- `Ctrl+B` 然后 `D` 脱离 tmux（会话继续运行）
- `ag attach` 随时重连
- `ag kill` 后容器保留，下次启动自动复用
- 使用 `--no-attach` 参数启动 Agent 但不进入 tmux