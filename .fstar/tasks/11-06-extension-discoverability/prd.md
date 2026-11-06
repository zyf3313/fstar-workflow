# 扩展可发现性与默认只读注入

## 背景

fstar 的可选扩展（`project-governance`、`planning-review`、
`persistent-task`、`multi-agent`、`tool-capability`）默认关闭。实际使用中，
用户在会话里表达持久约定（例如“记一下：终端代理用 `proxy` / `unproxy`”）时：

1. 会话上下文只显示 `Extension members in this context: {}`，用户看不到
   有任何可选能力存在；
2. `project-governance` 未授权时，`~/.fstar/index.md` 与项目
   `.fstar/index.md` 完全不注入，即使手工写了用户级规则也不会被读到；
3. routing 规定学习候选只挂在 session/result/recovery/archive 节点，
   用户中途提出的持久约定没有被定义为触发点，agent 直接落到了宿主
   （Claude Code）自带 memory，而不是 fstar 的 `user_rules`。

结论：能力存在但不可发现，就等于不存在。需要把“发现 + 读取”默认打开，
写入仍然保持逐次确认。

## 范围

### R-001 会话上下文默认展示可用能力

- 新增资源 `resources/runtime/capabilities.md`，用一句话说明五个可选扩展
  各自的用途与“默认关闭、按需授权”的事实。
- `hooks.session_context` 每次注入该资源（无论是否有授权），kind 记为
  `capabilities`，带 path/sha256/version 指纹。
- `inject.capabilities_input(root)` 与 `routing_input` 同一资源根解析路径。

验收：

- Given 一个未授权任何扩展的会话
- When SessionStart/compact 注入会话上下文
- Then 输出中包含 `capabilities` 输入，且五个包 ID 全部出现

### R-002 项目与用户索引默认只读注入

- 移除 `src/fstar/runtime/hooks.py` 中 “四项 governance 成员全齐才注入”
  的条件，`inject.index_inputs(project_root, user)` 默认执行。
- 保持 `_safe_context_path` 的符号链接/越界拒绝逻辑不变；只读、不写。
- 不因默认注入而放宽任何写入路径：`fstar-learn` 仍要求
  `project-governance` 授权、`proposal_hash` 与用户原话确认。

验收：

- Given 没有任何扩展授权
- When 项目 `.fstar/index.md` 与 `~/.fstar/index.md` 存在
- Then 两者内容都出现在 session context 的 `loaded` 中
- And 指向外部的符号链接索引仍然不被注入

### R-003 routing 增加持久约定的触发规则

- 在 `resources/runtime/routing.md` 明确：
  - 用户陈述的持久约定（跨会话、跨项目或明确要求“记下来”）属于
    session 节点的学习候选；
  - 当前没有覆盖目标位置的授权时，agent 必须先提出对应的扩展建议
    （通常是 `project-governance` 的 `rules` 或 `memory` 成员）；
  - 不得静默退化到宿主级 memory，除非用户明确拒绝 fstar 路径。
- 写入侧的确认闸门不变。

验收：

- routing 文本包含上述触发与禁止静默退化的要求
- 现有最小闭环语义不被改写

## 不做

- 不自动启用任何扩展；能力仍然默认关闭，发现与读取默认开启。
- 不改变 learn_bridge 的 proposal/confirmation 协议。
- 不改 `fstar extension list` 的输出格式（后续可另行考虑）。

## 验证

- `PYTHONPATH=src python3 -m unittest discover -s tests -t .` 全绿
- `node --test tests/test_package.cjs` 全绿
- `node scripts/build-package.cjs` 重建 `resources/package-assets.json`
- `fstar doctor` 健康
