# Runtime Hooks 与宿主适配（4 语义 hooks）

## Goal

实现 **4 个语义 hook**（session-context / worker-context / worker-result / doc-change）的 Python 3.9 stdlib 适配层，并映射到 Claude Code 与 Codex 的实际宿主事件。**无 turn-context、无第 5 个 hook、不开放自定义 hooks**。hook 只做定位、注入与幂等簿记，状态/证据/租约事务全部经核心 API。

旧版本文档中的以下要求已按父契约移除，不得恢复：turn-context 每轮注入、5 hooks、`doc/test-cases.md` 用例批准前置、`drafting` 阶段豁免、review-log 投影、每次文件修改后自动检查（doc-change 只做幂等簿记，与之不是同一件事）。

## 前置依赖

- `core-commands`（已交付：TaskStore/TaskService/EvidenceService 公开 API）
- `project-layout`（已交付：load_config、项目/用户索引、init）
- `workflow-content`（已交付：resources/skills、agents、runtime/routing.md）
- 与 `runtime-dispatch` 并行：共享结果消息与变更消息 schema（协调契约，见 design §6）；文件范围互不重叠

> 依赖关系写在这里，不靠父任务目录顺序隐含。父任务 `10-25-fstar-workflow-design` 拥有需求总集与最终集成验收。

## 交付物

- `src/fstar/runtime/` 适配包（`__init__.py`/`hooks.py`/`inject.py`/`registration.py`，Python 3.9 stdlib），模块名 `fstar.runtime` 为本子任务独占（与 runtime-dispatch 协商一致：dispatch 使用独立模块名）
- 4 个语义 hook 的入口逻辑、宿主事件映射表（**事件名/输入 schema 实测确认，标注 to-verify，不假设**）与缺事件时的边界回退
- CLI 机器入口 `fstar hook <name>`（经 `register_commands` + `_fstar_module_handler` 约定注册）与只读注册形态输出 `fstar hook plan --host <claude|codex>`
- 注入预算（config `context_injection.*`）与"全量适用规范 + 版本/指纹"加载
- 被动簿记静默跳过语义：无 task.json / 未 init 时不报错、不落盘、无占位噪声；routing 注入照常；**显式任务 CLI 缺上下文仍清楚报错**
- `tests/test_hooks.py`（unittest，与现有套件同规格）

## Acceptance Criteria

- [ ] 在 Claude Code / Codex 当前实际版本分别记录可用事件及输入 payload；无等价事件的 hook 验证边界回退（派发/回收/命令边界执行同一逻辑）并报告覆盖限制，不虚构支持
- [ ] session-context 注入 `runtime/routing.md` 全文 + 项目/用户索引 + 当前任务（会话隔离，只读）；只做工具绑定存在性与 detected_at 过期轻检查；无归档巡检、无完整工具扫描、无每轮动作
- [ ] worker-context 按角色完整注入适用上下文（角色卡、适用规范正文、任务 doc 快照、plan 项、baseline），**每个输入带版本/指纹**；超限输出索引行 + 未加载清单，worker 补读后才执行，不静默截断关键条件
- [ ] worker-result 完成/失败/取消只核对基线、登记交付证据（核心内部续租 +30m）或释放租约，并路由 check/debug；**不写 acceptance，worker done ≠ 验收**
- [ ] doc-change 幂等：指纹重算、相关证据 stale、记事件、输出变更传导提示；不跑测试、不写报告、不递归处理派生文件；planning 中无既有证据不产生 stale 噪声；**已有证据无 phase 豁免**
- [ ] 无 task.json / 未 init 时被动任务簿记静默跳过（不建文件、无输出噪声）；扩展协商路由与用户级注入照常
- [ ] learn 候选入口只挂现有会话/结果/恢复/归档节点；归档巡检仅 `fstar archive`（core 已实现）；无每轮扫描、无独立候选台账
- [ ] 边界重算全部走核心 API（`EvidenceService.invalidate/freshness/snapshot/record`、`TaskService.state/continue/release_lease`、`store.current`），不复制核心状态逻辑
- [ ] CLI 注册符合 `register_commands` + `_fstar_module_handler` 约定，可在未 init 目录运行；**内部 ImportError 不被吞掉**（模块缺失可静默跳过，模块内部导入失败必须暴露）
- [ ] 注册形态只读可输出（追加/去重、精确撤销自身条目的形状）；实际写入宿主设置归 package-install
- [ ] Python 3.9 stdlib 实现，`PYTHONPATH=src python3 -m unittest` 全套通过；**不依赖 core file-mode（mode:"file"）artifact_map 往返**（该修复在途，测试用条目级映射）

## 依据

- 父 `design.md` §3.8（hooks 契约）、§3.7（变更消息）、§4.1/§4.4（命令面与宿主集成）、§9（技术默认）
- 父 `implement.md` §2（开工规则）、§3 #4（本子任务验证项）
- 父 `research/hooks-skills-templates.md`：A/B 类 hook 机制、hook↔skill 关系（worker-context 硬绑定、其余软触发）、"doc-change ≠ 改完自动检查"
- 父 `research/worker-adapter-protocol.md`：两宿主传输实测事实（事件名仍须实现期实测）

## Notes

- 父任务：`../10-25-fstar-workflow-design/`。本文件是 Trellis 子任务 PRD；产品任务计划为 `plan.md`，不生成产品 `implement.md`（本目录 `implement.md` 是 Trellis 子任务执行计划）。
- 宿主事件名一律 to-verify：实现期在真实宿主上观察并留证据，不得把单平台事件名写成双平台保证。
