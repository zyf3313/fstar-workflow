# 安装包实施计划

> 本文件是 Trellis implement.md；产品任务执行计划为 plan.md。2026-10-30 仅规划刷新，未 start、未实现、未 pack/安装/测试产品、未修改宿主设置或执行 git。

## 必读与前置

实施/check 完整 Read 父 `../10-25-fstar-workflow-design/{prd,design,implement}.md`（父 design 自动注入截断时补齐），再读本子三文档与 JSONL 所列规范/研究。历史七态、13 skills、5 hooks、16 templates、用例审批均非当前要求。父十子任务已授权，不重复审批。

实际代码定点检查（不放 JSONL）：cli OPTIONAL_HANDLER_ATTR/_register_optional/build_parser；config.load_config；content 的 SKILLS/ROLES/TEMPLATES/validate_resources；runtime registration.plan/__main__.main/inject.resource_root；dispatch.register_commands；classifier._resource_root；project schema marker。结构检索先 CodeGraph，源码仅在接口需要处补读。

已有前置交付允许开始包组合；knowledge API/schema 可 pending，不能阻塞 Node/Python 打包骨架。Codex 用户级惯例、共享 resolver 接入、来源/许可及真实宿主交付未完成时保留相应集成/发布阻塞，不能拿静态规划标通过。

## 文件所有权

本子独占拟建：`package.json`、`bin/fstar.cjs`、`bin/fstar-hook.cjs`、`bin/fstar-bootstrap.py`、`scripts/build-package.cjs`、`src/fstar/installer.py`、`resources/package-assets.json`、`tests/test_installer.py`、`tests/test_package.cjs`。构建产物只在临时 stage/pack 目录，不新增随意发布副本或文档树。

只读消费现有 src、资源正文、注册表和规范；不写 cli/config/project/core/runtime/dispatch/tools/classifier，不与 knowledge-base 抢文件。共享接入按 design §8 由协调者安排原所有者串行提交：installer optional 注册、resource resolver 消费、planner/launcher 与 help index 引用。若实际需修改超出上述路径，先报告最小差异和所有者，不顺手扩张所有权。

## 顺序与完成判据

| ID | 工作 | 依赖/完成判据 |
|---|---|---|
| PI-I1 | 核对现有公开 API/资源清单，冻结 package-assets 字段及 roots 注入；交共享接入清单 | 首先；明确 source/installed/data ownership，不以 runtime verified 为 live 证据 |
| PI-I2 | Node 启动器、可信 bootstrap、npm 元数据/白名单与 build；打包所有现有 Python/资源 | I1；任意 cwd、无 checkout/PYTHONPATH 的 CLI/hook/dispatch 入口；Python>=3.9 诊断 |
| PI-I3 | installer register_commands、纯 plan、root/path 校验、manifest/hash/index/version | I1；由协调者接通 CLI optional 注册后验证六命令，无项目可运行 |
| PI-I4 | 缓存导入与 resolve_resources，版本/兼容/哈希错误；共享消费者交接 | I2/I3；A/B pin 读取真实不同内容，无 silent latest；未接消费者则 AC-04 阻塞 |
| PI-I5 | 安装/更新/卸载事务与备份，默认保留、显式覆盖/.new、精确 ownership | I3/I4；fresh/repeat/modified/collision/interruption/concurrent-change 测试通过 |
| PI-I6 | 按实际宿主版本验证用户级约定，fixture 适配器合并/去重与入口索引 | I2/I5；先证据后写 adapter；Codex 无全局证据不得挪用项目 hooks.json；无真实设置改动 |
| PI-I7 | migrate 支持表、同版本 no-op、未知路径拒绝、备份/回滚 | I5；故障注入验证原字节与引用，不虚构生产 schema2；knowledge 接口独立联调 |
| PI-I8 | doctor/version/help index 契约，完整资源与 listing 诊断 | I4/I6；12/4/4/11/5 分层，observed/estimated/unknown 分开；无副作用 |
| PI-I9 | 隔离 npm pack→解包→入口 smoke→临时本地 prefix 链接验证 | I2–I8；白名单、helper、路径字符、stdin/out/status、pin、无真实根访问有证据 |
| PI-I10 | 受影响回归/全量验证、独立 check、所有权及发布缺口交付 | I9；AC 逐项五态、真实命令/版本/耗时/重跑次数；不以本地 pack 代替发布验收 |

I2 可与 I3 契约固定后的测试 fixture 工作分组，但本轮不派 Agent。共享文件变更先协调，交 check 后实施者停止写同范围；check 可修本任务生产/测试并按影响复查，无需用例批准。

## 测试矩阵

所有测试 TemporaryDirectory；环境显式设置 HOME、FSTAR_USER_ROOT、FSTAR_RUNTIME_ROOT、npm cache/prefix、host roots；项目为临时目录，PATH 受控。不能运行会自动读取真实宿主配置的工具，不能全局 npm install、联网获取依赖或改真实 settings。真实宿主版本核对属只读实施调研，宿主运行测试仅隔离 profile。测试驱动与解包内容分目录。

| 测试 | 覆盖与预期 | AC |
|---|---|---|
| T1 wrapper | argv 含空格/中文/引号/$()/分号作为普通参数；流透传、非零/信号、spawn error、Python 缺失/3.8 拒绝/3.9 可用 | 01 |
| T2 tarball | build 清单与 npm pack 列表一致，无开发私有目录/pyc；全 Python/资源/mapping/registry/schema 到包；无源码路径可见亦可用 | 01/07 |
| T3 helpers | packed help/version；内部 hook 向 stdin 输入 fixture JSON 得文本且 stderr/状态正确；机器 hook JSON 及 dispatch retry/prepare/harvest fixture 真实入口可达 | 01/02 |
| T4 fresh/repeat | 临时用户与两宿主支持 fixture 安装；重复零重复项；跨两个项目 cwd 使用同一 CLI，项目无宿主/程序副本 | 02 |
| T5 settings | 混合匹配器/多 hook 同组/其他权限 env 插件字段保留；同 command 不同 options 不误删；预先同值项不接管；坏 JSON/未知格式/TOML 不支持拒绝 | 02/03 |
| T6 ownership | 未改/已改/用户同名/用户 .new 冲突/未知 manifest；update keep/overwrite/new 行为及备份；uninstall 保留全部用户数据和已改条目 | 03 |
| T7 versions | bundle/cache A/B，各自 routing/template/registry 不同内容；项目 A 全局 B；缺失/不兼容/哈希坏/非法版本/同版本不同内容拒绝；旧缓存保留 | 04 |
| T8 transaction | 暂存/资源写/设置写/manifest 提交分别故障；并发用户设置变更拒绝陈旧计划；恢复不覆盖后续修改；锁竞争和重复操作安全 | 05 |
| T9 migrate | schema1 no-op；未知链拒绝；合成转换故障恢复 marker/正文/索引/引用原字节；重复 rollback 不重复破坏 | 05 |
| T10 doctor | 删除/增加/损坏资源与入口；四语义 hooks 不按事件行数计；listing 无观测只估算；schema pending 如实报告；调用前后所有根文件集合/哈希不变 | 06 |
| T11 containment | 越根/symlink/绝对路径注入拒绝；不删未拥有祖先目录；缓存 pin 不改变 tools.yaml/任务/已评审文档；auto_commit 默认 false | 03/07 |
| T12 release | 包名未核实、source/license unresolved、Codex 用户级 unknown、无 live-delivery → release-ready=false；不“绿色 pack 即可发布” | 08 |

## 实施期命令与证据

以下只供实施/check，规划时不执行。独立 fixture harness 负责生成临时目录和环境，所有输出归临时根：

- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_installer.py'`（源码单测；必须另做无 PYTHONPATH 包 smoke）。
- `node --test tests/test_package.cjs`：创建隔离 stage，调用 build；用列表 argv 运行 `npm pack --ignore-scripts --json --pack-destination <temp-pack>`，npm cache/prefix 也临时；检查 tar 清单再解包至独立空目录。无 registry 查询/发布。
- fixture 中从外部 cwd 调用绝对 `node <unpacked>/bin/fstar.cjs ...` 与 hook launcher，清空 PYTHONPATH、使用 -I bootstrap；需要 npm bin 链接时仅 `npm install --prefix <temp-prefix> --offline --ignore-scripts --no-audit --no-fund <local-tarball>`，不用 -g，不跑包生命周期脚本。
- `PYTHONPATH=src python3 -m unittest discover -s tests`；`python3 -m compileall -q src/fstar tests`。实际 Python3.9 环境必须记录，不能以高版本编译冒充3.9兼容。
- 资源校验复用 content.validate_resources，同时检查 capability/semantic hook/registry/schema 与 manifest；全量测试在最终共享接口接入后一次完整执行，缺口/变更再针对扩大回归。

每条证据记录 cwd/隔离根、Node/npm/Python/宿主版本、真实命令/状态、产物哈希、耗时/重跑及未运行项。observed-schema/fixture-test/live-delivery 分别列；本轮不预填通过，不把 manifest 声明当文件真实存在，不把 schema observed 当宿主验收。

## 收工、阻塞与回滚

收工交接口、文件所有权、npm tarball 内容、冲突/迁移恢复证据及父 implement #9、集成 #27–32 覆盖。source/license unresolved 是实际 release blocker；固定提交原文和许可需内容所有者核实后交接，不在包任务静默豁免。npm 命名核实、Codex 用户级安装路径与两宿主 live-delivery 仍需真实证据。knowledge API pending 不阻塞打包组合，仅相关 schema/迁移联调待交付。

本子回滚自己的程序/资源不删用户知识、绑定、项目数据；安装操作按事务备份恢复且保留并发新修改，npm 本体的替换由用户包管理操作负责。修改共享契约由协调者安排原所有者，不能为使测试通过私改 runtime/core/tools。子任务随父整体检查和归档，不单独归档；此次只交规划，不触发这些操作。

## 独立检查记录（2026-10-30，Trellis check，实施者已停止写入）

环境：macOS（darwin 27.0.0），Python 3.9.6，Node v24.14.0，npm 11.9.0。全部命令在仓库根、临时 HOME/用户/宿主/项目根内执行；未访问网络、未写真实 `~/.fstar`/`~/.claude`、无全局 npm 安装、无 git 操作。基线：全量 492 项（knowledge-base 收口后）。检查后：安装器专项 94、Node 15、全量 515，均 0 失败；`compileall` 通过。

### 实际命令与结果

| 命令 | 结果 |
|---|---|
| `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_installer.py'` | Ran 94 tests, OK |
| `node --test tests/test_package.cjs` | tests 15, pass 15, fail 0 |
| `PYTHONPATH=src python3 -m unittest discover -s tests` | Ran 515 tests, OK |
| `python3 -m compileall -q src/fstar tests` | COMPILEALL_OK |
| `npm pack --dry-run --ignore-scripts --json`（含注入 `__pycache__` 哨兵） | pyc/`__pycache__` 为 0；清单 70 文件全部在包内 |
| 打包/解包/临时 prefix（`--offline --ignore-scripts`，非 `-g`）入口 | CLI/`fstar-hook`/机器 hook/`dispatch retry` 可达 |
| 真实 CLI 生命周期（隔离根，经 Node 包装器）install→update→doctor→uninstall | rc 全 0；doctor 计数 12/4/4/11/5、4 条目、healthy；卸载后 4 条 hook 精确移除、项目根未变 |

### 逐 AC 判定（五态）

- **AC-01 通过（fixture-test）**：tarball 不含源码 checkout/PYTHONPATH 依赖；`-I` bootstrap 从任意 cwd 解析包内 `src`（已用伪造 cwd `fstar/` 包与 `PYTHONPATH` 投毒验证不生效）；argv 中空格/引号/中文/`$()`/`;` 逐字节透传（端到端至 Python 计划的 host_roots）；退出码 42/127 传播；子进程信号原样重抛；包装器自身收到 SIGTERM/SIGINT/SIGHUP 转发子进程后不再误报成功；Python 缺失(127)/3.8(unsupported)/3.9+(通过) 诊断真实。
- **AC-02 通过（fixture-test，宿主入口范围受限）**：fresh/repeat install 幂等，项目根保持空；其他 settings 字段（permissions/env/plugins/其他 hooks）逐项保留；未知/坏 JSON 拒绝写入；Codex 报 `host_unsupported` 且绝不写项目 `.codex/hooks.json`。**限制**：仅安装 hook 设置条目与资源缓存；用户级 skills/agents/手动入口未写（宿主全局路径未证实，按 design §6 不伪造），"每流程每宿主一个手动入口"仍待宿主人证与共享入口工作。
- **AC-03 通过（fixture-test）**：所有权取 manifest 全值（source+destination+canonical hook 全字段），无 path/名称/substring 推断；修改项默认保留、显式覆盖先备份、`.new` 冲突不覆盖；uninstall 仅删仍匹配基线且 `ownership=owned` 的项，保留用户改动/同名未拥有/外部同值 hook/歧义重复项；不 rmtree 用户/项目根（代码中无 `rmtree`）。
- **AC-04 基本通过（fixture-test，消费端阻塞）**：显式>项目 config>用户 version>bundled 逐级实测；`latest`/范围/非法版本拒绝；缓存按自身 manifest 校验（身份/路径/兼容/哈希/installed），绝不静默 latest、读取不建缓存；A/B 两版本内容不同；第二 bundle 版本 install 形成独立缓存、旧缓存保留。**限制**：routing/role/template/registry 消费者接入 resolver 属 design §8 共享工作，本子未接，AC-04 的“真实消费”仍待协调者。
- **AC-05 通过（fixture-test）**：写前加锁（flock，跨进程实测并发一成一 `installer_plan_stale`、无重复条目）；写前重读校验文件/设置（含计划后被创建/删除的设置文件）；逐文件原子替换；manifest/hash/version/cache-manifest/index 最后提交且由**持久写前日志**保护，任一阶段注入故障后反序恢复，保留事务后用户修改；崩溃遗留 journal 由下次 install/update 前恢复（`recover_pending`），doctor 只读报告 `installer_transaction_pending`，dry-run 仅告警不写。迁移：schema1 同版本 no-op、未知链 `migration_unsupported`、合成 v1→v2 失败恢复原字节/标记、回滚绝不覆盖迁移后新内容、事务 id 路径注入拒绝。
- **AC-06 通过（fixture-test）**：doctor 只读（调用前后根快照一致；根不存在时不创建），计数 12/4/4/11/5（hooks 按语义数），listing 区分 observed/estimated/unknown 且字符预算 2400；入口索引与实际条目一致（重复安装不改所有权、卸载保留被保留条目）；release readiness 全 false（名称未核实、source_ref unverified、license unresolved、Codex unknown、live-delivery none），本地 pack 不豁免。
- **AC-07 通过（fixture-test）**：所有测试仅临时根；无全局安装、真实设置变更、联网或用户数据删改。
- **AC-08 阻塞（真实阻塞，未豁免）**：包名/命令冲突未核实、模板固定提交原文/许可 unresolved、Codex 用户级路径未证实、两宿主 live-delivery=0；不宣称可发布或宿主演收。

### 本轮发现并修复的缺陷（含回归）

1. `package.json:14-23` 白名单目录包含导致 `compileall` 后 `.pyc`/`__pycache__` 进入 tarball（已用哨兵 pyc 实测复现）。改为显式 `src/fstar/**/*.py` 与 `resources/**/*.{md,yaml,json}`；回归 `npm pack excludes bytecode artifacts even when __pycache__ exists in tree`。
2. `bin/fstar.cjs:100-112`、`bin/fstar-hook.cjs:61-73` 未转发包装器自身收到的终止信号，子 Python 被遗留（实测 SIGTERM 后子进程存活）。新增 SIGTERM/SIGINT/SIGHUP 转发与监听清理；回归 `wrapper forwards termination signals to the Python child`。
3. `bin/fstar.cjs:58-60`、`bin/fstar-hook.cjs:38-40` spawn `error` 与 `close` 双触发可能导致重复推进/重复回调。加 `failed` 守卫。
4. `src/fstar/installer.py:649-656` `_owned_setting` 按 canonical hash 匹配到 `externally_owned` 记录，uninstall 会删除用户预先存在的同值 hook。改为要求 `ownership=owned`；回归 `test_uninstall_keeps_preexisting_identical_hook`。
5. `src/fstar/installer.py:1087-1101` 卸载钩子未校验 matcher 组，重复身份会任删一条。改为 event+matcher+全值唯一匹配，歧义时全部保留；回归 `test_uninstall_keeps_duplicate_ambiguous_hooks`。
6. `src/fstar/installer.py:904-916` 陈旧计划未覆盖“计划后设置文件被创建/删除”。改为比较 `settings_digest` 与现状（含 None 语义）；回归两条 `*_after_plan_is_rejected`。
7. `src/fstar/installer.py:718-896` 原回滚只覆盖文件/设置，manifest/hash/version/cache-manifest/index 已提交后失败会留下半成品。改为持久写前日志（逐条 fsync）+ 反序恢复；新增 `_recover_abandoned_transactions`/`pending_transactions`/`recover_pending`、doctor 诊断与 CLI 写前恢复；回归 `test_metadata_failure_rolls_back_files_and_metadata`、`test_rollback_preserves_edit_after_our_write` 及 `TestDurableRecovery` 6 项。
8. `src/fstar/installer.py:882-902` `apply_plan` 直接信任计划 JSON 的 destination/settings_path，可写出用户根外或改写任意 JSON。新增计划路径全量校验（目标必须等于对应版本缓存/宿主根，拒绝 symlink 越根）；回归两条 crafted-plan 测试。
9. `src/fstar/installer.py:938-940` `.new` 写入未检查 symlink 祖先。补 `_reject_symlink_ancestors`；回归 `test_write_new_refuses_symlinked_ancestor`。
10. `src/fstar/installer.py:351-387` 缓存校验未验证自身 manifest 身份/路径/兼容，且 symlink 版本目录会被跟随。补校验与 `cache_usable` 判定（strict 抛错、doctor 报问题）；回归 symlink/错版本 manifest 2 项。
11. `src/fstar/installer.py:1245-1260` 入口索引重复安装将自有条目降级为 externally-owned；卸载即使条目被保留也从索引移除。改为按计划 `owned` 与“实际移除”更新；回归 2 项。
12. `src/fstar/installer.py:1218-1243` 卸载按目录名清理空缓存，可能删除用户建目录。移除该清理，旧缓存目录保留（符合“旧缓存保留”）。
13. `src/fstar/installer.py:1300-1318` 安装 manifest 记录结构未校验，畸形记录会被当作所有权依据。新增 files/settings_entries 结构校验（损坏即 `installer_manifest_corrupt`，不猜删）。
14. `src/fstar/installer.py:1405-1412` `rollback_migration` 接受任意 transaction id（含 `../`）。改为 `mig-<10 hex>` 正则 + 根内校验；回归 `test_unsafe_transaction_id_is_rejected`。
15. `src/fstar/installer.py:488` manifest 记录可用同 source 声明另一 destination 冒充所有权。补 destination 一致性判定。
16. `bin/fstar-bootstrap.py:19` 点号模块名守卫 `"." in argv[0].split(".")` 恒为假（死代码），带点模块名可越过限制。改为 `"." in argv[0]`；回归 `test_bootstrap_rejects_dotted_or_dunder_module_names`。

### 未修复/真实限制（不豁免）

- 崩溃恢复为“下次事务前重放 journal”，无独立 repair 命令；直接调用 `apply_plan` 的外部调用方在恢复后可能先得到 `installer_plan_stale`（CLI 已在计划前恢复）。日志与备份目录不做 GC。
- 宿主 skill/agent 安装与 help 入口索引消费属共享接口（design §8），本子未写；AC-02/04 的宿主侧“真实消费”仍待协调者与 e2e。
- Windows 无 `fcntl`（锁依赖 POSIX），设计未要求 Windows；信号映射仅在 POSIX 实测。
- update/uninstall 的宿主根取 `--host-root`/默认真实位置，而非 manifest 记录的 settings_path；用非默认根安装后再次操作必须重复 `--host-root`，否则只会在默认根上无操作（不会误删），但可能与预期不符。
- 迁移仅 schema1（no-op）与合成转换测试；无生产 schema2，知识 schema 交接仍 pending。
- 证据等级：以上均为 fixture-test / 静态审阅；observed-schema 与 live-delivery 未新增，0 项。
