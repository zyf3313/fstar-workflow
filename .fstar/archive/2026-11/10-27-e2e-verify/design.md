# 端到端验证设计（e2e-verify）

本文是 `10-27-e2e-verify` 的技术设计。权威依据：本子任务 `prd.md`、父任务 `10-25-fstar-workflow-design` 的 `prd.md` / `design.md`（全文）/ `implement.md`（全文，§4 32 项为最终验收骨架）。所有场景只针对**已交付的真实 API** 设计，不围绕不存在的功能设计；prd AC 中已被父设计收敛撤销的条目按 §2 的映射处理并如实记录偏差。

## 1. 边界与所有权

| 项 | 约定 |
|---|---|
| 本子任务拥有 | `tests/test_e2e_scenarios.py`（场景回归测试）、`.trellis/tasks/10-27-e2e-verify/evidence/`（证据台账）、必要时 `.trellis/tasks/10-27-e2e-verify/scenarios/` 下的运行说明 |
| 可修改的产品代码 | 仅限 e2e 场景暴露、且可追溯到**集成缺口**的缺陷（例如两模块对同一契约的理解不一致）。优先在发现处写最小复现报告给协调者；跨 `src/fstar` 多模块的缺陷**上报协调者决策，不静默全量修复**；每次修复单独记录（缺陷、根因、改动文件、受影响回归） |
| 不做 | 不新增 CLI 命令、顶层 task 字段、hook、skill、模板；不改父契约；不做 git 操作；不写真实 `~/.fstar`、`~/.claude`、真实 Codex 用户目录 |
| 证据不可回滚 | 失败/阻塞场景的记录永久保留，不得删除或改写为通过 |

## 2. PRD AC → 交付现实映射（含已知偏差）

本子任务 prd 的部分 AC 使用了父设计收敛**之前**的词汇或引用了已撤销范围（父 design §1.2 非目标明确排除"独立测试用例文档及审批包、独立 review-log"；§3.2 明确"无顶层 review[]、无独立用例批准证据前置"；父 implement.md §4 当前 12–16 项为 26字段/文档单源/模板/doc并发/plan执行，21–25 项为规范阅读/规范治理/知识格式/历史回忆/五能力，与 prd 中的旧编号引用不一致）。按下表映射到交付核心执行，偏差本身作为发现上报协调者：

| prd AC 原文 | 交付等价物（场景实际验证） | 诚实缺口 |
|---|---|---|
| 主任务 drafting→archived 全程合法 | `planning → in_progress → completed`（仅三态）+ `archive` 移树；`state show` 的 `effective_phase` 派生显示 | prd 的 drafting/planned/checking 七态词汇已被三态设计取代；记录为 prd 措辞过期，非实现缺口 |
| 非法转移被拒绝且报错可读 | `start_blocked` / `acceptance_blocked` / `archive_blocked` / `drop_forbidden` / `reopen_forbidden` / `lease_conflict` 等稳定 code + 非零退出 | — |
| 需求/设计/用例变更 → 证据 stale → 回 checking | `doc-change` hook / `evidence invalidate` → 相关证据 stale；completed 依据失效回 `in_progress`（交付中等价于"回检查"） | "落回 checking" 是派生显示语义，交付以 in_progress + awaiting_acceptance=false 表达 |
| 验收闸门：Agent 推不到 done | `accept` 强制 `actor.role=user`（`acceptance_forbidden`）；worker done 仅 harvest 完成（`next: dispatch independent check`） | "done" 词汇 → 交付为 `completed` |
| 归档提醒触发、暂缓与去重 | `archive` 输出 `archive_candidates` + `reminder_updates`；`meta.reminders` 按 reminder_key 去重、默认暂缓 7 天 | — |
| 评审闸门（无需求确认 drafting→planned 被拒等） | `start` 必须带确认来源（`confirmation_required` / `stale_confirmation`）；启用 planning-review 扩展后 `start` 要求已映射的 `artifact_map`（`planning_artifacts_missing`）；未启用该包时豁免 | prd 的"启动确认即 prd/design 最终批准"由 `started` 事件携带 source/快照表达；"改需求使证据 stale"走 doc-change/invalidate 路径 |
| 评审稿单源（无 AI 副本、无顶层 review[]、review-log 留痕） | `doc/` 单份正文由场景断言；`task.json` 26 字段无 `review[]`（`validate_task` 强制）；变更留痕在 `events[]`（`doc_changed` 类事件 + `evidence_invalidated`） | **prd 提到的 `doc/review-log.md` 已被父设计撤销**（非目标：独立 review-log）；交付用 `review record/list` + events 表达，记录为 prd 过期条目 |
| 模板可替换、槽位提取 | `content.extract_artifact` + `build_artifact_map` + `evidence.persist_artifact_map`（mode markers/explicit/file）；缺槽位/缺映射明确报错不推断 | 用户自带模板的"首次映射经用户确认"是 Agent 行为，fixture 只能验证机器侧提取与报错 |
| 规范主题归口 / `fstar spec check` | 交付无 `spec check` 命令（父 design §4.1 明确不保留）；等价物为 `content.validate_resources` 链接检查 + `knowledge` 目录快照诊断（`knowledge_unindexed` 等） | 记录为命令面差异，非缺陷 |
| 逐用例状态（`fstar acceptance status` 区分五态带版本/环境/run id） | `acceptance status` 输出每条 check item 的 `passed/failed/blocked/skipped/not_run` + `run_id`/`environment`/`delivery`；`_validate_check` 强制五态合法、passed 必须有命令或评审方法 | — |
| 文档一致性（doc-change 指纹/stale/事件；drafting 无噪声） | `doc-change` 幂等（未变更零写入）；非 planning 阶段证据 stale + completed 回滚；无映射时保守 `unknown_plan_items` 而非空 | "drafting 中无证据草案不产生 stale 噪声" → 交付为 planning 阶段无有效证据时 invalidate 返回空列表零写入 |
| 派发带版本 / 专职改文档 / 回读校验 | `worker-context` 每个输入带 `{path, sha256, version}`；`doc-edit` 构建 editor payload（item_ids + baseline_sha256 强制）；harvest 的 `baseline_conflict` 拒绝旧稿覆盖；回读四项（槽位/ID 唯一/关联/图文）由 `extract_artifact` 诊断（DUPLICATE_ID/INVALID_REFERENCE/MARKER_* 等）覆盖 | 图文一致性中的"图"语义检查是 check 角色职责，fixture 验证机器可判定部分 |
| 用例驱动检查（doc/test-cases.md、批准指纹、F-xxx 补丁建议） | **父设计已撤销该范围**（非目标：独立测试用例文档及审批包；§3.10"无测试用例文档或审批前置"）。交付等价物：check 证据 `items[]` 逐条 `plan_item`+`requirement_ids`+`result`+`command`；生成文档不能使用例变通过（`_validate_check_scope`：validated ids 必须已存在于 artifact_map，报告不能自造覆盖） | 整组 AC 记录为 prd 过期范围，场景只验证交付核心的逐条目覆盖与不可自造通过 |
| 最小闭环 / 会话内节点不落盘 / hook 边界 | 见 §4 S2；`python3 -m fstar.runtime` 被动语义静默跳过、routing 照常注入 | — |
| 扩展协商一次一个 / 拒后不重问 / 中途加载不重做 | 机器侧：`extension enable`（会话级与任务级）、scope custom 的 included/excluded 生效、拒绝后（disable）继续；routing.md 正文含"一次一个、拒后无新事实不重问"规则（静态验证注入内容）；中途启用 persistent-task 不使既有有效证据 stale、不改 phase | "主 Agent 只推荐一个包""拒后不再问""skill 加载生效"是宿主内 Agent 行为，fixture 无法证明，标记为 live-delivery 缺口 |
| extensions[]/capabilities[] 分离与恢复 | `enable_extension`/`record_provenance` 写入两侧；`validate_task` 对 extensions[] 严格 schema；写入口拒绝交叉形态（extension 记录进 `record_provenance` 被 `_validate_record` 拒；capability 记录进 `enable_extension` 被成员校验拒）；新进程 `state show`/`extension list` 读回 | 直接文件编辑把 extension 记录塞进 capabilities[] 时 `validate_task` 只查 dict 类型——分离由**写入口**保证而非深度 schema，如实记录 |
| skill 分层生效 / `skillOverrides` | 交付无 `skillOverrides` 配置；静态侧 `validate_resources` 校验 12 skills、描述 ≤200/合计 ≤2400 | 记录为未交付配置项；listing 实际占用是 live-host 观察项 |
| 工具绑定/降级、知识、两宿主 | 见 §4 S4–S6 | — |

## 3. 证据定义与分级

**e2e 证据 = 真实命令调用 + 如实记录**。每条记录含：完整命令行、退出码、期望 vs 实际、判定（pass/fail/blocked/skipped）、产物路径。命令通过子进程调用 `python3 -m fstar`（`PYTHONPATH=src`）与 `python3 -m fstar.runtime <hook>`（stdin 传 JSON payload），即真实 CLI/hook 入口，不走内部函数捷径（仅 §4 标注的少量 setup 步骤使用内部 API，因无对应 CLI 命令，逐处标注）。

| 级别 | 含义 | 本子任务现状 |
|---|---|---|
| fixture-test | 临时根目录（project/user/runtime/host 全部 TemporaryDirectory）内真实子进程命令的实测结果 | 本子任务主要证据级别 |
| observed-schema | 宿主二进制/schema 观察到的事件名与 payload 形态（`HOST_EVENT_MAP`、`hook plan` 输出的 `evidence` 字段），不证明宿主真实投递 | 注册计划、doctor 条目按此级记录 |
| live-delivery | 真实宿主会话内：hook 事件真实投递、原生 Agent 真实派发/转向/中断、skill 真实触发 | **当前 0 项**，全部列入 §6 阻塞清单 |

## 4. 场景矩阵

所有场景共用隔离剖面 §5。每格"命令"为真实调用序列的摘要；详细步骤写在 `tests/test_e2e_scenarios.py`。

### S1 持久生命周期全闭环（prd AC 1–5；父 §4 第 2/3/4/5/6/7/8/9 项）

| # | 步骤（命令） | 期望 |
|---|---|---|
| S1-1 | 临时根 `fstar init <proj>`；`fstar init --user`（`--user-data-root` 指向临时用户根） | created 四文件；重复 init preserved 不覆盖 |
| S1-2 | `task create` 主任务 + `--parent` 子任务；`extension enable persistent-task <task>`、`extension enable planning-review <task>`（`--confirm-user`） | extensions[] 记录含 source/scope；events 有 extension_enabled |
| S1-3 | 写 `doc/prd.md`/`plan.md`（带标记条目）；内部 API `content.extract_artifact`→`evidence.persist_artifact_map`（无 CLI，标注 setup） | artifact_map 持久化于 meta.templates |
| S1-4 | `start <task>` 不带确认 | rc≠0 `confirmation_required`（评审闸门：无确认不放行） |
| S1-5 | `start <task> --confirm-user` | planning→in_progress；started 事件绑定当时快照 |
| S1-6 | `dispatch implement --payload`（真实 payload 文件）→ 模拟 worker 改交付文件 → `dispatch harvest --result --payload --lease-token` | registered+租约；delivery 证据记录、租约自动续约 |
| S1-7 | 非法转移组：对 planning 任务 `accept`；对 in_progress 无新鲜 check 时 `accept`；agent 角色带 `--confirmation` 尝试 `accept`；对子任务单独 `archive`；`drop` 非 user 角色 | 各自稳定 code 非零退出（acceptance_blocked/check_not_independent/archive_child_forbidden/drop_forbidden 等） |
| S1-8 | `dispatch check` + check 证据（含一条 failed）→ harvest → `acceptance status` | awaiting_acceptance=false，blockers 含 unresolved_check；五态逐条可见 |
| S1-9 | 修复后再次 `dispatch check`（全 passed、scope=final）→ `acceptance status` → `accept --confirm-user` | awaiting_acceptance=true；accept 写 completed/completedAt/acceptance |
| S1-10 | 子任务同链路完成（或 user `drop` 带处置）后 `archive <主任务> --confirm-user` | 整树移入 `archive/<YYYY-MM>/`；archivedAt；输出 archive_candidates+reminder_updates |
| S1-11 | 构造第二个 30 天前完成未归档任务（直接改 task.json 时间字段模拟外部编辑，标注 setup）后归档第一个任务 | 提醒列出该任务（名称/时间依据/缺项）；`meta.reminders` 写入 deferred_until；再次归档同键去重不再重复提醒 |
| S1-12 | 证据失效：编辑 `doc/prd.md` → `python3 -m fstar.runtime doc-change`（stdin payload） | 相关证据 stale + 事件；已完成任务回 in_progress；无关证据不受累 |
| S1-13 | `continue --action replan --confirm-user --reason` | 回 planning、全部证据 stale、acceptance 失效、租约释放 |
| S1-14 | 孤儿租约：把 lease.expires_at 改为过去（setup）→ `continue <task>` | 只读报告 orphaned + choose_takeover_replan_or_drop；不自动重派 |
| S1-15 | `task list --all`、`state show`、`acceptance status` 在归档后 | 归档任务在 --archived 视图；活动视图无残留 |

### S2 非持久最小闭环 + 扩展协商（prd 最小内核组 AC；父 §4 第 1/10/20 项）

| # | 步骤 | 期望 |
|---|---|---|
| S2-1 | 未 init 的临时目录：`python3 -m fstar.runtime session-context`（payload 含 cwd） | stdout 注入 routing 全文 + "No initialized fstar project found" 行；rc 0；**目录树无任何 `.fstar`/task.json/runtime 新文件**（前后快照 diff 断言） |
| S2-2 | `python3 -m fstar.runtime worker-context`（payload role=fstar-implement） | 角色卡注入 + `Active task: session-only`；非 fstar 角色（如 trellis-*）不注入 |
| S2-3 | `dispatch implement --task-ref session-only ...` → `dispatch harvest`（session-only result） | registered:false/persistence:session_only；harvest recorded:false；零落盘 |
| S2-4 | `python3 -m fstar.runtime doc-change`（无关文件） | 静默跳过 rc 0 无输出噪声 |
| S2-5 | 会话级扩展：未 init 目录 `extension list` → `extension enable tool-capability --confirm-user` → `extension disable` | persistence:session_only；scope/members 校验照常；零落盘 |
| S2-6 | routing 正文断言：注入文本含五包 ID、"recommend only one highest-value package"、"do not ask again unless new facts" | 协商规则的唯一来源真实注入（机器可验证部分） |
| S2-7 | 中途加载不重做：对 S1 式 in_progress 任务先记录 delivery 证据，再 `extension enable multi-agent <task>` | 既有证据仍 valid、phase 不变、不产生 stale（启用扩展不是重做信号） |
| S2-8 | 三条底线机器侧：harvest 输出 `next: dispatch independent check`（实施/检查分离）；check failed 后 awaiting_acceptance=false（失败必回修复）；agent 角色 accept 被拒（完成仅用户确认） | 见 S1-7/S1-8，此处汇总断言 |

### S3 extensions[]/capabilities[] 记录与恢复（prd 扩展组 AC；父 §4 第 11 项）

| # | 步骤 | 期望 |
|---|---|---|
| S3-1 | `extension enable <id> --scope custom --include ... --exclude ...` | included/excluded 生效；重叠/未知成员被拒（invalid_extension_scope/members）；full 补全整包 |
| S3-2 | `extension disable` 后新进程（新子进程）`extension list <task>` / `state show` | extensions[] 当前态读回；启用/裁剪/停用历史在 events[] |
| S3-3 | 内部 API `tools.record_provenance`（无 CLI，标注）写 capabilities[]；再用 extension 形态记录调 `record_provenance`、用 capability 形态调 `enable_extension` | 两侧各自拒绝交叉形态；capabilities[] 只存 provenance（工具/版本/调用依据） |
| S3-4 | 直接文件编辑把 extension 记录塞入 capabilities[] 后读取 | `validate_task` 通过（仅 dict 检查）——如实记录"分离由写入口保证"的限制，不宣称深度 schema 检出 |

### S4 工具绑定与降级（prd 工具维度 AC；父 §4 第 25/26 项）

| # | 步骤 | 期望 |
|---|---|---|
| S4-1 | fixture PATH 放置假工具 + 用户 registry.d 声明 → `tools scan` | 注册表 strong、探针 weak、未分类进手动候选；detected_at/observations/proposals 齐全；未确认不写 tools.yaml |
| S4-2 | 内部 API `resolve_bindings`（项目>用户>默认）+ `apply_binding` 带确认 | 绑定确认后写入；`tool: null` 显式解绑停止回退 |
| S4-3 | 能力缺失：某维度不绑定 → resolution `state: unbound` + recommendation + `FALLBACKS` 降级文案 | 缺口报告含实际缺口与降级路径；无自动安装/换绑定 |
| S4-4 | `assess_availability` 三层（可发现/客户端加载/最小真实调用）用 fixture 观测 | 三层分别报告 verified/failed/unknown；`build_provenance` 生成 fstar.tool-use.v1 |

### S5 知识链路（prd 知识相关 AC；父 §4 第 22/23 项）

| # | 步骤 | 期望 |
|---|---|---|
| S5-1 | init 产出的项目索引 + fixture rules/memory/specs → 内部 API `load_catalog`/`load_context`/`resolve_context` | 严格 fstar.knowledge.v1；superseded/unreviewed 不加载；四层优先级裁决、冲突显式 |
| S5-2 | `prepare_change`（learn 提案）→ 无确认 `apply_change` → 带确认 `apply_change` | 无确认零写入；确认绑定提案哈希后正文+索引+引用一组更新 |
| S5-3 | 新 spec 文件列入任务 `implement.jsonl` → `python3 -m fstar.runtime worker-context` | 注入该 spec 全文且带 `{path, sha256, version}`（知识被上下文消费） |

### S6 两宿主证据（隔离剖面内；父 §4 第 27/28 项）

| # | 步骤 | 期望 |
|---|---|---|
| S6-1 | `hook plan --host claude` / `--host codex` | 每条 hook 含精确命令、`launcher_installed`（按磁盘实际）、`evidence: observed-schema|unverified-schema`；只读不写设置 |
| S6-2 | `install --host claude --host-root claude=<temp> --host-root codex=<temp> --user-data-root <temp>` | 宿主设置只写临时根；追加/去重；用户已有条目保留 |
| S6-3 | `doctor`（同临时根） | 12/4/4/11/5 计数健康；entries 为磁盘核实报告（indexed-but-uninstalled → entry_index_stale 且 healthy=false）；listing 证据区分 observed/estimated |
| S6-4 | `uninstall` | 只精确移除自身 4 条 hook 与安装器拥有文件；临时用户内容保留 |
| S6-5 | 全程断言真实 `~/.fstar`、`~/.claude` 未被触碰（运行前后 mtime/内容快照；且所有命令均显式传临时根） | 隔离剖面成立 |
| S6-6 | live-host 检查设计（**默认 blocked**）：若用户授权在真实宿主设置注册 hook 并开一个真实会话，则观察 SessionStart/PostToolUse 是否真实投递；否则按 §6 列为 blocked | 无授权不执行；绝不写真实设置 |

## 5. Harness 设计

- **实现**：`tests/test_e2e_scenarios.py`，unittest 驱动，Python 3.9 标准库 only。每场景一个 `test_s*` 方法；步骤通过 `subprocess.run([sys.executable, "-m", "fstar", ...], env={... PYTHONPATH: src, FSTAR_USER_ROOT/FSTAR_RUNTIME_ROOT/FSTAR_PROJECT: 临时根})` 真实调用 CLI，hook 用 `python3 -m fstar.runtime <hook>` + stdin payload。
- **夹具**：`tempfile.TemporaryDirectory` 提供 project/user/runtime/host 四根；无网络；不读真实 HOME（所有命令显式传根；环境变量覆盖）。
- **证据台账双用**：同一实现既是回归测试又是证据生产者——设置 `FSTAR_E2E_EVIDENCE_DIR=<child>/evidence` 时，每个场景把逐步命令/退出码/期望/实际/判定追加写入 `e2e-run-<YYYY-MM-DD>.md`；未设置时仅断言不落盘。失败场景的记录照常写入并被 unittest 判 fail，绝不静默丢弃。
- **时钟**：CLI 用真实时钟。需要"过期"的步骤（孤儿租约、30 天前活动）以受控的直接文件编辑模拟外部编辑，并在证据中标注 setup 性质；不用 monkeypatch 冒充真实时钟行为。
- **无 CLI 的 setup 步骤**（persist_artifact_map、record_provenance、resolve_bindings、knowledge API）：用内部 Python API，逐处标注"internal-API setup"；这本身记录为命令面观察（见 §6）。

## 6. 隔离剖面与阻塞清单（本子任务不能关闭的项）

live-host 检查的隔离规则：任何涉及宿主设置的命令必须 `--host-root`/`--user-data-root`/`--runtime-root` 全部指向临时目录；绝不以默认根运行 install/uninstall。在此剖面内无法取得 live-delivery 证据的项，列为 **blocked** 并写明需要用户提供什么：

| blocked 项 | 需要什么 |
|---|---|
| 真实 Claude/Codex 会话内 hook 事件投递（SessionStart/PreToolUse/PostToolUse/SubagentStop 实际触发） | 用户授权把 hook 注册进真实宿主设置并开一个真实会话观察 |
| 真实原生 Agent 派发/转向/中断（dispatch 的 adapter 步骤在宿主内真实发生） | 用户在真实宿主会话中按 adapter 指引执行一轮派发并回收结果 |
| skill 真实触发与 listing 实际占用 | 同上（真实宿主内观察） |
| npm 包名 `fstar` 冲突核实 | 需要网络/registry 查询（本子任务无网络） |
| 模板固定提交 `674bea3` 原文与许可核对 | 需要访问个人仓库该提交（无网络） |
| Codex 用户级安装路径证实 | 需要真实 Codex 宿主环境 |

以上全部为**父级开放项**，随本子任务报告上交，不在本子任务内静默豁免或伪造。

## 7. 缺陷处理与回归

1. 场景失败先分类：fixture 错误（改场景）/ 集成缺口（可由本子任务在协调者确认后修）/ 单模块缺陷（上报）/ 契约级问题（上报父级）。
2. 任何修复后重跑受影响场景 + 全量回归（`PYTHONPATH=src python3 -m unittest discover -s tests`，基线 542 项全过）+ `python3 -m compileall -q src/fstar tests`。
3. 修复记录逐条写入执行记录：缺陷现象、根因、改动文件、影响面；跨模块改动必须经协调者。

## 8. 与父级 32 项验收的关系

本子任务的场景矩阵覆盖父 §4 中可在 fixture 级验证的项并为 live 项产出阻塞清单；**父级 32 项整体核验发生在本子任务关闭之后**，由父任务执行。本子任务交付：场景回归测试、证据台账、回归清单（各子任务 AC ↔ 场景映射）、已知缺口清单。
