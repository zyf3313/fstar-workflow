# 核心命令实施计划

## 输入与放行

用户已批准 v1 总结并明确「没问题开始开工吧」。本轮只刷新已批准范围的子任务规划，不另加批准闸门；协调者负责后续任务启动和实施派发。本规划编辑不运行 task.py start、不修改 task.json、不写生产代码。

读取顺序：父任务当前 prd/design → 本子任务 prd/design → implement.jsonl 的适用规范/来源 → 代码现状。父 `design.md` 是自包含当前契约，父 `implement.md` §2 是 kickoff；research 只作来源，不覆盖父设计。`.trellis/spec/backend/index.md` 当前是占位索引，不能把占位建议当项目已验证规范。产品计划名 plan.md，本文件保留 Trellis implement.md。

技术默认：Python 3.9.6 兼容、标准库、unittest、`src/fstar/`。Node 24.14 包装稍后由安装子任务负责；核心无需 npm/网络依赖即可验证。

## 顺序、交付与完成判据

| 步骤 | 依赖 | 工作与目标文件 | 验证/完成判据 | 来源 |
|---|---|---|---|---|
| I-01 | 无 | models.py、__init__.py；26 字段及嵌套 schema、DomainError、确认/扩展结构 | test_models：精确顶层键、默认/null/数组、非法 phase/类型/混写、保留 meta 扩展 | CORE-01/02/05；AC-01/02/07 |
| I-02 | I-01 | store.py；根发现、路径约束、锁、原子替换、树扫描及 session 指针 | test_store：真实双进程争用、写失败原文件完整、损坏 JSON、symlink/..、会话隔离 | CORE-01/04；AC-05/06/09 |
| I-03 | I-02 | tasks.py；嵌套创建、list/current、状态派生、blocked、事件压缩与租约 | test_tasks：children 一致性、无写只读、token/到期/接管/续约、保留里程碑、容器聚合 | CORE-01/02/04；AC-01/05/06/07 |
| I-04 | I-02 | evidence.py；条目映射、哈希依赖闭包、交付快照、record/freshness/status | test_evidence：R-001 精确失效、CRLF 约定、映射丢失、生产/测试/配置改动、旧结果拒绝、五态覆盖 | CORE-03；AC-03/04 |
| I-05 | I-03/04 | tasks.py；start/accept/drop（含 revive）/continue 动作、review、extension 启用/裁剪/停用；统一 source 封套与必要覆盖重核 | test_lifecycle：完整与拒绝场景；replan 全部 evidence stale；失效 completed、历史验收留存、仅规划评审启用时要求相应稿件、无测试用例批准前置 | CORE-02/03/05；AC-02/03/04/08 |
| I-06 | I-05 | tasks.py/store.py；整树归档到 `.fstar/archive/YYYY-MM`、operation event 恢复、历史关联与候选事实/meta.reminders | test_archive：冲突无覆盖、子任务拒绝、不同中断点恢复、disposition 处置、历史新建关联、可选知识不阻塞 | CORE-01/05；AC-09 |
| I-07 | I-05/06 | cli.py、__main__.py；接受命令面、JSON/错误码、延迟注册 | test_cli：真实 subprocess 调用、独立模块缺席时 help 可用、失败不虚报成功；所有接受的 core 命令有解析与服务映射 | AC-08/10 |
| I-08 | I-07 | tests/ 集成用例与最终全量检查 | create→nested child→start→delivery/check→accept→archive；外部改动与接管负例；全部 unittest 通过 | AC-01–10 |

I-03 与 I-04 在 store/models 接口稳定后可并行，但 tasks.py 只分配一个实施写者；CLI 在服务签名冻结后实现。共享文件由主协调者合并修改，检查接手同范围后暂停实施写入。其他子任务可先用设计 API 准备，不能直接写 task.json 或增加顶层字段。

## 必须覆盖的验证场景

1. 每个新 task 的 26 键集合与权威清单完全一致；phase 永不保存 dropped/archived/旧七态；name/title/worktree_path 等保留。
2. 两个真实进程读取后写同一任务，锁防丢失更新；强制中断替换前/后留下完整旧值或完整新值。锁等待有界，异常不遗留独占锁。
3. 嵌套创建父登记失败/中断可发现不一致；不能因 children 空而遗漏实际子目录并验收。子树 terminal 聚合不重复写进度字段。
4. 固定 clock 检查 30 分钟边界、回报续约、过期接管；旧 token 即使 holder 名相同也不能写；continue 默认只读且不派发。
5. 映射至少两个稳定 ID，改一个只影响引用它及其依赖的证据；更改映射/删除条目/重复 marker 拒绝沿用；外部改文件无需 hook 仍可发现。
6. 同一 Git commit 下源码/测试/配置变化导致 delivery digest 变化；增补当前 required path 后旧证据覆盖不足。报告哈希变化被发现，不能依靠 commit 冒充当前版本。
7. 缺 check、新鲜但范围不全、只有 incremental、失败/阻塞/跳过/未执行、未解决问题、同一实施者冒充检查角色、过期确认等均不能 completed；有效独立 final check + 用户确认可 accept。
8. 用户来源测试断言字段完整性和版本绑定，不声称证明实际人类身份。conversation 缺原话/引用拒绝，review 指向非用户/旧版证据拒绝，Agent 代记 command 拒绝。
9. 未启用测试评审时可直接补测试并记录真实结果，缺 test-cases/review-log 不构成失败；check 修复生产代码后以新交付基线验证可通过。
10. 超过 200 事件时保留全部里程碑（含超过 200 个里程碑的场景），普通事件摘要可核时间范围/数量/必要来源，不新增 history.jsonl。
11. 五包的 full/custom/会话授权与显式 enable/crop/disable 行为，include/exclude 冲突拒绝、capabilities 不混写；无 task 的只读/会话授权不建任何目录。显式持久化写目标缺失则报错。
12. 归档仅从 `.fstar/tasks` 移动主任务树至 `.fstar/archive/YYYY-MM`，已存在目标不覆盖；同 operation_id 在源/目标两侧中断均能诊断恢复；带 symlink/../绝对路径失败且外部哨兵文件不变。归档历史关联不恢复旧任务。
13. 归档候选提供真实时间依据、状态及缺失项；`meta.reminders` 用任务ID+状态/缺项摘要+最近活动版本去重，默认暂缓7天；continue 不查询其他任务；失败巡检不回滚成功归档。

测试预期来自 PRD 判据；不得只复制代码分支来“证明”实现。采用 tempfile.TemporaryDirectory 隔离 project/home/runtime；运行子进程设置显式 PYTHONPATH，禁止碰真实用户 `.fstar`。mock 仅控制时间和 IO 故障；并发、路径逃逸、CLI 用真实文件/进程。

## 验证命令

在仓库根目录执行（实现后可运行）：

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
PYTHONPATH=src python3 -m fstar --help
PYTHONPATH=src python3 -m fstar task list --help
python3 -m compileall -q src/fstar tests
```

每组先跑对应 test 模块，最终一遍完整 unittest；通过后没有新变化不重复全量运行。当前没有项目 lint/typecheck 工具配置，不编造检查结果、不为了本子任务加第三方依赖。交付报告记录实际 Python 版本、运行命令、通过数量、失败/未运行项和限制。

## 共享接口交接

- project-layout：`.fstar/.schema-version` 的值 `1`，只读 `find_project_root(start)`；`atomic_write_json` 不解析 YAML；init 模块按 `register_commands(subparsers)` 接入。不让 core 生成项目索引/模板。
- runtime-dispatch/hooks：使用 TaskService 租约和 EvidenceService 记录/重核；主协调者持单写者 token。worker-result 声明角色/交付版本，worker done 不自动 accept。
- workflow-content：按 CLI 收敛面调用；review record 是补录，不重建用例批准前置；归档巡检只能在 archive 流程显示。
- installer：Python 包位于 src/fstar，入口 `fstar.cli.main(argv=None)`，Node 只转发参数/stdio/退出码；核心 import 不要求 runtime/tools/project 模块已存在。

## 回滚与最终核对

每步限制写入对应 src/tests 范围；失败先修复当前增量，不覆盖其他子任务共享接口。无旧产品数据迁移；测试数据可删除，用户真实数据不可用于故障测试。跨文件操作按 design 的 operation event、任务 ID 与目录事实诊断恢复，不声称所有操作只有一个文件事务。

最终检查逐项覆盖 AC-01–10、全部 core 命令、26 字段、5 包、事件软 200、30 分钟租约、item/delivery 指纹、archive 路径与来源声明限制。实现完由独立 check 核对并可直接修本范围代码、重跑受影响测试，最后整体检查。生产实现与任务 start 不属于本次规划刷新交付。

## 实施进度与自检证据（2026-10-29）

- I-01–I-08 已实施：`src/fstar/{__init__,__main__,models,store,tasks,evidence,cli}.py` 与 `tests/test_core.py`。
- 公开边界已稳定：schema marker `1`、`atomic_write_json`、`find_project_root`、`TaskStore`、`TaskService`、`EvidenceService`、`register_core_commands` / `main`；可选模块仅在模块真实存在时注册。
- workflow-content 映射交接采用 `meta.templates.artifact_map = {artifact: {item_id: {start_marker, end_marker, dependencies[]}}}`；core 规范化、计算 `artifact_map_sha256` 并持久化，content 只生成只读映射。
- 已运行 `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v`：20 tests passed；覆盖真实进程锁争用、30 分钟租约/旧 token、外部文件失效、路径与 symlink、归档冲突及移动后中断恢复、CLI 子进程与只读无项目不落盘。
- 已运行 `python3 -m compileall -q src/fstar tests`、`PYTHONPATH=src python3 -m fstar --help`、`PYTHONPATH=src python3 -m fstar task list --help`：通过。
- 额外复合 real CLI smoke 命令因执行权限被环境拒绝，未计为通过；CLI create/current 已由真实 subprocess unittest 覆盖。
- 当前仓库无 lint/typecheck 配置；未虚报。下一步停止实施写入，交独立 check。

## 独立检查结果（2026-10-29）

- 独立 check 已完成并直接修复核心缺陷，详见 `check-report.md`。
- 最终结果：`tests.test_core` 36 tests OK；全仓 discover 54 tests OK（含 layout 的 project/config）；`compileall` 与全部 `--help` 通过。
- 修复覆盖：严格 26 字段类型、最新 final check 治理、依赖闭包、递归子任务验收/归档、生产者独立性、创建回滚、租约/遗弃写闸门、review 来源、事件摘要折叠、可选模块 handler 分发（init 集成）与 CLI 来源/错误路径。
- 未做复合 shell smoke（权限被拒，未重试）；限制与下游 API 变更见 `check-report.md`。
- 追加（内容检查转报的契约缺陷）：整文件保守模式 `"mode":"file"` 现可经 `persist_artifact_map` round-trip，`snapshot` 输出 `granularity:"file"`，freshness/invalidate 按整文件哈希失效；新增 `test_file_mode_roundtrip_and_stale_on_change`。最终：核心 37 tests OK、全仓 discover 79 tests OK、compileall 与 help 通过。

