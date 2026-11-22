# 最终整体检查报告（只读最终检查）

- dispatch_id: final-check-001
- 检查者：fstar-check 全新实例（与全部交付者不同实例）；read_only，allowed_paths=[]，零改动
- 判据：.fstar/tasks/general-workflow-redesign/criteria.md（ec14028db9c315b4145a618d668fd5c6e17dc5311bb180566203061e9065ac03）A-001..A-012
- environment: macOS Darwin 27.0.0、Python 3.9、Node v24.14.0；分支 chore/general-workflow-design，工作区未提交改动
- baseline: HEAD 6032b52365926104b07154b1358fd5a733718084 + S-1..S-6 未提交工作树
- 结束时复验：15 个派发输入文件指纹、HEAD、`git diff HEAD --stat`（42 files changed / 1912 insertions / 250 deletions）与开工前逐字一致
- measured duration / retries: Python 全量回归 2 次（117.06s）、Node 16/16 1 次、manifest 构建 3 次、7 个独立探针共 170 条断言；探针脚本自身预期写错迭代重跑 6 次（非交付缺陷，逐条记录在报告）

## 判定表

| 标准 | 结论 | 关键证据 |
|---|---|---|
| A-001 通用四阶段与运行状态兼容 | passed | 旧 26 键 task.json 读回 0 个新键、往返字节一致（仅 canonical 末尾换行差异）；真实 CLI set-status/set-work-item/set-next/add-deliverable；state show 旧任务省略新字段不报 null；source_snapshot 前后同值；phase 与 status 相互独立 |
| A-002 按需文档与扁平任务目录 | passed | TEMPLATES 12 项无 doc/ 前缀，prd/design 在 scenarios/software；manifest 64 条目无 templates/doc；全仓 templates/doc 零命中；本任务根目录已扁平 |
| A-003 任意位置交付编辑与基线安全 | passed | 任务根/自选目录/遗留 doc//session-only 四类路径通过结构校验；7 个越界输入被 unsafe_dispatch_path 拒；harvest 白名单外写入 → scope_violation 且未写入；store.project_file 三重拒绝 |
| A-004 实施与检查角色分离 | passed | 四张角色卡字段齐全；check 卡最终检查 allowed_paths 必须为空且不自行修复；implement 卡声明自查不等于独立检查；check 模板按标准条目切分、最终检查不并行、read_only 无 changed_paths；内核实测 check_not_independent 拒同实例 |
| A-005 局部复验与最终只读检查 | passed | 默认 rework 三条证据全 stale 且 scope.mode=full；显式 localized 仅相交证据 stale，其余 valid，事件带三个审计列表；局部作废后 awaiting_acceptance=False、blockers=[rework_requires_new_check]，补新最终检查后恢复；空/畸形范围 4/4 拒；最终检查缺 read_only 两次均 invalid_check，incremental 不受限；harvest 带 changed_paths → final_check_not_read_only 且派发未标记 harvested、可重试 |
| A-006 用户验收与规则自验收门槛 | passed | 未知 criteria 条目被拒并列出 unknown；rule_ref/quote 缺失、criteria_refs 非法 5/5 拒；真实 CLI accept --rule --confirmation 退出码 0，task.json 与事件双写；execute 六步与全局规则文件五项准入门槛逐条对应、user-judgment 即停、永不覆盖类别集合相同、报告路径一致；routing 写明 fresh final check 本身不构成豁免 |
| A-007 意图驱动的技能选择协议 | passed | 四状态输出同时含 prompt-state 与 skill-reminder，提醒 804 字符且不含 SKILL 正文；资源缺失降级为固定一行不静默；未初始化路径零写入；派发携带 selected_skills 且 worker prompt 写明不扩权与防递归；skill_usage 三类状态校验、not_used/failed 缺 reason 3/3 拒；旧形状兼容；routing 无 magpie/herdr 字样，Python 无技能名硬编码与目录扫描、无自动安装 |
| A-008 技能选择的真实宿主有限案例 | passed（有限范围） | 复核 checks/check-005-host.md：真实 Skill 工具调用（加载 ~/.claude/skills/fstar-help 并执行 doctor/help）、同一行动不重复加载、跨阶段重选、无匹配不建任务不追问、worker 补选；该记录基线 routing.md 与交付树不同（差异不在技能选择节），受影响的协议行为本轮已自行重测 |
| A-009 四能力接口、缺席降级与分发兼容 | passed | 四类齐备；空注册表全部 available=False 并指向规定降级；破损 adapter probe 异常不抛栈；能力不兼容握手降级；probe/handshake 零副作用；magpie.py 零 diff；installer 经 adapter 转交且 native_only 绕过探针 |
| A-010 经验范围、纠正与停用闭环 | passed | 五字段落盘回读；旧文档仍加载且 confidence 如实为 null；越 scope 不注入；显式 documents 直选无法绕过 scope/到期/停用；自然语言条件被排除并标 unknown（显式判定后才注入）；到期理由写明日期；read 全程零写入且拒绝时钟覆盖；纠正经 prepare→确认→apply 事务、旧记录保留原文与 source 并标 superseded、新记录带 confidence 与新 source、索引同步；停用各路径都不注入；非法 scope/confidence/expires 5/5 拒；promote 无 consent 拒、有 consent 才过 |
| A-011 旧安装升级与完整生命周期 | passed | install --dry-run 零写入；真实 install 写入临时 host root 与临时 user 数据根（未触碰真实用户配置）；doctor 退出码 0、read_only、healthy；update --dry-run 零写入；version 报 0.9.0/资源 8/schema 1/release_ready false；migrate 为独立显式命令且无安装副作用；旧 task.json 与旧规则文档仍可读；生命周期 e2e 走通 创建→交付→独立最终检查→awaiting_acceptance→用户验收→归档，恢复路径正常；manifest 幂等 |
| A-012 范围边界与发布状态 | passed | HEAD==main、main..HEAD 为 0、未提交未推送；package.json 与 cli_version 均 0.9.0、标签最新 v0.9.0、npm 无新版；源码零 herdr、零调度器实现（仅接口与降级）、零云同步、零进程内 LLM 推理、零自动习惯记录；README 按约定未动 |

## 三线检查结论

- 理解正确性：通过。交付与 A-001..A-012 语义逐条对应，未擅自扩大也未遗漏；A-005 用真实事件与 acceptance_status 验证而非以 routing 措辞代替实现；A-010 用真实 packaged bridge 子进程验证而非以字段落盘代替过滤闭环。
- 符合约定：通过。判据全部取自已确认结论与既有规格，未新增需求、未把 machine 当已通过、未把受控案例当通用语义可靠。
- 交付可用性：通过，但不构成用户验收。验收仍须用户按 fstar-execute 程序明确完成。

## 并行拆分与汇总

本轮为单一只读最终检查实例，未并行分片（依 check 模板「只读最终检查不并行」与 C-21）。实例对 A-001..A-012 整体负责，未按文件切分。零 changed_paths，全部探针在 /tmp 临时项目内。

## 影响面（两层）

第一层（签名兼容）：全部新增/变更签名调用方已核对，新参数均带默认值，旧 payload/result/规则文件/ReadSelection 形状兼容；零调用方因签名变化失败（955 全绿佐证）。全仓只有 tasks.py 两处入口调用 evidence.invalidate_scope，无第二套作废路径。

第二层（机制交互）：

- 事件类型：S-2 新增 status_changed/work_item_updated/next_step_changed/deliverable_updated 未进 MILESTONES，属普通事件，超限折叠进 summary（保留 count/by_type/last_at）。四项新事件的权威状态在 task.json 顶层字段，折叠不影响现值追溯。
- 注入路径：技能提醒经 inject.resource_root() 取同一可信根，无新信任面，只读单个已知文件不扫描目录；read_context 仍走 _safe_context_path。
- 归档/验收校验：_validate_archive_tree 只消费 phase/acceptance/evidence_refs/disposition，对新字段被动记录；acceptance_status 消费 evidence_refs/retired_by_rework，不消费 validation_facts 文本或 skill_usage_reported。
- 预算与压缩：prompt-context 输出本不计注入预算，新增提醒约 804 字符/轮为固定开销；skill_usage 挂 validation_facts 不新建存储。
- installer manifest：副本上两次重建 sha256 恒为 89c599cf…，与磁盘 64 条目逐一相符。
- 范围外实现复查：零调度器/herdr/云同步/自动习惯/Python 内 LLM 推理。

## 必须修复项

无。

## 建议改进（不阻断）

1. A-002 任务目录残留：本任务目录仍保留 doc/design.md、doc/s4-spec.md（被 plan.md 与 check-004.md 引用）与 research/、samples/ 两个展开目录；模板集已不再生成 doc/，如需自洽可迁移这两个被引用文件到根目录（牵动链接）。
2. A-002 措辞差异：criteria.md 写"检查记录固定放入 checks/"，fstar-check SKILL.md 写"单份短记录可留在任务根 as check.md"（源自用户原话 C-22）。按实质判通过，建议协调者决定收紧 SKILL 表述或在 criteria 补一句。
3. A-003 授权面：editor 结构性目录约束移除后，授权完全落在"协调者逐文件列白名单 + harvest scope_violation + 角色卡文字"三层；越出项目仍被双层拒绝。未见新越权路径，但这是真实的内核护栏移除，建议在角色卡或 routing 补一句"editor 派发白名单应只列交付文件"。
4. 事件分类：请协调者确认 S-2 四个新事件按普通事件处理是有意为之。
5. A-008 版本对齐：宿主证据基线与交付树不同，建议下次 install/update 后补一次对照观察并更新基线指纹。
6. install --host-root 与 --host 需同时给出，易踩坑；可在 help 文案补一句。

## 已验证 / 未验证分层

已验证（本次实跑可复现）：955 Python OK、Node 16/16、manifest 幂等；7 个探针 170 条断言全绿；A-001..A-007、A-009..A-012 行为面均由本实例实跑确认。

未验证（明确保留）：

1. A-008 真实宿主语义超出 5 个受控案例范围：自然对话命中率与任意意图匹配无统计证据。
2. 真实宿主的完整长版提醒未激活：全局安装仍为 0.9.0/资源 8，旧 prompt-states.md 无 [skill-reminder]，真实宿主仍走降级短句；工作树已含完整提醒，需 install/update 生效（发布与全局更新按用户要求推迟，本轮未越权执行）。
3. 规则自验收五门槛的执行正确性未被机器强制：内核只强制可审计性，"每条 machine/证据新鲜/无 user-judgment"三项由 execute 程序约束；本次 CLI 验证在临时项目用合成规则文件完成，未在真实任务跑过完整自验收闭环。
4. experience 读写未触及真实用户知识：纠正/停用/读取均在临时 fixture 完成，真实 ~/.fstar/rules/ 未改动。
5. A-011 真机升级路径未执行：仅验证临时根上的安装/更新/doctor 与旧数据读取，真实全局安装原地升级未做；Node tarball 打包安装由 test_package.cjs 覆盖。
6. 依赖蔓延极端组合未专门固定：局部范围指向的条目依赖未被点名的条目时，内核按交集判定保留未命中的依赖 valid，符合保守表述但无用例固定。
7. 整项任务的最终验收仍待用户。

## Repairs and reruns

零修复。Python 全量 2 次（第一次汇总行被自身 tail 管道过滤）；Node 1 次；manifest 在仓库副本上构建 2 次（仓库内 manifest 未被写入）；探针脚本 6 次迭代均为检查者自身预期写错（a/./b 实为合法相对路径、旧 task.json 往返差 1 字节为 canonical 换行、editor 缺 item_ids 的拒绝针对 editor 角色、install 需同时给 --host 与 --host-root、migrate 需自己的 --project、continue --action takeover 需 --reason）。

## Uncovered scope and blockers

无 blockers。派发的 15 个输入指纹、HEAD、只读约束全部满足并复验一致。所有探针在 /tmp/fstar-final-check-BeTtms/**，install/doctor 目标为临时 user 数据根与临时 host root；未 npm publish、未 git push、未合并、未改版本、未改 README。遗留探针目录可手动删除。

结论：A-001..A-012 全部 passed，无 failed/blocked，未发现必须修复项。本检查不代替用户验收，也不构成合并或发布建议。
