# Design: origin 链、reopen 归档语义与上下文继承

本文件是任务 antigravity-adoption 自身的 design（A-013 首次实践：clarify 收敛 → design → plan 复核）。P-002/P-003 的实施依据，P-004 中 A-009/A-010 的修复方向也在此定调。

标注约定：**[事实]** = 已读源码核实（src/fstar/，CLI 0.12.0，data schema 1）；**[提案]** = 设计决策；**[否决]** = 记录被否决备选及理由。

覆盖 criteria：A-001（reopen）、A-002（origin 与注入）、A-006（兼容与迁移）；并含 A-009/A-010 的方向性设计（供 P-004 引用，细稿在 P-004 落）。

---

---

## 已定决策（2026-11-28 用户确认）

以下事项原列于 §9 待确认，现经用户确认落定：

1. **对话产物与 walkthrough.md 落位**：任务生命周期内对话产生的文件（如 antigravity-comparison.html、调研报告等）一律放任务 doc/ 目录（本任务为 `.fstar/tasks/antigravity-adoption/doc/`）；walkthrough.md 同样落 doc/（即 `doc/walkthrough.md`），P-003 注入路径按此实现。此规则同时作为任务修复项：任务生命周期内对话产物不再散落仓库根或任务根，需写入 routing/工作流规则（由 P-004 落地，作为 A-006 材料落库的扩展而非新条目）。
2. **attach 聚合并入 unarchive 流程**：不设独立 `task attach` 子命令，attach 作为 `fstar task unarchive` 的内置步骤执行（§2.4 第 4 步按此实现）。
3. **steward 的 extension member 挂 multi-agent 包**：不新建包（§6 授权方案按此定案）。
4. **P-002 增加兼容测试**：无 origin 旧任务全链路（create/list/archive 等）行为不变，作为 P-002 的明确交付内容。

## 1. origin 字段（A-002）

### 1.1 实现事实

- **[事实]** task.json 顶层字段由 `models.py` 的 `TASK_FIELDS` 元组固定；已有 `OPTIONAL_TASK_FIELDS = ("status", "status_detail", "work_items", "next_step", "deliverables")` 先例——可选协作字段，缺席即默认值，校验在 `validate_optional_fields`。origin 走同一模式，不破坏旧数据读取。
- **[事实]** 现有父子关系是**物理嵌套**：`create(parent=...)` 把子任务写到 `parent_dir/subtasks/<name>` 并登记进父任务 `children`（名字列表，非 ID）；`_children_consistency` 强制 children 与磁盘目录一致。
- **[事实]** 已存在指向归档树的弱关联机制：`meta.related_tasks[]`（`{id, archive_path, relation, reason}`），create 时校验归档路径与 ID 匹配；`tasks.py:432` 注释明确"Archived hits can only be linked to a follow-up task, never reopened or mutated"。

### 1.2 设计提案

**字段定义**（新 OPTIONAL_TASK_FIELD）：

```json
"origin": {
  "task_id": "<uuid>",          // 父任务 task.json 的 id（权威标识）
  "archive_path": ".fstar/archive/2026-11/<name>",  // 归档树内身份路径（store.identity_path 格式）
  "reason": "followup/修复任务挂靠"   // 为什么挂靠
}
```

- **指向双字段（id + path）**：id 不变且全局唯一，path 是当前物理位置；reopen 后 path 会失效（见 §2.4），以 id 为主键、path 为提示性缓存，路径解析失败时按 id 在 tasks_root + archive_root 扫描兜底。**[否决]** 只存 id（每次全树扫描定位，热路径太贵）；只存 path（reopen 改变路径后链断裂）。**[否决]** 复用 `meta.related_tasks`：语义是"事后弱关联"，无注入/聚合行为，且字段结构面向纯归档路径，混用会让两个语义（记录 vs 驱动行为）纠缠。
- **与 children/parent 的关系**：origin ≠ 现有 parent。`parent`（物理嵌套、子任务在活动父任务 subtasks/ 下）保留原语义不变；origin 表达"我生长自一个（可能已归档的）父需求任务"。当父任务被 reopen 后，coordinator 可选择把 followup 子任务物理迁入父任务 subtasks/（§2.4 聚合规则），**[提案]** 迁入时把 origin 转写为普通 children 关系并保留 origin 字段作溯源，不要求两者永远同步。
- **校验规则**（在 `validate_optional_fields` 或 `create` 内）：创建带 origin 的任务时，按 archive_path（经与 related_tasks 相同的 `.fstar/` 前缀解析规则）读父 task.json，id 必须匹配，否则 `invalid_origin` 拒绝。父任务处于归档树或活动目录均可（活动父任务建议直接用 parent 嵌套而非 origin，规则在 routing 提示，内核不强制）。
- **向后兼容**：origin 缺席 = 行为与今天完全一致（A-006）。加入 OPTIONAL_TASK_FIELDS 后旧 task.json 无需改写。

## 2. reopen 状态机（A-001）

### 2.1 实现事实

- **[事实]** 已有两种"回退"机制，都不是本需求的 reopen：
  - `continue --action reopen`（tasks.py:999）：只作用于**未归档**的 completed 任务，phase→planning、completedAt→null、acceptance.state→historical、final check 证据置 stale，事件 `reopened`。
  - `drop --action revive`：只针对 dropped（有 disposition）任务，事件 `revived`。
  - **[事实]** 已归档任务没有任何恢复路径：`archive()` 只处理 tasks_root 下的顶层目录移入 `.fstar/archive/<YYYY-MM>/`；locate 明确归档任务只读。**[事实]** MILESTONES 集合已含 `reopened`、`revived`、`archived`。

### 2.2 事件类型：新增 `unarchived`

**[提案]** 新事件 `unarchived`，而非复用：
- **[否决]** 复用 `revived`：语义已被占用（dropped→active），且 drop/revive 明确要求 user 角色、作用于 disposition；混淆会让事件审计读错对象。
- **[否决]** 复用 `reopened`：现有 reopened 只改 phase 字段不动目录；本操作的核心是目录移动 + archivedAt 清除，语义不同层级。

事件 data：`{"from": "<identity_path>", "reason": "..."}`，加入 MILESTONES（保证 compact_events 不裁剪）。

### 2.3 命令与转换规则

**[提案]** 新子命令 `fstar task unarchive <ref>`（或 `fstar archive --undo`，倾向前者，与 `task create` 对称；P-002 定案）。语义：

1. 前置：目标必须在 archive_root 下（`task_dir.relative_to(store.archive_root)` 通过），否则 `not_archived` 拒绝。
2. **仅顶层归档任务可 unarchive**：与 archive 对称（`archive_child_forbidden` 反向镜像）。**[否决]** 允许从归档树内部恢复单个子任务：归档树是"验收快照"，部分恢复会让归档月份目录里的父子树残缺，回溯完整性（A-001 的"归档后的父目录树内可完整回溯"）被破坏。
3. 权限：**user 角色确认**（与 reopen/drop 同级——这是把已验收快照挪回工作面，coordinator/agent 不得自行执行）。复用 `validate_source` 确认链。
4. 状态转换：`phase` 不动（保持 completed）还是回 planning？**[提案]** 联调场景父任务本身不再返工、只是挂新子任务，父保持 completed，新子任务独立走自己的生命周期；但父任务的 `acceptance`/`evidence` 保持原样（归档前已 valid）。**[否决]** 强制父回 planning：会连带触发 `_require_children_ready` 语义混乱，且用户需求是"挂子任务"不是"父任务返工"。若后续真要父返工，可用现有 `continue reopen`（unarchive 后即可用）。
5. 字段处理：`archivedAt` 置 null 并记入事件 data（保留历史值）；`completedAt` 保留（父任务确实完成过）。子树内所有任务同样清 archivedAt（整树移动，一次遍历 `_scan_tree` 写回）。
6. 目录移动：`archive_root/<month>/<name>` → `tasks_root/<name>`，复用 archive 的两阶段模式（staging rename 或直接 os.rename——单次 rename 原子性足够，[提案] 直接 rename + 失败时事件不落，保持"事件在动作成功后写"的现有约定）。目标已存在 → `archive_conflict`（与现有 code 对齐）。清 tree pointers（archive 用 `clear_tree_pointers`，unarchive 反向：清归档侧指针遗留，重建 current 无必要）。
7. 事件顺序：**先移动后写事件**（对齐 archive 的 pending→completed 两段写法；简化为：rename 成功、重读 task.json、清 archivedAt、append `unarchived` 事件、写回）。中断恢复（operation_id 重试）**[提案]** 第一版不做归档那种完整的 operation 恢复链，但事件里记录 identity_path 使手工/doctor 检查可追溯；如实现中发现半移动状态可检测（目录不在 archive 也不在 tasks）再加恢复分支。

### 2.4 聚合规则（父子共同重新归档，followup 子任务进父目录树）

**[提案]** 流水线：

1. 父任务已归档、用户报告问题落在其范围 → coordinator 判断挂靠（prompt-states 联调提示，P-004 内容）。
2. `fstar task create --origin <parent_id/ref> <followup-name>`：父在归档树中，origin 校验按归档路径通过；子任务先落在 tasks_root 顶层（平铺）。
3. 需要父上下文密集协作或准备收尾时：`fstar task unarchive <parent>` 挪回 tasks_root。
4. **聚合迁移命令（[提案] 并入 unarchive 或独立 `task attach`）**：unarchive 时扫描 tasks_root 顶层所有 `origin.task_id == 父 id` 的任务，把它们整体迁入父 `subtasks/`，登记进父 children，origin 字段保留（溯源）。**[否决]** 创建时直接写进归档父目录：会写脏归档树（归档=验收快照原则），且 `archive()` 恢复中断分支假设归档树稳定。**[否决]** 只在 create 时若父未归档才允许挂靠（现状）：正是 A-001 要解除的限制。
5. 完成后父+子作为一棵树重新 `fstar archive <parent>`——现有 archive 已支持整树（`_validate_archive_tree` 递归校验所有子任务 completed/dropped + 证据 valid），**无需新逻辑**，A-001 的"一起重新归档"免费获得。归档月份取新归档时刻（父任务会出现在新的月份目录；旧月份目录里不再有它——**[提案]** 接受，事件链 `archived → unarchived → archived` 保留完整回溯；**[否决]** 移回原月份目录：archive 目标冲突处理复杂化且无实际收益）。
6. unarchive 时顶层是否还留有其他 origin 指向该父但未 attach 的任务：不强制，attach 是显式动作；孤儿检测留给 doctor/检查（P-005 独立检查项）。

## 3. 上下文注入（A-002）

### 3.1 实现事实

- **[事实]** `hooks.worker_context` 已注入当前任务文档：`inject.task_doc_inputs` 只读 `doc/prd.md`、`doc/design.md`、`plan.md`、`clarify.md`（无 walkthrough.md——**[事实]** 项目中尚无任何 walkthrough 引用，A-005 是新增）。
- **[事实]** 预算：`max_file_bytes` 256KB、`max_total_bytes` 2MB、`max_artifact_bytes`（inject.py DEFAULTS）；`prepare_read_context`（dispatch.py:188）是 coordinator 显式选文件的另一通道，带 sha256 + unloaded 降级报告。
- **[事实]** role 门禁：editor/research 角色要求 task extensions 里有对应 included member，否则 `extension_not_authorized`。

### 3.2 设计提案

**注入清单**：task 携带 origin 时，`worker_context` 在现有 `task_doc_inputs` 之外追加父任务输入：

| 优先级 | 文档 | 来源 |
|---|---|---|
| 1（必有） | 父 `design.md`（doc/design.md） | origin 解析出的父目录 |
| 1（若有） | 父 `doc/walkthrough.md`（收尾产物，A-005 定名后统一；路径已定：任务 doc/ 下） | 同上 |
| 2（可选） | 父 `criteria.md` | 只在预算内附带 |

**[否决]** 注入父全套（clarify/plan/prd/research）：联调 worker 需要的是"做了什么、怎么验证的"，不是需求过程全史；token 预算应留给本任务上下文。**[否决]** 注入父 task.json 全文：体积大、含全量 events（最多 200 条），信息密度低——注入 `task_summary` 式摘要行（父 name/title/description）即可。

**裁剪规则（防 token 膨胀）**：复用 inject 现有 per-file/total 预算：
- 父文档 ≤ max_file_bytes：全文注入（fingerprinted，与现有输入同机制）。
- 超预算：**[提案]** 截断加载并把超限记入 unloaded/deferred 报告（"parent_context_partial"），不静默截断。**[否决]** "大文档自动摘要+关键决策段"：内核没有可靠的语义摘要器（那是 LLM 能力），自动截首去尾会假装完整。正确路径是 A-005 让 walkthrough.md 本身保持精简（模板限定"改了什么+如何验证+证据"），使全文注入天然可控；超限时降级为"deferred + 提示 worker 自行读父目录"。coordinator 也可用 `prepare_read_context` 主动带选段，双通道并存。
- 父文档注入同样过 `_safe_context_path` 与治理/规划成员门禁（governance/planning grant 过滤照旧——父文档在任务树内，天然通过，但代码路径复用）。

**降级行为（如实记录）**：
- origin 指向的父 task.json 缺失/ID 不匹配：**不阻断** dispatch（本任务仍可执行），在注入文本 footer 追加显式行：`Parent context unavailable: <原因>`，并随 worker context JSON 报告（as_json 分支带 `parent_context: {"status": "missing"|"loaded"|"partial", "origin": ...}`）。
- 父已 unarchive（path 失效）：按 id 在 tasks_root 顶层解析成功 → 正常注入；两处都找不到 → 按缺失降级。
- **[提案]** dispatch payload 的 `context_report` 增加 parent_context 字段，harvest 时随结果落档——注入失败可审计，杜绝"冒称注入成功"（A-002 原文要求）。

## 4. evidence 一致性（reopen → 再归档循环）

**[事实]**：acceptance 是历史决策（`_validate_archive_tree` 注释明确信任 recorded state，不按当前文件指纹复核）；`artifact_map` 存于 `meta.templates`，`artifact_map_sha256` 锁定映射本身；`evidence.invalidate` 有 `evidence_invalidated` 事件。

**[提案]**：
- 父任务 unarchive **不动**其 evidence/artifact_map：归档前后校验规则一致（信任 recorded acceptance），原证据继续有效。父任务的证据描述的是它自己的交付物，子任务生长不改变这些文件（子任务改的是产品代码——那会正常触发其他任务的 fingerprint 失效，机制已存在）。
- **再归档时**：`_validate_archive_tree` 对父沿用现有规则（acceptance valid + evidence_refs 非空）即可，无需 reopen 循环特判；新子任务按正常任务验收。
- **[否决]** unarchive 时批量 invalidate 父证据或重建 artifact_map hash：会把一次"挂子任务"放大成"父任务重新验收"，用户需求不要求且成本高；真实冲突（子任务改了父证据引用的文件）会由现有 `evidence invalidate`/delivery_snapshot 机制在子任务自己的验收环节暴露。
- 唯一新增一致性检查：unarchive 时若发现父 `acceptance.state` 非 valid（理论不可能出现在归档树，防御性）→ 拒绝并报错，不静默修复。

## 5. A-009 授权链路修复方向

**[事实]**（hooks.py worker_context + extensions.py）：
- `worker_context` 的 grants 来源：有 task_ref 时 `grants(task["extensions"])`（任务持久授权记录）；session-only 或无 task 时 `grants(payload.get("extensions", []))`。
- `fstar extension enable` 不带 ref → 返回 record + `persistence: "session_only"`，**只活在 CLI 调用进程的返回值里**，没有任何落盘/会话共享。
- editor/research 的 role_member 门禁检查 `context`；宿主 Agent 工具的 PreToolUse payload（session_id + agent_type）里没有这些 record，hook 拿到的 extensions 为空 → `extension_not_authorized`。

**修复方向（二选一或并用，P-004 定案）**：
1. **[提案，首选] 宿主派发 payload 携带 extensions**：runtime-dispatch 的 dispatch wrapper 构造 PreToolUse payload 时，把 session 内已 enable 的 extension records 放进 payload.extensions（与 dispatch.py:624 session-only 分支同构——该分支已经这么用）。需要解决"session 内已启用"的存放：**[提案]** 会话级 runtime 文件（runtime_root 下按 session_id 存 session grants 小 JSON，`extension enable` session-only 时写入，uninstall/过期清理）。**[否决]** 复用任务持久记录：会话级授权写进任务会把临时 session 授权永久化，越权。
2. **[提案，备选] hook 解析 session 授权**：worker_context 拿 payload.session_id 去读上述 session grants 文件。本质上和 1 需要同一个存储，只是读取方不同——**[提案]** 两处都接同一 session-store：payload 携带优先、缺失时 hook 回读，覆盖 payload 被宿主裁剪的情况。
3. **[否决]** 放宽 role_member 门禁（hook 失败仅告警现状不可取，见 A-009 原文；直接去掉门禁则无授权审计）。

## 6. A-010 fstar-steward 角色（骨架）

**[事实]**：ROLES = ("research", "implement", "check", "editor", "learn")（content.py）；role card 在 resources/agents/fstar-<role>.md；hook 的 role_member 映射现只有 research/editor 两个有授权门槛。

**[提案]** 骨架（细节 P-004 落地）：
- `content.ROLES` 增加 `"steward"`；新增 `resources/agents/fstar-steward.md` role card。
- 职责边界：任务生命周期操作（task create / start / accept / archive / drop、deliverable 注册、任务文档建档与初稿 clarify/criteria/plan/design/walkthrough 创建）、返报告返回可验证事实（命令输出、事件 id、注册结果）。
- allowed paths：**只写** `.fstar/tasks/**`（活动任务树）+ 通过 CLI 间接改 task.json；**不写**产品代码（那是 implement）、不改既有文档条目内容（那是 editor，steward 只建档/初稿）、不执行检查（check）。与 implement/editor 同构地写进 role card 的 "Allowed paths and rules" 段。
- 授权：**[提案]** steward 挂新 extension member（如 `multi-agent/steward` 或并入现有包，P-004 与 A-009 链路修复同次设计），role_member 映射加入 hooks.py；CLI actor-role 枚举加 `steward`。
- **[否决]** 让 editor 兼任建档：editor 的 baseline 冲突保护模型面向"已存在条目"，建档（新建文件）没有 baseline 可比，混入会稀释两个角色的校验语义。

## 7. 兼容与迁移（A-006）

**[事实]**：
- `store.py SCHEMA_VERSION = "1"`；`fstar version` 报 data_schema supported [1] current 1。
- `fstar migrate` 由 installer.py 的 `MIGRATIONS: Dict[Tuple[int,int], object] = {}` 驱动（当前为空 = 无链），支持 `--to-schema`/`--dry-run`/`--rollback`（快照回滚事务）。
- 全局资源迁移（resource-migrate）与数据 schema 迁移是两套机制，注释明确"Resource migration never migrates the data schema"。

**[提案]**：**不 bump schema 版本，不写迁移**。
- 理由：origin 是纯新增可选字段（OPTIONAL_TASK_FIELDS 模式），旧数据"无字段 = 无行为"天然成立；`unarchived` 事件、`meta.templates` 不变；读取端从不要求字段存在。A-006 的"无 origin 字段的任务行为不变"由代码路径保证 + 兼容测试覆盖（P-002：用旧格式 task.json 跑 create/list/archive 全链路）。
- **[否决]** bump 到 schema 2：引入空迁移链（1→2 no-op）徒增版本面，且 MIGRATIONS 的语义是"转换不可直接读取的数据"，这里不适用。若未来 origin 结构 breaking 变更再启用。
- 未来真需迁移时的路径已在：注册 `MIGRATIONS[(1,2)]` transform，走 `fstar migrate --to-schema 2` 快照回滚。

**材料落库（A-006 前半）**：antigravity-comparison.html 移至 `.fstar/tasks/antigravity-adoption/doc/antigravity-comparison.html`（clarify 第五轮用户已确认任务 doc/ 位置），P-005 执行。

## 8. 影响范围汇总

| 变更 | 文件 | 类型 |
|---|---|---|
| origin 字段 + 校验 | models.py, tasks.py | P-002 |
| unarchive 命令 + 事件 + attach 聚合 | tasks.py, cli.py | P-002 |
| 父上下文注入 + 降级报告 | runtime/hooks.py, runtime/inject.py, dispatch.py | P-003 |
| session grants 存储 + A-009 链路 | extensions.py, runtime/hooks.py, installer/CLI session 层 | P-004 |
| steward 角色 | content.py, resources/agents/, hooks.py, cli.py | P-004 |
| walkthrough.md 模板与命名 | resources/templates, runtime/inject.py task_doc_inputs | P-004（命名需在 P-002 前协调，注入路径依赖它） |

## 9. 待确认 → 已定（见文首"已定决策（2026-11-28 用户确认）"）

1. walkthrough.md 存放路径：**已定** —— 落任务 doc/ 目录（`doc/walkthrough.md`），P-003 注入路径按此实现；task_doc_inputs 需同步；与 A-005 模板一起定。
2. attach 聚合动作：**已定** —— 并入 `task unarchive`，不设独立子命令（一次心智模型）。
3. steward 的 extension member 归属：**已定** —— 挂 multi-agent 包，不新建包。
4. （补充落定）P-002 交付包含无 origin 旧任务全链路行为不变的兼容测试。
