# Legacy 资产盘点：personal-trellis/spec/guides + spec/templates

范围：仅 `/Users/zhangyangfan/workspace/projects/personal-trellis/spec/guides`（10 篇）与
`/Users/zhangyangfan/workspace/projects/personal-trellis/spec/templates`（9 篇），共 19 个 Markdown。
旧资产盘点（原调研为只读）。

当前命名说明（2026-10-28）：下文 PRD/TDD 是旧扩展的原有术语/引用；fstar 曾选 `TDD.md` 后已撤回，现用 `doc/design.md`。测试用例草案或用户提供/修改稿须获用户 approved 且指纹新鲜，check 才可按稳定 ID 编写/补充测试；逐用例代码与运行证据落 `acceptance/check-<n>.md`。本说明不改写旧资产事实。

**本文件中的 fstar 映射与合并建议均为待评审提案，不代表用户已批准。**

标注约定：**[事实]** = 文件内容可直接核对；**[建议]** = 我的推荐，需决策。

---

## 一、guides/（10 篇）

| 文件 (行数) | 目的 **[事实]** | 触发条件 **[事实]** | fstar 映射 **[建议]** | 重复/合并机会 **[建议]** |
|---|---|---|---|---|
| `code-comments.md` (19) | 注释规范：只为代码无法自陈的信息写注释；过期注释视为缺陷 | 写/改/评审代码注释时 | skill reference（编码规范类，短） | 体量最小；建议并入项目级 `specs/coding.md` 或编码规范 reference，不单列主题 |
| `code-search.md` (59) | 结构化代码检索路由 + CodeGraph「软安装」流程 + 索引缺失排查 | 定义/签名/调用/影响类问题；`rg` 用于字面文本 | skill reference（研究/上下文获取能力） | L9-36 属通用「能力发现与软安装」样板（见 §三-A）；检索路由部分与 fstar codegraph 环境说明重叠，去重 |
| `database-access.md` (61) | 库访问安全边界：只读入口（readonly+max_rows+最小权限账号）、写入口分离 | schema/数据核查、被授权的 DB 变更 | skill reference（环境/工具能力，按项目可选） | L8-32 同属 §三-A 样板；读写闸门可与 fstar 授权作用域规则合并表达 |
| `document-consistency.md` (45) | 变更矩阵（哪类改动动哪些文档）+ 可执行传播循环 + 冲突/证据复用规则 | 项目已维护 PRD/TDD/UI 产物，或用户要求产物更新 | **核心 skill reference**（check/验收阶段） | 与 fstar「需求变更→证据 stale→回 checking」语义高度同构，建议作为该机制的说明载体；L39 引用 3 篇其他资产，是枢纽 |
| `knowledge-search.md` (99) | 本地文档检索（QMD）+ 软安装 + 已验证基线数据 + 最小查询路径 | 跨项目文档/旧决策发现；单个小文件直读 | skill reference（检索能力） | L8-33 同属 §三-A；L35-71「Verified baseline」是 2026-10-18 的日期化实测 **[事实]**，不宜作为长期规范正文 **[建议]** |
| `module-clarification.md` (94) | 逐模块需求澄清：五类事实区分、8 维缺口清单、收敛判据、短回复的确认作用域 | 大/复杂、跨业务模块的需求澄清；Trellis brainstorm 内 | **核心 skill reference**（需求/brainstorm 阶段） | 与 fstar 需求收敛/验收闸门强相关；L3、L57-58、L94 硬编码「native Trellis」措辞 **[事实]**，需改写为 fstar 阶段名 |
| `product-technical-design.md` (178) | 中文产品需求说明/技术方案的生成编排：模板获取、范围、大文档分段、图示、评审与联动 | 用户要求 产品需求说明 或 技术方案；大迭代的单次询问 | skill reference（文档生成场景），与 4 篇模板捆绑 **[建议]** | L20-35 的「从安装包取模板 + 记录 fixed ref」等价 fstar 安装包版本固定；L90-118 的 `docs/requirements/` 布局与 fstar `tasks/<id>/` 布局需择一，避免两套计划 |
| `testing-acceptance.md` (179) | 测试与验收：输入/有界发现、用例生成与评审、共用源自检、自动化分层表、执行/缺陷/回归 | 用户要求测范围/生成用例/写自动化/执行/回归/验收总结 | **核心 skill reference**（check/验收阶段） | L166-179「Reference candidates」为外部候选 **[事实]**，建议移入 research/；oracle 不得取自被测实现、用例定义版本≠运行版本等规则与 fstar 证据指纹直接对齐 |
| `ui-design.md` (96) | UI 路线（基线 vs 特性）、`emil-design-eng` 软安装+条件专家技能表、条件式交付合同 | 新界面/交互变更/UI 实现或评审；显式要 UI 交付物 | skill reference（UI 场景，可选加载） | L20-45 同属 §三-A；与 `ui-baseline`/`ui-feature` 是 1:2 绑定组 **[事实]** L16/L18 |
| `web-research.md` (98) | 外网调研路由：能力发现（gh/Exa）、最小路径、入围后的社区证据二次核实 | 外部事实、当前文档、来源验证、选型参考 | **核心 skill reference**（research 阶段） | L8-35 同属 §三-A；L62 引用 `exploration` 模板 **[事实]**，应与 fstar `research/<主题>.md` 约定合并 |

---

## 二、templates/（9 篇，全部 zh-CN）

| 文件 (行数) | 目的 **[事实]** | 触发条件 **[事实]** | fstar 映射 **[建议]** | 重复/合并机会 **[建议]** |
|---|---|---|---|---|
| `exploration.zh-CN.md` (49) | 参考项目探索报告：能力选择/复用、调用证据、候选核实、社区证据、取舍、停止条件 | 仅参考项目探索或重要选型；简单事实查询不生成（开头明示） | optional template（调研记录骨架） | 与 fstar `research/<主题>.md` + 决策记录重叠，建议只保留「选型证据」列结构，不新增第二套记录 |
| `prd.zh-CN.md` (119) | 中文产品需求说明：背景/流程/模块（M-xxx/F-xxx 编号）、字段字典、模块验收、跨模块、待确认 | 用户要求 产品需求说明（由 `product-technical-design` 编排） | **默认评审稿模板**（`doc/prd.md`） | **[事实]** 与 fstar 任务内 `tasks/<id>/prd.md` 同名不同物（任务记录 vs 人读需求书）→ **[建议]** 必须改名或明确双轨关系，否则两处权威源冲突 → **[2026-10-27 已消解]**：取消 `prd.md` 双轨，评审稿是人机共用的唯一内容源 |
| `review-change.zh-CN.md` (47) | 评审/冻结/变更记录：冻结基线表、需求→验收映射、变更记录、交付前一致性检查 | 需要持久记录时；可并入既有方案附录/任务记录（开头明示） | optional template | 与 fstar `acceptance/` + `task.json` 字段大面积重叠 **[建议]**：优先作为这些结构的「人类可读视图」，不另建并行台账 |
| `technical-design-profiles.zh-CN.md` (71) | 项目类型适配（前端/CLI/数据/基础设施契约块）+ 按问题选图 + 借鉴边界 | 配合 `technical-design` 使用，按模块裁剪；不另建并行方案 | skill reference（非独立模板）**[建议]** | **[事实]** 无独立标题占位、自称「配合」→ 建议作为 `doc/design.md` 模板的 reference/附件，避免被当作第 5 份文档 |
| `technical-design.zh-CN.md` (252) | 中文技术方案 10 章：理解与范围/总体/实体状态存储/逐模块逐功能/专项合同/迁移发布/测试/影响/配置字典/附录 | 用户要求 技术方案 | optional template（大任务人读文档） | 体量最大 **[事实]**；第 7 章「测试与验收」与 `test-cases`、第 2/3 章与 `prd` 字段部分重复 → 建议保持引用而非复述 |
| `test-cases.zh-CN.md` (56) | 测试用例：清单表 + 复杂用例详情 + 交付前自检 + 覆盖与待确认 | 按 `testing-acceptance` 使用；用户/AI 共用一份源 | 核心模板（任务产物）| 与 fstar `acceptance/check-<n>.md` 职责相邻：建议用例=定义、check=运行结论，明确切开 **[建议]** |
| `test-execution.zh-CN.md` (45) | 执行与验收记录：本次执行/结果/问题与回归/验收建议与限制；运行 ID 唯一、定稿不覆盖 | 实际执行后单独保存；只生成用例时不要求 | 核心模板（任务产物）| **[事实]** 「唯一运行 ID + 精确版本/哈希 + 不覆盖历史」与 fstar 证据指纹/`stale` 语义一致 → 建议合并为 `acceptance/check-<序号>.md` 的字段定义 |
| `ui-baseline.zh-CN.md` (91) | 项目级 UI 设计语言与框架：目标/设计语言/应用框架/全局交互与状态/资产索引/查看实现参考/评审 | 新界面项目在功能开发前；已有项目引用现有基线 | optional template（UI 项目） | 与 `ui-feature` 分层（全局 vs 单功能）合理 **[事实]**；建议整体作为 UI 场景条件资产，不进核心集 |
| `ui-feature.zh-CN.md` (69) | 单功能页面与交互：入口路径/页面布局/状态与交互矩阵/表单与可访问性/原型与实现映射/评审 | 已有基线下的功能级交互设计 | optional template（UI 项目） | 头部已要求关联 PRD/TDD/基线版本 **[事实]** → 与 fstar `task.json` 的版本/范围字段合并表达，避免重复登记 |

---

## 三、跨文件结构性重复（最重要的合并机会）

**A. 「Capability discovery and AI soft install」样板在 5 篇指南中近乎同构**
`code-search.md:9-36`、`database-access.md:8-32`、`knowledge-search.md:8-33`、`web-research.md:8-35`、`ui-design.md:20-45`。
共同骨架 **[事实]**：尊重用户已选工具 → 按能力而非名字评估 → 无 Adequate 等价物时推荐指定来源（CodeGraph / DBHub / QMD / gh+Exa / emil-design-eng）→ 展示精确动作与影响 → 逐作用域单独授权 → 三层验证（可发现 / 客户端加载 / 一次真实最小调用）→ 被拒则降级并说明缺口 → 不重复已拒请求。
**[建议]** 抽为 1 份共享 reference（fstar「能力发现与软安装约定」），5 篇只留各自的引擎/工具特定内容与降级路径。预计可去掉约 120-150 行重复。

**B. 引用枢纽与固定搭配**
`document-consistency.md` 被 `module-clarification.md:76`、`product-technical-design.md:161`、`ui-design.md:92`、`testing-acceptance.md:157` 引用 → 单一核心 reference。
成对/成组关系 **[事实]**：`product-technical-design` → `prd` + `technical-design` + `technical-design-profiles`(+UI 两篇)；`ui-design` → `ui-baseline` + `ui-feature`；`testing-acceptance` → `test-cases` + `test-execution`；`web-research` → `exploration`；`document-consistency` → `review-change`。
**[建议]** 以「1 篇 skill reference + N 篇配套模板」为打包单位，fstar 侧对应 `skills/<能力>/references/` + `templates/<产物>.md`，与 `directory-proposal.md` 的按需覆盖模型一致。

**C. 宿主耦合措辞**
`module-clarification.md:3`、`product-technical-design.md:3`、`testing-acceptance.md:6-9` 显式写「native Trellis / 扩展 Trellis 工作流」**[事实]**。**[建议]** 迁移时统一替换为 fstar 阶段名与验收闸门语义。

**D. 语言与命名**
9 篇模板全为 `*.zh-CN.md`，指南全为英文 **[事实]**；`directory-proposal.md` 的 fstar 模板名为 `prd.md/design.md/implement.md/check.md`。**[建议]** 需决定：中文模板作为安装包默认还是用户覆盖项，以及 zh-CN 后缀惯例是否保留。

**E. 时效化内容**
`knowledge-search.md:35-71`（2026-10-18 实测）、`testing-acceptance.md:166-179`（外部候选仓库）、各指南末尾 Sources 链接 **[事实]** 都会漂移。**[建议]** 归入带日期与来源的 research/appendix，不作为规范正文。

---

## 四、事实 vs 建议 摘要

- 事实：19 个文件、共 1727 行；10 指南 + 9 模板；5 篇含同构软安装章节；1 篇（`code-comments`）仅 19 行；3 篇指南硬编码 Trellis 措辞；模板全部 zh-CN。
- 建议（未批准）：3 份核心 reference（`document-consistency`、`testing-acceptance`、`module-clarification` + `web-research`）；1 份共享「能力发现与软安装」reference 替换 5 处样板；UI/中文文档/探索类作为可选资产；`review-change` 与 `test-execution` 并入 fstar `acceptance/` 语义；解决 `prd.zh-CN.md` 与 fstar `prd.md` 同名双权威风险。
- 未决/风险：fstar 任务布局与 `docs/requirements/` 布局的取舍；中文模板的默认 vs 覆盖定位；时效证据的归档方式。均需用户评审。
