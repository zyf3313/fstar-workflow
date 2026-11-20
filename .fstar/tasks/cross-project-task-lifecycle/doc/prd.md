<!-- fstar:slot:artifact_type:start -->prd<!-- fstar:slot:artifact_type:end -->
<!-- fstar:slot:version:start -->0.1.1<!-- fstar:slot:version:end -->
<!-- fstar:slot:review_state:start -->draft<!-- fstar:slot:review_state:end -->
<!-- fstar:slot:author:start -->zyf3313（用户提出需求；fstar-editor 按 dispatch docs-cross-project-1 整理）<!-- fstar:slot:author:end -->
<!-- fstar:slot:date:start -->2026-11-19<!-- fstar:slot:date:end -->
<!-- fstar:slot:reviewer:start --><!-- fstar:slot:reviewer:end -->

# 产品需求文档：跨项目任务生命周期

> 需求来源为用户在任务会话中的原话确认与已收集决策；本文档为草稿，未经过正式评审或用户验收。

## 1. 背景与范围

fstar 当前以单仓库为边界：一个项目一个 `.fstar/` 数据根，任务、验收、
分支信息均在该仓库内。多仓库开发会产生跨项目的开发需求，用户希望由
一个仓库中的主任务统一管控，在其他项目下建立对应仓库的子任务，由主
任务分发并维护双向关联；同时需要验收中（awaiting_acceptance）状态、
分支绑定、以及不在项目仓库内存储 `.fstar/` 的存放方式。本 PRD 覆盖
范围、不做、依赖与验收条件；具体实现方案见 [design.md](design.md)。

本任务同时落地用户要求的自然语言确认措辞与场景优化（见 R-007）。

<!-- fstar:item:R-001:start -->
### R-001 跨仓库主子任务与分发

- 业务结果：主任务能在一个仓库中管控分布在多个仓库的关联任务，
  并在每个子仓库下建立对应任务，由主任务分发。
- 模块与优先级：任务生命周期 / dispatch —— P0。
- 范围：创建跨项目关联（双向）；主任务向其他项目的子任务分发
  有界 scope；关联记录指明对应仓库所在位置。
- 不做：不自动 git 操作（checkout / merge / reset）；不做远端 URL
  自动识别合并。
- 用户原话：「多仓库开发会有跨项目的开发的需求有没有兼容，我理想中的
  是肯定是由一个仓库里的主任务来管控，然后在其他项目下我也希望建对应
  仓库的任务，由主任务来分发，同时需要创建对应关联关系对应仓库是在哪」
- 依赖与约束：跨项目关联记录于任务 meta 下的 external
  children/parent 引用（project_id + task_id，双方各记一份）；
  父任务验收前必须校验子任务证据新鲜度；子仓库不可用（路径失效等）
  时阻断统一完成，不得静默通过。
- 验收条件（Given / When / Then）：
  - Given 一个已初始化的主项目与至少一个其他已初始化项目，When
    主任务建立跨项目子任务，Then 两侧任务均记录指向对方的
    project_id + task_id 关联，且现有 26 字段 task.json 结构与同仓库
    children 语义保持兼容。
  - Given 存在活跃跨项目关联，When 父任务尝试完成，Then 系统校验
    各子任务证据新鲜度，子任务过期则阻断完成。
  - Given 子项目路径当前不可用，When 父任务尝试统一完成，Then 完成
    被阻断并给出原因，而不是静默通过。
<!-- fstar:item:R-001:end -->

<!-- fstar:item:R-002:start -->
### R-002 项目数据存放模式（不进仓库的 .fstar）

- 业务结果：不想把 `.fstar/` 上传到项目仓库的用户可以改用其他
  存放模式，且同名项目不冲突。
- 模块与优先级：install / init —— P0。
- 范围：三种存放模式——project-shared（默认，`.fstar/` 进仓库）、
  project-local（`.fstar/` 留在本地，通过本地 git exclude 忽略）、
  user-directory（集中放在用户级目录下，每个项目一个文件夹）。
- 不做：不做 spec 与 task 拆分到不同存放位置的混合模式。
- 用户原话：「有些项目不想将.fstar 上传到对应项目仓库中 ...
  初始化有几种方式如果不想在项目下的话就放在用户级下面开个项目的
  文件夹里面存放每个项目，但是文件名重复了怎么办」
- 依赖与约束：user-directory 模式使用稳定的项目 UUID + 可读项目名
  组合作为用户级下的项目文件夹名，避免文件名重复冲突；不按同名或
  远端 URL 自动合并项目身份；项目路径迁移后需显式重新绑定
  （rebind），不做自动识别。
- 验收条件（Given / When / Then）：
  - Given 用户选择 user-directory 模式，When 初始化，Then `.fstar`
    数据存放在用户级目录下该项目专属文件夹中，项目仓库内不产生
    `.fstar/`。
  - Given 两个不同路径但同名的项目均使用 user-directory 模式，
    When 各自初始化，Then 生成两个互不覆盖的独立存储位置。
  - Given 项目被移动到新路径，When 访问其 user-directory 数据，
    Then 系统不自动合并/迁移，要求用户显式重新绑定。
<!-- fstar:item:R-002:end -->

<!-- fstar:item:R-003:start -->
### R-003 目标项目初始化与规范读取

- 业务结果：主任务向其他项目分发前，目标项目必须已初始化；实施
  读取目标项目自身的开发规范，不以主项目规范替代。
- 模块与优先级：dispatch / specs —— P0。
- 范围：跨项目分发前检测目标项目初始化状态；数据根缺失（未 init）
  则先走初始化流程；数据根存在但 specs 为空骨架或空项目时，引导
  探索补全或在任务中明确记录"目标项目尚无规范"的方向，不因占位
  内容而永久阻断。
- 不做：不以主项目 specs 替代目标项目 specs。
- 用户原话：「其次还有就是开发规范需要读对应项目下的规范，如果发现
  项目下没有需要走初始化流程」
- 依赖与约束：依赖 R-001 的关联机制。
- 验收条件（Given / When / Then）：
  - Given 目标项目已初始化且 specs 完整，When 主任务跨项目分发，
    Then 实施方读取的是目标项目下的规范。
  - Given 目标项目未初始化（无数据根），When 主任务尝试跨项目分发，
    Then 分发被引导走初始化流程后再继续。
  - Given 目标项目已初始化但 specs 为占位骨架或空项目，When 跨项目
    分发，Then 系统引导探索/回填规范，或明确记录空规范方向后继续，
    而不是永久阻断。
<!-- fstar:item:R-003:end -->

<!-- fstar:item:R-004:start -->
### R-004 验收中状态与返工流转

- 业务结果：在 in_progress 与 completed 之间增加 awaiting_acceptance
  状态；check 完成后进入验收中等待用户验收；发现问题可转回规划再
  回到执行；阶段随用户形态转变。
- 模块与优先级：任务生命周期 —— P0。
- 范围：状态序列 planning → in_progress → awaiting_acceptance →
  completed；新鲜 final check 触发进入 awaiting_acceptance；返工
  时回到 planning 并将证据置 stale 后重跑；过期检查不能用于验收。
- 不做：不自动 git 操作；不自动 reopen。
- 用户原话：「我想加个 验收中的状态 加在执行中和已完成的中间 ...
  就在 check 完了之后让用户验收 ... 如果发现有问题就可以调到规划中
  然后再是执行中 ... 阶段这些是可以随着用户的形态来转变的」
- 依赖与约束：completed 但未归档的任务可因用户显式请求 reopen；
  已归档任务不可变，后续工作走关联的 follow-up 任务。
- 验收条件（Given / When / Then）：
  - Given 任务处于 in_progress，When 一次新鲜的 final check 通过，
    Then 任务进入 awaiting_acceptance，而不是直接完成。
  - Given 任务处于 awaiting_acceptance，When 用户在对话中提出问题，
    Then 任务回到 planning，相关证据置 stale 并需重新检查后才能再次
    进入验收。
  - Given final check 证据已过期，When 尝试验收，Then 验收被拒绝。
  - Given 任务已完成未归档，When 用户显式要求返工，Then 任务可
    reopen；已归档任务不 reopen，改为建立关联 follow-up。
<!-- fstar:item:R-004:end -->

<!-- fstar:item:R-005:start -->
### R-005 跨仓库统一验收

- 业务结果：子任务进入各自 awaiting_acceptance 后，主任务聚合
  集成验证；一次显式用户确认覆盖列出的子任务版本与主任务，不逐仓
  重复询问。
- 模块与优先级：acceptance —— P0。
- 范围：统一验收前逐子任务校验证据新鲜度与目标仓库可用性；确认
  信息中列出各子任务的版本/基线。
- 不做：不逐仓库重复弹出确认。
- 已收集决策（用户本轮确认）：子任务进入验收中，主任务聚合集成
  验证，一次显式确认覆盖列出的子任务版本和主任务。
- 依赖与约束：依赖 R-001、R-004；确认以自然语言对话形式呈现（见
  R-007）。
- 验收条件（Given / When / Then）：
  - Given 全部子任务处于 awaiting_acceptance 且证据新鲜，When 用户
    对主任务给出一次显式确认，Then 主任务与全部子任务一起完成，
    确认中列出各子任务版本。
  - Given 任一子任务证据过期或仓库不可用，When 尝试统一验收，Then
    整体完成被阻断并说明原因。
<!-- fstar:item:R-005:end -->

<!-- fstar:item:R-006:start -->
### R-006 分支绑定与 QA 任务定位

- 业务结果：任务记录对应分支名；QA 通过分支（或项目/worktree/分支
  组合）能快速定位到对应任务。
- 模块与优先级：任务查找 / 状态查询 —— P1。
- 范围：任务记录绑定的分支；查找顺序为显式任务引用 > 有效兼容的
  session pointer > 唯一的 project/worktree/branch 候选；存在歧义
  时列出选项（含 completed 与 archive 中的匹配）交用户选择。
- 不做：不自动 reopen；不自动切换分支。
- 用户原话：「当前任务中有没有对应的分支名 ... QA发现了个问题要找到
  对应任务 ... 如果任务能够绑定了分支是否能够让ai能够快速识别呢」
- 依赖与约束：repo / worktree / branch 组合用于消歧。
- 验收条件（Given / When / Then）：
  - Given 任务已绑定分支，When 询问该分支对应的任务，Then 能定位
    到该任务。
  - Given 分支/候选存在歧义（多个匹配，含已完成或已归档），When
    查找，Then 系统列出候选供选择，不自动选定或自动 reopen。
<!-- fstar:item:R-006:end -->

<!-- fstar:item:R-007:start -->
### R-007 自然语言确认与用户面措辞（本任务落地）

- 业务结果：用户面对的所有 fstar 触点——完成/验收确认、路由引导、
  执行、归档、continue 恢复、prompt-states 注入文案——均使用自然
  语言对话式表达，用户看到的是自然语言的完成/确认信息，而不是
  fstar 命令；agent 在内部记录实际对话确认。
- 模块与优先级：acceptance / routing / continue / prompt-states /
  归档 —— P0（本任务范围内完成，不推迟到下一任务）。
- 范围：routing.md、执行与归档指引、continue 恢复提示、
  prompt-states.md 各状态注入文案，随本任务一并调整措辞；统一验收
  确认（R-005）同样以自然语言呈现。
- 不做：不改变自然语言确认的行为语义（确认仍为用户显式、一次性、
  可追溯记录）。
- 用户原话：「我再提几个场景优化项然后上面说的那个措辞 跟着这次
  任务一块改了」
- 依赖与约束：已确认 UX 方向——用户应看到自然语言的完成/确认，
  而非 fstar 命令；agent 内部记录实际对话确认。
- 验收条件（Given / When / Then）：
  - Given 任务通过 final check 进入 awaiting_acceptance，When 向用户
    呈现验收请求，Then 用户看到的是自然语言描述（做了什么、验证
    结果、等待确认），而不是命令或命令回显。
  - Given 统一验收场景，When 主任务请求确认，Then 确认信息以自然
    语言列出各子任务版本并请求一次确认。
  - Given 任一 prompt-state（no_task/planning/in_progress/
    awaiting_acceptance）触发注入，When 文案呈现给用户侧会话，
    Then 使用自然语言指引而非命令式指令罗列。
<!-- fstar:item:R-007:end -->

## 2. 业务流程

以跨仓库功能开发为例（现状 → 目标）：

1. **现状**：任务、验收、分支信息都锁在单仓库 `.fstar/` 内；无
   awaiting_acceptance 状态；无跨项目关联；确认呈现偏命令式。
2. **目标**：主任务（仓库 A）创建/关联其他仓库（B、C）的子任务，
   分发有界 scope；分发前确认目标项目已初始化，实施读取目标项目
   自身规范；各子任务 check 完成后进入 awaiting_acceptance；主任务
   聚合集成验证后，用户以自然语言形式一次显式确认统一完成。全部
   用户面措辞（路由、执行、归档、continue、prompt-states）随本
   任务一并调整为自然语言表达。
3. **返工**：验收中发现问题 → 回到 planning（证据置 stale）→
   重新 in_progress → 重新 final check → 再次 awaiting_acceptance。
   完成未归档的任务可按用户显式请求 reopen；归档任务不可变，走
   follow-up。
4. **异常恢复**：子仓库路径失效或证据过期时阻断统一完成并说明原因；
   项目迁移后要求显式 rebind；歧义查找给出候选列表。
5. **确认 UX**：确认本身仍是用户显式、可追溯的行为，仅在呈现层
   使用自然语言（见 R-007）。

## 3. 模块与逐功能要求

- **任务生命周期**：新增 awaiting_acceptance 状态及其全部合法迁移
  （见 R-004）；状态机随用户形态转变，但每次迁移都有事件记录。
- **跨项目关联**：project_id + task_id 双向链接（记录于任务 meta
  下的 external 引用），记录对方仓库位置；提供按关联查询与验收前
  新鲜度校验；现有 26 字段结构与同仓库 children 语义保持兼容。
- **存放模式**：install/init 支持三种模式的创建与解析；user-directory
  使用稳定 UUID + 可读名，路径别名独立处理。
- **分发**：跨项目 dispatch 复用现有 dispatch 协议（身份、基线、
  scope），附加目标项目初始化与规范加载要求。
- **查找**：显式任务 > session pointer > 唯一 project/worktree/branch
  候选；歧义列出选项。
- **归档**：归档不可变；完成后未归档才可 reopen。
- **自然语言 UX**：routing.md、执行/归档指引、continue 提示、
  prompt-states.md 文案随本任务一并落地（R-007）。

## 4. 跨模块要求与影响

- 兼容：既有 legacy 任务保持可读；不做破坏性迁移；不自动执行任何
  git checkout/merge/reset。
- 本任务不做：npm publish、main 合并、本地 host 设置变更。
- 迁移与回滚：新增 phase 与数据根涉及持久化数据结构变更，需有
  备份与显式反向迁移方案，不做破坏性自动搬移（详见
  [design.md](design.md) 第 6 章）。

## 5. 待确认、评审与版本

- 本文档状态为 draft；用户已确认的范围仅限本会话中带原话引用的
  条目与已收集决策（统一验收、三种存放模式），不代表 PRD 已通过
  正式评审或验收。
- 无新增待确认问题：doctor 对三种存放模式的健康检查呈现与
  prompt-states 具体措辞为实现层常规选择，采用 design.md 第 8、9 章
  标注的默认方案。
- 版本 0.1.1；需求作者为用户（zyf3313 原话提出，fstar-editor 按
  dispatch docs-cross-project-1 整理成文）；日期 2026-11-19；评审人
  空缺。
