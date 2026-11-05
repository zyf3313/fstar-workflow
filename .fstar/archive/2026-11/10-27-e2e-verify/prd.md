# 端到端验证

> **已撤销词汇说明（2026-10-31，父文档为权威）**：本文早于父任务 `10-25-fstar-workflow-design` 的最终收敛，部分 AC 沿用了已撤销的旧范围词汇。执行以父 `prd.md` / `design.md` / `implement.md` 与本子任务 `design.md` §2 映射表为准，不要据此重开需求。映射速查：
> - **七态生命周期词汇**（drafting/planned/checking/fixing/awaiting_user 等持久 phase）→ 交付为三态 `planning → in_progress → completed` + `archive` 操作；"落回 checking"为 `in_progress` + `awaiting_acceptance=false` 的派生显示（"done" → `completed`）。
> - **`doc/review-log.md`** → 已撤销（父非目标：独立 review-log）；变更留痕在 `events[]`（`doc_changed` 类事件 + `evidence_invalidated`）。
> - **test-cases 审批流**（doc/test-cases.md、批准指纹、F-xxx 补丁建议、未批准不能写测试）→ 整组撤销（父非目标：独立测试用例文档及审批包）；交付等价物为 check 证据 `items[]` 逐条 `plan_item`/`requirement_ids`/`result`/`command`，报告不能自造覆盖。
> - **`fstar spec check` 命令** → 无此命令（父 §4.1 明确不保留）；等价为 `content.validate_resources` 链接检查 + knowledge 目录快照诊断。
> - **`skillOverrides` 配置** → 未交付配置项；静态侧由 `validate_resources` 校验 12 skills 及描述限额，listing 实际占用为 live-host 观察项。

## Goal

端到端跑通一个主任务从 drafting 到 archived 的完整闭环（**启用持久任务包后**），含非法转移拒绝、证据失效、验收闸门、**评审闸门**与归档提醒；**并跑通不落盘的最小闭环端到端与扩展包协商加载场景**

## 前置依赖

依赖全部其他 9 个子任务。这是 v1 的整体验收，不是一个独立功能。

> 依赖关系写在这里，**不靠父任务目录顺序隐含**。父任务 `10-25-fstar-workflow-design` 拥有需求总集、任务地图与最终集成验收。

## 交付物

- 端到端验收场景与执行记录
- 回归清单（对应各子任务的验收标准）
- 已知缺口清单（明确标注未覆盖，不留模糊）

## Acceptance Criteria

- [ ] 一个主任务从 `drafting` 走到 `archived`，全程转移合法
- [ ] 非法转移被拒绝且报错可读
- [ ] 需求/设计/用例或交付版本变更 → 证据变 stale → 有效状态落回 `checking`
- [ ] 验收闸门生效：Agent 推不到 `done`
- [ ] 归档提醒触发，且支持暂缓与去重
- [ ] 工具维度：绑定可用时按绑定调用；能力缺失时产出缺口报告并走降级路径
- [ ] **未覆盖项明确列出**（如长期设计资产 / 原型、第一版不开放自定义 hooks、第一版不做交付评审工作台与多人在线评审）

**2026-10-27 追加范围对应的验收**（父任务 `implement.md` §4 第 12–16 项）：

- [ ] **评审闸门**：无需求确认时 `drafting → planned` 被拒；`planned → implementing` 启动确认即 prd/design 最终批准；改需求使相关证据 stale；未启用评审包时豁免
- [ ] **评审稿单源**：任务目录只有 `doc/` 一份正文，无 AI 版副本；`task.json` 无顶层 `review[]`；`doc/review-log.md` 变更留痕与 `events[]` / `evidence[]` 一致
- [ ] **模板可替换**：用用户自带模板生成评审稿，槽位仍可提取；提取不到时明确提示而非推断；改模板不影响已评审文档
- [ ] **规范主题归口**：新增规范必须归入已有主题或带归口理由；`fstar spec check` 能查出无索引文档与失效链接
- [ ] **逐用例状态**：`fstar acceptance status` 区分未运行/通过/失败/阻塞/跳过，带交付版本、用例版本、环境、run id
- [ ] **文档一致性**（父任务 `implement.md` §4 第 17–20 项）：`doc-change` 改 `doc/prd.md` → 指纹更新、非 drafting 阶段证据 stale、记事件；drafting 中无证据草案不产生 stale 噪声，已有用例 review/check evidence 仍按变更失效
- [ ] **派发带版本**：`worker-context` 注入的每个文档带版本/指纹
- [ ] **专职改文档**：`fstar-editor` 只改指定文件的指定条目，越界显式报出；改完 `fstar doc check` 通过
- [ ] **回读校验**：语义槽位齐否、条目 ID 唯一稳定、关联未断、图文一致——四项都能检出

**用例驱动检查验收**（父任务 implement.md §4 第 21–25 项）：

- [ ] 开发完成进入 checking 后，check 根据已写代码 + prd 生成逐条目用例与场景链用例；用户供稿/修改入口同样写入 doc/test-cases.md。稳定 ID 保持，生成文档不能使任一用例变通过
- [ ] 缺用例、未批准、changes_requested、批准指纹过期均不能让 check 写测试；用户口头 approved 可由 Agent 代记原话与当时指纹；批准新鲜后逐条目用例落单测、场景链用例落集成测试并实际运行
- [ ] check 只改测试代码；生产缺陷交 fixing/implement。F-xxx 可附绑定问题/用例/行号的 unified diff 建议补丁但不得自动应用，implement 的采纳/改写/否决均可追溯（否决有理由）
- [ ] `acceptance/check-<n>.md` 逐条 ID → 测试代码/测试标识 → 命令/结果/日志证据可追溯，含交付/用例版本、指纹、环境、run id；未运行/失败/阻塞/跳过不得记通过
- [ ] 用户改用例（含外部编辑与在途运行）使对应 review/check evidence stale；重审和重跑后才可进 awaiting_acceptance，旧结果不会覆盖为新鲜；drafting 已有证据同样失效
- [ ] 生成目录、模板及注入引用使用 doc/design.md，无活动 doc/TDD.md 引用；历史命名撤回记录保留

**最小内核 + 扩展包验收**（父任务 `prd.md` §12、`design.md` §2.4、`implement.md` §4 第 26–32 项）：

- [ ] **最小闭环端到端**：未加载任何扩展包时，在任意目录走完「澄清 → 执行 → 基础检查 ↔ 修复 → 用户确认」；三条底线成立（实施/检查分离、失败必回修复、完成仅用户确认）；全程**无 `doc/`、无 `task.json`、无任何落盘**
- [ ] **会话内节点不落盘**：`clarifying/executing/checking/fixing/awaiting_user` 只出现在会话路由，磁盘与 runtime 无对应记录；不承诺跨会话恢复
- [ ] **扩展包协商加载**：出现扩展信号时主 Agent 只推荐**一个**最高价值包并说明收益/代价；用户同意后显式调用对应 skill，包内能力生效；**中途加载不重做已完成的工作**
- [ ] **拒绝后继续**：用户拒绝扩展包后最小闭环继续推进；无新事实时不再重复推荐同一包
- [ ] **`extensions[]` 记录与恢复**：启用持久任务包后启用/裁剪/停用写入 `extensions[]`，历史进 `events[]`；`scope: custom` 的 `included[]/excluded[]` 生效（裁掉的能力确实不加载）；新会话能读回授权状态
- [ ] **`extensions[]` 与 `capabilities[]` 分离**：两个数组互不混写，schema 校验能检出交叉字段
- [ ] **hook 最小闭环边界**：无 `task.json` 时任务相关注入静默跳过，不报错不落盘；扩展协商路由规则照常注入
- [ ] **skill 分层生效**：核心 4 个（execute/check/debug/help）可自动触发；协商 9 个经扩展包同意后由主 Agent 路由调用；`skillOverrides` 配置后 listing 占用下降

## 依据

- 父任务 `research/architecture-map.md` §4 阶段矩阵与 §8 已知不一致
- 父任务 `prd.md` Acceptance Criteria
- 父任务 `research/review-workbench.md`（本轮五项决定）

## Notes

- 父任务：`../10-25-fstar-workflow-design/`（PRD、任务地图、跨子任务验收标准）
- 本子任务的详细技术设计与执行计划在开工前补齐 `design.md` / `implement.md`。
