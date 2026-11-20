# 全局资源管理与 Magpie 集成计划

## Summary

一次全局更新，已迁移项目跟随全局；会话启动发现旧项目提示迁移；安装/初始化可选接入 Magpie，缺失跳过。来源：clarify.md 用户确认及即将登记的 PRD R-001..R-005。

## Patterns to Mirror

复用 installer 的 ownership/预览/冲突/备份/事务恢复、resolve_resources、hook 注入预算、runtime 隔离和 subprocess 有界超时。保持任务状态与证据门禁，不改 Magpie 私有文件。

## Files to Change

src/fstar/installer.py、project.py、runtime/hooks.py、runtime/registration.py、新增必要适配模块；resources/runtime 与相关 skills；tests 对应安装/初始化/hook/集成测试；README.md、package.json、resources/package-assets.json。不修改真实宿主设置或 Magpie 数据。

## Tasks

<!-- fstar:item:P-001:start -->
### P-001 全局资源与旧项目迁移（R-001/R-002）
全局为默认安装/更新目标。全局资源与宿主 skills/agents/hooks 版本一致。既有项目 pin/副本通过显式确认迁移；所有权+指纹识别、备份、用户修改冲突保留，其他配置不动。数据 schema 单独检查，不能暗中迁移任务规范。测试：临时多项目、全局更新一次、pin 冲突、重复迁移和失败恢复；README 说明。优先级 P1，依赖无，顺序实施。
<!-- fstar:item:P-001:end -->

<!-- fstar:item:P-002:start -->
### P-002 会话启动检查与提醒（R-003）
SessionStart 启动检查项目遗留资源/有效版本/全局完整性，自然语言提示；同会话 clear/compact 不重复，明确延后决定按项目与目标版本保存到用户 runtime；全局目标变更可重新提示。hook 不修改项目/任务/资源；全局和旧项目 hook 重复触发不重复注入；重启生效边界明确。测试：无项目、全新/旧/已迁移、双 hook、延后/损坏全局、预算。依赖 P-001。
<!-- fstar:item:P-002:end -->

<!-- fstar:item:P-003:start -->
### P-003 Magpie 可选适配（R-004）
安装/初始化检测 PATH+平台 App 位置并探测公开能力，有则按命名 skills 接入，无则正常跳过；hooks 和子 agents 用工具原生全局目录共存。幂等、冲突不覆盖、卸载/更新所有权清晰，Magpie 无响应有超时。无私有配置写入、无模型/账号变更。提供可调用 CLI/脚本入口并复用安装器逻辑；测试 fake Magpie 的缺失/旧版/失败/成功/重复/路径含空格/用户同名文件，文档如实列能力。依赖 P-001。
<!-- fstar:item:P-003:end -->

<!-- fstar:item:P-004:start -->
### P-004 集成验证与交付（R-005）
README 与实际 CLI/行为对齐，资源版本按现有发布规则升级，manifest 重建。实现者跑针对性+全量 Python/Node；独立 check 验证全部 R 条目及全链路，进行调用方和机制交互两层影响检查。检查失败修复再测；最终证据绑定全部真实交付文件和需求，不能用目录或仅文案证据代表全任务。依赖 P-001..P-003。
<!-- fstar:item:P-004:end -->

## Validation

临时 user/runtime/host 根与 fake Magpie；Python unittest 全量、Node package 测试、build-package manifest 幂等。真实 App 只读 --help/--version；没有 live 写入测试则如实报告。

## Risks

全局与项目配置优先级、项目副本覆盖全局、Magpie router 导致命名子流程不可发现、ownership 双方不同步、安装失败恢复、会话已缓存旧资源。不能将未测试的宿主行为描述为已保证。

## Acceptance

完整检查后进入 awaiting_acceptance，以自然语言汇报等待用户确认。本任务尚无验收/提交/合并/发布授权。
