# 验收标准

来源：本任务 clarify.md 收敛结论（2026-11-28 主会话多轮探讨，用户逐点确认）。任务内独立编号（A-001 起，避免与其他任务编号混淆）。每条含独立验证方式（A-003 plan_item 绑定验证方式规则的实践）。

<!-- fstar:item:A-001:start -->
## A-001 分包结构落地
src/fstar/ 下按体系分包：core/（tasks/store/models/project/knowledge/dispatch，knowledge.py 归 core）、skills/（自 resources/skills 迁入）、agents/（hooks/inject/角色定义，自 resources/agents 迁入）、plugins/；integrations/ 与 src 并列且 claude-code/codex 分开摆放；cli.py 保持单文件薄壳不拆。验证：全量测试通过 + `fstar doctor` 通过。
<!-- fstar:item:A-001:end -->

<!-- fstar:item:A-002:start -->
## A-002 插件接口骨架与 magpie 迁入
plugins/base.py 定义固定接口（name/version/capabilities/detect/assist_install/bind），工厂模式：接口统一定义、各插件自主实现；registry/ 作为插件目录；magpie 作为首个实现整体迁入，既有 magpie 功能行为不变。本期不做第二个插件。验证：magpie 相关测试全部通过 + 手动冒烟一条完整链路（detect 到 bind）。
<!-- fstar:item:A-002:end -->

<!-- fstar:item:A-003:start -->
## A-003 一次性完整迁移
完整迁移脚本覆盖所有已安装场景，做到"更新一次性使用最新"——不漏迁移（用户原话："不能漏的漏 没迁移的没迁移"）；自动迁移与卸载重装两条路径均文档化。验证：用旧版本布局的测试环境跑迁移后 doctor 通过、功能正常；卸载重装路径有文档。
<!-- fstar:item:A-003:end -->

<!-- fstar:item:A-004:start -->
## A-004 布局版本机制
安装记录包含布局版本号；`fstar update` 检测布局落后时自动跑迁移；`fstar doctor` 校验布局一致性；~/.fstar/resources/ 版本目录堆放清理为"当前版本 + 结构版本号"。验证：模拟旧布局环境的测试用例通过。
<!-- fstar:item:A-004:end -->

<!-- fstar:item:A-005:start -->
## A-005 兼容性
无破坏性变更被静默引入。验证：老任务数据在新包结构下读写正常。
<!-- fstar:item:A-005:end -->
