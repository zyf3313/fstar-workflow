# 进展与未完成范围

## 后台学习

check-learning-trigger-001：A-001/A-005 整体未验证；隔离环境下角色、缺卡和接线的 31 项测试通过，session context 实际包含语义识别与后台派发指令，但没有宿主自然触发或归档端到端的证据。自然触发依赖协调者的语义判断；归档复盘覆盖依赖实际移交的来源。未发现已证实的功能缺陷，不能把指令存在当成行为通过。检查只读，未调用外部模型；受并行修改影响，基线以检查者记录的逐文件 SHA256 为准。同一检查者准备了隔离宿主自然触发测试，但自动审批以调用外部宿主模型与此前禁止外部模型调用的约束冲突为由拒绝启动；没有模型调用、成本为零，归档场景也未尝试。这是验证受阻而非功能失败，不能绕过审批；自然触发和归档行为仍未验证。

实施 dispatch implement-learning-001，修复 repair-learning-001。新增 learn 角色及资源版本11。独立检查 check-learning-001 发现缺卡静默成功及skill/role约定冲突；check-learning-002确认两项已修复，265项针对性Python和16项Node通过。代码检查通过不等于交付完成：check-learning-live-001 在隔离宿主通过 --agents 注入真实角色卡，观察到 run_in_background、async_launched 和 completed，证明显式派发可在后台返回；未覆盖自然触发、真实安装和完整 skill 加载。缺卡场景 launcher 直接调用 exit 1，但宿主未呈现错误且无 hook 执行事件，不能区分未执行或非阻塞。check-learning-live-002 首轮 blocked：官方文档称 PreToolUse exit 1 为非阻塞错误（本地 CLI 版本较旧，仍需实测）；夹具中项目级 skill/agent 及 hook 观察包装已尝试写入但未确认存在；Bash 步骤因安全分类器超时未运行任何模型验证（预算 0/2 已用）。hook 是否执行、skill 暴露、缺卡时协调者可见结果均未确立，不能宣称宿主闭环已通过。

更新：check-learning-live-002 在隔离快照用 hook 观察标记确认：有效资源 hook 实际运行 exit 0；旧代码缺卡 exit 1 被宿主视为非阻塞而照常派发；改为缺卡 exit 2 后宿主以 is_error 阻断并把 role_card_unavailable 传回协调者，未启动 worker、未重试。该修复（runtime/__main__.py 缺卡时返回 2）及 tests/test_worker_hook_failure.py（SHA256 24a6be47…）已在主工作区。未覆盖：语义自动派发、真实全局安装、Codex 等其他宿主。

check-planning-001 failed：fstar-learn SKILL.md 把全部流程知识限定在项目 references，与 A-003 冲突；A-004 计划协议本身通过（38 项针对性测试）。repair-scope-001 已解除写入，按范围分流修复（项目流程 / 用户明确跨项目流程放 user rules 或 memory / 范围不明不写入），测试须全部使用临时用户目录。

check-worktree-001 passed（仅对其快照有效）：52 项单测通过，真实 linked worktree（project-shared）10 项场景通过。未验证：project-local、user-directory 两种模式下的真实 worktree，以及 worktree 中的知识写入、验收、归档路径。该检查曾在真实 ~/.fstar/runtime/projects/6f0467… 下误留 lock 与会话指针，用户已自行删除并已核实；之后的检查须使用临时用户目录。

repair-scope-001 complete：fstar-learn SKILL.md 仅改两处流程段（284d5c… → 98fbe129…），新增 tests/test_user_procedure_scope.py（ee83e6f4…），src 未改。针对性 50 项中 48 通过；tests.test_learning_role 2 项因资源清单未重建报 resource_integrity，属预期，待统一重建后复跑。check-scope-001（独立检查该修复）与 check-worktree-002（project-local、user-directory 真实 worktree，以及 worktree 中知识写入、验收、归档路径）已在后台派发，均为只读并强制使用临时用户目录。资源清单用 npm run build:package（scripts/build-package.cjs）重建，须等两项检查结束、确认无需再修复后执行。

check-scope-001 passed：A-003 分流正确，未新造 user/procedures，其他资源中没有残留“流程全归项目”的表述；新测试经 bridge 子进程实测，47 项通过；test_learning_role 的 2 项失败确认只因清单中 SKILL.md 指纹未更新（manifest 中唯一不匹配的条目）。检查提出的措辞观察已核实：HEAD 中“No project-governance grant covers…”和“Use after project-governance authorization”两句在更早的修复里就已改写，其语义保留在授权段；当前授权段与 2ecaeff 快照逐字相同，本次修复只改了两处流程段。观察项不阻塞交付：跨项目读取的否定断言是按构造成立的，没有真正压测过滤逻辑；真实 HOME 守卫只比较 mtime。

check-worktree-002 failed，确认两项缺陷：(1) tasks.py 的 _branch_candidates 按 checkout 根去重，同一物理任务被扫描两次，project-local 和 user-directory 模式下 locate 误报 ambiguous；(2) store.py 在 project-local 模式下，若 Git 跟踪了 .fstar 骨架但没跟踪 storage-mode，worktree 会被误判为 project-shared，task create 在 worktree 本地另起数据，doctor 只能事后报 split。已通过：两种模式在干净 worktree 下的数据根、锁、checkout 根、branch 和 worktree 记录、会话指针、冲突保护；worktree 中的知识 prepare 和 apply；验收和归档（内部 API 模拟）。已派 repair-worktree-002 修复。
该检查违反只读约束：自行运行 build-package.cjs 改写了 resources/package-assets.json（新 SHA256 6a909472…），还有若干 node、python、fstar 调用没有隔离。真实 ~/.fstar/runtime/projects 前后的条目名称不变，但条目内容未核实。协调方已核对改写后的清单：64 个条目与现有文件全部一致；与 HEAD 相比只新增了 resources/agents/fstar-learn.md，resource_version 从 10 改为 11。它在违规重建后的环境里跑出的全量 1078 项通过，不作为验收证据。

repair-worktree-002 第二轮（部分完成）：tasks.py 改为按解析后的 fstar_root 去重；store.py 新增 ensure_writable_layout，接入 transaction、write、set_current、clear_tree_pointers、knowledge.apply_change 和 recover_changes、crossproject 多项目锁、installer 的 migrate 和 rollback、initialize_project。指定的 5 个模块 71 项通过。协调方在隔离环境下跑 tests.test_branch_location，发现 2 项 ERROR：用 --force-separate 显式分离的 worktree 也被守卫拒绝写入，这属于回归。已定的产品语义：显式分离是合法的，必须能写入；守卫只拦截非显式造成的身份不一致。第三轮要求在显式分离时持久化一个只绑定该 worktree 的标记，守卫识别后放行，doctor 报告中要区分显式分离；完成后跑全量 Python。已知剩余风险：公开的 register_user_directory_project 被直接调用时不受守卫保护，仓库内唯一调用方 initialize_project 已先调用守卫；本轮只在 docstring 写明前置条件。

repair-worktree-002 第三轮完成：force_separate 初始化成功后，在 worktree 的 Git 私有目录写入 fstar-separate.json。该标记绑定 checkout 路径、数据根、存储模式和项目 ID，并校验 gitdir 的反向引用；守卫只在标记与当前布局完全匹配时放行。doctor 新增 explicit_separate 标识，判定逻辑不变。test_branch_location 的 2 项回归已修复；在隔离环境下跑全量 Python，1083 项通过，0 失败。交付 SHA256：store.py f36014af…、project.py 8971fda9…、installer.py 9776e513…、tasks.py 579a4d0d…、knowledge.py 0e2da1ff…、crossproject.py 9b138bbe…、test_worktree_identity.py 9b7a95d0…。协调方核对资源清单：清单中 6 个 python 源文件的指纹已过期，但全量测试没有因此失败，说明完整性检查可能不覆盖 python 文件。这一点要在重建清单后确认，不能把全量通过当作清单是最新的证据。剩余风险：标记写入失败时，初始化前面已完成的写入不会回滚。已派 check-worktree-003 做只读独立检查，指令开头明确禁止运行 build-package 以及任何未隔离的调用。

check-worktree-003 failed（遵守只读和隔离约束，没有改动文件，SHA256 前后一致，真实 ~/.fstar 条目名称集合不变）。已通过：缺陷 1 的去重；缺陷 2 中分裂布局下 task create、set_current、learn apply（session-only 和持久任务）都在写入前失败，快照不变，doctor 和读取仍可用；显式分离标记的复制、逐项篡改都会被拒绝，标记不被 Git 跟踪，doctor 显示 explicit_separate；三种干净布局不被误拦；临时副本中全量 1083 项通过；清单中 6 个 python 文件的指纹已过期，再次确认。确认的问题：Git 跟踪了共享骨架的干净 linked worktree 在 Git 不可用时无法新建任务，因为 store.py 约 209 行的 git ls-files 失败后，被约 224-226 行改报为 worktree_data_conflict（该 Git 检查不在 HEAD 中，属于本任务新增）。未验证：transaction 外直接 write、clear_tree_pointers、crossproject、migrate、rollback、recover、rebind 在分裂布局下的专项拒绝测试；doctor 判定与修复前是否逐项等价；性能未量化。已派 repair-worktree-003：Git 不可用时仍拒绝写入，但改报新的错误码 worktree_layout_unverifiable，并补上述入口的专项测试。

repair-worktree-003 完成：Git 无法执行、ls-files 失败、git diff 执行出错时，改抛 worktree_layout_unverifiable；git diff 返回 1（存在实际改动）、未跟踪数据、符号链接三种情况仍抛 worktree_data_conflict。新增 test_split_identity_blocks_direct_write_entry_points，覆盖事务外 write、clear_tree_pointers、cross_project_locks、migrate、rollback_migration、recover_changes、rebind_registered；新增 test_git_failure_is_unverifiable_and_does_not_write，用隔离的 PATH 真正隐藏 Git。TaskStore.rebind 在该布局下会先返回 rebind_requires_user_directory，因此没有单独测试。守卫没有加事务内缓存，同一事务可能重复调用 Git。隔离环境下全量测试 1085 项通过。交付 SHA256：store.py 0c82321f…、test_worktree_identity.py 7047df5e…。已派 check-worktree-004 做只读独立检查，重点包括边界情况（HEAD 不存在）以及 rebind 是否留下绕过守卫的路径。

check-worktree-004 failed（只读、隔离均守住，七个源文件的 SHA256 前后一致，真实 ~/.fstar 条目名称集合不变）。已通过：以下四种情况都报 worktree_layout_unverifiable，快照不变——Git 完全不可用、ls-files 返回 2、diff 返回 128、真实删除 worktree HEAD；已跟踪文件被修改、出现未跟踪文件、出现符号链接时都报 worktree_data_conflict；代码对 diff 返回值 0、1、其他非零严格区分；非 Git 目录和三种干净布局都不会被误拦；临时副本全量 1085 项通过。确认的缺陷：TaskStore.rebind（store.py:797）只在 transaction 中检查 source，没有检查 target，却在第 828 行和第 832 行写入注册表和目标指针。从合法的 user-directory 项目 rebind 到冲突的 project-local worktree 时返回 rebound: True，并创建了目标指针；project.py:788 的入口也会走到这里。另外，测试的快照辅助函数只覆盖普通文件。已派 repair-worktree-004：在写入前对 target 调用守卫，排查其他接收目标路径并写入的函数，补三项测试，并把快照扩展到目录和符号链接。随后 check-learning-live-002 通过标记确认缺卡 hook exit1 实际执行但宿主继续派发；repair-learning-002 将特定 PreToolUse 缺卡错误映射为exit2。check-learning-live-003 独立活体复测通过：派发被阻止，协调者收到原因，无再次尝试；另31项针对性测试通过。证据见 checks/check-learning-live-003.md。自然触发、真实全局安装与最终集成版本仍未验收。全量1061项Python通过的是修复前版本，不可冒称当前最终全量结果。

repair-worktree-004 完成：TaskStore.rebind 在事务及任何锁创建前检查目标布局；扩展快照覆盖目录和符号链接，新增冲突目标、Git 不可用和干净目标成功重绑定测试。实施者报告隔离全量 1087 项通过，store.py SHA256 55fac048…，test_worktree_identity.py 262b81eb…；尚非最终版本验收。检查后与写入前的并发竞态未测试，公开 register_user_directory_project 仍要求调用者预先检查。已派独立 check-worktree-005 复查目标守卫与影响。

check-worktree-005 failed：独立复现三项问题：(1) 干净 linked worktree 重绑定返回成功但随后写入被冲突守卫拒绝；(2) 显式独立目标的 pointer 和注册表被静默覆盖，标记随之失效，两条 rebind 路径均需核对已有身份；(3) 目标 pointer 是目录时报错前已修改注册表，source pointer 也可能变化。5 项定向测试通过但未覆盖成功后写入；扩展套件 61 项出现 3 个 NameError 子项，dispatch.py 当时正在并行编辑，不能归因于 worktree 修复。快照基线 store.py 55fac048…、test_worktree_identity.py 262b81eb…，独立检查无交付写入。依据 fstar-debug 已要求原实施者先分类根因、保护独立数据并修复，之后重新独立检查；并发竞态和崩溃持久性仍未验证。

fstar-repair-005 完成：两入口 rebind 在写入前拒绝身份分裂目标（worktree_data_conflict）、外来或非文件指针及模式不一致；同身份和普通目录重绑定成功且可写；I/O 故障按字节比对回滚，恢复失败报 rebind_recovery_failed。协调方隔离复跑定向 168 项中 165 通过，3 个 unreadable pointer 子用例失败；在隔离环境实测 doctor 退出 1 的原因是过期资源清单（resource_integrity），并非指针处理回归。随后协调方重建资源清单（resource_version 11，64 条目）并隔离全量复跑 1102 项全部通过，Node 打包测试 16 项通过；真实 ~/.fstar/runtime/projects 仍为 2259 条。已知限制：竞态仅对同一协作锁有效，进程/机器崩溃无持久化日志保障。修复后哈希：store.py 4ab9f743…、test_worktree_identity.py 14ab506b…。尚待独立复查竞态与崩溃限制及两处修复的最终整合。

spec-context 第二轮修复（安全审查超时警示下需人工核实）：正文按哈希校验进入 payload/prompt，来源绑定（user_root/checkout 变更即 input_unverifiable），worker 回执 read_context 记为 worker_reported 而非已证明，缺失回执判 stale；持久证据记录 user_root，删除或换用户目录即失效；selection_reason 不允许为空。修复后哈希：dispatch.py 201dbf7b…、evidence.py 7c45267c…、execute SKILL.md cf6f91bc…、test_dispatch_context.py d08871dc…。实施者定向测试曾通过，但最终合并测试输出丢失；协调方隔离复跑 dispatch/context/crossproject/worktree/storage 定向 168 项（含上述 3 个清单过期子用例），重建清单后全量 1102 项通过。尚未做独立复查；真实宿主语义派发与 worker 实际读取仍未验证。

## Worktree

implement-worktree-001 已修复 user-directory 的 worker plan路径 ValueError（使用identity_path），204项关联测试通过。已新增 checkout_project_root、identity_root 及共享任务库解析，三个真实 Git worktree 场景覆盖已提交元数据/归档副本、跨树任务读写与执行分支、分支规范差异及独立本地任务冲突；实施者报告扩展回归409项通过，尚未独立检查。仍需补齐 locate 的稳定会话身份、无分支规范时来源提示、installer/doctor入口统一、project-local/user-directory跨checkout场景及知识写入目标验证。已要求实施者继续处理这些缺口。已有学习改动须保留；不允许真实数据迁移、删除或覆盖。

## 规划文档实施与整合

implement-planning-001 报告规划资源已实施、模板与授权定向测试通过，尚未独立检查。tests.test_content 的两项学习协议断言失败，已要求实施者核实是否为旧字面契约或真正缺失，不允许仅删除断言掩盖问题。资源清单按协调要求暂未生成，相关 resource_integrity 失败须等各写者结束后统一构建并复测，不能算通过。

## 规范读取与确定性步骤

check-spec-script-001 failed A-006：普通派发允许空 read_context 且 prompt 省略，未形成从索引选择、正文加载到派发与核验的闭环；用户目录文件因必须是项目相对路径而不能走带指纹的 read_context。A-007 整体未验证：已有选择加载与已提供指纹核验等机制，但缺少集成和覆盖清单。隔离环境中 253 项组件测试通过，不代表宿主端到端或最终验收。检查只读，逐文件哈希前后一致；日志还出现 crossproject 锁文件 ResourceWarning，原因未检查。implement-spec-context-001 已交付 context 选择加载入口、项目/用户根路径及指纹、缺失/预算延迟报告、worker 上下文和持久证据新鲜度检查；实施者报告定向 120 项及 1 项 worktree 测试通过。较广 storage 测试中有资源清单过期相关错误，另有安装退出码 2 未独立定位，须统一重建后复查。check-spec-context-002 failed：独立复现已加载正文未进入 worker prompt；持久证据只存项目相对路径，换 checkout 后可能校验错误分支而把过期证据判新鲜；未启动 worker 且无输入回执的结果仍可被记录 valid，故实际读取不能声称已验证。120 项定向测试通过但未覆盖上述问题；已要求原实施者修复正文与哈希绑定、源 checkout 绑定和诚实呈现未验证状态，再独立复查。并行 worktree 修复期间不得把不稳定输入当作最终验收。

修复交付后协调方隔离重跑定向 123 项 OK（crossproject.py:111 project.lock ResourceWarning 仍在，未定位）。check-spec-context-003 passed（P-002 / A-006、A-007 本范围）：基线 dispatch 201dbf7b…、evidence 7c45267c…、execute skill cf6f91bc…、test_dispatch_context d08871dc… 起止一致，store.py 4ab9f743… 与 test_worktree_identity 14ab506b… 复查期间未变。独立复现确认：完整正文进入 worker prompt 并与哈希及源根绑定，篡改、无正文、缺绑定、空 selection_reason、新旧混合载荷均被拒；持久证据绑定实际 checkout/用户根，两 checkout、真实 linked worktree、删除源、换用户目录均判不新鲜；无回执为 not_reported/stale，伪造回执仅为 worker_reported 且标注非读取证明；crossproject 旧载荷保持 not_applicable/valid。另跑存储模式全部 34 项、worktree、验收/e2e/知识、core/hooks、项目/内容等共约 650 项 Python 测试及 Node 包测试 16 项均通过。未验证：真实宿主派发中 worker 是否实际读取正文；同项目字节一致副本的适用条件未验证：后续隔离探测中，身份根或数据根不同的副本被判为不新鲜，不能笼统声称其按内容判新鲜。存储模式中依赖资源清单的用例此次通过；协调方此前执行过资源清单重建及会重写清单的 Node 包测试，不能将清单变化归因于单一检查者；最终集成时须重新核实。整体验收仍待 worktree 重绑定修复独立复查及统一全量回归。

check-worktree-006：独立只读检查中，重绑定专项 10 项和 6 个额外场景通过，覆盖两入口、成功后写入、身份冲突及故障回滚；三种模式的外来 worktree 冲突均被拒绝。更广的 90 项回归出现 4 failures、4 errors，部分明确是资源清单过期，install 退出码 2 等其余失败尚未独立定位；因此整体检查未通过，待最终重建后复跑。协作锁无法保证非协作写入的安全，逐文件替换不提供崩溃后的多文件事务恢复；未做竞争或断电测试。A-003 整体未在此项检查中验收。

check-spec-context-005 failed：现代回执缺 root 已正确拒绝，但畸形回执的短 root/path/sha256 仍可复制任意内容到诊断和持久证据；长内容、额外字段、数量上限和非列表处理通过。implement-spec-context-006 删除诊断中的不可信字段值。check-spec-context-006 独立只读复查通过该范围：短字段和正文未出现在会话输出或持久证据；数量上限、显式 root 和旧载荷兼容通过，定向测试 126 项通过。该结论不代表 A-006/A-007 整体验收；worker 回执依旧只是其自行报告，不能证明实际读取。

check-learning-host-001（协调方真实宿主验证，非独立检查）：经用户明确授权，用 Herdr 桌面端在 AgentWorkspace 空间临时副本中运行真实 Claude 会话。自然识别长期约定、遵守授权边界均通过，但协调者始终在主会话内联处理，未自动派发后台 fstar-learn 子 agent；干净环境（仅新版 routing）下会话已引用该派发要求且确认角色可用，仍未派发。真实仓库与 ~/.fstar 前后逐文件一致。A-001 的自动后台派发在该场景不满足。归档复盘未验证，需已验收测试任务，不能伪造用户确认。证据见 checks/check-learning-host-001.md。

implement-learning-dispatch-001/002：按真实宿主失败强化“识别长期约定后先派发后台 fstar-learn”的说明，新增每次提示注入的派发要求，并把提示压回既有 ≤12 行约束。静态独立复查 check-learning-dispatch-002 通过 206 项。随后在隔离宿主复测观察到 `Backgrounded agent`，主会话在子代理运行时继续回答，后台完成后提示，未声称持久保存（check-learning-host-002）。该复测使用项目级新版 hook 并屏蔽全局旧 hook，非真实全局安装。

归档复盘仍未验证：完整归档需要有效的持久任务 archive 授权、用户对具体归档的确认和已验收任务；已有归档样本只能作为复制模拟，不能当作真实未归档任务，且复制后仍需授权。为避免继续用虚构交付反复验收，协调方停止了该路径。

check-spec-context-005（第二次派发，原始报告 checks/check-spec-context-005.md）：——诊断有界不复制正文（对抗用例含容器类型字段、超长正文、15/30 条非法，输出均无正文且 <2KB）；modern context 缺 root 拒绝、root 严格 project/user、legacy 无回归；文本一致性疑点解除（1720 行 "omitted root means project" 指载荷条目，回执条目另行要求显式 root，二者不矛盾）；crossproject 锁修复 33 项通过。发现 F-1（中）：test_dispatch_context 的 linked-worktree 证据用例确定性 ERROR——setUp 在写 config.yaml 前构造 TaskStore，补写 config 后 _check_writable_layout 抛 worktree_data_conflict；根因在 store.py 身份观测或测试构造顺序，待修复定位。回执部分通过不代表 A-006/A-007 整体通过。已派 check-worktree-rebind-007 独立检查 rebind 交付（store.py/project.py/test_worktree_identity），并入 F-1 定位；A+B+C 身份切换锁实施待该检查基线确认后派发。

F-1 修复（implement-F1，同 rebind 实施者）：归属判断为测试构造顺序问题——真实项目 config.yaml 总是先于 TaskStore 写入，"store 打开后外部改身份须拒绝"语义对真实威胁正确，不放宽。仅改 tests/test_dispatch_context.py（用例内写完 config 后以相同根重建 store，a883555d…），store.py/project.py 未动。验证：test_dispatch_context 12 项 OK（协调方隔离复跑确认；前次"126"系三模块合跑总数，非该文件）；test_worktree_identity 36 项 OK；对抗确认外部 aaa→bbb 改 config 仍抛 worktree_data_conflict，守护未削弱。遗留：DispatchCase 其他用例若在 store 存活期改写 config 有同类风险（目前仅此一例）。

check-worktree-rebind-007（原始报告 checks/check-worktree-rebind-007.md）：rebind 交付通过与设计要求一致——写入前拒绝身份分裂、条件性回滚仅限自己写入字节（外部并发编辑保留并报 rebind_recovery_failed）、无夸大安全声明、锁身份按 identity_root。定向 36/36、storage_modes 34/34、project 14/14、user_directory_resolution 8/8 全过；检查期间见到的 F-1 ERROR 为修复落地前状态，已另行闭环。遗留（转入 A+B+C 或记录）：C cross_project_locks 拿锁后不复查（后续任务核心）；B init 全程无锁（后续任务核心）；E record_explicit_separate_worktree 重复抛裸 FileExistsError（低）；D 窄场景——worktree 含被跟踪的 main 侧 .fstar skeleton 时 force-separate 无出路（低，待用户决定是否新增认领命令）；A 锁身份已处理。

A+B+C 身份切换锁实施（implement-identity-lock-001）已派发：A 切换锁（新旧身份锁排序、超时、锁后复查、runtime_root 贯通）、B 注册表锁后于项目锁、C 跨项目拿锁后复查布局。D（认领遗留 worktree 新命令）按用户决定暂缓。

implement-identity-lock-001 已交付（协调方隔离复跑三模块 79 项 OK）：project.py 58dbffca…（A：_transition_locks 排序去重非阻塞 flock+截止、锁内复核前置后数据/注册/marker 同组、runtime_root 贯通三入口）、crossproject.py ca37518e…（C：cross_project_locks 锁后逐 store _check_writable_layout）、B 在 project.py user-directory 分支项目锁先于 _rebind_registry_lock。store.py 未动。新增 7 项竞争测试（等待在飞事务、锁超时零写入、部分失败后旧 store 全拒、runtime_root 共享锁、注册表锁顺序、跨项目锁后复查及其正向路径）；实施者报告 worktree_identity 41、crossproject 24、project 14、全量 1115 项 OK。D 未引入，无夸大安全声明。

check-identity-lock-001（原始报告 checks/check-identity-lock-001.md）：A+B+C 全部通过——静态逐行核对与设计一致；7 项新测试断言真实（零字节变化、LOCK_NB 探测项目锁已持等）；对抗用例（反序双锁 0.51s 超时无挂起、dry-run 无锁、转换与注册表锁并发无死锁、正向放行）通过；六模块回归及全量 1115 项 OK 与实施者一致；基线 8 项起止一致。仅 1 条低级备忘（lock_timeout 时空锁目录已建，零数据写入，不构成缺陷）。身份切换锁范围结案。遗留待办：D 待用户决定；E marker 重复裸 FileExistsError 低级未修。

## 发布前最后步骤

全部交付项已独立检查通过（回执修复、锁超时关闭、F-1、rebind、身份切换锁 A+B+C）。剩余：在稳定文件集上统一重建 resources/package-assets.json（此前 21:45 的重建违反流程约束，须最终重新生成）→ 全量隔离回归 + Node 包测试（含会重写清单的 test_package.cjs，最后跑）→ 最终影响检查 → 用户确认后进入合并发布流程。

2026-11-27 收尾执行：写入方全部结束（53 文件两次采样哈希稳定）；确认 21:45 清单已过期（project.py/crossproject.py 两入口过时）后在真实仓库统一重建（b8a186da…，rv11，64 项）；全量隔离回归 Python 1115 项 OK、Node 16 项 OK（test_package.cjs 最后跑）；此前受清单影响的 e2e/storage_modes/installer 185 项定向复跑 OK。日志 /tmp/fstar-final-regress.nTCu7h/。清单重建后无失败用例，此前 34F/167E 全部归因清单过期成立。剩余：最终影响检查与用户确认。

遗留 D/E 决定（2026-11-27 用户采纳协调方建议）：D（认领 0.11.3 遗留分离 worktree 的新命令）不加——无出路场景极窄（仅 worktree 含被跟踪 main 侧 .fstar skeleton 时 force-separate 被拒，且行为为明确报错的 fail-closed），普通遗留场景 init --force-separate 已实测可解；加命令等于显式豁免防护，前置条件多、写错风险大，留待真实案例出现后按研究方案（本地 project_id 异于 main、布局健康、marker 冲突语义等六条前置）单独立项。E（record_explicit_separate_worktree 重复抛裸 FileExistsError）不修——低级、仅直接 API 调用可见、经 CLI 重复 init 已被 WORKTREE_IDENTITY_EXISTS 拦截；修复需再走完整实施+检查+清单重建+回归，不值得拖发布。两者记录为后续任务候选。

check-final-impact-001（原始报告 checks/check-final-impact-001.md，只读）：跨功能影响核对七项全部通过——普通非 linked 项目零影响、旧调用方（旧 payload/旧 evidence/两任务路径/ROLES 扩 5）不被破坏、锁超时语义无回退且 ResourceWarning 清零、跨项目锁后复查与 rebind 拒绝语义正确、清单 64 项逐条一致、dispatch×transaction×身份组合自洽。抽样复跑 427 项全过。三条观察（无缺陷级）：①中低——user-directory 项目残留 project-shared 时代 .fstar 时知识/spec 读仓库残留、任务读 data root 的分裂读面（建议 doctor 后续报告，记遗留）；②低——tracked shared worktree 写路径每次 2-4 次 git 子进程的性能开销；③交付提醒——resources/agents/fstar-learn.md 及 5 个新测试文件为未跟踪但被清单引用，提交交付集时必须一并 git add。最终影响检查完成，等待用户最终确认后进入合并发布流程。

## 仍需完成

最终全量隔离回归已完成：Python 1105 项通过、Node 16 项通过。独立只读复查见 checks/check-final-003.md：多项判据仍有未验证范围，不能宣称整体通过；归档复盘、真实全局安装、宿主角色选择和实际规范读取、完整确定性流程，以及 worktree 崩溃、非协作并发和历史数据兼容仍有覆盖缺口。部分先前检查仅有本文件摘要，缺少 checks/ 下的原始报告。

2026-11-26 用户表示“验收通过 开始走合并发布流程吧”，这是对当前交付的验收及合并发布授权，不改变上述验证覆盖事实。协调方随后执行 `fstar start --confirm-user` 补记启动，工具事件来源显示 interactive-cli、用户角色、空引用；这并非用户在交互式 CLI 中亲自启动的事实，不能把该来源当作用户原话或直接操作的证据。内核等待验收转换因缺少已登记的合格最终检查而被阻断，尚未记录内核验收。发布前检查还发现 README 过时及旧独立 worktree 兼容性问题，正在处理。

## 发布前复查轮（2026-11-26 晚）

编号说明：本轮派发名沿用了 implement/check-spec-context-004、005，与上文已用的 005/006 重名；下文均指本轮，以哈希区分。

- 真实 linked worktree 端到端验证（协调方经 Herdr 创建，非独立检查）：真实宿主 worker 收到完整正文，两个 canary 及哈希复现；持久证据绑定实际 checkout，真实 linked worktree 可用，复制副本一律判不新鲜（更正上文“字节一致副本”的笼统说法）。验收/e2e 套件失败经临时副本重建清单后通过，归因为资源清单过期。验证用分支 `verify/spec-context-e2e` 及若干 /tmp 目录待用户同意后用非强制命令清理。
- 发现缺陷：回执 root 接受任意字符串；crossproject 锁超时时未关闭已打开的锁文件流（即上文 crossproject.py:111 ResourceWarning 的根因）。
- implement-004：锁超时路径用 try/except BaseException 关闭流（crossproject.py 33c86ba8…），新增回归测试且确认在旧代码上失败；回执改为字面 JSON 说明并增加 malformed_receipts 诊断。check-004：锁修复通过；回执仍有两处缺陷——诊断复制整个非法对象（无界、泄露正文，实测 10,499 字节含正文），以及缺省 root 被当作 project 接受。
- implement-005：诊断改为非数组只记类型、逐项只记 index 与原因码、上限 10 条并计 omitted；modern context 缺 root 拒绝。落地哈希 dispatch.py 38a8dd94…、test_dispatch_context.py 00192f6e…、fstar-execute SKILL.md 7a460a96…。实施者交接报告未收到；dispatch.py mtime 未随内容变化，原因未查。结果字段说明仍写“omitted root means project”，疑与显式 root 要求矛盾。check-005 首次派发零验证（检查者误判无工具），已重派。
- 约束违规：`resources/package-assets.json` 于 21:45:39 在真实仓库被重建（555a380b…，resource_version 10→11），来源未确定。该清单基于未稳定文件集生成，不能作为验收依据，最终须统一重建。
- 身份切换锁调研（fstar-research，只读）：`init --force-separate` 切换身份不加锁且锁路径随身份变化，持旧锁的 store 切换后仍可写入 main 数据根；`cross_project_locks` 加锁后不复查布局；0.11.3 遗留分离 worktree 无 marker 被拒且无出路，`record_explicit_separate_worktree` 重复时抛原始 FileExistsError。方案 A 切换锁（新旧锁排序、超时、锁后复查）、B 注册表锁后于项目锁、C 跨项目锁后复查、D 显式认领遗留 worktree 新命令。用户授权按协调方建议推进：实施 A+B+C；D 涉及新 CLI，暂缓待用户单独决定。已知局限：协作锁、按路径字符串区分锁身份（大小写不敏感文件系统、bind mount 等），记为遗留。A+B+C 将改 crossproject.py，待 check-005 回报后再派发，避免改动其基线。
- worktree rebind 修复：store.py f08c8b1d…（21:42）、project.py 91569a43…、test_worktree_identity.py f1866c5a… 已变化，交接报告未收到，尚未独立检查。
- rebind 实施者隔离日志（/tmp/fstar-repair-005.CSLP9T）协调方直接核对：定向 19 项 OK（12:59）；全量 1102 项 34 failures/167 errors（13:02）——该运行早于当时一切清单重建，失败大量为 resource_integrity（日志中 288 处），不能当作 rebind 修复的失败证据；log 中数字 1102/34/167 与日志一致，此前疑其无依据系误判。时间线显示 project.py 21:37、store.py 21:42、test 21:43 之后清单 21:45:39 被重建，且清单哈希与当前全部文件一致（含 store.py/project.py/execute SKILL.md），即重建发生在 rebind 最终改动之后、内容正确；最可能来源是 rebind 实施者运行了 build-package，违反“保持原样”约束，须向用户披露。test_unreadable_pointer…（0 期望 1 返回、空 stderr）等个别失败未分类，须在统一重建后复跑确认。
