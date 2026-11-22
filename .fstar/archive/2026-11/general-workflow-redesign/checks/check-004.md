# S-4 独立检查报告（最终检查）

- dispatch_id: s4-check-001
- 检查者：fstar-check 全新实例（与全部交付者不同实例）
- scope: final（只读：未修改任何交付文件，探针全部在 /tmp 临时项目运行）
- 对照规格：[s4-spec.md](../doc/s4-spec.md) K-1..K-6
- 实施派发：s4-kernel-001（K-1/K-2/K-3/K-6 内核）、s4-resources-001/002（K-4/K-5 + routing/execute 补全）、s4-cleanup-001（旧夹具补 read_only + check 资源文档）
- environment: python3（tests 864/864 OK，103.1s）、node --test tests/test_package.cjs 16/16（7.8s）
- 交付基线：branch chore/general-workflow-design @ 6032b52 + 未提交工作树；全部 14 个输入文件 sha256 与派发指纹逐一核对一致（含 s4-spec.md 完整 64 位与 13 个 src/tests/resources 文件重算完整哈希），交付未被改动
- 幂等：build-package 两次 manifest 字节不变（sha256 69af58de…857c25e8f8 前后一致）

## 一、理解线（对每项 K 的理解与实现宣称）

- K-1：打回从"全量作废"扩展为可选局部作废。实现：evidence.validate_rework_scope（规范化+校验）、EvidenceService.invalidate_scope（单一作废逻辑）、_rework_scope_touches（交集判定）。宣称两条入口共用、事件带审计字段、CLI 双入口 --scope-file。
- K-2：最终检查只读三重门禁。实现：_validate_check 记录时强制 read_only:true + final_delivery_current 新鲜度；dispatch.harvest 拒绝带 changed_paths 的 final 检查。
- K-3：规则验收可引用 criteria 条目。实现：_validate_acceptance_rule + _criteria_item_ids（artifact_map 条目并集），accept 与 accept_unified(master) 双写 acceptance 与事件。
- K-4：criteria.md 增判定方式 + criteria.mapping.yaml 使 A-xxx 可提取。
- K-5：execute Skill 六步自验收收尾程序 + fstar-check 角色卡只读要求。
- K-6：重访文档列表调整（实现偏离规格，见四）。

## 二、符合线（逐条核对，对照标准编号）

| 项 | 结论 | 关键证据 |
|---|---|---|
| K-1.1-3 范围对象与交集判定 | passed | evidence.py:43-100。五通道全覆盖：validates[].artifact∈artifacts；items[].id/dependencies[].id∈criteria_refs；delivery.paths/input_files/report.path∈paths∪artifacts；check 类 items[].requirement_ids∩criteria_refs。mapping 与规格形状逐字段一致，mode 缺省 full |
| K-1.4 空 localized 拒绝 | passed | evidence.py:64-65 抛 invalid_rework_scope，不静默退化；测试 test_empty_localized_scope_is_rejected、test_malformed_scope_is_rejected（paths 非数组、mode=partial 均拒） |
| K-1.5 两入口同一段逻辑 | passed | tasks.py:784（report_problem）与 tasks.py:979（continue rework）都只调 evidence.invalidate_scope，无第二套作废路径（全仓库 grep 确认无其他调用方） |
| K-1.6 事件审计字段 | passed | 两入口事件 data 均含 scope/invalidated_evidence_ids/retained_evidence_ids；rework_requested 在 MILESTONES（tasks.py:21），compact_events 不折叠，acceptance_status 的 retired_by_rework 依赖它（evidence.py:509-512）可长期存活 |
| K-1.7 默认行为不变 | passed | git diff 确认旧代码是逐条 valid→stale + stale_reasons=[{"type":"rework_requested","reason":reason}]；invalidate_scope full 模式产生逐字节相同结果（test_default_rework_still_invalidates_everythings 断言 stale_reasons 原文） |
| K-1 CLI --scope-file | passed | cli.py:100/147/285/316；accept --rework 与 continue --action rework 双入口；测试 test_cli_scope_file_on_accept_rework_and_continue_rework 走真实 main() |
| K-2.1 read_only 门禁 | passed | evidence.py:380-382，`is not True`（缺省与 false 都拒），incremental 不受限（测试覆盖） |
| K-2.2 harvest 拒绝 changed_paths | passed | dispatch.py:1126-1130 final_check_not_read_only；拒绝发生在 _record_harvested 之前 → dispatch 未标记 harvested，可重试（探针 2 实测：同一 dispatch 被拒后清空 changed_paths 重试成功） |
| K-2.3 交付新鲜度（按路径比对） | passed（含偏离，见四） | evidence.py:454-487 final_delivery_current：每个路径取最新 delivery 证据为有效基线。探针 2 实测：双路径漂移→拒（列出 both）；只重交付 src.py→仅 report.py 仍阻塞；全部重交付→final check valid |
| K-2.4 独立性不变 | passed | check_not_independent 逻辑未动（evidence.py:371-375） |
| K-2 增量不受影响/旧证据不追溯 | passed | test_incremental_check_is_not_constrained、test_harvest_incremental_check_with_changes_is_not_rejected、test_stored_legacy_final_check_without_read_only_stays_usable（门禁只在记录时执行） |
| K-3.1-3 rule 字段与校验 | passed | tasks.py:1030-1062。criteria_refs 非空字符串数组、未知条目拒并列出 details.unknown；_criteria_item_ids 取全部 artifact 条目并集（跳过 "mode" 键） |
| K-3.4 双写 | passed | accept（tasks.py:1094-1108）与 _complete_one（tasks.py:1264-1278）：acceptance 记 rule_ref+criteria_refs，事件 accepted_via_rule 含全部给出字段；accept_unified 只对 master 传 rule，子任务不经规则校验 |
| K-3.5 零回归 | passed | test_old_style_rule_file_still_works（老式规则文件、acceptance.criteria_refs=[]）、test_no_rule_acceptance_path_is_unchanged（无 rule 时事件无 accepted_via_rule） |
| K-4 criteria 模板与 mapping | passed | validate_resources 0 诊断；criteria.md 含判定方式 machine/user-judgment 与"含 user-judgment 不得自验收"；criteria.mapping.yaml 与 plan.mapping.yaml 仅 artifact_type 一行不同；extract_artifact 实测提取出 A-001、A-002 |
| K-5 execute 收尾程序 | passed | SKILL.md 六步与 ~/.fstar/rules/self-acceptance.md 逐条对齐：五项门槛一致、永不覆盖清单六类一致、防漂移三条一致、报告路径 checks/self-acceptance.md 一致；命令行 `fstar accept <task> --rule RULE.json --confirmation SOURCE.json` 与 CLI 实际参数一致（cli.py:92-95） |
| K-5.4 check 角色卡 | passed | agents/fstar-check.md:10：最终检查 allowed_paths 为空、只回报不修复、发现交付被改动必须说明而非修改；三个检查相关资源 grep 确认均含 read_only 要求 |
| K-6 重访列表 | passed（含偏离，见四） | _REVISIT_DOCS 现值 ("doc/prd.md","doc/design.md","plan.md","clarify.md","criteria.md")，_docs_to_revisit 只报告实际存在的文件；continue --action replan 行为不变（test_replan_records_criteria_and_legacy_docs） |
| routing.md 第四条/规则豁免段 | passed | 硬规则 4 写明"按受影响条目+依赖局部复查、无法界定时全量保守、复查后仍需一次新的最终只读检查"，与内核 localized 语义 + rework_requires_new_check 阻塞一致；规则豁免段与 execute 六步程序互指一致 |

## 三、可用线（实际运行）

- 全量回归：864 tests OK（0 失败 0 错误）；Node 16/16。
- 幂等：manifest 两次构建字节一致。
- 探针 1（/tmp 独立临时项目）：localized rework(criteria_refs=[A-001]) 后相关 check 置 stale、delivery 保留 valid；acceptance_status 变 False 且 blockers=[rework_requires_new_check]；补一次新 final check 后 awaiting 恢复 True 且 evidence_refs 指向新检查；随后带 criteria_refs/report/scope 的规则验收成功，事件与 acceptance 双写全部查到。
- 探针 2：final 检查带 changed_paths → final_check_not_read_only 且 dispatch 未标记 harvested、同 dispatch 干净重试成功；缺 read_only → invalid_check；按路径交付基线（部分重交付解除已修复路径、未修复路径仍阻塞、全部重交付后 final valid）。

## 四、影响面（impact-check-guide 两层）

- 第一层（调用方签名）：report_problem/continue_task/accept/accept_unified 新参数均带默认值；全仓库调用方仅 cli.py，零改动兼容。models.py 的 deliverable criteria_refs 是另一个既有字段，与验收规则 criteria_refs 无冲突。
- 第二层（机制交互）：compact_events 不折叠新事件键；acceptance_status 的 retired_by_rework、rework_requires_new_check 消费链完整（enter_awaiting_acceptance/accept/state/request_recheck 均正确）；accept_unified/_require_children_ready、archive/_validate_archive_tree 对新字段为被动记录，无隐式依赖；hooks.py 无 read_only/final 消费点；invalidated/retained 列表受证据数上界约束，无无界增长；installer manifest 63 文件哈希逐一核对一致。

## 五、必须修复才能验收

无。

## 六、实施偏离报告（均已评估为合理）

1. **K-6 偏离**（tasks.py:40-47）：规格要求从 _REVISIT_DOCS 移除 doc/prd.md、doc/design.md；实现保留两者并新增 criteria.md——旧任务目录里已存在的 doc 文件在 replan 时仍应被提示重访，移除会产生漏报。_docs_to_revisit 按存在性过滤，新任务行为与规格意图一致。已有注释与测试固化。
2. **K-2 第 3 条偏离**（evidence.py:454-487）：规格说"用现成的 _validate_current 判定"；实现新增 final_delivery_current 做按路径的有效基线判定——_validate_current 逐证据对照自身快照，修复后旧 delivery 永远 stale，会永久阻塞"检查失败→修复→重交付"流程（正是规格遇阻条款预设的情形）。测试与探针 2 双重覆盖。

## 七、建议后续改进（不阻塞验收）

1. evidence.py:91-94：_rework_scope_touches 对 input_files/delivery.paths 条目直接 .get("path")，历史数据混入非 dict 条目会抛 AttributeError 而非 DomainError；建议做 isinstance 防御（与 _validate_current 的容错风格对齐）。
2. execute SKILL.md 第 5 步只写 --confirmation FILE 一种确认方式；CLI 同时支持 --confirm-user + --invocation。当前文本可照做（更严格），仅表述收窄提示。

## 三线检查结论

- 理解线：六项 K 的实现与规格语义对应清楚，无歧义项。
- 符合线：全部条目 passed；两项实施偏离均合理且已按规格要求报告。
- 可用线：全量回归、独立探针、幂等、manifest 完整性全部通过。

结论：S-4 通过最终检查，建议进入用户验收。
