# Antigravity 借鉴落地执行计划

依据：clarify.md 的用户确认结论、criteria.md 的 A-001 至 A-006。适用规范入口：项目索引 .fstar/index.md 所列 .fstar/specs/backend/index.md（Python 内核）、.fstar/specs/frontend/index.md（包交付面）及 .fstar/specs/guides/index.md（全项目工程指南），具体适用正文按变更范围选择。计划的步骤本身不代表验收通过；检查结果以 progress.md 和检查记录为准。

<!-- fstar:item:P-001:start -->
## P-001 设计：origin 链、reopen 语义与数据 schema
- 目的：确定任务 schema 扩展（origin 来源标记）、已归档父任务 reopen 的状态转换与事件记录、以及归档聚合（父子一起重新归档时目录树的形成规则）的完整设计。P-001 产出的 design.md 同时充当本任务自身的 design（origin/reopen/注入等机制设计），P-001 完成后 plan.md 需按 design 结论复核并修正 P-002/P-003 的拆分（如有偏差），作为 A-013 新规则的首次实践。
- 输入：clarify.md、criteria.md（A-001/A-002/A-006）、src/fstar/tasks.py 现有 schema 与事件系统、store.py 归档路径逻辑、既有归档树实例（.fstar/archive/2026-11/）。
- 行动：只读调查现有 task.json 结构、archive/revive 事件流和迁移机制（fstar migrate）；产出 origin 字段定义、reopen 状态机（含事件类型、目录移动规则、父子重归档规则）、上下文注入的文档清单（design.md/walkthrough.md）及降级行为设计；区分实现事实与设计提案。
- 产出：design.md 设计记录（含影响范围与兼容性分析）。
- 完成判据：覆盖 A-001、A-002 的机制设计与 A-006 的兼容性/迁移风险。
- 遇阻处理：设计不确定处保留为待确认并列出选项；不覆盖或迁移用户数据。
- 依赖与调整：无前置；设计结论调整后续步骤拆分。
<!-- fstar:item:P-001:end -->

<!-- fstar:item:P-002:start -->
## P-002 内核实现：origin 字段、reopen 与归档聚合
- 目的：实现 P-001 确定的 schema 扩展、reopen 命令/事件、父子共同重归档。
- 输入：P-001 设计、现有源码及规范。
- 行动：分解为可验证实施范围，交由 fstar-implement 派发实施，具体涵盖：tasks.py 新增 `unarchived` 事件（入 MILESTONES）与 `fstar task unarchive <ref>` 命令（仅顶层归档任务、user 角色确认、整树 `archive_root/<month>/<name>` → `tasks_root/<name>` 目录移动并清整树 archivedAt、acceptance 非 valid 拒绝）；attach 聚合并入 unarchive（扫描 tasks_root 顶层 `origin.task_id` 匹配的任务整体迁入父 subtasks/、登记 children、origin 字段保留，不设独立子命令）；origin 可选字段按 OPTIONAL_TASK_FIELDS 模式（id+archive_path+reason，校验 invalid_origin，缺席=行为不变，不 bump schema）；兼容测试（无 origin 字段旧 task.json 的 create/list/archive 全链路行为不变）。walkthrough.md 路径约定为任务 doc/walkthrough.md（design 已定决策），P-003 注入依赖此路径。
- 产出：内核代码、测试（含无 origin 旧任务全链路兼容测试）、变更说明。
- 完成判据：覆盖 A-001、A-002 的实现证据与 A-006 的兼容性测试（无 origin 字段的旧任务行为不变）。
- 遇阻处理：冲突保护优先；超出授权范围的决定（如破坏性迁移）单独返回用户。
- 依赖与调整：依赖 P-001；实现变化回写设计。
<!-- fstar:item:P-002:end -->

<!-- fstar:item:P-003:start -->
## P-003 dispatch 上下文继承实现
- 目的：带 origin 的联调任务在 dispatch/check 时自动注入父任务 design.md 与 walkthrough.md。
- 输入：P-001 设计（注入清单与降级行为）、src/fstar/dispatch.py 现有 payload/read_context 逻辑、P-002 的 schema 实现。
- 行动：交由 fstar-implement 实施 dispatch 注入与降级记录；注入路径为父任务 `doc/design.md` 与 `doc/walkthrough.md`（design §3.2 清单，walkthrough 落 doc/ 已定）；注入过 inject 现有 per-file/total 预算（超限截断记入 deferred，不静默）；origin 缺失/ID 不匹配/父不可解析时降级——不阻断 dispatch，context_report 增加 parent_context 字段（loaded/partial/missing）随 harvest 落档，杜绝冒称注入成功；coordinator 可经 prepare_read_context 主动带选段（双通道）。运行针对性测试（父文档存在/缺失/超预算/origin 指向已归档任务等场景）。
- 产出：dispatch 代码、测试、变更说明。
- 完成判据：覆盖 A-002 的注入证据（含降级路径如实记录）。
- 遇阻处理：父文档缺失时降级不阻断；注入失败不冒称成功。
- 依赖与调整：依赖 P-002。
<!-- fstar:item:P-003:end -->

<!-- fstar:item:P-004:start -->
## P-004 workflow 内容层：plan 验证方式、Challenger 规则、walkthrough 模板
- 目的：规则与模板层落地三个借鉴点，不改动内核。
- 输入：criteria.md（A-003/A-004/A-005）、resources/runtime/ 现有 workflow 内容、resources/runtime/prompt-states.md。
- 行动：交由 fstar-implement 更新 workflow 内容——plan 模板/规则增加"每个 plan_item 绑定独立客观验证方式"；fstar-check 规则增加 Challenger 反例检查项；walkthrough.md 收尾产物模板（改了什么+如何验证+证据）纳入 execute/accept 流程说明；prompt-state 增加联调问题识别提示（问题落在已归档大需求范围内时提示挂靠而非孤立任务）；routing.md / fstar-clarify SKILL.md 增加澄清循环规则（A-007）——用户消息含意见征求时先回应分析；建任务后继续 clarify 循环直到澄清；与 fstar-clarify "Maintain clarify.md yourself" 行的派发化改造（若 X-1 范围后续确认）在同次变更中协调；实施 coordinator 纯派发模式（A-008）——修改 routing.md、prompt-states.md 及各 skill（fstar-clarify 的 "Maintain clarify.md yourself" 行改为派发维护、fstar-plan 的 plan.md 维护路径同样派发化），明确主 agent 直接写文件的例外边界仅限会话内即时草稿与宿主记忆；修复派发授权链路（A-009）——排查 host Agent 派发 payload 的 extensions 携带方式与 hook 授权解析（src/fstar/runtime/hooks.py worker_context 的 grants 来源），修复后验证 fstar-editor/research 派发注入正常；新增 fstar-steward 角色（A-010）——host agent 定义（resources/agents/ 与宿主安装）、role card、hook worker-context 的角色识别与授权成员归属（与 A-009 的链路修复同次协调）、routing.md 中该角色的路由条目；实施对抗性澄清与协同调度（A-011）——fstar-clarify SKILL.md 增加对抗追问模式段落（质疑清单、待确认标注规则、与 plan 的交接约束）；routing.md coordinator 行为段增加协同调度规则（调研、对比、批量分析类工作派发 fstar-research 等 worker，coordinator 不亲自做长链路文件检索）；重整 fstar-clarify 为探索主导式（A-012）——SKILL.md 行为模式重构（四条规则：每轮主动出题、主动 grill、立场前置、收口自查），与 A-011 对抗追问清单合并设计，避免两套相似规则；实施规划时序规则（A-013）——fstar-plan SKILL.md 触发条件、prompt-states.md planning 状态、fstar start 软门禁；任务对话产物归档规则——对话过程中产生的文件（调研报告、对比材料、walkthrough 等）一律落任务 doc/ 目录，不散落仓库根或任务根，此规则写入 routing.md/工作流规则（与 A-006 材料落库呼应，作为其扩展而非新条目）。
- 产出：runtime 资源更新、变更说明。
- 完成判据：覆盖 A-003、A-004、A-005、A-007、A-008、A-009、A-010、A-011、A-012、A-013；资源变更通过 fstar update 预览确认。
- 遇阻处理：规则表述与现有 routing/capabilities 冲突时返回设计协调。
- 依赖与调整：依赖 P-002 的 schema 定型（origin 命名）；规则内容可并行起草；steward 是 A-008 落地的前置角色，同批交付。
<!-- fstar:item:P-004:end -->

<!-- fstar:item:P-005:start -->
## P-005 材料落库与独立检查交付
- 目的：讨论材料入库、全量验证、独立检查。
- 输入：P-002 至 P-004 成果、仓库根 antigravity-comparison.html。
- 行动：将 antigravity-comparison.html 移入项目正式位置（按 P-001 设计确定路径，遵循仓库规范与 git 忽略规则）；运行适用测试套件；由独立 fstar-check 按影响检查指南验证调用方与机制交互（重点：archive 恢复、事件完整性、既有任务兼容），修复并复查失败项；产出本任务 walkthrough.md。
- 产出：检查报告、逐条证据、未覆盖事项、walkthrough.md。
- 完成判据：覆盖 A-001 至 A-006，明确不可自动判定项。
- 遇阻处理：失败返回对应步骤修复；不能验证的内容如实报告。
- 依赖与调整：依赖 P-002、P-003、P-004。
<!-- fstar:item:P-005:end -->
