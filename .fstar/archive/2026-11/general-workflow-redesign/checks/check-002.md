<!-- Allowed placeholders: {{run_id}}, {{environment}}, {{delivery_baseline}}, {{duration_retries}} -->
# 检查报告 check-002

- scope: incremental
- environment: macOS (Darwin 27.0.0)，python3 + node --test；分支 chore/general-workflow-design 工作区未提交改动（S-1 与 S-2 同在工作区，本报告只检 S-2 部分）
- delivery baseline: 工作区未提交改动（S-2 实施：src/fstar/models.py、src/fstar/tasks.py、src/fstar/cli.py、tests/test_task_schema.py、resources/package-assets.json）
- measured duration / retries: Python 全量 823 tests 约 106s（1 次）；S-2 代码 stash 后基线 807 tests（806 通过 + 1 个 import 错误模块）约 104s（1 次）；node 16 tests 约 8s（1 次）；test_task_schema 单独 17 tests 约 1.4s（1 次）；CLI 实测脚本 1 轮；并发/交错探针各 1 轮；build-package 幂等 1 次

| 标准 / 要求编号 | 对照内容与版本 | Test path and identifier | Command or review method | Result | Log |
|---|---|---|---|---|---|
| S-2-1 全量测试 | plan.md S-2 完成判据；dispatch S2-check-001 标准 1 | tests/（全量）；tests/test_package.cjs | `PYTHONPATH=src python3 -m unittest discover -s tests -t .` → Ran 823 tests, OK（退出码 0）；`node --test tests/test_package.cjs` → 16 pass / 0 fail（退出码 0）；stash 掉 S-2 三个源文件后基线为 806 通过 + 1 个 import 失败模块（tests.test_task_schema 引用了被 stash 的 API），823 = 806 + 17 新增，确认零回归且新测试真实依赖新代码 | passed | 本地运行输出 |
| S-2-2 向后兼容真实性 | dispatch 标准 2 | tests/test_task_schema.py::SchemaFieldTests；独立复测脚本 | 独立构造 HEAD 时代旧 task.json（26 字段、无新键），`store._read_path` 读入后 `store.write` 写回，`read_bytes()` 前后完全一致（字节级）；读入结果不含任何新键、无默认值注入；`new_task` 实测输出 26 键、TASK_FIELDS 26 项、五个新字段均不在其中（models.py 第 8–14 行确认）。仓库内测试用 dict 相等（弱于字节级），但 atomic_write_json 为 sort_keys 确定性序列化，字节级由我独立验证成立 | passed | 独立探针输出 byte-identical round trip: True |
| S-2-3 source_snapshot 隔离 | dispatch 标准 3；design.md §4 兼容评估点 | src/fstar/tasks.py:154-155；tests/test_task_schema.py::test_new_fields_do_not_change_source_snapshot | source_snapshot 仅哈希 {task_id, phase, description, meta.templates}，五个新字段为顶层键，结构上不可能进入哈希；测试覆盖（写入全部五字段后 snapshot 不变）；我另在 CLI 实测项目中比较了带/不带新字段的同一任务 snapshot，相等 | passed | 代码审读 + 双向复测 |
| S-2-4 字段校验质量 | dispatch 标准 4 | tests/test_task_schema.py::test_validation_rejects_malformed_optional_fields（13 例）；独立构造 21 个非法输入 | 独立跑 21 个非法输入（含枚举外 status/state、缺 since、非 ISO since、status_detail/work_items/deliverables 未知键、重复 id/name、空 id/name、evidence_refs 非字符串数组、next_step 单边、顶层未知键），21/21 被 DomainError 拒绝，错误码均以 invalid_ 开头；测试用 assertRaises 真实失败而非恒真 | passed | 探针输出 rejected: 21/21 |
| S-2-5 CLI 表面 | dispatch 标准 5 | tests/test_task_schema.py::CliSurfaceTests + 临时项目实测 | 临时项目实测 `state set-status/set-work-item/set-next/add-deliverable` 全部退出码 0 且落盘正确；错误路径：`--status sleeping` 被 argparse choices 拒绝（退出码 2）、非 active 缺 reason → reason_required（退出码 2）、set-next 单边参数 → invalid_next_step（退出码 2）、set-next 无参清除成功；`state show` 正确展示 status（默认 active）、status_detail、其余字段缺席时省略不输出 null | passed | /tmp 临时项目 CLI 运行输出 |
| S-2-6 lease 旁路评估 | dispatch 标准 6（重点） | src/fstar/tasks.py:564-574 注释与四个写方法；并发探针 | 结论：可接受，无需加检查。依据：(a) transaction() 用 fcntl flock 项目级独占锁串行整段读-改-写（store.py:677-698），两个 Agent 并发 set_work_item 实测（线程并发）两条目均保留、两个 work_item_updated 事件均在、lease 完好，无丢更新；(b) 现有 _require_unleased 只用于改变语义/影响验收的操作（set_blocked、extension change、review record、enter_awaiting_acceptance），新字段为与 phase 正交的描述性协作状态，不 gate 任何生命周期；(c) dropped 任务仍被 _require_not_dropped 拒绝（task_dropped，实测）；(d) lease 期间 set_blocked 仍被拒绝（实测），释放后恢复，说明旁路未误伤守卫面。残留风险仅为事件顺序交错（逻辑层面，无数据损坏），可接受 | passed | 并发与交错探针输出 |
| S-2-7 schema 版本不 bump | dispatch 标准 7 | src/fstar/store.py:17 SCHEMA_VERSION="1"；installer.py migrate（2123 起） | 实施者理由与代码事实一致：SCHEMA_VERSION 是项目存储定位标记（require_project/rebind 用它判定项目根与数据根，bump 会让所有现存项目直接 unsupported_schema），而非 task.json 字段版本；task.json 本身无内嵌版本号，新字段由 validate_task 就地校验；migrate 生产注册表为空、1->1 显式 no-op，本改动无旧数据需要搬运。不 bump 正确 | passed | 代码审读 |

Result values: passed, failed, blocked, skipped, not_run.

## 三线检查结论

- 理解正确性：S-2 范围（design §4 五个可选字段 + state 展示 + 兼容）被准确执行：字段全可选、new_task 不预填、旧文件字节级不变、source_snapshot 不受影响、每次变更追加事件、state show 按默认值/省略两种方式降级展示。未发现越界改动（tests/test_content.py、test_e2e_scenarios.py、test_installer.py 的 11→12 模板计数改动属 S-1，未触碰）。
- 符合约定：plan.md S-2 完成判据（现有测试零回归、新字段读写与降级显示有测试覆盖）逐条满足；事件信封沿用 v1 结构（_actor_source 走 system 类型，不冒充用户命令，与 §5.3 一致）。
- 交付可用性：全部命令与探针可复现；manifest（package-assets.json）重建后 62 条目逐一核验 sha256 全部匹配，build-package 幂等（重跑无新增 diff，哈希更新仅对应 cli.py/content.py/models.py/tasks.py 与 S-1 模板条目移动）。

## 并行拆分与汇总（大任务适用）

本次为单一检查实例（S2-check-001），无并行分片。

## Repairs and reruns

无修复。lease 旁路经评估不构成缺陷（见 S-2-6），未改动实施代码；S-1 模板文件未触碰。

## Uncovered scope and blockers

- 无 blockers。
- 两条非阻断观察，留给协调者/后续步骤裁量：
  1. `_is_iso_timestamp` 接受纯日期字符串（如 "2026-11-21"）——fromisoformat 的宽松面；语义上仍是合法 ISO 日期，非错误，但若要求完整时间戳需收紧。
  2. service 层 `set_work_item`/`register_deliverable` 的 normalizer（work_item/deliverable）会静默丢弃未知键（store 层 validate 仍会拒绝带未知键的存量数据，写入路径产生的数据始终规整）——行为一致但与 validate_optional_fields 的拒绝策略不完全对称，仅为风格差异。
- 未验证项：S-3..S-6 未实施（不在本范围）；`fstar state show` 对 deliverables 字段的断言在 StateShowTests 中未显式覆盖（CliSurfaceTests 经落盘读取覆盖了 deliverables 内容），属覆盖面小缺口，非缺陷。
- scope 标为 incremental：S-2 为六步切分中的第二步，最终（final）检查待 S-6 完成后另开只读检查。
