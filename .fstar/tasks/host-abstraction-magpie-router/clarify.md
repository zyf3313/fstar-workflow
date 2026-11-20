# 澄清：Host 抽象层、Codex 对齐与 Magpie 软路由

## 已确认需求

用户确认（原话）：
> 我的目的就是做个通用的然后能通过 magpie的能力实现共享，还有你说的skills重复配置的问题我想的是magpie应该集成的是软路由吧 如果有就直接配到magpie通过magpie统一管理如果没有 就配置到各个agents上面就好了

用户同时确认节奏：上一批（global-resource-management）先验收合并发版 0.7.0，再以新任务实施本项。

## 已核实事实（2026-11-20，codebase 对照）

- 宿主注册：`src/fstar/runtime/registration.py` 只有 claude/codex 两套 plan。Claude hooks 为用户级 `~/.claude/settings.json`；Codex hooks 只有**项目级** `.codex/hooks.json`，4 个事件实机验证，`UserPromptSubmit`（prompt-context）`verified=False`（大小写未实机确认）。
- skills：安装器只为 claude 写原生 skills；Codex 无 skills 通道。
- agents：只有 Claude agents 目录机制；Codex 无可对应的子代理定义（其 dispatch 走 fstar 自己的协议）。
- Magpie（0.1.4380）公开能力：skills hand-over/分发、library instructions、MCP；无 hooks/子 agent 导入接口。
- 上一批已实现：默认真装全局 `~/.claude`、只读会话检查+迁移提醒、可选 Magpie hand-over（`--magpie` 或集成脚本）、ownership 交接。

## 实现默认值

- 统一 host 适配层：显式能力矩阵（host × 能力：hooks 事件/作用域、skills 路径、agents、instructions），标注 支持/不支持/未验证；安装器按矩阵执行，未知 host 明确报错而不是猜。
- ~~软路由优先级：Magpie 可用且接管成功 → skills 只经 Magpie（不写原生副本，归属记录 "magpie"）~~ **已被返工取代**（见下）。
- Codex 对齐：确认并尽量升级到用户级 hooks（若 Codex 支持）；补 skills 通道；`UserPromptSubmit` 实机验证后标注 verified，不可验证则保留 to_verify 并给 fallback；不支持项（子 agents）明确"不适用"而不是静默缺失。
- 共享 instructions：Magpie 存在时写入 fstar 工作流入口（自然语言、无命令堆砌），覆盖没有 hooks 的工具。
- 不做：不实现 Magpie 私有文件写入；不改模型/账号/provider；不自动验收提交合并。

## 返工（2026-11-20，awaiting_acceptance 阶段用户报告）

用户原话：
> 我发现好像magpie 只是软路由的作用但是那个claude 本身agent下面还是要注入skills要不然没有办法手动使用/fstar-*相关的命令了

### 新核实事实（2026-11-20，实机只读核查）

- Magpie 向宿主投递 skills 的机制：在宿主 skills 目录放**一个**符号链接的聚合路由 skill（实机证据：`~/.claude/skills/magpie-skills -> ~/.config/magpie/skill-router/6e03dd487f26`，其 SKILL.md 列出库内全部技能的描述与路径；另有单技能直链 `grill-me -> ~/.config/magpie/library/skills/grill-me`）。Claude Code 侧因此只有 `/magpie-skills` 一个入口，**不会有各技能独立的 `/fstar-*` 斜杠命令**。
- 斜杠命令是客户端本地特性，只来自宿主原生 skills 目录；Magpie 的请求期注入无法补上这个入口。
- 当前实现（`_plan_host_files` 中 route=="magpie" 分支）在路由成功后不写原生副本并回收已装副本——直接导致 `/fstar-*` 不可手动调用。这是缺陷。

### 返工后的确认结论

- **原生 skills 始终安装**：凡是能力矩阵声明了原生 skills 通道的宿主（claude、codex），安装/更新一律照常写原生副本，保证 `/fstar-*` 手动入口。
- **Magpie hand-over 变为附加分发**：Magpie 存在时额外把技能交给库（其他无原生通道的 agent 经路由 skill 共享），但**不再回收/抑制原生副本**。
- `--native-only` 语义调整为"跳过 Magpie 库 hand-over，仅装原生"。
- 归属记录：原生副本保持 installer-owned；Magpie 库 hand-over 状态单独记录（不再用 ownership="magpie" 表示"原生已让位"）。
- doctor：Magpie 消失后原生副本仍在、入口不受影响；库 hand-over 缺失降级为提示性诊断（不再暗示技能丢失）。
- README 的软路由章节按新语义改写。
- 已知代价（如实告知用户，不在本次处理）：原生 + Magpie 库双份存在时，经 Magpie 的请求里模型可能看到技能两次（原生清单 + 路由 skill 清单）；如需去重可在 Magpie 侧用其 skill 配置排除 claude，属 Magpie 自身配置，fstar 不代管。


## 开放问题

无产品阻塞。Codex 用户级 hooks 与 skills 目录是否被官方支持需实机/文档核实；若不支持，如实降级为项目级或标注限制。
