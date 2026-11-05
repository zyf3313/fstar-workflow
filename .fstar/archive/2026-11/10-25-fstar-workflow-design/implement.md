# fstar 实施计划

> 本文件名是 **Trellis 父任务的 `implement.md`**。fstar 产品的任务执行产物为 `plan.md`，不得因本文名称生成产品 `implement.md`。

父任务 `10-25-fstar-workflow-design` 当前执行计划。用户已批准最终规划并授权全部十个子任务实施；本文不启动任务、不改产品代码、不做 git 操作。十个子任务全部属于第一版、一次性交付；顺序只表达依赖。每个子任务 kickoff 先按父 `prd.md` 与 `design.md` 刷新其旧文档，范围未变不重新审批。

## 当前执行进度（2026-10-29）

- core-commands 独立 check 已修复13类缺陷；报告核心36项、目录18项、最终完整54项 unittest 均通过，compileall 与 help 检查通过。CLI optional handler 已在服务发现前分派并兼容 project 旧键。限制：结构校验不防同权限伪造、POSIX锁、交付路径需调用者完整声明、宿主/Node尚未集成；本子任务仍需父级整体检查与用户验收。
- core-commands 与 project-layout 的五份规划文件已按当前父契约刷新，上下文清单校验通过。
- 父 design.md 超过单文件自动注入上限；每次实施/check 派发必须明确要求补读全文，不能依赖截断内容。
- project-layout 独立 check 已修复10项问题，18项目标测试和编译通过；AC-10 又以隔离真实 CLI 子进程核验 fresh/repeat/incompatible JSON/--user/--dry-run/help，全部符合预期。AC-01–10 当前均有检查证据，仍随父任务做最终集成验收。
- workflow-content 独立 check 已修复10项问题，新增6项测试；12/4/11/5 清单、描述限额（合计888字符）、映射/标记提取、核心集成夹具与纯读不变量均验证。保留限制：固定提交模板全文与许可核验未完成（结构化改写+署名，非逐字复制）；语义正确性为静态审阅，宿主行为留待 runtime/e2e 证据。
- 整文件模式（mode:"file"）跨模块缺陷已由核心检查者修复：persist 接受顶层 mode 键、snapshot/freshness 按整文件哈希判定、覆盖规则适配，新增往返与失效回归。最终全套 79 项测试在实际 Python 3.9.6 上通过，compileall 通过。核心/目录/内容三子任务实现与独立检查均收口，未单独归档，随父任务整体验收。
- runtime-hooks 规划刷新完成：4 语义 hooks、宿主事件映射标记为实施期实测、被动簿记/显式报错矩阵、注入预算与指纹、核心 API 边界重算；fstar.runtime 命名与 dispatch 模块分工明确；清单已修正为仅规范/研究引用并复验通过。
- runtime-hooks 与 runtime-dispatch 均已交付首轮代码，实施者报告专项53/42项、合并174项测试通过。事件名仅有本机二进制/schema/现有注册的观察依据，不等于本产品真实宿主事件投递通过；RD-I7实际派发/转向/中断仍未完成。
- 联合独立 check（2026-10-29）已完成并自修：统一为单一 harvest 回收路径（hooks worker-result 强制携带登记 payload 并委托 dispatch.harvest，宿主事件与 CLI 不会双记，重放防护任务持久化）；区分输入基线与期望输出（合法 implement/editor 写入不再一律 stale/conflict）；失败/取消保留协调者租约不孤儿化兄弟 worker；检查交接持久化；嵌套子任务路径匹配修复；`orphan` 收编为 dispatch 子命令（无新增顶层用户命令，恢复入口为 continue）；doc-change 输出 canonical `fstar.change.v1` 并保守保留受影响条目数据；worker-context 完整加载 implement/check manifest 所列适用规范正文；去掉 trellis-* 角色误映射。宿主能力矩阵已产出（10-27-runtime-dispatch/research/dispatch-host-capabilities.md），按 observed-schema/fixture-test/live-delivery 分级，live-delivery 目前 0 项——真实宿主内派发/转向/中断仍未验证，不得宣称 runtime 宿主验收通过。core file-mode 缺陷早已修复并新增真实 file-mode 回归，旧"在途"说明已清除。
- runtime 联合独立 check 已完成：修复17项缺陷（含统一单一 harvest 路径、输入/输出基线区分、重放防护、租约保留、handoff 持久化、orphan 收编为 dispatch 子命令等），专项113项、全套192项测试在实际 Python 3.9.6 上通过，compileall 通过。宿主能力矩阵已建立，live-delivery 为 0：真实宿主内派发/转向/中断留待 e2e-verify，runtime 子任务随父验收而非已宿主验收。两子任务旧 description 已刷新。
- tool-binding 独立 check 完成：核实重放防护不可被滥用、TOCTOU/符号链接拒绝、flock 两进程语义，修复 provenance 降级调用误记（真实工具名+fallback 标记）与观察时间字符串比较两处缺陷，新增3项回归。专项78项、全套270项测试通过，compileall 与隔离 smoke 通过。AC-01–10 均按实际代码核验。
- tool-classifier 独立 check 完成（2026-10-30）：修复7项缺陷，含 argv 锚定、宿主默认路径、错误地用 --version 证明能力、受限 PATH、宿主事实缺来源、来源标注和取消绑定后重复提案。专项51项、全量323项测试在 Python3.9.6 通过；编译与资源校验通过。MCP/skill真实宿主调用仍待e2e，不将fixture证明等同宿主验收。
- package-install 首轮实现已交付：Node 启动器/隔离 bootstrap/Python 安装器/资源解析/精确所有权/迁移与 doctor；cli.py 可选列表加入 installer（授权单行）。实施者报告安装器71项、Node 13项测试通过，本地 pack 及离线 prefix 安装隔离验证通过；全量489项中仅1项为 tools 测试名下对 install 命令的过时守卫（父命令面已授权），已交其所有者更新。真实限制如实保留：Codex 用户级路径未证实、模板原文/许可 unresolved、发布就绪 false。独立 check 进行中。
- knowledge-base 实施者曾因 API 限流中断，已恢复并完成交付：src/fstar/knowledge.py（约2900行）+ 95项契约测试 + knowledge-format.md 两个澄清小节（无新必填字段、无策略变更）。严格 fstar.knowledge.v1 解析、只读目录快照（无效文档为阻断性诊断而非静默缺失）、完整适用阅读与四层优先级裁决、精确授权提案（摘要绑定内容/路径/所有权/scope）、按所有者根的分组事务与显式可恢复提交。纯内部库：无 CLI 注册、无台账、无 QMD/搜索引擎。全量489项中仅 test_tools.py 的 install 守卫为跨所有者过时断言（父命令面已授权安装器六命令），交其所有者更新。
- tools 测试所有者已更新 test_tools.py 的命令面守卫：禁元组改为确实不存在的命令（bind/status/validate/verify/reminder），安装器六命令按父设计 §4.1 认可；专项80项、全量489项测试通过，compileall 通过。
- package-install 独立 check 完成（2026-10-30）：修复16项确认缺陷，含 pyc 混入 npm 包白名单、wrapper 不转发终止信号、externally-owned 同值 hook 可被卸载误删、hook 移除忽略 matcher 组、陈旧检测漏掉计划后设置增删、半提交元数据改为持久预写日志+逆向恢复、apply_plan 信任外部计划 JSON 的越根路径、.new 写入漏符号链接祖先包含检查、缓存校验缺自身清单身份检查、entry-index 重复安装降级与卸载丢项、空缓存按名删除用户自建目录、损坏 manifest 猜测删除、迁移回滚接受任意事务 ID 等；全部新增回归测试。专项安装器94项、Node 15项、全量515项在实际 Python 3.9.6 / Node 24.14.0 通过，compileall 与 npm pack 清单核验（注入 __pycache__ 哨兵后 tarball 仍 0 pyc）通过。真实 CLI 生命周期（install→update→doctor→uninstall）经 Node wrapper 在临时根全程 rc 0，doctor 12/4/4/11/5 健康，卸载精确移除自身4条 hook，项目根未动。AC-08 发布闸门如实保留：包名/命令占用未核实、模板固定提交原文/许可 unresolved、Codex 用户级路径 unknown、live-delivery 0；宿主 skill/agent 入口安装与 resolver 消费方接线为设计 §8 共享工作，未在本子交付。
- knowledge-base 独立 check 完成（2026-10-30）：发现并修复3项真实缺陷——(1) 仅索引编辑且无正文变更时绕过索引清单循环，可能整篇破坏性重写索引并发布（修复为联合遍历+新增防丢无关散文回归）；(2) 只读锁文件 PermissionError 裸泄漏而非 DomainError 封套；(3) delete/supersede/rename 可跳过 required_review 陈旧评估防线（修复为以当前字节哈希填充）。专项98项、全量492项测试在实际 Python 3.9.6 通过，compileall 与资源校验通过。AC-01–10 逐项核验通过。残余观察（非缺陷）已记录：严格类目录下非 .md 文件不加载；授权的显式索引删除是允许的同意边界行为。实施与独立检查均收口，未单独归档，随父任务整体验收。
- knowledge-base 规划已核对、清单通过并启动实施：严格 fstar.knowledge.v1 解析、只读目录快照、完整适用阅读与优先级裁决、精确授权提案、分组事务与可恢复提交；纯内部库，无新增用户命令，与安装包实施互不争写。
- 当前9个子任务有代码实现和独立检查记录（全部前置子任务收口）；e2e-verify 已完成清单填充并启动（planning → in_progress），规划刷新与实施进行中。，模板原文/许可核对、Codex用户级安装证据、真实宿主集成与父级验收仍未完成。
- 一次组合shell smoke被权限拒绝，未计为通过且不重试该被拒动作。已有独立检查证据不代表用户验收；父级整体集成与确认仍待完成。
- 用户决定（2026-10-31）：(1) 真实宿主验证（写 ~/.claude/settings.json 注册 hook、真实会话观察投递/派发以关闭 live-delivery=0）缓后执行，届时需单独授权；在此之前本地证据收尾继续，live-delivery 保持 0 如实报告。(2) persistent-task 的 task/evidence/lease/events 成员被 custom 裁剪时，安全机制（证据失效、租约、归档恢复、事件完整性）保持常开——裁剪仅 gate 面向用户的工作流消费入口，不削弱任务一致性与可恢复性；该边界按此执行，不再作为未决项。
- e2e-verify 本地阶段收口（2026-10-31，独立复查通过）：(1) 生命周期成员边界按用户决定固化——routing/continue/archive skill 明确 gate 的 workflow 消费入口与"安全机制常开"条款；修复 tasks.py 中断归档恢复分支被 archive 成员误挡的边界矛盾（恢复仅匹配 pending operation id + 目标归档根，伪造 op id 被拒，新归档仍需授权），新增边界回归与伪造 op id 回归。(2) e2e 子 prd.md 顶部加 superseded-terms 映射（七态/review-log/test-cases 审批/spec check/skillOverrides→交付等价物），不改需求语义。(3) S1 四个检查状态行改为真实子进程执行（passed/blocked/skipped 真实退出码+日志回读，not_run 设计性不执行），五态投影与父契约一致。(4) 版本注入审查确认基线 {path,sha256} 指纹路径全链路已交付（payload 校验→prompt 渲染→harvest 重哈希→evidence 失效），version-injection 成员仅门槛增强，execute skill 文本同步。最终基线：全量 662 项 Python 测试、15 项 Node 包测试在 Python 3.9.6/Node 24.14.0 通过，compileall 与资源校验通过。本地可实现的集成项至此收口；剩余验收缺口全部需要外部条件：真实宿主验证（用户已决定缓后，live-delivery 保持 0）、Codex 用户级安装路径、npm 名称核实、模板固定提交原文与许可。
- 四项外部条件验证全部完成（2026-11-01，用户按序授权逐项执行；证据：.trellis/tasks/10-27-e2e-verify/evidence/live-host-2026-11-01.md）：(1) **真实宿主（Claude 2.1.316）live-delivery 达成**——备份→dry-run→真实 install（4 hook 字符串 matcher 写入，其他键保留）→doctor healthy→真实 `claude --debug -p` 会话中 `bin/fstar-hook.cjs session-context` 以 status 0（1854ms）执行并注入完整 fstar session context（routing 指纹、扩展协商、grants `{}`、诚实"未初始化项目"报告）→uninstall 精确移除→settings 字节级还原→用户根清理。验证过程抓到并修复两个真实缺陷：**F1** hook matcher 原写数组，宿主只接受竖线分隔字符串（官方校验文案+运行时 `split("|")` 消费代码实证；修复 `_plan_host_settings` 序列化+回归测试）；**F2** launcher 无执行位致宿主 126 Permission denied（chmod 修复；installer X_OK 预检列为加固项）。(2) **Codex 用户级路径**——`~/.codex/hooks.json` 证实为真实用户级 hook 层（官方"loading hooks from both …hooks.json and …config.toml"警告原文），schema 与 CODEX_PLAN 完全一致（生成协议 schema 核对），信任模型为 `[hooks.state]`+trusted_hash 且首次使用需交互式 TUI 信任审查——headless `codex exec` 不运行未信任 hook（临时测试 hook 三种写法实测未触发，用户批准的实测）；installer 拒绝 Codex 用户级安装的决定维持，理由字符串已更新为真实约束（F4）。(3) **npm 包名**——`fstar-workflow` 未注册可用（`fstar`/`@fstar/*`/`fstar-hook` 亦空闲，近似名 fstarter/fstar-wangeditor 无关）。(4) **模板固定提交与许可**——源仓库 commit 674bea37 可达，prd/technical-design/profiles 三源文件确认存在；源仓库无 LICENSE 文件且 library.json license_decision=pending；fstar 模板经直接 diff 确证为结构性改编（非逐字）且逐份带出处标注。落地：package.json/resources/package-assets.json/build-package.cjs 的 source_ref/license_status 从 unverified/unresolved 更新为实证值（source-pending-adaptation-only），notes 记录核验日期与结论；version_report release_readiness 更新为实证状态（package_name_verified=true、codex_user_level=unsupported-for-unattended、live_delivery=claude session-context；release_ready 保持 false——发布仍为所有者决定）。最终基线：663 项 Python 测试（+1 matcher 回归）、15 项 Node 测试全过，manifest 73 文件哈希全一致，真实宿主环境已完全还原（claude 无 hooks 键、codex 无测试残留）。

(1) runtime-hooks——`inject.resource_root(project_root, user_root)` 委托 `installer.resources_root`（resolve_resources 的只读便捷封装），无 user root 时精确回 bundled（fresh 项目行为不变）；session-context/worker-context 以真实项目/用户上下文解析根，routing/role 卡实际从所选根注入；registration planner 命令改为引用包内 `bin/fstar-hook.cjs`（与 installer._hook_command 逐字一致，含引号规则），每条 hook 附 `launcher_installed`（按磁盘实际存在）与 `evidence: observed-schema|unverified-schema`，卸载提示改为 manifest 基线全值匹配语义（去掉 'command contains fstar.runtime' 子串建议），plan 条目显式声明 `semantic`，installer `_semantic_for_shape` 优先取显式键。(2) tool-classifier——`load_registry` 增加 project_root，包注册表根默认取 resolver 所选根（显式 package_root 仍覆盖供 fixture）；scan 不再固定 bundled registry。(3) 内容消费——AC-04 真实消费落地：A/B pin 下注入的 routing 正文与分类器消费的注册表逐字不同（fixture 实测），所选根过 `validate_resources`，坏 pin 报 `resource_integrity/resource_version_unavailable` 而非静默回 bundled。(4) help/entry-index——新增 `installer.entry_index_report`（读 `fstar.entries.v1` 后逐条核对磁盘，缺文件条目标 `missing` 并附说明，绝不声称已安装）；doctor entries 块改为该磁盘核实报告，indexed-but-uninstalled 条目产生 `entry_index_stale` 诊断并使 healthy=false；无索引时报告显式空（行为不变）。(5) 诚实不变量自检通过：resolver 读取零创建、latest/范围拒绝、symlink 缓存拒绝、真实 `~/.fstar` 未被无根调用触碰、FSTAR_USER_ROOT 下坏 pin 经宿主文本入口以 rc1 + 可读错误退出、hook 被动语义与预算/事件映射未动、fresh session-context 17ms。测试：新增 `tests/test_integration_wiring.py` 27 项（每行 a 无 pin 行为不变 / b pin 真实改变消费内容 / c 坏 pin 诚实报错三段覆盖），更新 test_hooks.py 1 条过时命令断言；全量 542 项（基线 515 + 27）在 Python 3.9.6 全过，compileall 通过，Node 15 项全过。真实限制如实保留：宿主侧 launcher 观察仍为 observed-schema、live-delivery 仍 0（e2e 待做）；help skill 正文未改（其"读索引再查实际文件"由 doctor/entry_index_report 提供机器源）；无 CLI `help` 命令（本就不在命令面）；模板默认消费方（doc/plan 产物模板）无运行时读取代码，pin 对其影响体现为安装缓存内容本身，无额外接线需要。

## 1. 执行序

| # | 子任务 | 优先级 | 前置 | 完成判据 |
|---|---|---|---|---|
| 1 | core-commands | P0 | — | 三态/归档命令、26字段schema、证据/租约/验收/扩展授权、原子写与来源边界测试通过 |
| 2 | project-layout | P0 | core-commands | 三级目录/配置/索引/init、主题规范与按授权创建产物，重复接入不覆盖 |
| 3 | workflow-content | P0 | 1,2 | 12 skills、4角色、11模板、routing、知识格式和模板映射校验通过 |
| 4 | runtime-hooks | P0 | 1,2,3 | 4 hooks 在两宿主实测；无 turn-context；无task时被动簿记安全跳过 |
| 5 | runtime-dispatch | P0 | 1,3 | 四角色原生派发/回收、依赖安全并行、写入交接、变更传导、最多1次重试、孤儿只读恢复 |
| 6 | tool-binding | P1 | 1,2 | 5契约、tools schema/解析、三层可用性、provenance与缺口语义 |
| 7 | tool-classifier | P1 | 6 | Python分类确定性可测，注册表/weak探针/手动残渣与安全扫描 |
| 8 | knowledge-base | P1 | 1,2,3 | 统一知识schema、context/references、索引/裁决、learn授权原子更新 |
| 9 | package-install | P0 | 2,3,4 | 安装/更新/卸载/迁移可恢复，资源/设置不覆盖，doctor按实际宿主报告 |
| 10 | e2e-verify | P0 | 全部 | 两宿主最小闭环、持久嵌套任务、五扩展组合与失败路径有真实证据 |

依赖优先于 P0/P1。#4/#5/#6/#8 在 #3 完成后可并行，#7 严格等 #6；#9 等 hook 注册形态稳定，#10 等全部。并行还必须满足文件/共享接口/配置写入不冲突；目录顺序、父子关系和优先级均不替代依赖。

## 2. 子任务开工与收工

### 开工

1. 读父 `prd.md` 当前范围与 `design.md` 对应契约，不以 research 历史正文覆盖当前规则。
2. 按当前契约更新自己的 prd/design/implement 与描述字段；移除七态、test-cases审批、review-log、5 hooks、13/11 skill 等旧要求。明确引用产品 `plan.md` 与父 Trellis `implement.md` 的区别。
3. 核实所有前置子任务的公开契约/交付版本；会影响范围/方案/拆分的真实未决项返回父规划，普通技术默认在子设计内决定。
4. 填充真实 implement.jsonl/check.jsonl 上下文；不得只引用会截断晚期决定的超大历史 policy。父 `design.md` 是自包含当前实施契约，应优先注入；再加载本子任务适用 specs/research 正文。
5. 用户对本第一版和十子任务已有实施授权。只在范围变化、新权限/外部副作用或真正决定冲突时请求新授权；旧文档刷新本身不重开审批。
6. 依 Trellis 子任务流程启动并实施；本父收敛工作不代替子任务启动。

### 收工

1. 逐项执行子 PRD AC 和本文对应验证，保存真实命令/结果/环境/版本，不把未运行或跳过算通过。
2. 独立 check；check 可在本任务范围直接修复生产/测试代码并复查，但不得改变已确认需求/方案。
3. 确认未私增顶层 task 字段、正常 phase、扩展包、skills/hooks/templates/roles/capabilities 或面向用户命令；确需改契约先更新父设计并按范围变更处理。
4. 回写本子任务落实的设计细节与证据；不要把技术实现默认升级成未经确认的产品范围。
5. 子任务完成保留在父 subtasks 树，不单独归档；父整体收尾时整树归档。

## 3. 各子任务验证

### #1 core-commands

- task.json 顶层键集合严格等于设计 §4.2 的26项；拒绝旧 `review[]`、doneAt、七态值和正常 dropped phase。
- create/start/accept/drop/archive/state show/continue、extension、review/evidence、acceptance status 及结构化错误符合 §4.1；无任意 state set。
- start 绑定启动授权及当前指纹；accept 缺用户来源、独立check通过、新鲜交付或子任务条件时拒绝；正确来源可完成。
- 模拟同权限 Agent 写 `confirmed_by:user`：测试只能证明来源核验拒绝不完整/不匹配记录，不写成CLI能安全阻止shell伪造。
- 修改需求条目、生产代码、测试或共享配置使相关证据 stale；无关条目不全篇失效；哈希不能替代语义覆盖检查。
- events普通项超过200压缩摘要、里程碑仍保留；租约30m及回报续30m；接管保留旧/new holder和原因。
- 原子写并发/中断/损坏恢复、路径穿越、归档目标冲突与同操作重试有测试。
- blocked/dropped/revive/replan 通过收敛命令面完成，来源与处置完整；不存在实现者自写自解捷径。

### #2 project-layout

- 空项目、已有项目、重复init分别验证：只建授权骨架、已有资料优先引用、不覆盖；工具包未启用也可接入。
- 用户/项目/默认配置按事项合并；local/runtime与git边界正确；已有ignore规则不被强改。
- 已有项目全局探索类型/栈/模块/权威文档；零项目缺背景时复用对话并询问，不捏造技术选型。
- 生成用户/项目索引不复制正文；topic记录Applies to/读取条件/权威路径；新增主题有理由。
- 最小闭环不创建.fstar元数据；单独规划评审授权可写评审产物而不隐式task.json；产品任务只建plan.md不建implement.md。
- knowledge仅context/references，无decisions/history/journal/workspace；嵌套subtasks与整树月归档布局正确。

### #3 workflow-content

- 清单严格：12 skills、4 roles、11 templates、5 package IDs；archive命名，无finish/recall/ui独立skill。
- routing只含调用前判断：五包、一次一个、拒绝无新事实不重问、plan自动、最小节点、意图路由；无归档巡检到continue/每轮hook。
- 默认最小闭环实际派implement再派独立check，主Agent不写生产代码；三底线均成立。
- doc写作全部派editor，版本绑定与旧稿冲突返回；clarify/plan/check/research/learn/init各自维护产物。
- plan含ECC骨架、ID/来源/依赖/优先级/并行/验证；review确认后无额外plan批准。
- check指引允许自修生产/测试、按影响复查并最终整体验证；无test-cases审批前置，报告五态/基线/耗时。
- 知识格式、语言规则、规范读取/写作、learn授权/冲突/原子索引指引一致。
- 模板映射更换标题/ID写法后可解析；缺槽位清楚报错，不猜批准。prd/design来源提交和design章节调整有引用。
- 每个description≤200字符，12个描述正文≤2400；不把名称/分隔成本或字符混称token。

### #4 runtime-hooks

- 在 Claude Code/Codex 当前实际版本分别记录可用事件及输入；无等价事件时验证边界回退并报告，不虚构支持。
- session-context在start/clear/compact等价事件注入routing和当前数据；无turn-context、无每轮归档提醒/完整工具扫描。
- worker-context完整注入适用规范与版本/指纹；超限显示未加载清单，worker补读后才执行。
- worker-result完成/失败/取消只登记交付并路由检查/debug，不写acceptance。
- doc-change只做幂等指纹/stale/event/传导提示；不跑测试、写报告或递归处理派生文件。外部编辑由核心边界重算覆盖。
- 无task.json时被动任务簿记跳过不落盘；明确CLI缺上下文仍报错。

### #5 runtime-dispatch

- adapter使用宿主原生Agent工具完成implement/check/research/editor，CLI dispatch仅准备/登记，不声称单独shell能派当前会话Agent。
- 每轮含task/session ref、plan项、baseline、版本/指纹、allowed paths、上下文、验证和返回条件；结果核对同一dispatch/baseline/授权范围。
- plan中满足依赖且无写入/共享资源冲突的implement并行；同范围交check后implement暂停，无冲突项继续。
- 对话/文件变更统一消息；支持实时转向则确认送达，否则检查点停止并重派；旧结果留历史不算当前通过。
- 派发失败自动重试最多1次并携前因，仍失败进入debug；环境阻塞不循环。
- 会话中断后continue只读展示孤儿/遗留产物，用户决定接管/重派/放弃；不能假报恢复原worker。
- editor限定doc文件/条目且提交前检查baseline；check可修生产/测试；角色越界被拒或显式报告。

### #6 tool-binding

- 五契约结构完整且判定要点可探测；ui不进入第六契约。
- tools.yaml schema、项目>用户>默认的按事项覆盖、strong/weak/none与确认来源测试。
- 三层验证分别报告，最小真实调用按维度选择安全动作；缺口/降级不自动安装或改绑定。
- capabilities[]只存实际维度/工具/版本/依据，不与extensions[]混写。

### #7 tool-classifier

- 固定输入快照两次分类结果相同（排除detected_at）；AI不在分类路径。
- 注册表strong、未注册探针weak、未命中进入手动候选；用户registry优先。
- PATH/MCP/skills探测失败隔离；未知工具不执行其任意自述命令；读权限/超时/坏配置有明确结果。
- init/显式scan才全扫，session只做轻检查；未确认不写binding。

### #8 knowledge-base

- fstar.knowledge.v1必填/枚举/类型校验；superseded和unreviewed不加载，非法值报错。
- enforced rule > 项目明确spec > default rule > confirmed memory；冲突显式说明，已有项目权威文档优先。
- rules/memory/spec统一格式且英文规则正确；context/references按项目语言，不误套同一正文schema。
- 候选内容/来源/归属展示；明确授权不重复问，未确认/拒绝/暂缓不生效或反复催促。
- 正文+索引+引用原子更新；同文件并发排队；修正/替换/淘汰/重命名同步引用。
- `task list --archived`动态展示做过什么，无history文件；回忆不自动恢复任务。

### #9 package-install

- 全新安装、重复安装、更新、卸载、损坏恢复、迁移失败回滚均验证；项目/用户内容不被删除。
- 资源基线与CLI/resource/schema版本分离，项目指定资源版本实际可解析，不默默用latest。
- 用户改资源默认保留并提供覆盖/.new；hook设置追加/去重，卸载只精确移除自身条目。
- 两宿主生成各自单一入口，支持skill时不额外造同义别名；help入口索引与实际安装一致。
- doctor区分实际可观察listing与估算，检查12 skills/4 roles/4 hooks/11 templates/5 capabilities及schema/routing；不能通过伪造skillUsage“修复”。
- auto_commit=false；任何git操作需用户显式发起，不把安装等同git初始化。

### #10 e2e-verify

执行 §4 清单；每项记录宿主版本、项目fixture、真实命令/交互、期望/实际、证据路径、通过/失败/阻塞/跳过，修复后重新执行受影响项并最终整体回归。

## 4. 集成验证

| # | 检查项 | 通过标准 |
|---|---|---|
| 1 | 最小闭环 | 未init任意目录完成澄清→implement子Agent→独立check→修复复查→用户确认；无fstar元数据但允许必要产品文件写入 |
| 2 | 三态 | 仅planning/in_progress/completed；checking/fixing/待验收为角色/证据/派生显示；archive非phase |
| 3 | 完成来源 | Agent/worker done不能完成；缺/错范围/stale用户来源被拒；报告不承诺同权限shell不可伪造 |
| 4 | 回规划与一般修改 | 根本方向变化回planning并全部stale/释租；一般fix留in_progress；用户话语不明才澄清 |
| 5 | 证据失效 | 条目级与交付基线精准/保守失效，旧历史保留，不把文档哈希当实现正确证明 |
| 6 | 父子聚合 | 目录体现归属；依赖单独表达；子节点未全终态不能整体验收，全终态也仍需父整体验收 |
| 7 | 租约/孤儿 | 30m/续30m、单写者、takeover记录；跨会话只读报告等用户决定 |
| 8 | 归档 | completed+子树+新鲜依据+无未决后整树月归档；重试不覆盖；相关新需求新建任务 |
| 9 | 归档提醒 | 仅archive完成后运行；状态/时间依据/缺项/暂缓去重可见；不阻塞或自动归档其他任务 |
| 10 | 扩展协商 | 五包独立、一次一个、full/custom有效、拒绝不重问、中途加载保留有效工作 |
| 11 | 授权分离 | extensions与capabilities schema及行为互不混写；包授权不替代安装/绑定权限 |
| 12 | 26字段 | 顶层键严格匹配；events软200里程碑保留；无历史review[]/doneAt/顶层dropped字段 |
| 13 | 文档单源 | doc仅prd/按需design；无test-cases/review-log；clarify/plan/research/check各自归属 |
| 14 | 模板 | 恰11份；用户模板显式mapping，缺槽位报错；更新不改旧评审产物 |
| 15 | doc并发 | editor绑定讨论/baseline，旧稿不能覆盖；check独立一致性检查；文件改动传导/失效 |
| 16 | plan执行 | 当前有效来源展开；依赖/并行/写入约束成立；plan进度单写；无额外审批 |
| 17 | 原生并行 | 实际Agent派发，依赖安全任务并行，冲突范围串行；主Agent不写生产代码 |
| 18 | check自修 | 独立角色可修生产/测试、按影响复查且最终整体检查；需求变化返回clarify，未运行不通过 |
| 19 | 派发失败/恢复 | 最多1次重试；转向能力按宿主实际；孤儿不自动重派或假装恢复 |
| 20 | 4 hooks | 两宿主实测4项，无turn-context；无task被动跳过，显式缺上下文不静默成功 |
| 21 | 规范阅读 | 先全局概况/完整索引/约束，再完整适用正文与上下游；摘要/截断不替代条件 |
| 22 | 规范治理 | init按真实项目规划；learn先归已有主题；新增有理由；重复/冲突/链接/索引有检查 |
| 23 | 知识格式 | unified schema/语言/过滤/优先级；未授权候选不加载，原子索引更新 |
| 24 | 历史与回忆 | archived动态派生，无history/journal；recall为路由意图，continue仅当前任务 |
| 25 | 五能力 | 确定性分类、weak/strong、三层验证、绑定确认、缺口降级；无AI分类/自动安装 |
| 26 | init工具流程 | 初探只提案；包未启用仍接入；session只轻检，全扫非热路径 |
| 27 | 安装/更新 | 用户级跨项目资源、项目只数据；更新/卸载/迁移保护用户内容和设置 |
| 28 | listing/help | 12 descriptions限额/分层正确；doctor报告实际/估算边界；入口索引与安装匹配 |
| 29 | 语言/知识 | 对话/任务默认中文、skills/routing英文为主、rules/memory英文、specs默认英文可覆盖；无双份正文 |
| 30 | 来源/许可 | 模板固定提交和Trellis参考边界准确；实际复用资源保留来源并核对许可 |
| 31 | 非目标 | 自定义hook、第三平台、peer runtime、工作台、test审批包、UI资产等没有被偷偷实现成必需范围 |
| 32 | 整体回归 | 十子任务全部证据有效；共享接口修复后相关回归及全流程两宿主检查完成 |

## 5. 回滚点

| 子任务 | 回滚原则 |
|---|---|
| core-commands | schema变更必须升版本、备份迁移；代码回滚不能让新数据静默降级 |
| project-layout | 可重建安装器骨架，不删已有用户/项目资料 |
| workflow-content | 回滚默认资源不追溯改写任务/知识 |
| runtime-hooks | 精确撤销自身注册项，不覆盖/删除用户其他设置 |
| runtime-dispatch | 停止派发并修适配器，不回退主Agent inline生产代码 |
| tool-binding/classifier | 代码/契约回滚不自动更改用户已确认绑定 |
| knowledge-base | 功能回滚不删除知识；索引失败恢复原组文件 |
| package-install | 卸载保留~/.fstar用户内容和项目.fstar；迁移用备份恢复 |
| e2e-verify | 验证产物无业务回滚；失败如实保留与重跑 |

## 6. 已定默认与子任务实测事项

不得将以下固定值重新列为产品未决：条目级指纹；events软200且里程碑永存；租约30m、有效回报续30m；派发最多自动重试1次；26顶层字段；12 skills/4 roles/4 hooks/11 templates/5 packages/5 capabilities。

子任务可按父设计 §9 实施默认：SHA-256与原子IO；事件封套/类型；meta内遗弃/关联/提醒；归档提醒默认30天和暂缓7天（可配置且明确这是技术默认）；配置语言键；模板映射语法；资源缓存与哈希。实测宿主事件/转向/取消/权限/恢复，发现缺口明确降级，不把假设写成功能保证。

以下才触发父级重新收敛：实际宿主无法满足核心实施/check分离；确认的资源清单无法安装；26字段或命令面无法承载已批准需求；许可事实要求改变复用范围；用户明确改变产品范围。普通库选择、函数/API内部形态、测试框架、文件拆分由子任务按契约选择。

## 7. 父任务收尾

1. 十子任务全部完成或经用户明确drop，子文档均已按当前契约刷新。
2. §4 的32项集成验证有实际记录；失败/阻塞不伪装通过，修复后有受影响回归与最终整体检查。
3. 父 `design.md` §9 技术默认已落实或明确保留为真实限制，无研究旧规则进入实现。
4. 实现与当前 prd/design/implement 一致；超大历史 policy 不作为唯一注入源。
5. 用户对整体交付验收；命令记录可核验来源，同时如实说明批准防伪的权限边界。
6. 归档前衔接learn候选但不强迫沉淀；满足条件后主任务整树归档，并在结果后执行其他长期未归档任务提醒。

### 收口记录（2026-11-02，用户验收后归档）

- 十子任务 + 新增 `11-01-host-skill-adaptation` 全部完成；父 §4 集成验证有实际记录（evidence/live-host-2026-11-01.md + 11-01 任务 implement.md）。
- F1-F6 全部有结论：F1/F2/F4 已修并有回归；F3 观察记录；**F5 已关闭**（宿主侧 skills/agents 适配安装实现 + 真实宿主双实锤：12 skills 出现在会话 skill 列表、4 agents 实弹派发按定义运行）；F6 记录为格式级改进候选（不阻塞）。
- 最终基线：676 Python + 16 Node 全绿；package-assets.json 73 文件 0 hash 不一致；真实宿主环境字节级还原（settings.json sha256 bd2695cb…，skills 340 条无 fstar，~/.fstar 仅剩 runtime/）。
- 保留的真实限制，不伪装通过：Codex live-delivery=0（交互式信任审查才能关闭）；release_ready=false（发布由用户决定）；`.trellis/spec/` 仍为 Trellis 模板未填充（项目事实源为 docs/project-context.md 与任务文档）。
- 用户验收：2026-11-02 明确同意归档。
