# Plan: defect-report-batch1

已核对（见 guides/defect-report-verification.md 流程）后的高性价比修复批次。
不做的条目：B-16（不成立）、B-08（已有 cross 替代）、退出码映射（不成立）。

## A1. B-02/B-04 lease 释放与错误信息（文案级，不改状态机）

- `src/fstar/tasks.py:731-735` `lease_conflict`（enter_awaiting_acceptance）详情
  补一句：`"hint": "release via 'fstar interrupt <task> --dispatch-id ... --release-lease-token ...' or wait for expiry at <expires_at>"`。
- `src/fstar/tasks.py:728-730`：`phase == "awaiting_acceptance"` 时改用独立分支
  报 `phase_transition_forbidden`，消息为
  "Task is already in awaiting_acceptance; use `fstar accept <task>` to accept it"。
- 同类 `_require_unleased`（tasks.py:246）的 details 补同样 hint。

## A2. B-11 add-deliverable 写入 artifact_map（`src/fstar/tasks.py:664-687`）

`register_deliverable` 在写 deliverables 的同时，把
`meta.templates.artifact_map[path] = {"items": {}}` 之类的空映射写入（复用
`evidence.py:108 persist_artifact_map` 的 normalize 规则，不绕过它——直接调用
`EvidenceService.persist_artifact_map` 不可行因为它独立事务；在 register_deliverable
的事务内写同结构字段并保持 `artifact_map_sha256` / `artifact_map_source` 一致）。
source 用当前 actor。不删除既有 artifact_map 条目，只 merge。

## A3. B-10/B-17 enforced 规则注入 + 可见状态行（`src/fstar/runtime/`）

- `inject.py` 新增 `enforced_rule_inputs(user_root)`：解析
  `~/.fstar/index.md` 中 `strength: enforced` 的 Rules 行，读对应
  `user_root/rules/<name>.md` 全文，作为 InjectedInput 注入。
- `hooks.py session_context`：把 enforced 规则正文加入 inputs（受 budgets 限制）。
- 可见状态行（B-17）：`runtime/__main__.py` 的 `session-context` 分支在
  `print(result["text"])` 之外，向 **stderr** 打一行
  `⏺ fstar SessionStart ✓ project=<name|-> rules=N Xms`（stderr 不会进入模型
  注入通道，用户在终端可见；hook 协议下 stdout 是注入体）。计时用
  `time.perf_counter()` 在 main 里量。worker-context 保持注入语义不变，不加状态行。
- prompt-context 不加输出（节流，按增补篇设计只在状态变化时输出——本次先不做
  变化检测，保持现状）。

## A4. B-03 `fstar schema` 命令（`src/fstar/dispatch.py`）

新增顶层 `schema` 子命令：`fstar schema {payload|result|change}`，输出
各 schema 的字段表 + 一个最小可运行 JSON 示例到 stdout。纯只读，不碰任务。
示例基于 `dispatch.py` 的 `validate_payload` / `validate_result` 必填字段。

## A5. B-14 `--version` 别名（`src/fstar/cli.py`）

`build_parser` 加 `parser.add_argument("--version", action="store_true")`；
`main()` 在 parse 后若 `--version` 则调用与 `version` 子命令相同的 handler 输出
并 `return 0`。注意 argparse `--version` 与子命令互斥的处理：在 parse_args 之前
无法拦截，采用 `parse_known_args` 或直接在 argv 预扫描 `--version`（预扫描更简单
且不影响现有解析）。

## 测试与回归

- 全量 `PYTHONPATH=src python3 -m unittest discover -s tests -t .`
- `node --test tests/test_package.cjs`
- 未改 `resources/`，不需要 rebuild manifest；若实现中改了 resources，跑
  `node scripts/build-package.cjs`

## 明确不做

- B-16 doctor（不成立）；B-08（cross 已覆盖）；退出码映射（现状正确）；
- dispatch register 幂等（B-07，机制大改动，单独任务）；
- stdin payload（B-14 部分，涉及 CLI 多处，单独任务）；
- fstar status 命令（B-01，扩展功能，单独任务）。
