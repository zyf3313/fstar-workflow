# OpenSpec explore 与本项目 Trellis brainstorm 对比

日期：2026-10-29。性质：外部调研与 fstar 规划建议，不授权实现。

## 来源与范围

OpenSpec 核查版本：`6d04a1b58dedc95729d34e4f223d9d483aae210a`。

- https://github.com/Fission-AI/OpenSpec/blob/6d04a1b58dedc95729d34e4f223d9d483aae210a/skills/openspec-explore/SKILL.md
- https://github.com/Fission-AI/OpenSpec/blob/6d04a1b58dedc95729d34e4f223d9d483aae210a/src/core/templates/workflows/explore.ts
- https://github.com/Fission-AI/OpenSpec/blob/6d04a1b58dedc95729d34e4f223d9d483aae210a/docs/explore.md
- https://github.com/Fission-AI/OpenSpec/blob/6d04a1b58dedc95729d34e4f223d9d483aae210a/openspec/explorations/explore-workflow-ux.md
- https://github.com/Fission-AI/OpenSpec/blob/6d04a1b58dedc95729d34e4f223d9d483aae210a/schemas/spec-driven/schema.yaml
- 本项目 `.claude/skills/trellis-brainstorm/SKILL.md`，尤其 Planning Flow、Question Rules、First Principles、Convergence Gate。对比仅针对当前本地版本，不推断所有 Trellis 发行版本。

## 核实发现

| 维度 | OpenSpec explore | 本地 Trellis brainstorm |
|---|---|---|
| 目的 | 思考伙伴；探索问题，可暂停、转向、不形成提案 | 将需求收敛为规划产物并通过最终规划闸门 |
| 询问方法 | 按决策依赖推进；先目标范围后接口数据；上游改变时重访下游假设；不相关分支跳过 | 每次一个最高价值问题，包含推荐及取舍；第一性原理分析与收敛清单 |
| 证据 | 先查 specs、源码、测试、配置，不让用户回答可核实事实 | 同样要求先查证据、不猜用户意图 |
| 表达 | 多条探索方向、可视化、自然交流，不强迫固定问答格式 | 较明确的阶段顺序与问题格式，产物持续更新 |
| 记录 | 明确要求先在对话中区分确认/提议/未决；不会默认落盘 | 每次答复后更新 PRD，复杂任务后续补 design/implement |
| 正式产物 | 经授权记录到 proposal/specs/design/tasks，服从 schema | prd/design/implement，收敛整理后最终评审 |

“问得更细”不是由问题数保证；OpenSpec 的明确优势是依赖驱动探索、允许发散与暂停、上游变化时重新检查推论。两者都有证据优先和一次聚焦一个问题，不能说 Trellis 没有这些。

## 探讨落地文件的事实

- explore skill 及生成模板均写明：无 mandatory outputs，`Track decisions in the conversation, not in files`，不自动 capture。
- 默认 spec-driven schema 只有 proposal/specs/design/tasks，没有 discussion/exploration 必需产物。
- 仓库确有 `openspec/explorations/explore-workflow-ux.md`，结构为 Context / Open Questions / Potential Approaches / Next Steps / Related。
- 该文件将探索记录是否导出、存哪里、用什么格式、如何供 propose 使用列为待探索问题。它是研究实例，不能当作已经实现的标准探索存储协议。

## fstar 适配

用户明确要求：clarify 的探讨核心以 OpenSpec explore 为参考替代 Trellis；讨论过程需落在任务根目录，并为 PRD/design 等产物提供参考。

- 保留 `fstar-clarify` 名称与职责；借鉴探索姿态、按依赖追问、证据优先、假设审视、方案取舍与可视化，不增加 openspec skill/CLI 依赖。
- 自由讨论时不催促逐项批准或规划收尾；目标明确时以阻塞决策为焦点深入。检查用户、场景、成功标准、正常/异常路径、边界与取舍，但不把这些变成每个任务都要填的问卷。
- fstar 自行增加任务根 `clarify.md`（2026-10-29 用户确认，取代工作命名 discussion.md），由 fstar-clarify 整理并自行落笔，承接持续讨论；doc 仅维护任务 doc/。这不是照搬 OpenSpec 现有模板。
- 建议结构：当前问题与目标 / 已核实事实及来源 / 按主题的讨论（方案与取舍、确认结论、未决项）/ 被替代结论及原因 / 文档传递关联。
- 记录关键推理与决定，不机械复制完整聊天；提议、待确认、已确认、已被替代必须区分。只有已确认且适用的结论进入正式需求与方案；生成产物不能自动等于批准。
- PRD/design 是当前评审依据；discussion 是来由与推导记录，research 是外部/代码事实依据。新讨论若与已批准文档冲突，先显式同步并处理版本有效性，不能让执行者自行选一份。
- 在已有任务及授权持久化范围内持续记录，无须每次单独问是否保存；最小闭环未启用持久化时仍可只在会话内讨论。
- 不照搬 OpenSpec store、schema CLI、逐次写文件确认或 propose/apply 门槛；fstar 已确认的 doc 分工和评审后自动 plan/execute 规则保持。

## 同轮模板决定

用户接受移除 review-log 独立文件，底层变更事件保留；research 模板按需保留。新增 discussion 记录的是讨论理由与未决分支，不是重新命名的 review-log 自动投影。
