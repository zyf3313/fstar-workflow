# 验收标准

来源：本任务 clarify 讨论中的用户确认结论（会话记录 + antigravity-comparison.html 讨论材料）；具体测试和限制随设计完善。每条需提供独立验证证据。

<!-- fstar:item:A-001:start -->
## A-001 联调子任务挂靠与 reopen
用户报告的问题落在已归档大需求功能范围内时，修复任务作为该大需求任务的子任务创建（parent 关系），而不是平铺孤立任务；即使父任务已归档，也通过显式 reopen 机制将父任务挪回任务目录（非静默文件移动，事件留痕），完成后父子一起重新归档。归档后的父目录树内可完整回溯联调期生长出的所有子任务。
<!-- fstar:item:A-001:end -->

<!-- fstar:item:A-002:start -->
## A-002 origin 链与上下文继承
任务 schema 支持来源标记（origin/parent 指向父需求任务）；带 origin 的联调任务在 dispatch/check 时自动注入父任务的 design.md 及收尾 walkthrough 文档作为上下文，无需人工重新解释需求。注入失败或父文档缺失时如实降级并记录，不冒称注入成功。
<!-- fstar:item:A-002:end -->

<!-- fstar:item:A-003:start -->
## A-003 plan_item 绑定验证方式
计划模板/规则要求每个 plan_item 在规划阶段绑定独立客观验证方式（"怎么证明做到了"），验收时核对该证据；验收标准含糊的 plan_item 不进入实施派发。
<!-- fstar:item:A-003:end -->

<!-- fstar:item:A-004:start -->
## A-004 Challenger 检查规则
fstar-check 规则增加反例检查项：不只验证"实现了"，还专门构造反例/边界用例并验证；作为 workflow 内容层规则，不改动检查内核。
<!-- fstar:item:A-004:end -->

<!-- fstar:item:A-005:start -->
## A-005 walkthrough 标准化收尾产物
任务验收前产出统一格式的 walkthrough.md（改了什么 + 如何验证 + 证据：命令输出/测试结果），存放于任务目录；该文档同时是联调期子任务上下文注入的来源之一。
<!-- fstar:item:A-005:end -->

<!-- fstar:item:A-006:start -->
## A-006 讨论材料落库与兼容性
Antigravity 对比讨论材料移入项目正式位置（不入 git 跟踪的生产面除外，遵循仓库规范）；既有任务数据、归档树和迁移路径不因新 schema 字段或 reopen 机制被破坏（向后兼容：无 origin 字段的任务行为不变）；数据 schema 变更如需迁移，走 fstar migrate 快照回滚机制。
<!-- fstar:item:A-006:end -->

<!-- fstar:item:A-007:start -->
## A-007 建任务后的需求澄清循环
任务创建是早期动作，创建后 coordinator 必须回到需求探讨，继续与用户往返（回应意见征求、补充方案分析、确认边界）直到需求澄清；澄清未完成前不得生成规划文档、不得推进阶段或询问下一步。探讨未结束时任何推进动作让位于继续探讨。本条源于用户对实际流程缺陷的反馈（原话见 clarify.md 补充）。
<!-- fstar:item:A-007:end -->

<!-- fstar:item:A-008:start -->
## A-008 coordinator 纯派发模式
主 agent（coordinator）的职责仅限：与用户对话、分析决策、获得确认、派发子 agent。任务的创建（fstar task create）、任务文档的创建与改写（clarify.md、criteria.md、plan.md、design.md、progress.md、walkthrough.md 等）、以及一般文件写入，全部由派发的子 agent（fstar-implement / fstar-editor 等）后台完成；主对话线程不被文件操作打断。本条源于用户对工作流的优化要求（原话见 clarify.md 补充），是行为规则变更而非知识沉淀。
<!-- fstar:item:A-008:end -->

<!-- fstar:item:A-009:start -->
## A-009 派发授权链路修复
coordinator 通过宿主原生 Agent 工具派发 fstar-editor 等 worker 角色时，PreToolUse worker-context hook 报 extension_not_authorized，导致 hook failed：原因是 CLI 单次调用的 fstar extension enable 授权（session_only）无法带入宿主派发 payload 的 extensions 数组，hook 看到的授权上下文为空。修复目标：宿主派发链路正确携带授权记录，或 hook 对 session 内已启用授权有可靠解析方式；派发不被注入失败静默降级为无上下文运行（当前 hook 失败仅告警不阻断，worker 缺失 role card 与任务文档注入仍能跑完，行为不可接受）。验证：派发 fstar-editor/fstar-research 角色时 hook 正常注入且无 failed 报错。
<!-- fstar:item:A-009:end -->

<!-- fstar:item:A-010:start -->
## A-010 fstar-steward 任务管家角色
新增 fstar-steward worker 角色（host agent 定义 + role card + 授权链路），专职任务生命周期操作：fstar task create、任务文档建档与初稿（clarify.md/criteria.md/plan.md/design.md/walkthrough.md 创建）、deliverable 注册、fstar start/accept/archive 等生命周期命令执行。它是 A-008 纯派发模式的前置：coordinator 派发"建任务/落档/归档"类活给 steward，弥补 fstar-editor 仅能编辑已存在文档条目的空缺。角色定义与现有 fstar-implement/editor 同构（allowed paths + 生命周期命令边界 + 返回可验证事实）。
<!-- fstar:item:A-010:end -->

<!-- fstar:item:A-011:start -->
## A-011 对抗性需求澄清与协同调度
两项强化：(1) fstar-clarify 增加对抗性追问模式（grill 式）：每个需求块必须过质疑清单——隐含假设、失败判定标准、边界条件、未声明的预期；解释不了的点标注待确认，不得带入 plan。与现有"补全缺失信息"式澄清互补，不新增独立 skill（遵循少命令、规则内嵌原则）。(2) coordinator 协同调度强化：调研、对比、批量分析类工作主动派发 fstar-research 等 worker 后台完成，coordinator 不亲自做长链路文件检索；此为 A-008 的执行面补充，落进 routing.md 的 coordinator 行为段。均源于用户对需求探讨质量和协同方式的优化要求（原话见 clarify.md 补充）。
<!-- fstar:item:A-011:end -->

<!-- fstar:item:A-012:start -->
## A-012 澄清主导式重整（fstar-clarify 行为模式重构）
fstar-clarify 从"应答式"重构为"探索主导式"：(1) 每轮主动出题——每轮探讨结束前列出"发现但未讨论的潜在需求、风险、边界空白"，不等用户问"还有啥问题"；(2) 主动 grill——对用户每个新主张默认过质疑清单（假设、失败判定、边界），解释不了的标待确认，不等用户触发；(3) 立场前置——方案分歧时 coordinator 先给推荐和理由再列选项，不把决策树整个抛给用户；(4) 收口自查——用户说"没有了"不当作终点，触发完整自查（来源、边界、判据、冲突），有发现继续提，无发现明确说"我方已无未决项，等你拍板"。源于用户反馈：探索不主动，每次都要用户问"整体出的任务有啥问题没"再去做（原话见 clarify.md 第五轮反馈）。
<!-- fstar:item:A-012:end -->

<!-- fstar:item:A-013:start -->
## A-013 规划时序：clarify 收敛 → design → plan
修复文档时序缺陷：(1) plan.md 的创建前置条件由语义判断改为明确判据——clarify 已收敛（用户认可需求、无未决阻塞项）且，对需要设计记录的任务（含状态机/schema 变更/多方案取舍），design.md 已存在并经用户过目；design 先于 plan，plan 基于 design 拆派发步骤，不再允许把设计作为 plan 的早期执行步骤兜底。(2) fstar-plan SKILL.md 与 prompt-states.md 的 planning 状态补充该时序规则，明确"settled"的判定不能以单句授权代替。(3) fstar start 增加软门禁：复杂任务（criteria 声明需要 design）无 design.md 时拒绝启动并提示，简单任务不受影响。源于用户指出的流程缺陷：任务未探讨完就出了 plan.md（原话见 clarify.md 第六轮反馈）。
<!-- fstar:item:A-013:end -->
