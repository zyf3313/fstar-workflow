# Runtime Hooks 执行计划

> 本文件是 **Trellis 子任务的 `implement.md`**。fstar 产品任务执行产物为 `plan.md`，不得因本文名称生成产品 `implement.md`。

## 0. 前置核实（开工第一步）

1. 读父 `prd.md`/`design.md` 全文（design 超注入上限，必须显式补读全文）与父 `implement.md` §2–§3 #4。
2. 核实前置交付版本：`src/fstar/{store,tasks,evidence,cli,config,project,content}.py` 当前公开 API（见本任务 design §8）；`resources/{skills,agents,runtime,references}`。
3. 与 runtime-dispatch 对齐：结果/变更消息 schema、模块命名（`fstar.runtime` 归本任务）、派发包装器对 worker-context 入口的复用。
4. **不依赖 core file-mode（mode:"file"）修复**：全部实现与测试走条目级 artifact_map。

## 1. 实施步骤

| # | 步骤 | 产出 | 完成判据 |
|---|---|---|---|
| 1 | `src/fstar/runtime/__init__.py` + `hooks.py` 骨架：4 个入口函数、宿主事件映射表（to-verify 标注）、payload 解析 | 包骨架 | import 无副作用；未 init 目录可 import |
| 2 | session-context：定位、config/索引读取、current 只读、轻检查、注入组装 | `hooks.py` + `inject.py` | 未 init 静默跳过任务部分；routing 全文注入；无写操作 |
| 3 | worker-context：角色卡 + 全量适用规范 + 指纹注入、预算与 unloaded 清单 | `inject.py` | 每个输入带 sha256；超限出索引行 + 补读要求；不静默截断 |
| 4 | worker-result：结果核对、`EvidenceService.record`/`release_lease`、路由提示 | `hooks.py` | done 不写 acceptance；失败/取消释放租约并记事件 |
| 5 | doc-change：命中过滤、幂等指纹比对、`invalidate` + 传导提示 | `hooks.py` | 无变化零写入；planning 无证据零噪声；已有证据无豁免 |
| 6 | CLI：`register_commands` + `_fstar_module_handler` 注册 `fstar hook …` 族与 `hook plan --host` | `hooks.py` 内 handler | 未 init 可运行 plan/session-context；显式任务数据请求仍报错 |
| 7 | `registration.py`：两宿主注册形态只读输出 | `registration.py` | 输出含去重键与精确撤销所需字段；不写宿主设置 |
| 8 | 宿主实测：两宿主真实事件名/payload 记录，更新映射表与 to-verify 结论 | 实测记录（任务 research/ 或报告） | 每个语义 hook 有实测事件或明确回退声明；不虚构 |
| 9 | `tests/test_hooks.py`：见 §2 清单 | 测试 | 全套 unittest 通过（Python 3.9） |

## 2. 测试清单（unittest，临时目录 fixture，不触真实宿主设置）

- session-context：未 init（静默、routing 仍注入）、已 init（当前任务摘要、会话隔离、无写）、轻检查只读。
- worker-context：四角色注入差异、每输入指纹、超限 unloaded 清单、无 task.json 跳过、session-only 引用。
- worker-result：done→record（租约续期由核心断言）、failed/cancelled→release、不写 acceptance、旧 dispatch 结果拒绝。
- doc-change：改 doc 条目→stale+事件+提示；无关文件静默；重复触发幂等（第二次零写入）；planning 无证据零噪声；非 doc 路径跳过。
- CLI：`hook plan` 两宿主输出、`--json` 结构化、未 init 显式请求报错、内部 ImportError 穿透（不吞）。
- 回归：`PYTHONPATH=src python3 -m unittest discover -s tests` 全套通过；`python3 -m compileall -q src/fstar tests`。

## 3. 边界与禁止项

- 不新增第 5 个 hook、无 turn-context、无每轮扫描/归档巡检、无自定义 hook 入口。
- 不写 acceptance、不跑测试、不写检查报告、不伪造宿主事件支持。
- 不复制核心哈希/状态逻辑；一切事务走核心 API。
- 不写宿主设置文件（只输出 plan 形态）；实际注册归 package-install。
- 不私改 config schema 或核心模块；`context_injection` 键缺省回退默认值。
- 不依赖 file-mode artifact_map；不改 core 文件。

## 4. 收工核对（对照父 implement.md §2 收工）

1. 逐项跑本 PRD AC 与父 implement §3 #4；保存真实命令/结果/环境/版本。
2. 独立 check；check 可修本范围生产/测试代码，不改已确认需求。
3. 确认无私增：顶层 task 字段、phase、扩展包、skills/hooks/templates/roles 数量、面向用户命令。
4. 回写实测宿主事件结论与 to-verify 清单的最终状态（证实/回退）。
5. 留在父 subtasks 树，不单独归档。
