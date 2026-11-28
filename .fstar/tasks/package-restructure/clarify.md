# 包结构体系重构：需求探讨收敛记录

来源：主会话多轮需求探讨（2026-11-28），以下结论均经用户逐点确认。

## 用户确认的方案方向（2026-11-28 clarify 收敛）

### 目标结构

src/fstar/ 下按体系分包：

- **core/**：tasks、store、models、project、knowledge、dispatch（knowledge.py 归 core，不单列）。
- **skills/**：从 resources/skills 迁入。
- **agents/**：hooks、inject、角色定义，从 resources/agents 迁入。
- **install/**：安装器 + 布局版本 + 迁移脚本机制。
- **plugins/**：base.py 固定接口——name/version/capabilities/detect/assist_install/bind，工厂模式（接口统一定义、各插件自主实现）+ registry/ 插件目录；magpie 作为首个实现整体迁入。

**integrations/ 与 src 并列**（host 集成：claude-code/codex 分开摆放），不放 src/fstar/ 内。

### cli.py 不拆

cli.py 现为约 587 行的薄壳，仅做参数解析转发，保持单文件；结构只按体系分，不按 CLI 表面分。

### 插件定位

fstar 与外部工具的能力集成（如 magpie）。核心行为：检测用户装没装——装了直接接入，没装则按用户选择配合安装。本期只做接口骨架 + magpie 迁入，不做第二个插件。

### 迁移策略（用户定的原则）

用户原话："我觉得重构就要彻底""能够让用户更新一次性能够使用最新的就好 不能漏的漏 没迁移的没迁移"。据此确认：

- 一次性完整迁移脚本（自动迁移 or 卸载重装两条路径均文档化）。
- 布局版本写进安装记录；`fstar update` 检测布局落后自动跑迁移；`fstar doctor` 增加布局校验。
- `~/.fstar/resources/` 的版本目录堆放清理为"当前版本 + 结构版本号"。

### 范围外

用户级知识库/沉淀规范重构——用户明确延后单独聊（原话："这个沉淀 还是要单独聊下先把项目这个包重构了这个任务完了再聊"）。
