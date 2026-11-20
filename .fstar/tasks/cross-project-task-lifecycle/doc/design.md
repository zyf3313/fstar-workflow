<!-- fstar:slot:artifact_type:start -->design<!-- fstar:slot:artifact_type:end -->
<!-- fstar:slot:version:start -->0.1.1<!-- fstar:slot:version:end -->
<!-- fstar:slot:review_state:start -->draft<!-- fstar:slot:review_state:end -->
<!-- fstar:slot:author:start -->fstar-editor (dispatch docs-cross-project-1)<!-- fstar:slot:author:end -->
<!-- fstar:slot:date:start -->2026-11-19<!-- fstar:slot:date:end -->
<!-- fstar:slot:reviewer:start --><!-- fstar:slot:reviewer:end -->

# 技术设计：跨项目任务生命周期

> 本文为设计草稿，含标注为实现默认选择的决策；不新增用户需求，不声称已实现或已测试。需求见 [prd.md](prd.md)。

## 1. 理解与范围

在现有单仓库 fstar 内核（task 生命周期、dispatch、evidence、
hooks runtime）上扩展跨项目能力与验收中状态，并随本任务落地全部
用户面自然语言措辞。范围内：跨仓库主子关联与分发、目标项目初始化
检查与规范加载、三种存放模式、awaiting_acceptance 状态机、统一验收、
分支绑定与任务定位、routing/execute/archive/continue/prompt-states
自然语言措辞。范围外：自动 git 操作、npm publish、main 合并、host
设置变更。

## 2. 总体技术方案与全景流程

文字流程（主 → 子 → 验收）：

1. 主任务（仓库 A）创建跨项目关联：向目标项目 B 发起子任务创建，
   双方任务记录各写入对方 project_id + task_id 的 external 引用。
2. 分发前置检查：目标项目数据根缺失（未 init）则先走 init 流程；
   数据根存在但 specs 为空骨架或空项目时，引导探索补全或在任务中
   明确记录空规范方向，不永久阻断。
3. 跨项目 dispatch：复用现有 dispatch 协议（身份、基线、scope、
   read_context），read_context 解析到 B 自己的 specs；不以 A 的
   specs 替代。
4. 子任务完成后由新鲜 final check 触发进入 awaiting_acceptance。
5. 全部子任务 awaiting_acceptance 且证据新鲜时，主任务聚合集成
   验证；一次用户显式确认统一完成（确认信息以自然语言列出各子
   任务版本）。
6. 任一子仓库不可用或证据过期 → 阻断统一完成，说明原因。

状态机（文字 + 迁移表）：

| 当前状态 | 触发 | 新状态 | 证据处理 |
|---|---|---|---|
| planning | start | in_progress | 记录分支（见 D-006） |
| in_progress | 新鲜 final check 通过 | awaiting_acceptance | final check 证据须新鲜 |
| awaiting_acceptance | 用户确认（含统一验收） | completed | 证据新鲜性在确认前校验 |
| awaiting_acceptance | 用户提出问题 | planning | 相关证据置 stale |
| planning（返工） | start | in_progress | 需重新 dispatch/check |
| completed 未归档 | 用户显式 reopen | planning | final check 证据置 stale |
| completed 已归档 | 任何 | 不可变 | 走关联 follow-up 任务 |

异常恢复：过期 final check 不能进入验收；子仓库路径失效阻断统一
完成；项目迁移需显式 rebind；歧义查找给出候选列表。

## 3. 实体、状态与存储结构

- **project 身份**：稳定项目 UUID（init 时生成并写入数据根）+ 可读
  名。user-directory 模式下用户级目录内项目文件夹 = UUID + 可读名
  组合，避免同名冲突；不做同名或远端 URL 自动合并；路径别名与
  身份解析分开处理。
- **跨项目关联**：现有 26 字段 task.json 结构与现有 `children`
  （同仓库子任务）语义完全保留；跨项目链接记录在任务 meta 下的
  `cross_project_links`（external children/parent 引用，形如
  `{direction: child|parent, project_id, task_id, path_hint}`），
  双方各记一份，path_hint 仅作位置提示，权威解析走 project 注册
  信息。不替换 children 字符串、不新增顶层 parent 字段。
- **分支绑定**：现有 task.json `branch` 字段记录任务分支；查找时以
  repo/worktree/branch 组合消歧。
- **状态**：`phase` 增加 `awaiting_acceptance`（prompt-states.md 已含
  该状态的注入文案，本任务一并做自然语言措辞优化，见 D-007）。
- 兼容：legacy 任务字段缺失时按现有解析回退，保持可读；无破坏性
  迁移。

## 4. 模块技术设计

<!-- fstar:item:D-001:start -->
### D-001 跨仓库主子任务与分发机制

机制：跨项目关联写入双方任务 meta 下的 cross_project_links
（project_id + task_id 双向）；主任务 dispatch 复用现有协议，向子
任务传递有界 scope。处理流程：创建关联 → 前置初始化检查（D-003）
→ dispatch → 汇报。失败与兼容：目标仓库不可用时阻断并报告；legacy
任务无 cross_project_links 字段照常工作；同仓库 children 语义不受
影响。关联需求：[prd.md R-001](prd.md)。
<!-- fstar:item:D-001:end -->

<!-- fstar:item:D-002:start -->
### D-002 三种存放模式与项目身份

机制：install/init 增加 `--storage` 选择——project-shared（默认）、
project-local（本地 git exclude 忽略 `.fstar/`，文件仍在项目下）、
user-directory（`.fstar` 数据存放于用户级目录下该项目专属文件夹）。
项目身份 = 稳定 UUID + 可读名，避免同名文件冲突（对应 R-002 的
用户疑问）。失败与兼容：project-local 模式下 update/doctor 需能从
项目内路径解析；user-directory 模式下项目路径迁移要求显式 rebind
命令；不做 spec/task 拆分混合模式。
实现默认（标注：常规实现选择，非新用户问题）：doctor/update 的健康
检查对三种模式统一以存储模式标识 + 数据根解析结果呈现，user-directory
额外校验项目文件夹与注册 UUID 一致。
关联需求：[prd.md R-002](prd.md)。
<!-- fstar:item:D-002:end -->

<!-- fstar:item:D-003:start -->
### D-003 目标项目初始化检查与规范加载

机制：跨项目 dispatch 前检测目标项目数据根可解析；数据根缺失
（未 init）则拒绝分发并引导走 init（fstar-init skill 负责探索与
spec 内容，CLI 负责建数据根与索引回填——与现网行为一致）。数据根
存在但 specs 为空骨架或空项目时：引导 fstar-init 式探索补全；若
目标项目确无规范可写（新项目），在任务中明确记录该方向后继续分发，
不做永久阻断。实施 worker 的 read_context 解析目标项目自身 specs。
关联需求：[prd.md R-003](prd.md)。
<!-- fstar:item:D-003:end -->

<!-- fstar:item:D-004:start -->
### D-004 awaiting_acceptance 状态与返工

机制：`phase` 增加 `awaiting_acceptance`；新鲜 final check 通过后
进入该状态（而非直接完成）；验收前校验 final check 证据新鲜，过期
拒绝验收。用户在验收中提出问题 → 迁回 planning，证据置 stale，重走
in_progress → final check → awaiting_acceptance。completed 未归档
任务支持用户显式 reopen（final check 证据置 stale）；已归档任务不可
变，走关联 follow-up。prompt-states.md 的 awaiting_acceptance 段落
措辞随 D-007 一并优化。
关联需求：[prd.md R-004](prd.md)。
<!-- fstar:item:D-004:end -->

<!-- fstar:item:D-005:start -->
### D-005 跨仓库统一验收

机制：主任务在所有子任务均处于 awaiting_acceptance 时进行聚合集成
验证；逐子任务校验证据新鲜度与仓库可用性（不可用则整体阻断并说明
原因）；一次显式用户确认覆盖确认信息中列出的各子任务版本与主任务，
不逐仓库重复确认。确认以自然语言呈现（D-007），agent 内部记录实际
对话确认。失败与兼容：任一子任务过期/不可用 → 阻断；统一完成后子
任务各自的 acceptance 事件记录来源为主任务的统一确认引用。
关联需求：[prd.md R-005](prd.md)。
<!-- fstar:item:D-005:end -->

<!-- fstar:item:D-006:start -->
### D-006 分支绑定与 QA 任务定位

机制：start 时记录的 branch 字段作为任务与分支的绑定（现有字段，
补全使用与查询约定）。查找顺序：显式任务引用 > 有效兼容 session
pointer > 唯一的 project/worktree/branch 候选；多候选（含 completed
与 archive 中匹配）时列出选项交用户选择，不自动选定、不自动
reopen。失败与兼容：legacy 任务 branch 为空时回退到现有 task
current / list 定位。
关联需求：[prd.md R-006](prd.md)。
<!-- fstar:item:D-006:end -->

<!-- fstar:item:D-007:start -->
### D-007 自然语言确认与用户面措辞（本任务落地）

机制：随本任务一并调整所有用户面文案——routing.md 的路由引导、
执行与归档指引、continue 恢复提示、prompt-states.md 各状态注入
（no_task/planning/in_progress/awaiting_acceptance）、统一验收确认
（D-005）。呈现原则：向用户描述做了什么、验证结果、等待什么确认；
fstar 命令仅出现在 agent 内部操作与事件记录中，不作为用户面话术。
行为语义不变：确认仍为用户显式、一次性、可追溯。
实现默认（标注：常规实现选择）：prompt-states 文案沿用现有
Trellis 风格短句，仅将命令式表述改为自然语言指引；doctor 文案
随 D-002 默认呈现。
关联需求：[prd.md R-007](prd.md)。
<!-- fstar:item:D-007:end -->

## 5. 专项技术设计（按实际类型选择）

本任务类型为内核扩展 + 文案调整，无独立专项（性能/安全）章节新增。

## 6. 迁移、发布与回滚

- **前向兼容**：新增字段（phase 取值、meta.cross_project_links、
  存储模式注册信息）均为可选；旧读取器遇到未知 phase 取值时拒绝
  状态迁移而非崩溃，新读取器完全兼容旧任务（legacy 任务保持可读，
  不做破坏性自动搬移）。
- **升级备份**：引入新 phase 与 user-directory 数据根前，实施步骤
  要求对受影响项目的 task.json 与数据根做一次性备份（复制到数据
  根内 `backups/` 或用户提供位置）；不自动覆盖。
- **显式反向迁移**：提供反向操作路径——将任务从 awaiting_acceptance
  迁回旧语义由事件记录显式 revert 支撑；user-directory 项目可显式
  rebind 或迁回项目内（rebind 均为显式命令，不做自动搬移）。
- **发布边界**：本任务不做 npm publish、不合并 main、不改本地 host
  设置；回滚 = 在备份存在的前提下执行显式反向迁移并移除新增代码，
  风险集中在 phase 枚举与数据根解析两处，均有备份与反向路径。

## 7. 影响范围

| 项目模块 | 受影响功能或范围 | 本次改动及影响 |
|---|---|---|
| 任务生命周期（state/phase） | 状态机与迁移校验 | 新增 awaiting_acceptance 及迁移规则（D-004） |
| dispatch 协议 | 跨项目分发、read_context 解析 | 新增跨项目 scope 与目标项目规范加载（D-001/D-003） |
| install/init | 存放模式、项目身份 | 新增三种 storage 模式与 UUID 身份（D-002） |
| acceptance | 统一验收 | 主任务聚合校验与一次确认（D-005） |
| 查找/状态查询 | 分支定位 | branch 绑定查询与歧义候选（D-006） |
| routing / prompt-states / continue / 归档文案 | 用户面话术 | 全部改为自然语言确认措辞（D-007） |

本章不强制代码路径、类、函数或行号。

## 8. 配置与字典（适用时）

存放模式取值：project-shared | project-local | user-directory。
状态取值：planning | in_progress | awaiting_acceptance | completed
（归档为位置而非状态）。cross_project_links 方向取值：child |
parent。

## 9. 附录、评审与版本

- 版本 0.1.1；作者 fstar-editor（dispatch docs-cross-project-1）；
  日期 2026-11-19；评审人空缺（draft，未评审）。
- 未运行任何测试，未做任何实现；本文仅描述设计。
- 实现层常规选择已在 D-002、D-007 中标注为实现默认，非新增用户
  问题。
