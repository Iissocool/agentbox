# Agentbox 开发进度

> 最后更新: 2026-06-10

## 已完成的功能

### 核心框架
- `agentbox/__init__.py` - 包初始化，版本号
- `agentbox/config.py` - 配置管理
- `agentbox/state.py` - 会话状态追踪
- `pyproject.toml` - 项目配置和 `agentbox`/`ag`/`agx` CLI 入口

### Agent 运行器
- `agentbox/agents/runner.py` - 单 agent、compose、team、compare、sandbox 运行编排

### Tmux / Sandbox / Pipeline
- `agentbox/tmux_mgr/manager.py` - tmux session/window 管理
- `agentbox/sandbox/manager.py` - Docker 沙盒管理
- `agentbox/orchestrator/pipeline.py` - Pipeline/PipelineStep/StepType 和内置 pipeline
- `agentbox/orchestrator/engine.py` - 顺序/并行执行、上下文传递、状态持久化

### Workflow
- `agentbox/workflow/core.py` - WorkflowEngine
- AGENTS.md 加载和 prompt 注入
- git repo 检测、diff、diff stat、merge、discard
- 测试命令自动检测和执行
- ask 工作流：注入 AGENTS.md 后启动本地或 sandbox agent
- review 工作流：diff + test + merge/discard/skip 交互

### Docker Compose
- `agentbox/compose/manager.py` - DockerComposeManager
- 生成 `.agentbox/docker-compose.yml`
- `stack up/down/logs/status` 多容器栈管理

### CLI 命令
- agent 命令：`claude`、`codex`、`aider`、`goose`、`opencode`、`run`
- 编排命令：`compose`、`team`、`compare`、`pipeline`
- workflow 命令：`ask`、`review`、`diff`、`merge`、`test`
- 管理命令：`sandbox`、`session`、`stack`、`config`、`init`、`list`

## 验证

```bash
python3 -m compileall agentbox
agentbox --help
agentbox ask --help
agentbox review --help
agentbox diff --help
agentbox test --help
agentbox stack --help
agentbox test -c true
```

## 后续可选增强

- 为 WorkflowEngine 增加单元测试
- 为 Docker Compose 栈增加镜像不存在时的构建或回退策略
- 支持从 YAML 文件定义更复杂的 stack 服务参数
