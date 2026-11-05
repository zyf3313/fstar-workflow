# fstar-plan 对 OpenSpec 的借鉴建议

日期：2026-10-29。用户已确认采用「ECC 输出骨架 + OpenSpec 规划规则 + fstar 优先级/依赖/并行条件」组合；以下借鉴规则作为 fstar-plan 内容设计依据。不构成当前项目实施授权。

## 核查来源

固定版本 `6d04a1b58dedc95729d34e4f223d9d483aae210a`：
- https://github.com/Fission-AI/OpenSpec/blob/6d04a1b58dedc95729d34e4f223d9d483aae210a/skills/openspec-propose/SKILL.md
- https://github.com/Fission-AI/OpenSpec/blob/6d04a1b58dedc95729d34e4f223d9d483aae210a/skills/openspec-continue-change/SKILL.md
- https://github.com/Fission-AI/OpenSpec/blob/6d04a1b58dedc95729d34e4f223d9d483aae210a/schemas/spec-driven/schema.yaml

该版本 skills 清单没有独立 openspec-plan。propose 按依赖生成整套规划产物；continue-change 逐个生成产物；任务拆分细则主要在默认 schema 的 tasks.instruction 中，产出 tasks.md。产物之间的 requires 与代码任务之间的依赖是两个层次，不能混为自动并行调度。

## 值得补入 fstar-plan 的建议

1. 使用当前磁盘中的需求/方案及有效版本，不仅凭会话记忆；核对计划依赖的输入完整性，文件存在不等于内容齐全。
2. 拆任务前检查未决问题；会改变范围、方案或任务拆分的问题返回 clarify，不把未经确认的假设写入计划。discussion 仅提供理由与来源，不能覆盖已批准 PRD/design。
3. 规划期先查相关代码、测试、配置及规范，不把泛泛的“了解代码库”“制定方案”推给实施者；未知点应具体描述。
4. 任务按依赖排序、大小适合一轮实施和验证；每项明确完成判据或验证方法。
5. 每组实施工作列出所需测试和文档责任，不将所有质量工作推到最后；最终单独检查跨模块集成。适配 fstar 时仍保持 implement/check 角色分离：实施交付后由 check 补测/运行，doc 落文档；不是要求 implement 自检替代独立 check。
6. 补齐被中断的计划时保留有效内容，只更新缺失/受影响部分，不能仅因文件存在就当规划完整。

## 与 ECC、fstar 的分工

- ECC 骨架继续保留：Summary / Patterns to Mirror / Files to Change / Tasks / Validation / Risks / Acceptance。
- OpenSpec 借鉴：输入依赖核对、未决项处理、证据支撑的任务拆分、每项验证、分组闭环。
- fstar 已定补充：任务 ID、优先级、前置任务、并行条件、来源 ID/版本指纹；plan 形成内容，doc 写 plan.md。
- 并行组应检查依赖、写入范围和共享资源冲突；优先级不覆盖依赖；worktree 不能消除语义冲突。此为 fstar 建议，不宣称来自 OpenSpec。
- 不照搬 OpenSpec 的 proposal/specs/design/tasks 产物全链、store/schema CLI 或每次规划后重新等待 apply 的交互。fstar 保持用户已定的评审后自动 plan、无未决阻塞且计划有效后 execute。
