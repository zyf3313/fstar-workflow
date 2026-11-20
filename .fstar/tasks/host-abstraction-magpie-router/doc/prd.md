<!-- fstar:slot:artifact_type:start -->prd<!-- fstar:slot:artifact_type:end -->
<!-- fstar:slot:version:start -->0.1<!-- fstar:slot:version:end -->
<!-- fstar:slot:review_state:start -->draft<!-- fstar:slot:review_state:end -->
<!-- fstar:slot:author:start -->FrancisZhang<!-- fstar:slot:author:end -->
<!-- fstar:slot:date:start -->2026-11-20<!-- fstar:slot:date:end -->
<!-- fstar:slot:reviewer:start --><!-- fstar:slot:reviewer:end -->

# 产品需求文档：Host 抽象层、Codex 对齐与 Magpie 软路由

> 来源：任务 clarify.md（用户原话与 2026-11-20 codebase 核实事实）与 plan.md。上一任务（global-resource-management，已合入 main，0.7.0）为本任务的前置事实来源，只读参考。

## 1. 背景与范围

现状（任务启动时的核实快照，**历史背景**；实现后的当前能力以 README 能力矩阵为准——其中 Codex 用户级 hooks 与 skills 通道已实机核实为 supported，并带 Codex 侧人工信任审批的 caveat）：安装器仅支持 claude/codex 两套宿主注册计划（`src/fstar/runtime/registration.py`）；Claude hooks 为用户级 `~/.claude/settings.json`，Codex hooks 当时仅项目级 `.codex/hooks.json`；skills 当时只为 Claude 原生安装，Codex 无 skills 通道；子代理机制仅 Claude 存在。Magpie（0.1.4380）公开能力已核实为 skills hand-over、library instructions、MCP，无 hooks/子代理接口。

目标（初始需求，用户原话）："做个通用的然后能通过 magpie 的能力实现共享……magpie 应该集成的是软路由，如果有就直接配到 magpie 通过 magpie 统一管理，如果没有就配置到各个 agents 上面"。该初始需求在验收阶段由用户以下列原话返工细化："我发现好像magpie 只是软路由的作用但是那个claude 本身agent下面还是要注入skills要不然没有办法手动使用/fstar-*相关的命令了"——据此确立 R-003 的原生始终安装 + Magpie 附加库分发语义（返工记录见 clarify.md）。

<!-- fstar:item:R-001:start -->
### R-001 Host 能力矩阵

- 业务结果：`fstar` 以一张显式的宿主能力矩阵（host × 能力：hooks 事件与作用域、skills 路径、agents/子代理、instructions 位置）驱动安装与 `doctor` 报告；每个单元格标注 supported / unsupported / unverified，且未验证项绝不在输出中被表述为已保证。
- 模块与优先级：installer / doctor / registration，P1。
- 范围：矩阵为唯一事实来源，安装器按矩阵执行；矩阵之外的未知宿主明确报错（沿用 `unknown_host`），不猜测、不静默降级。
- 不做：不实现新宿主；不宣称任何未实机核实的能力。
- 验收条件：Given 矩阵声明某能力 unsupported，When 安装到该宿主，Then 该能力被跳过且报告如实说明；Given 未知宿主名，When 安装，Then 报 `unknown_host` 错误并列出已知宿主。
<!-- fstar:item:R-001:end -->

<!-- fstar:item:R-002:start -->
### R-002 Codex 对齐

- 业务结果：Codex 在能力矩阵内与 Claude 同等对待：hooks 作用域核实后取用户级（若 Codex 官方支持）否则维持项目级并在文档说明；skills 通道补齐；prompt-context（`userPromptSubmit`）事件实机验证通过则升级 verified，否则保留 to_verify 标注与既有 fallback；子代理能力明确标注"不适用"而非静默缺失。
- 模块与优先级：registration / installer，P1。
- 范围：只使用 Codex 官方支持的机制；核实手段为实机验证或官方文档，二者皆无则维持 unverified 并如实降级。
- 不做：不依赖未文档化的 Codex 行为；不把 unverified 项当作已保证能力宣传。
- 验收条件：Given Codex 用户级 hooks 位置经实机验证存在，When 安装，Then hooks 写入用户级且 doctor 报告为 supported（用户级）；Given 无法验证，When 安装，Then 维持项目级 + 文档化限制说明；Given skills 通道补齐，When 安装到 Codex，Then skills 落到矩阵声明的 Codex skills 路径（该路径本身须先核实，未核实则标注 unverified）。
<!-- fstar:item:R-002:end -->

<!-- fstar:item:R-003:start -->
### R-003 Magpie 软路由（skills，附加分发）

- 业务结果：安装/更新时——凡是能力矩阵声明了原生 skills 通道的宿主（claude、codex），**原生副本一律照常安装**，保证 `/fstar-*` 手动斜杠命令入口（斜杠命令是客户端功能，只由宿主原生 skills 目录供给；Magpie 对宿主只交付单一聚合路由 skill，无法提供逐条 `/fstar-*` 命令）。Magpie 存在时**额外**将技能 hand-over 到 Magpie 库，供没有原生 skills 通道的其他 agent 通过其路由 skill 共享。hand-over 是附加分发，不回收、不抑制原生副本。
- 归属记录拆分：原生副本保持 installer-owned；Magpie 库 hand-over 状态（handed_over / handover_failed 等）单独记录，不再用 ownership="magpie" 表示"原生已让位"。
- `--native-only` 语义：跳过 Magpie 库 hand-over，仅装原生。
- doctor：Magpie 消失或 hand-over 缺失时，原生入口不受影响；库 hand-over 缺失为提示性诊断（不暗示技能丢失、不要求回退）。
- 模块与优先级：installer / magpie，P1。
- 范围：单技能 hand-over 失败只影响库分发（原生照常），如实报告；幂等；旧记录（ownership="magpie"）读取兼容与迁移。
- 不做：不写 Magpie 私有文件；不改模型/账号/provider/路由；不代管 Magpie 侧 per-agent 的 skill 路由配置（用户如需在 Magpie 侧为 claude 排除重复清单，属 Magpie 自身配置）。
- 验收条件：Given Magpie 可用，When 安装，Then 原生 skills 目录包含全部技能 **且** 库 hand-over 成功、hand-over 状态如实记录；Given hand-over 某技能失败，When 安装，Then 原生副本照常存在，仅库分发缺失并报告；Given `--native-only`，When 安装，Then 仅原生、无库 hand-over；Given Magpie 消失，When doctor，Then 原生技能完整可用，仅提示库 hand-over 缺失。
- 已知代价（如实记录）：原生 + Magpie 库双份存在时，经 Magpie 的请求中模型可能看到技能清单两次；去重属 Magpie 侧配置，不在本任务范围。
<!-- fstar:item:R-003:end -->

<!-- fstar:item:R-004:start -->
### R-004 共享 Magpie Instructions

- 业务结果：Magpie 存在时，通过其公开 library instructions 能力写入一段 fstar 工作流入口说明（自然语言描述工作流入口，不堆砌命令清单），使没有 hooks 的工具也能被引导进入 fstar 工作流；已存在的用户 instructions 不被覆盖，冲突时保留用户内容并报告。
- 模块与优先级：magpie / installer，P2。
- 范围：仅在 Magpie 探测可用且 instructions 能力可写时执行；能力不可用则跳过并如实报告，不影响基础安装。
- 不做：不覆盖、不合并改写用户已有 instructions；不写 Magpie 私有文件。
- 验收条件：Given Magpie 可用且无冲突，When 安装，Then fstar 工作流入口 instructions 写入 Magpie library；Given 用户已有 instructions，When 安装，Then 用户内容原样保留、输出冲突报告；Given Magpie 不可用，When 安装，Then 跳过且基础安装成功。
<!-- fstar:item:R-004:end -->

<!-- fstar:item:R-005:start -->
### R-005 文档、测试与发布

- 业务结果：README 更新（能力矩阵、Codex 支持状态与限制、Magpie 附加库分发行为与失败降级语义）；测试覆盖矩阵驱动安装、Codex 侧结构/幂等/重复注册防护、Magpie 附加库分发（原生副本始终存在且内容正确、单技能 hand-over 失败仅影响库分发、`--native-only` 不探测 Magpie、Magpie 移除后 doctor 提示性诊断且原生仍可用、幂等重跑、旧 ownership="magpie" 记录兼容）、instructions 冲突保留；全量 Python + Node + manifest 幂等检查通过；版本与 package-assets manifest 同步更新。
- 模块与优先级：docs / tests / release，P1。
- 范围：测试全部使用隔离临时根与 fake Magpie/fake CLI；真实 Magpie 仅允许 `--version`/`--help` 只读探测；独立检查须做两层影响检查（含上一任务全局资源/迁移路径与既有 Claude 安装回归）。
- 不做：不自动验收、提交、合并或发布（须用户确认）。
- 验收条件：Given 全部测试在隔离环境通过且影响检查无回归，When 实施完成，Then 进入验收中状态等待用户确认，期间不发生合并/发布动作。
<!-- fstar:item:R-005:end -->

## 2. 业务流程

角色：fstar 用户（安装/更新/doctor）、宿主（Claude/Codex）、Magpie（可选共享层）。

安装流程（目标）：解析宿主与根目录 → 读能力矩阵 → 逐能力决定安装动作（unknown 宿主报错）→ 原生 skills 无条件安装（矩阵声明 skills 通道的宿主照常写原生副本）；Magpie 可用时逐技能**附加** hand-over 到库（失败仅使该技能库分发缺失并如实报告，不影响原生副本）→ 可用且可写时写共享 instructions（冲突保留）→ 写 manifest/归属记录 → 输出含每个技能原生安装与库分发状态及未验证项标注的安装报告。

异常恢复：Magpie 探测失败→整体跳过库分发（原生安装不受影响）；单技能 hand-over 失败→仅该技能库分发缺失并如实报告（原生副本不受影响）；instructions 冲突→保留用户内容并报告；doctor 检测 Magpie 不可达→提示性诊断 `MAGPIE_LIBRARY_UNREACHABLE`（info 级，原生入口不受影响，不需要回退）。现状与目标差异（任务启动时现状，历史）：当时 skills 仅 Claude 原生、无矩阵、Codex 无 skills 通道。

## 3. 模块与逐功能要求

- installer：以矩阵为输入执行安装；未知宿主报错（复用 `unknown_host`）；归属记录复用上一任务 manifest/fingerprint 机制与 `fstar.magpie-integration.v1` schema（旧 ownership="magpie" 记录读取兼容，见 R-003）。
- registration：矩阵中 hooks 部分即现有 CLAUDE_PLAN/CODEX_PLAN 的 verified/to_verify 语义扩展；`verified` 仅表示"实机观察到的 schema"，不表示"保证触发"。
- magpie：附加库分发与 hand-over 复用现有 probe/discover/handover/记录结构；新增 per-skill `library` 状态记录（原生始终安装，不回收、不抑制原生副本）；Magpie 移除后的提示性检测。
- doctor：按矩阵报告能力状态与未验证项；Magpie 不可达或库 hand-over 缺失为提示性诊断（`MAGPIE_LIBRARY_UNREACHABLE`，info 级；原生入口不受影响，无需回退）。

## 4. 跨模块要求与影响

- 兼容迁移：上一任务已装的全局资源与 magpie-integration.json 记录必须兼容读取，不重置归属。
- 非功能：所有外部子进程调用有超时；原子写；失败不中断基础安装。
- 影响检查：两层影响检查须覆盖上一任务（全局默认、迁移提醒、Magpie hand-over）与既有 Claude 安装路径。

## 5. 待确认、评审与版本

- 待确认（任务启动时清单，**历史**；实现期已实机核实，当前状态以 README 能力矩阵为准）：Codex 用户级 hooks 是否官方支持；Codex skills 目录位置；`userPromptSubmit` 事件名大小写。核实结果：用户级 `~/.codex/hooks.json`（`$CODEX_HOME/hooks.json`，五个 PascalCase 事件）与 `$CODEX_HOME/skills` 已实机核实（2026-11-20，codex-cli 0.167.0），矩阵标 supported；`verified` 仅表示 schema 被实机观察到，且 Codex 需用户在 TUI 首次人工批准 hooks 方才运行（headless `codex exec` 不运行未信任 hooks），该信任边界如实写入安装报告与 README。当时任一项未核实即按 R-002 降级处理并保留标注（历史规则，已按核实结果收敛）。
- 版本 0.1，draft，评审人空。文档完成不等于实现、检查或用户验收。
