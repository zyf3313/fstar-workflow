# 核心命令独立检查报告

检查对象：`.trellis/tasks/10-27-core-commands` 的 `src/fstar/{__init__,__main__,models,store,tasks,evidence,cli}.py` 与 `tests/test_core.py`。
权威依据：父任务 `10-25-fstar-workflow-design/design.md` 全文（已完整读取，非截断版）、父 `implement.md`、本子任务 prd/design/implement、`check.jsonl`。实现者报告只作起点证据。

检查者只修改核心与 `tests/test_core.py`；未修改 `project.py`/`config.py`/resources/宿主设置/全局 home/git。

## 修复的确认缺陷

1. `evidence.acceptance_status`：旧轮 passed final check 会压过更新的未解决失败。父设计 §5.2 要求最新当前轮 fail/blocked 阻止用更早 passed 充数。现以最新新鲜 final 为准，旧的标 `superseded`，并有 `unresolved_check` blocker。
2. `evidence._validate_current`/`snapshot`：依赖闭包只记录裸 ID，依赖条目变化不会失效。现 `validates[].dependencies` 记录闭包条目哈希，任意可达条目变化、缺失或映射冲突均产生 stale 原因（`dependency_changed/dependency_missing/mapping`）。
3. `tasks.accept` / `tasks.archive`：验收与归档未递归核对子任务。新增 `_require_children_ready` 与 `_validate_archive_tree`，逐层要求 completed 或 disposition、验收证据仍新鲜、无 blocked/lease、disposition 无待处理项；归档返回整树 ID 并清指针。
4. `models.validate_task`：仅校验少量字段类型。现校验 id 为 UUID、所有字符串/时间/对象/数组字段类型、26 键、phase/priority、children 唯一安全名、blocked 结构、evidence/lease/acceptance 类型、extensions 七字段、events 五字段封套。
5. `evidence.record`：未阻止 delivery 生产者兼任 check 生产者；`accept` 也无最终防线。现 record 与 accept 双重拒绝同 producer id（`check_not_independent`）。
6. `tasks.create`：子目录发布后父登记写入失败时，内存中已 append 导致回滚条件失效、残留未登记子目录。现按磁盘父 children 判断并清理。
7. 租约/遗弃闸门：`set_blocked`、review record、extension enable/disable、evidence record/invalidate、artifact map 写入在活跃租约或 dropped disposition 下会被拒绝（`lease_conflict`/`task_dropped`）。`drop` 签名 disposition 变默认值以支持 revive。
8. `tasks.continue_task`：replan/revise/reopen 现必须带确认来源，replan 仅限 in_progress（completed 需先 reopen）；写入 `confirmation_required`/`replan_forbidden`。
9. 来源封套：`_actor_source` 不再把机器/agent 事件标成 `command`（改 `system`）。review 类型确认必须引用当前有效、approved、producer=user 的 review evidence。
10. `evidence._validate_check`：check 条目的 `plan_item`/`requirement_ids` 必填，必须覆盖 validates 条目，且 validates 条目 ID 必须已存在于持久 `meta.templates.artifact_map`（报告不能自定义覆盖范围）。
11. `tasks.compact_events`：摘要不再每次新建；后续压缩折叠进已有 summary（count/by_type/first/last），里程碑永不清除。
12. `cli` 可选模块分发：新增 `_fstar_module_handler` 约定，在创建 TaskService 前调用；桥接 layout 现有 `_fstar_project_handler`；`main` 将带 `.code/.message` 的模块异常翻译成 JSON/人读错误（exit 2）。修复前 `init` 在未初始化根上返回 `project_not_initialized`。
13. `cli` session-only extension：删除返回未初始化 `TaskService.__new__` 的死路径；enable/disable 需显式 `--confirmation` 或 `--confirm-user`；确认来源 actor 决定调用 actor，不再默认把 CLI 调用者标成 user。
14. `cli` dropped/lease 与 JSON 错误路径：state/acceptance 服务调用使用锁内 task dict；错误码与退出码保持 design §2（2 输入、3 闸门、4 冲突、1 IO）。
15. 整文件保守模式 round-trip（内容检查转报）：`persist_artifact_map` 接受内容模块输出的顶层 `"mode": "file"` 映射（含空 artifact items），持久化保留该声明；`snapshot` 在 file 模式下输出 `granularity:"file"` 的整文件哈希；`freshness`/`invalidate` 以整文件哈希比对，任何改动即失效；`_validate_check` 的 artifact_map 覆盖校验在 file 模式下接受任意条目 ID（覆盖即整文件）。

## 新增回归测试（tests/test_core.py）

- 严格 26 字段类型/嵌套 schema；最新失败 final 压制旧 pass；依赖闭包失效；同 producer 兼任 check 被拒。
- stale confirmation 拒绝 accept；review 来源必须是 approved 用户评审。
- 删除交付文件被检出；子任务验收 stale 阻止父 accept；归档递归拒绝非终态子任务。
- dropped 任务拒绝普通写入并可显式 revive；continue 动作缺确认被拒；孤儿租约可见（`orphaned`/下一步）。
- 两个真实进程各 10 次读改写，最终计数 20（无丢失更新）。
- 归档列表、related_tasks 历史关联及错误 id 拒绝、归档候选与 `meta.reminders` 去重。
- CLI `init` 真实子进程、`state`/`acceptance` JSON、缺目标 `task_required`、无项目只读不落盘、session-only extension。

## 验证命令与结果

环境：Python 3.9.6（macOS），标准库；仓库无 lint/typecheck 配置，未运行或编造。

```sh
PYTHONPATH=src python3 -m unittest tests.test_core -v          # 37 tests, OK
PYTHONPATH=src python3 -m unittest tests.test_project -v       # 10 tests, OK（layout）
PYTHONPATH=src python3 -m unittest tests.test_config -v        # 8 tests, OK（layout）
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v   # 79 tests, OK
python3 -m compileall -q src/fstar tests                        # OK
PYTHONPATH=src python3 -m fstar --help                          # OK
PYTHONPATH=src python3 -m fstar task list --help                # OK
PYTHONPATH=src python3 -m fstar init --help                     # OK
```

真实 CLI smoke：`fstar --json init <fresh>` 创建 4 个 `.fstar` 文件并返回 root；重复 init 保留既有文件（exit 0）。原“复合 shell smoke”命令曾被环境权限拒绝，未重试、未绕道，也不计入通过。

## 剩余限制（未声称已解决）

- 不声称阻止同权限进程/Agent 伪造来源、actor 或测试结果；`source: command`/`confirmed_by=user` 只是结构一致性校验，非身份安全边界。
- 仅 `evidence.record` 以 lease token+到期强制写者身份；其余命令以 role/确认/活跃租约拒绝为闸门。未给所有 API 增加 token 参数（保持 design §2 公开签名）。
- 持久任务授权（design §7 表中 create 输入）无项目级存储落点；按 design §2 的 `create` 签名由宿主/会话授权决定，core 不新建隐藏授权库。
- 交付路径集合由调用方（plan/派发范围）提供；core 能检出内容变化与删除，不能推导“新增必需路径”，需派发侧补传后重录。
- review evidence 的 state 不因 artifact 变化自动改 stale（freshness 计算可报告）；accept 以 final check 为准。
- events 压缩按软 200；被压缩的普通 `archive_operation` 事件在极端事件量下可能不再可用于中断恢复（design 将其定义为普通操作事件；archived 里程碑保留）。
- 锁为 POSIX `fcntl`；Windows 未实现（design 允许）。
- 归档巡检阈值 30 天/暂缓 7 天为技术默认；候选基于事件时间，不用 mtime。
- 未做真实宿主集成、Node 包装或跨平台验证（他子任务范围）。

## 下游需要的接口/行为说明

- 可选模块协议：`register_commands(subparsers)` 用 `parser.set_defaults(_fstar_module_handler=fn)`；`fn(args)` 返回可 JSON 序列化结果，异常带 `.code/.message/.path` 时由 CLI 转成错误。layout 现有 `_fstar_project_handler` 由 cli 自动桥接，无需改 layout。
- 整文件保守模式：`persist_artifact_map` 接受并保留顶层 `"mode":"file"`；file 模式下 `snapshot()` 返回 `granularity:"file"`、每个 item 绑定整文件哈希、无 dependencies；freshness/invalidate 按整文件哈希判断。内容模块可直接把 `build_artifact_map` 的输出交给 `persist_artifact_map`。
- `EvidenceService.snapshot()` 的 `dependencies` 现在是 `[{id, sha256}]`（闭包，含直接条目；file 模式恒为空）。
- `record()` 的 check evidence 必须提供 `plan_item`、`requirement_ids`，且 validates 条目须已在 artifact_map 中；delivery producer 不得与 check producer 同 id。
- `acceptance_status(ref=None, *, task=None)`、`freshness(ref=None, *, task=None)` 可用于已持锁的 task dict；返回 `superseded`/blocker（`unresolved_check`、`children_incomplete`、`acceptance_stale`）。
- `TaskService.drop(..., disposition="keep")` 现在有默认值；replan/revise/reopen 必须传确认来源。
- continue 默认仍只读；显式 takeover/replan/revise/reopen/unblock 才写。

结论：AC-01–10 在本子任务范围内可观察项已逐项核对并修复；核心 37 个测试、全仓 79 个测试通过。
