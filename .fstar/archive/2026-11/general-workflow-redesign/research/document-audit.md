# 近期任务文档检查

日期：2026-11-21。只读抽样，结论不代表对所有历史任务的审计。

## 问题与范围

用户指出近期任务生成的文档格式、细度和 plan.md 内容不符合预期。本次对照模板、生成规则及三个近期任务，确定样稿应解决什么问题。

## 输入与方法

检查的仓库相对路径：
- resources/templates/task/plan.md、clarify.md
- resources/templates/doc/prd.md、design.md
- resources/templates/task/plan.mapping.yaml
- resources/skills/fstar-plan/SKILL.md、fstar-doc/SKILL.md
- .fstar/archive/2026-11/global-resource-management/plan.md、clarify.md
- .fstar/archive/2026-11/worktree-shared-data-root/plan.md、clarify.md、doc/prd.md、doc/design.md
- .fstar/archive/2026-11/prompt-context-hook/plan.md

先查询 CodeGraph；Markdown 未完整收录，随后直接读取上述文件。此环境 rg 命令不可用，文件定位使用 Python 标准库。没有修改归档任务或运行产品测试。

## 发现与对应改进

| 观察 | 具体依据 | 影响 | 样稿改进 |
|---|---|---|---|
| 计划项包含大量混合信息 | global-resource-management/plan.md 的 P-001 同时描述目标、所有权、迁移、备份、测试等 | 执行者仍需自己拆解步骤与完成条件 | 分开输入、行动、产出、验证与阻碍处理 |
| 内容重复 | worktree-shared-data-root 的四份文档反复解释共享数据根、doctor 和模式回归 | 更新成本高，容易出现不同版本 | 澄清保存目标与决定，计划引用并写执行顺序 |
| 模板主要定义栏目 | task/plan.md 是标题加任务字段；plan Skill 集中在字段清单 | 标题齐全不等于内容可执行 | 增加正例、内容质量要求和适用条件 |
| 生成形式不一致 | prompt-context-hook/plan.md 采用单一 P-001 加 a–f 文件修改清单，另两个任务采用多任务结构 | 计划粒度与接手体验不稳定 | 以独立产出和依赖划分步骤，而非机械按文件划分 |
| 状态说明容易产生歧义 | 已完成归档的 worktree-shared-data-root PRD/design 仍显示 draft | 单看文档难知其评审有效性 | 区分任务状态、文档性质与确认依据；明确权威来源 |
| 确认依据不够严格 | worktree-shared-data-root/clarify.md 第 39 行以“用户已被告知”说明方案方向 | 不能单凭已告知推导已确认 | 保留关键用户答复，区分推荐、已确认和假设 |

状态和确认字段的观察不证明历史任务未经授权。该澄清记录后续另有四项明确确认；本次发现只针对可读性和来源表达。

## 整改边界与依赖

- task.json 保留任务阶段权威；样稿不创建第二份真实任务状态。
- doc/ 保留但按需创建；PRD/design 等由具体场景决定。
- 计划中的动作不等于已完成；执行结果与证据要单独标明。
- 条目标记、artifact_map、指纹和证据关联是后续兼容评估对象，不能直接删除。
- 归档是历史资料，本轮仅用新目录中的样稿展示替代写法，不回写历史。

## 验证方式与限制

当前验证：内容对照、文件链接检查与一次只读独立检查（未修改文件；报告已返回并据此修正表述）。样稿的用户评阅仍未发生。没有生产代码变更，无需运行产品回归测试。

后续实现验证：多场景生成、换会话接手、需求变更后同步、简单事项避免冗余文档、交付证据对齐目标。这里只提出验收方向，未声称已执行这些测试。
