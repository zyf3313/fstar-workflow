# Walkthrough: antigravity-adoption

任务目录：`.fstar/tasks/antigravity-adoption/`。改了什么 + 如何验证 + 证据。

## 改了什么（按 P-001 ~ P-005）

### P-001 设计（commit 6b6e811 内）
- 产出 `design.md`：origin 字段（id+archive_path+reason，OPTIONAL_TASK_FIELDS 模式，不 bump schema）、unarchive 状态机（新 `unarchived` 里程碑事件、仅顶层、user 确认、整树移动、attach 聚合并入 unarchive）、父上下文注入清单与三态降级（loaded/partial/missing）、A-009 session grants 与 A-010 steward 的方向性设计。
- plan.md 按 design 复核 P-002/P-003 拆分（A-013 首次实践）。

### P-002 内核（commit 6b6e811 + 55ab8a8）
- `src/fstar/models.py`：`OPTIONAL_TASK_FIELDS` 增加 `origin`（+20 行，含测试计数资源清单同步）。
- `src/fstar/tasks.py`：`_validate_origin` / `_locate_origin_parent`（id 权威、path 提示、归档树+活动顶层双扫描兜底）；`create(--origin)`；`unarchive()`（not_archived / unarchive_child_forbidden / unarchive_forbidden / invalid_confirmation / unarchive_blocked / archive_conflict 拒绝路径；先 rename 后事件；整树清 archivedAt；`_origin_followups` attach 聚合进 subtasks/ 并登记 children，origin 字段保留）。
- `src/fstar/cli.py`：`task unarchive` 子命令 + `task create --origin`。
- `tests/test_origin_unarchive.py`：10 个新测试，含无 origin 旧任务全链路兼容测试。

### P-003 注入（commit 0997742）
- `src/fstar/runtime/inject.py`：`resolve_origin_parent`（archive_path 优先、id 扫描兜底）、`parent_context_inputs`（design.md / walkthrough.md 必注、criteria.md 预算内；超限 deferred 不静默；三态报告）。
- `src/fstar/runtime/hooks.py`：`worker_context` 注入父文档，`task_summary.parent_context` 随 JSON 报告，footer 显式 loaded/partial/missing 行。
- `src/fstar/dispatch.py`：payload `context_report.parent_context` 校验 + harvest 落档（注入失败可审计，杜绝冒称成功）。
- `tests/test_parent_context.py`：11 个测试（注入、unarchive 后 id 解析、缺失降级、超预算 partial、无 origin 兼容、双通道、harvest 落档）。

### P-004 规则与角色（commit 7c4056c）
- A-003：`resources/templates/task/plan.md` 每步骤绑定验证方式；fstar-plan SKILL.md 含糊步骤回退澄清不派发。
- A-004：fstar-check SKILL.md 增加 Challenger 职责（反例/边界用例，按 blast radius 缩放）。
- A-005：doc/walkthrough.md 标准收尾产物；`archive(workflow=True)` 硬门禁 `walkthrough_missing`。
- A-007/A-011/A-012：fstar-clarify 重构为探索主导式（澄清循环 + 四规则 grill 模式 + 质疑清单）。
- A-008：routing.md/prompt-states.md coordinator 纯派发模式（会话草稿与宿主记忆例外 + 无子 agent 降级）。
- A-009：`store.set_session_grants`/`read_session_grants`（session_id 哈希的 project_runtime 槽位）；worker-context / session-context 双通道解析（payload extensions 优先、session store 回读）；CLI `extension enable --session` 持久化。
- A-010：`content.ROLES` + `resources/agents/fstar-steward.md` role card + hooks/dispatch role_member 门禁（multi-agent/steward）+ CLI actor-role 枚举。
- A-013：fstar-plan 触发条件、prompt-states planning 状态、`fstar start` 软门禁 `design_doc_missing`（criteria.md `design-required` 标记扫描）。
- A-006 扩展：routing.md 对话产物落任务 doc/ 规则。
- `tests/test_p004_rules.py`：start 门禁、session grants 往返与 hook 回读、steward 门禁、archive walkthrough 硬门禁。

### P-005（本 commit）
- `antigravity-comparison.html` → `.fstar/tasks/antigravity-adoption/doc/antigravity-comparison.html`（git mv）。
- 本 walkthrough.md。
- `checks/final-check.md`：A-001~A-013 逐条独立核验 + Challenger 反例结论。

## 如何验证

- 全量 Python：`PYTHONPATH=src python3 -m unittest discover -s tests` → **Ran 1146 tests, OK**（2026-11-28，含新增 test_origin_unarchive.py 10、test_parent_context.py 11、test_p004_rules.py 若干）。
- Node 包测试：`node --test tests/test_package.cjs` → **16 pass, 0 fail**。
- Challenger 现场用例（见 checks/final-check.md）：unarchive→attach→再归档→stale archive_path 注入解析、origin 链（孙任务指向子任务）、直接 `archive(workflow=False)` 绕过面。
- 影响面定向回归：`tests.test_external_host_upgrade tests.test_worktree_identity tests.test_hooks` → 166 tests OK。

## 证据

- commit：6b6e811（P-002 in progress，含任务文档与讨论材料）、55ab8a8（P-002 完成）、0997742（P-003）、7c4056c（P-004）、本 commit（P-005）。
- P-002 commit 正文记录 "full regression 1125 passed"；P-004 commit 正文记录 "full Python suite 1146 OK; node --test 16 pass"。
- Challenger 现场验证输出（2026-11-28，临时目录）：
  - `unarchive attached: ['fix-1'] -> .../tasks/root`
  - `re-archived to: .../archive/2026-11/root`
  - `origin.archive_path (stale): .fstar/archive/2026-11/root` → `parent_context: loaded | parent_path: .fstar/archive/2026-11/root | loaded kinds: ['parent_design', 'parent_walkthrough']`（id 扫描兜底生效）
  - 链式 origin：`chain parent_context: loaded .fstar/archive/2026-11/root/subtasks/fix-1`（注入一层父，符合设计 §3.2 清单）
