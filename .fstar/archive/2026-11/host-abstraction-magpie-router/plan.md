# Host 抽象层、Codex 对齐与 Magpie 软路由计划

## Summary

统一 host 安装能力矩阵，澄清并补齐 Codex 支持项；有原生 skills 通道的宿主始终安装原生技能，保证 /fstar-* 手动入口，Magpie 可用时额外向库分发供共享。来源：clarify.md 用户原话、返工要求与已核实事实。

## Patterns to Mirror

复用上一批的 global_resources/magpie 归属记录、installer ownership/备份/事务、registration plan 结构、hook 注入预算；测试全部隔离临时根与 fake CLI。

## Files to Change

src/fstar/runtime/registration.py、installer.py、magpie.py、global_resources.py、runtime/hooks.py（如需 instructions 注入）、cli.py；resources/runtime 与 skills 文案；tests；README.md、package.json、resources/package-assets.json。不写真实宿主/Magpie 配置。

## Tasks

<!-- fstar:item:P-001:start -->
### P-001 统一 Host 能力矩阵（R-001）
显式矩阵：host × {hooks 事件与作用域, skills 路径, agents, instructions}，取值 supported/unsupported/unverified；安装器与 doctor 均按矩阵执行/报告；未知 host 明确报错。测试覆盖矩阵驱动的安装、doctor 报告与未知 host；README 列矩阵。优先级 P1，依赖无。
<!-- fstar:item:P-001:end -->

<!-- fstar:item:P-002:start -->
### P-002 Codex 对齐（R-002）
核实 Codex 官方支持的 hooks 作用域与 skills/instructions 位置；能用户级则用户级，否则项目级并说明。补齐 skills 通道；prompt-context 事件实机验证（能验证则标 verified 并留见证，不能则保留 to_verify+fallback）。子 agents 标注不适用。测试：Codex 侧安装结构、幂等、重复注册防护；未验证项不被宣称为已保证。
<!-- fstar:item:P-002:end -->

<!-- fstar:item:P-003:start -->
### P-003 Magpie 软路由（R-003，2026-11-20 返工修订）
原生 skills 始终安装（矩阵声明了 skills 通道的宿主照常写原生副本，保证 /fstar-* 手动入口）；Magpie 存在时**额外** hand-over 到库供其他 agent 共享，不回收、不抑制原生副本；`--native-only` = 跳过库 hand-over。归属记录拆分：原生副本 installer-owned，库 hand-over 单独记录。doctor 将库 hand-over 缺失降为提示性诊断（原生入口不受影响）。README 软路由章节按新语义改写。测试：原生副本在路由后仍存在且内容正确、hand-over 状态如实记录、--native-only 行为、幂等、Magpie 移除后原生仍可用、旧 ownership="magpie" 记录的迁移兼容。
<!-- fstar:item:P-003:end -->

<!-- fstar:item:P-004:start -->
### P-004 共享 Instructions 与交付（R-004/R-005）
Magpie 存在时写 fstar 工作流入口到 library instructions（自然语言，不列命令），覆盖没有 hooks 的工具；不覆盖用户已有 instructions（冲突保留）。README/版本/manifest 更新；实现者跑全量，独立 check 验证 R 条目与两层影响检查（含上一批全局资源/迁移与既有 Claude 路径回归）。
<!-- fstar:item:P-004:end -->

## Validation

临时 user/host/runtime 根；fake Magpie；真实 Magpie 仅 --version/--help；Python 全量 + Node + manifest 幂等。

## Risks

Codex 已核实的 hooks schema 仍需宿主交互式信任审核，verified 不保证每次触发；原生技能清单与 Magpie 路由清单可能重复，去重由 Magpie 侧配置处理；instructions 写前指纹检查仍存在并发修改窗口；旧项目与全局 hooks 并存时须保持迁移去重与归属保护。

## Acceptance

完整检查后进入验收中，等待用户确认；不自动提交合并发布。
