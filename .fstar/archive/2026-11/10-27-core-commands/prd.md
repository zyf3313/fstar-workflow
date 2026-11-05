# 核心命令、任务存储与证据

## 目标与依据

为 fstar v1 提供可独立运行的持久任务核心，使任务能够安全创建、恢复、检查、由用户验收并整树归档。最小闭环默认不落盘；用户启用持久任务能力后才建立任务数据。

本次为已获批准的 v1 范围在子任务开工时的刷新，不重新请求未变范围的批准。当前跨子任务权威是父任务 `design.md`；父 `implement.md` §2 规定开工方式，`research/policy-decisions.md` 只作历史依据，其晚期历史段落不能覆盖父设计。此处 `.trellis` 规划文件仍名 `implement.md`；产品生成的任务执行计划名 `plan.md`。

## 前置与边界

本子任务无其他实现前置，是其余子任务的核心依赖；完全自研，不复制 Trellis 源码。交付标准库 Python 包 `src/fstar/`、`python -m fstar` 入口和 `tests/` 下的 unittest。Node 安装与 CLI 包装由 package-install 负责。

core 拥有任务/证据/schema、原子存储与锁、租约和以下已接受命令：`task create/list/current`、`start`、`accept`、`drop`、`archive`、`state show`、`continue`、`extension list/enable`、`review record/list`、`evidence invalidate`、`acceptance status`。命令选项和内部服务 API 补齐回规划、阻塞、接管、记录结果等行为，不扩展顶层命令族。

runtime-dispatch、runtime-hooks 使用本子任务 API，不另写 task.json；project-layout 负责 init、配置、索引与模板；tool 子任务负责 tools；package-install 负责 Node 包装与安装资源；workflow-content 负责语义路由、文档质量判断和归档巡检文案。核心提供归档巡检的只读事实与统一暂缓/去重数据接口，不实现额外 reminder/inspect/doc-check/spec-check 命令。

## 需求

### CORE-01 持久化与层级

- `task.json` 严格保留 26 个权威顶层字段，名字和类型见 design；不恢复顶层 review、status、doneAt、父任务重复进度等旧字段。
- 子任务位于主任务内部 `subtasks/<name>/`，children 与直接子目录一致；父子归属不等于实施依赖。依赖仍在 PRD/plan 中由主 Agent 协调。
- task.json 的变更与对应事件在同一原子替换中完成；并发写受锁和租约约束。非法输入、路径逃逸、归档目标冲突必须明确拒绝，不能覆盖已有任务。
- 历史后续需求新建任务，通过 `meta.related_tasks` 定位历史任务，不移动历史任务回来开发。历史视图由 `task list --archived` 现算，不新增 history/journal。

### CORE-02 状态与命令闸门

- phase 仅 `planning | in_progress | completed`；放弃为 `meta.disposition` 遗弃戳；归档只改变目录及 archivedAt。blocked、孤儿租约、待验收均不是新 phase。
- start 使用已有用户启动/规划确认与当前依据指纹；评审即放行，plan 有效且无阻塞后实施，无第二次 plan 批准。未归档的 completed 任务经用户显式重开回 in_progress，保留旧验收历史。
- completed 只由 accept 写入，必须有覆盖当前范围与交付版本的 check 角色新鲜通过证据以及可追溯的用户验收。worker done、生成报告、review approved 均不能代替任务验收。
- 待验收为「新鲜检查通过且无租约」派生标记；存在阻塞、未终结子任务或未决正确性问题时同时说明不能验收的原因。
- 用户否决后按明确意图继续修改或回 planning；回规划必须有原因、使**全部当前证据**失效、旧验收失效并释放租约。不得用自由 state set 绕过闸门。
- completed 的当前依据被修改时有效状态回 in_progress，保留旧验收历史。读取时可报告派生差异，实际变更通过受锁命令持久化。
- dropped 仅用户确认可设置，处置必须为保留现场、丢弃现场或转知识；`drop` 命令的显式 revive 动作可回 planning。丢弃不授权删除仓库代码，转知识不自动把候选提升为生效知识。

### CORE-03 证据、检查与确认来源

- validates 绑定 artifact、稳定条目 ID 与各条目内容哈希，并覆盖代码/测试/配置等交付版本。改 R-001 只使依赖 R-001 的证据失效；无法精确判定时明确降级并要求重核，不猜测语义。
- 新鲜度在读取、派发/恢复、回收结果、accept、archive 时重核。hook 只是触发入口；外部编辑同样可被检出。历史证据不能被新记录覆盖或无条件恢复有效。
- check 报告逐项关联 plan/需求、代码基线、实际验证命令与结果、环境和 run id；结果分通过、失败、阻塞、跳过、未执行。缺运行依据、映射或当前覆盖不能算通过。
- 检查者与实施者职责分离；check 可修本任务生产和测试代码，修后重跑受影响验证；最终整体检查不可由局部复查替代。核心验证声明的角色和证据结构，不声称能证明真实人类/Agent 身份或实际运行真实性。
- acceptance.source 保留 `command | conversation | review`；对话代记保留用户原话、定位引用和当时指纹；review 来源引用新鲜且属于用户确认的评审证据。Agent 代记不得标成直接用户 command。来源校验用于追溯与流程一致性，不是抵御拥有同一文件权限的 AI 的安全边界。
- review record/list 保留为中途产物评审/补录能力，不将暂缓的 test-cases 文件、用例审批或 review-log 投影设为检查前置。

### CORE-04 租约、恢复与事件

- 同一任务只有一个有效写者；租约默认 30 分钟，worker 每次有效回报续约 30 分钟。接管保留原 holder、原因、新 owner；旧 token 回报被拒。
- continue 默认只读，核对任务/关键产物/执行者/证据一致性；活跃执行者不重复派发，过期租约不假装存活、不自动接管或重派。显式用户决定接管、放弃或回规划时才写入。
- 会话当前任务指针按 project + session 隔离，无全局 current task。最小闭环不写任务、指针或租约。
- events 软上限 200；压缩最老普通事件为摘要，评审、验收、归档、扩展启用等里程碑不清除，允许里程碑本身超过 200。无 history.jsonl。

### CORE-05 扩展与归档

- 五个候选扩展包：规划评审、持久任务、多 Agent、项目治理、工具能力。测试评审包暂缓。extensions 与 capabilities、evidence 分工独立，启用/裁剪/停用事实可追溯；裁剪和停用由 extension 命令族显式动作承载。
- 未启用持久任务时扩展授权只在会话中；CLI 可返回 session-only 结果，不能声称进程退出后仍保存授权，也不能因此隐式 init。
- archive 仅处理主任务整树；检查完成/放弃状态、子任务终结、当前证据与验收有效、无阻塞/活动租约/未决正确性问题、用户归档确认及目标无冲突。子任务单独归档被拒。
- 归档完成后提供其他长期未归档任务的可核实事实、缺失条件与去重/暂缓结果，由 archive 流程汇总。continue 不做归档巡检。可选知识候选暂缓不阻塞归档。

## 验收条件

| ID | 可观察结果 |
|---|---|
| AC-01 | 新任务恰好 26 个顶层字段；嵌套创建、children 校验、历史关联和 archive 列表符合 CORE-01。 |
| AC-02 | 合法三态流可执行；直接越过 start/check/user acceptance、旧七态、dropped 写 phase、自由 state set 均不能绕过校验。 |
| AC-03 | 对话代记保留原话/引用/指纹；缺来源或旧来源/旧检查拒绝 accept；有效记录可完成；实现者报告不能充当独立 check。 |
| AC-04 | 条目修改只使受影响依赖 stale；交付文件变化、删除或旧 worker 结果被检出；完整有效检查恢复待验收，历史仍可查。 |
| AC-05 | 双进程争用无丢失更新/半截 JSON；30 分钟到期、回报续约、显式接管和旧 token 拒绝可复现。 |
| AC-06 | continue 默认无写盘、不重派、不巡检；两个会话 current 隔离，孤儿租约和不一致明确展示。 |
| AC-07 | events 超过 200 后里程碑全部保留，普通事件可追溯摘要；五包授权可查且与工具 provenance 不混写。 |
| AC-08 | 未授权最小闭环查询/扩展结果不创建任何目录；显式任务写操作缺目标时返回可操作错误，不虚报已保存。 |
| AC-09 | 路径逃逸/符号链接逃逸/归档冲突不覆盖数据；只归档整树；失败/中断可诊断；历史需求以新任务关联。 |
| AC-10 | unittest 覆盖完整 create→start→check→accept→archive 场景以及失效/接管/冲突负例；CLI 在其他子模块尚未交付时可独立执行。 |

## 不在本子任务内

Node 发布、宿主适配与派发、hook 安装、模板/语义图文校验、工具扫描分类、知识正文写入、自动依赖调度、数据库、对等进程 runtime 和旧 Trellis 数据迁移。无未解决的范围性阻塞；实现默认与接口见 design，必要联调不新增产品范围。
