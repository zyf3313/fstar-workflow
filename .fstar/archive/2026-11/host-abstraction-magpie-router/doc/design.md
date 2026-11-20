<!-- fstar:slot:artifact_type:start -->design<!-- fstar:slot:artifact_type:end -->
<!-- fstar:slot:version:start -->0.1<!-- fstar:slot:version:end -->
<!-- fstar:slot:review_state:start -->draft<!-- fstar:slot:review_state:end -->
<!-- fstar:slot:author:start -->FrancisZhang<!-- fstar:slot:author:end -->
<!-- fstar:slot:date:start -->2026-11-20<!-- fstar:slot:date:end -->
<!-- fstar:slot:reviewer:start --><!-- fstar:slot:reviewer:end -->

# 技术设计：Host 抽象层、Codex 对齐与 Magpie 软路由

## 1. 理解与范围

在既有 installer（`src/fstar/installer.py`，SUPPORTED_HOSTS、host_roots、manifest/ownership/事务回滚）、registration（`src/fstar/runtime/registration.py`，CLAUDE_PLAN/CODEX_PLAN 的 verified/to_verify 语义）与上一任务的 magpie.py / global_resources.py（上一任务写入的 ownership="magpie" 归属记录——本任务起仅作为旧格式兼容读取、probe/hand-over、隔离测试注入点）之上，引入显式能力矩阵与 skills 附加库分发（Magpie 软路由）。本设计不改既有 hooks 语义与卸载精确性（dedup key = event + command，仅删 manifest 记录且匹配 baseline 的条目）。

## 2. 总体技术方案与全景流程

全景流程（安装）：roots 解析（复用 `roots_from_args`，未知宿主在解析期即报 `unknown_host`）→ 查能力矩阵 → 按能力逐项安装（hooks 按 plan、原生 skills 无条件安装、instructions 按矩阵）→ Magpie probe 可用时逐技能**附加**库 hand-over（`library skill hand-over <name>`，每技能结果独立，只描述库分发结果：handed_over / handover_failed 等，不表示原生安装动作）→ 记录 manifest 与归属 → 输出逐技能安装与库分发报告。原生 skills 始终安装：凡能力矩阵声明 skills 通道的宿主（claude、codex）照常写原生副本，保证 `/fstar-*` 手动斜杠命令入口（斜杠命令只由宿主原生 skills 目录供给，Magpie 对宿主只交付单一聚合路由 skill，无法提供逐条命令）；hand-over 不回收、不抑制原生副本。`--native-only`：跳过库 hand-over，仅装原生（不探测、不调用 Magpie）。库 hand-over 失败或 Magpie 不可用只使该技能的库分发缺失并如实报告，基础安装与原生副本不受影响。后续更新：已 handed_over 且指纹匹配 → 库 hand-over skip（already_integrated）；指纹不匹配 → 重跑 hand-over；失败不影响原生更新，仅报告。文本等价：无图；所有判定与失败降级路径以本节与 R-003 验收条件文字覆盖。

## 3. 实体、状态与存储结构

- 能力矩阵：模块级声明（host × capability → supported/unsupported/unverified + 位置/说明），驱动安装与 doctor；矩阵中 hooks 单元格与 registration plan 的 verified/to_verify 一致。
- 归属记录：沿用 `fstar.magpie-integration.v1`（user_root/magpie-integration.json，per-skill sha256），新增**独立的** per-skill `library` 字段记录库 hand-over 状态（handed_over / handover_failed 等）；原生副本保持 installer-owned（记录于安装 manifest），不再用 ownership="magpie" 表示原生让位；旧记录（ownership="magpie"）读取兼容，按 `library` 字段语义解释（等价 handed_over）。
- 安装 manifest：沿用现有结构（原生技能副本照常记录）；库分发状态不在 manifest 中，见归属记录条目；卸载仍只删 manifest 记录且匹配 baseline 的条目。

## 4. 模块技术设计

<!-- fstar:item:D-001:start -->
### D-001 Host 能力矩阵（R-001）

机制：单一矩阵数据结构（建议放 registration 或新模块 `host_capabilities.py`），installer 与 doctor 均只读引用；矩阵单元格含状态、路径/作用域、证据说明。未验证单元格（如 Codex `userPromptSubmit` 大小写）沿用 registration 的 to_verify 表达，输出报告中 unverified 永不写成"已保证"。处理流程：安装前按矩阵过滤能力 → unsupported 跳过并报告 → unverified 项按其既有 fallback 执行（hooks 的边界回退已存在于 runtime/hooks.py 的 HOST_EVENT_MAP 路径）。失败与兼容：矩阵读取是纯数据，无 I/O；doctor 对每个 unverified 项给出"如何验证"的提示。不新增宿主；矩阵只描述 claude/codex 现状。
<!-- fstar:item:D-001:end -->

<!-- fstar:item:D-002:start -->
### D-002 Codex 对齐（R-002）

机制：先核实（实机或官方文档）三点——用户级 hooks 位置、skills 目录、`userPromptSubmit` 事件名大小写。核实成功→矩阵/plan 更新为 supported（verified）并留见证说明；核实失败或无文档→维持现状（项目级 hooks；skills 标 unsupported/unverified；prompt-context 保留 `verified=False` + to_verify + fallback "fstar hook prompt-context invoked manually"）。skills 通道：若核实出官方 skills 位置，installer 按与 Claude 相同的 staging/fingerprint/幂等/重复注册防护机制写入（复用 installer 现有 ownership 机制）；未核实则不写。子代理：矩阵标注 unsupported（Codex 的 agents 是编码工具而非 fstar 角色定义，见 magpie.py 文档），报告为"不适用"。失败与兼容：项目级 `.codex/hooks.json` 既有安装不受影响；升级到用户级须提供从项目级迁移的路径（沿用 global_resources 迁移模式：只迁移 manifest 记录且指纹匹配的项目级副本，冲突保留并报告）。
<!-- fstar:item:D-002:end -->

<!-- fstar:item:D-003:start -->
### D-003 Magpie 软路由——附加分发（R-003）

机制：route_skills()（扩展 magpie.integrate 为安装路径的库分发入口）仍做 probe（可注入 discover/runner，环境变量 FSTAR_MAGPIE_BINARY/FSTAR_MAGPIE_AGENTS_SOURCE 隔离）→ 可用则逐技能 hand-over（现有 `_public_handover`，仅公开 CLI，30s 超时）→ 每技能结果独立，但返回的每技能结果只描述**库分发**结果（handed_over / handover_failed 等），不再表示原生安装动作。installer 的 `_plan_host_files` 删除 route=="magpie" 的跳过/回收分支：凡能力矩阵声明 skills 通道的宿主，原生安装路径无条件执行（保证 `/fstar-*` 手动斜杠命令入口；斜杠命令只由宿主原生 skills 目录供给，Magpie 只交付单一聚合路由 skill，无法提供逐条命令）。归属记录：原生副本 ownership 保持 "owned"/native 语义；库 hand-over 结果记入 magpie-integration.json（沿用 `fstar.magpie-integration.v1`）的独立字段（per-skill handover 状态），不再用 ownership="magpie" 表示原生让位。`magpie_managed_update_required` 语义调整：原生更新不再被库归属阻塞——已 handed_over 且指纹匹配→库 hand-over skip（already_integrated）；指纹不匹配→重跑 hand-over；hand-over 失败不影响原生副本，仅报告。`--native-only`：跳过库 hand-over，仅原生。doctor：库 hand-over 缺失或 Magpie 不可达改为提示性诊断 `MAGPIE_LIBRARY_UNREACHABLE`（severity=info；信息明确说明原生技能入口已安装且不受影响，不暗示技能丢失、不要求回退；info 级诊断不计入 healthy 判定，原 MAGPIE_OWNER_MISSING 不再使用）。失败与兼容：Magpie 路径任何异常（OSError/TimeoutExpired/非零退出）只使该技能库分发缺失并如实报告，基础安装不中断；旧记录（ownership="magpie"）兼容读取并按新字段语义迁移。不写 library.json/providers.json 等私有文件；不代管 Magpie 侧 per-agent 路由配置。已知代价：原生 + 库双份时经 Magpie 的请求可能看到技能清单两次，去重属 Magpie 侧配置。
<!-- fstar:item:D-003:end -->

<!-- fstar:item:D-004:start -->
### D-004 共享 Instructions（R-004）

机制：Magpie probe 可用时，通过其公开 library instructions 能力写入 fstar 工作流入口说明：自然语言描述（何时、如何进入 fstar 工作流），不列命令清单。写前先读现有 instructions：为空或仅含 fstar 旧指纹内容→写入并记录指纹；存在其他内容→保留用户内容，报告冲突（沿用上一任务"冲突保留+报告"模式），绝不覆盖或合并改写。能力不可写（CLI 不支持或调用失败）→跳过并报告，不影响安装。失败与兼容：超时与非零退出按技能级同样模式降级；卸载只移除指纹匹配的 fstar 自有内容。
<!-- fstar:item:D-004:end -->

<!-- fstar:item:D-005:start -->
### D-005 测试、文档与发布（R-005）

机制：测试全部使用隔离临时根（temp user/host/runtime roots）、fake Magpie 二进制与注入 runner/discover，真实 Magpie 仅 `--version`/`--help`（沿用 magpie.py/global_resources.py 的既有隔离测试模式与注入点）。用例组：矩阵驱动安装与 doctor 报告、未知宿主报错；Codex 侧结构/幂等/重复注册防护、unverified 项输出措辞（不得含"保证"式表述）；软路由成功（原生副本照常存在且内容正确、库 hand-over 状态如实记录）、单技能 hand-over 失败仅影响库分发（原生副本保留、其余技能不受影响）、Magpie 移除后 doctor 提示（`MAGPIE_LIBRARY_UNREACHABLE`，info 级，原生仍可用）、`--native-only` 不探测 Magpie、幂等重跑（指纹匹配 already_integrated、指纹变化重交付）、旧 ownership="magpie" 记录读取兼容；instructions 写入/冲突保留/能力不可用跳过。发布：README 增能力矩阵与 Codex 限制说明、package.json 版本、resources/package-assets.json 同步；实现者跑全量 Python+Node+manifest 幂等；独立 check 验证 R 条目与两层影响检查（上一任务全局资源/迁移 + 既有 Claude 安装回归）。失败与兼容：所有新路径失败均不阻断既有安装行为；发布须用户确认，不自动合并。
<!-- fstar:item:D-005:end -->

## 5. 专项技术设计（按实际类型选择）

CLI 工具类：无长驻服务；所有子进程调用带超时（probe 10s、hand-over 30s）、argv 形式（非 shell 字符串）、原子写（tmp+os.replace+fsync）。

## 6. 迁移、发布与回滚

- 迁移：上一任务 magpie-integration.json 与全局资源记录向后兼容读取；Codex 若升级用户级 hooks，项目级旧条目按 manifest 记录+指纹匹配迁移，冲突保留。
- 发布：版本号与 manifest 同步，README 更新后发版；回滚沿用 installer 事务（mid-failure 恢复本次写入）与精确卸载（仅删自有且匹配 baseline 的条目）。

## 7. 影响范围

| 项目模块 | 受影响功能或范围 | 本次改动及影响 |
|---|---|---|
| src/fstar/installer.py | 宿主安装、skills 安装、manifest | 新增矩阵驱动与附加库分发路径（原生 skills 无条件安装，`--native-only` 跳过库分发）；既有 Claude 安装路径保持回归兼容 |
| src/fstar/runtime/registration.py | hooks plan | Codex plan 按核实结果更新作用域/verified；verified 语义不变 |
| src/fstar/magpie.py | hand-over、归属记录 | 扩展为附加库分发入口（原生始终安装，不回收/不抑制原生副本；Magpie 移除后 doctor 提示性检测）；公开 CLI 用法不变 |
| src/fstar/global_resources.py | 全局资源/迁移/提醒 | 兼容读取，不重置归属；迁移模式复用于 Codex hooks 作用域迁移 |
| runtime/hooks.py、cli.py、doctor | 边界回退与报告 | 按矩阵报告 unverified 与回退提示 |
| tests/、README.md、package.json、resources/package-assets.json | 测试与交付 | 新用例组与文档/版本更新 |

## 8. 配置与字典（适用时）

FSTAR_MAGPIE_BINARY / FSTAR_MAGPIE_AGENTS_SOURCE（既有，测试隔离注入）；magpie-integration.json schema `fstar.magpie-integration.v1`（新增 per-skill `library` 字段记录库 hand-over 状态，旧 ownership="magpie" 记录向后兼容读取）；能力矩阵为代码内声明常量，非用户配置。

## 9. 附录、评审与版本

未核实事实清单（设计撰写时的快照，**历史**；与 PRD 待确认一致）：Codex 用户级 hooks、Codex skills 目录、`userPromptSubmit` 大小写、Magpie library instructions 写入的具体 CLI 前置条件。实现期核实结果以 README 能力矩阵为准：Codex 用户级 hooks（`$CODEX_HOME/hooks.json`，五个 PascalCase 事件）与 skills 目录（`$CODEX_HOME/skills`）已实机核实（2026-11-20，codex-cli 0.167.0）为 supported——`verified` 仅表示 schema 被实机观察到，且 Codex 侧含人工信任审批 caveat（headless `codex exec` 不运行未信任 hooks）；Magpie library instructions 前置条件按 D-004 的读-写与冲突保留模式处理。无法核实的项维持 unverified 标注，不宣称保证。版本 0.1，draft，评审人空。
