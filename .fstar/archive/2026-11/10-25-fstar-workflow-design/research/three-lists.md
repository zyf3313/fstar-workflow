# Trellis 盘点：可复用 / 需替换 / 需新增

盘点对象：Trellis 0.6.17（`@mindfoldhq/trellis`）。
详细证据见 `trellis-inventory.md`。

---

## 一、可复用（直接借用，不重造）

| 资产 | 位置 | 复用理由 |
|---|---|---|
| **channel runtime** | `trellis channel` CLI | 平台中立的多 Agent 协作底座：`events.jsonl` 追加日志（21 种事件、序列锁、可重放）、`spawn --agent implement\|check`、`interrupt`（持久化事件 + supervisor 转成 turn-abort + stdin 重定向）、`wait --kind done --all`、`worker_guard`（idle_timeout 5m / max_live_workers 6，双重执行） |
| **CLIAdapter** | `dist/`（JS，不可改） | 18 个平台的命令构造与输出解析。自研派发时的参考实现 |
| **会话身份解析** | `scripts/common/active_task.py:68-121` | 跨平台拿 per-window 身份的硬知识：`TRELLIS_CONTEXT_ID` → hook payload → 已验证平台环境变量 → 30s shell-ticket 桥。21 平台审计、12 个无验证名 |
| **工作流条件块机制** | `workflow.md` 的 `[platform, ...]` 块 | 一份文档表达平台差异，不维护多份 |
| **per-turn breadcrumb 注入** | `shared-hooks/inject-*` | 每回合注入当前阶段状态，驱动「继续」的上下文感知 |
| **spec 分层概念** | `.trellis/spec/<layer>/index.md` | 分层指针 + 按需加载，符合「只读必要上下文」 |
| **jsonl 上下文清单格式** | `{"file","reason"}` + 32/64/128KB 预算 | 子 Agent 上下文裁剪，机制合理 |

## 二、需替换（机制与需求冲突，不能包装）

| 资产 | 冲突点 | 处理 |
|---|---|---|
| **task 层（Python）** | 仅 3 状态 `planning/in_progress/completed`；无验收、无证据、无租约；7 个字段从不写入（`dev_type`/`worktree_path`/`commit`/`pr_url`/`relatedFiles`/`notes`/`subtasks`） | 重建 |
| **任务布局** | 扁平同级目录 + JSON `parent`/`children` 关联。用户明确拒绝「靠 JSON 才能理解整体关系」 | 改为嵌套 `subtasks/`，目录体现归属 |
| **`task.py archive`** | `task_store.py:1351` 强写 `completed`，唯一闸门是分支元数据校验；能从 `planning` 直接归档 | **必须替换**，与验收闸门语义冲突 |
| **完成判据** | `tasks.py:113-121`：子任务「完成」= 不在 active 目录里（已归档） | 改为记录在 `task.json` 内的显式结果 |
| **`subtasks` 字段** | 死别名，从不写入，仅被 `rename` 重写 | 丢弃 |

## 三、需新增（Trellis 完全空白）

| 能力 | 说明 |
|---|---|
| **生命周期状态机** | 7 阶段 + `fixing` 闭环 + `dropped`；系统校验转移合法性；`blocked` 为阶段属性 |
| **用户验收闸门** | Agent 最高推到 `awaiting_acceptance`；Trellis 零验收概念 |
| **证据与失效** | 证据携带 `validates` 版本指纹；需求变更 → `stale` → 有效状态落回 `checking`。Trellis 全包零 `evidence` 字段 |
| **归档提醒台账** | 已 `done` 未归档的巡检、去重、暂缓。Trellis 的 `completed` breadcrumb 是文档承认的死代码 |
| **全局跨项目记忆** | Trellis 的 `trellis mem` 是**只读索引器**（搜各家 AI 自己的 transcript），不是存储 |
| **任务级租约** | Trellis 全局无锁、无租约（task 和 session 都没有） |
| **task ↔ channel 耦合** | 完全解耦：worker 的 `done`/`error` 从不推进状态，归档不影响 worker。要建立耦合（worker 完成 → 记录证据；验收通过 → 停止 worker）需新代码，接入点是事件日志的 `done`/`error`/`killed` |

---

## 四条对架构有决定性影响的事实

1. **Python task 层是项目内生成代码，官方指定为定制点**，可与模板逐字节对比后自由 fork；nvm 下的 JS CLI/core 不可动。→ 自研 task 层不必受制于上游。

2. **完成由目录位置定义，不由记录的结果定义。** 任何验收/证据模型必须在 `shutil.move` **之前**写入 `task.json`，移动后 active 指针已被删除（`task_store.py:1429`）。

3. **channel runtime 与 task 状态完全解耦，耦合是绿地决策而非约束。** 唯一联系是用于显示过滤的 `--task` 字符串。

4. **Trellis 自身承认状态转移需要重设计**（`workflow.md:270-276` 注释：`completed` 块留待 "future status-transition redesign"）。→ 自研状态机不是重复劳动，是补上游已知缺口。
