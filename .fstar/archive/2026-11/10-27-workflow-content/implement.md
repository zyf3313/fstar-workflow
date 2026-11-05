# 工作流内容实施计划

## 实施进度（2026-10-29，trellis-implement 交付记录）

- WC-I1 完成：只读核对 core `EvidenceService.persist_artifact_map`（真实签名 `persist_artifact_map(ref, *, mapping, source)`，外壳为 `meta.templates.artifact_map = {artifact: {item_id: {start_marker, end_marker, dependencies[]}}}`，含 file 模式 `mode` 键）与 project-layout `ProjectContext/TopicReference/DocumentReference/initialize_project/initialize_user/load_config`。未修改 core/project/config 或其测试。登记差异：core 的 `_extract_item` 要求 marker 在全文恰好出现一次并按同一 ID 展开，content 的 marker/边界/重叠校验与其对齐；core dependencies 仅在单 artifact 内闭包追踪，因此 build 对跨 artifact 显式关联暂报 `CROSS_ARTIFACT_DEPENDENCY_UNSUPPORTED`，未发明第二持久格式。
- WC-I2 完成：11 模板 + 3 映射（`fstar.template-map.v1`，JSON 语法）+ 唯一 knowledge-format/document-checklist/profiles 已写入 `resources/`。源模板全文未能从固定提交 `674bea37cf2f6f25cd20dab93e1a54ae1f13ce66` 逐字获取（本环境已持久化的只有 personal-template-review.md 的结构核对摘要，未含许可核验后的可复制全文）；模板按已批准结构改写并在文中保留来源与限制声明，profiles 为宿主中立来源卡并同样声明非逐字复制。该项限制已在报告中上报，未发明“已复制”表述。
- WC-I3 完成：`src/fstar/content.py` 提供只读 `validate_resources/load_mapping/extract_artifact/build_artifact_map/validate_links`，Python3.9 标准库；不计算条目哈希、不写盘、不打印、无 CLI。
- WC-I4 完成：12 skills（英文主正文、中英双语 description）、4 角色卡（派发/返回字段对齐父设计 §3.7）、唯一 `runtime/routing.md`。
- WC-I5 部分：与 core 的同一 marker fixture 已以真实公共 API 集成验证（见 test_content.CoreIntegrationTests：content build → `EvidenceService.persist_artifact_map` → `snapshot` 哈希由 core 计算）。**blocked**：与 project/knowledge/package 的实联调未执行（对应模块尚未交付），未伪造集成结果；整文件模式经 core persist 的往返被 core 拒绝，属 core 接口不一致，待 core-commands 协调。
- WC-I6 完成（trellis-check）：独立检查、本范围自修并回归，结果见同目录 `check-report.md`。

实测结果：`PYTHONPATH=src python3 -m unittest discover -s tests` → 78 tests OK（原 54 + 本任务 24；其中 trellis-check 新增 6）；`python3 -m compileall` 通过；validate_resources 对 resources 根返回空诊断（smoke 通过）。本环境 `python3` 为 3.9.6，上述套件即在 3.9 上通过。

### 独立 check 记录（2026-10-29，trellis-check）

- 复跑：test_content 24 tests OK；全库 78 tests OK；py_compile/compileall OK；validate_resources 0 diagnostics。
- 修复：content.py 的 references separator/非法映射/占位符/必需单件资源/模板-映射成对提取校验；research/check/project-index 占位符声明；doc/check/init/learn/clarify/plan skill、editor/research 角色卡、routing 的缺口（debug 路由未覆盖等）。详见 `check-report.md`。
- **blocked**（未执行、不记通过）：project 索引接点、knowledge 加载/原子事务、package resolver/doctor、tool 扫描绑定、runtime hooks/dispatch、双宿主行为。
- **限制**：固定提交模板全文与许可未能取得（无网络/无本地克隆），模板为按批准结构改写并保留来源与非逐字声明；工作区非 git 仓库，无法用 diff 证明所有权。
- 整文件模式：content 输出与 core `snapshot` 读取一致，但 core `persist_artifact_map` 拒绝顶层 `mode` 键；属 core 所有权，未改 core。

## 当前状态与读取要求

本轮仅准备本目录 prd/design/implement 与两个 jsonl。已有第一版实施授权保持；未启动本子任务、未写产品资源/代码、未执行 git。以下复选项是后续实施工作，不能视为已经完成。

开始实施先读父 `../10-25-fstar-workflow-design/{prd,design,implement}.md` 与本子 PRD/design；**父 design 若注入截断，必须用 Read 补齐全文**，尤其后半的跨子任务接口/清单/默认值，不能用 policy 历史或摘要代替。jsonl 只列当前父契约与有针对性的小来源，源码由执行者按范围另读。

前置为 core-commands、project-layout。当前可以准备内容；集成前须核对它们实际交付 API，普通接口实现细节由所有者协调，不重复索取产品批准。backend spec 当前仍是待填模板，不宣称已有 lint/typecheck 命令。

## 实施顺序

| ID | 工作与完成判据 | 依赖/并行 | 验证及文档责任 |
|---|---|---|---|
| WC-I1 | 核对 core §5.1 marker/metadata 接口及 project §2 init/config 类型；确认资源根由调用方提供，登记真实接口差异。 | 首先；不得改 core/cli/project/config。 | 本子 design 同步实际接口；只读检查上游契约。 |
| WC-I2 | 从固定提交取 prd/design/profiles 全文、核对来源/许可，完成11模板及3映射；补唯一 knowledge-format 与 document-checklist。 | I1；模板与映射同一写者。 | 逐路径清单、默认章节、占位/链接、知识字段；profiles 不计模板。 |
| WC-I3 | 实现 content.py 只读 API、标准库受限解析、结构/路径/ID/槽位/关联检查、core artifact_map 窄适配；不计算条目哈希。 | I2 的语法/fixture 固定后。 | test_content.py 覆盖 T1–T5/T8；映射/错误规范更新 design。 |
| WC-I4 | 编写12 skills、4角色和唯一 routing，接入共享 checklist/知识参考；完成英文主正文与中英短 description。 | I1 后可与 I2/I3 分文件进行；共享语法先固定。 | T1/T6/T7/T9；语义 check 按 PRD AC，不靠关键词判正确。 |
| WC-I5 | 与 core 跑相同 marker fixture；与 project 校验索引字段/语言；向 hooks/dispatch/knowledge/package 提供内容 API 和清单。 | I2–I4、相关上游实际可调用。 | T4/T5/T8/T10；未交付依赖记阻塞，不 mock 成集成通过。 |
| WC-I6 | 本任务整体独立 check，自修资源/校验器后按影响回归；交付实测结果/未覆盖项及精确所有权。 | I5；检查范围交接后停止实施写入。 | 全部 AC、整个 test_content 套件；父 implement §3 #3/§4 的相关集成项。 |

产品代码在未来按父协议交原生 implement；本计划不启动任何执行者。主 Agent 单写 plan/协调进度，worker 通过回报更新；本 Trellis implement.md 不变成产品模板。

## 测试矩阵

| ID | 场景与可观察结果 | 所有者 |
|---|---|---|
| T1 | 精确集合=12 skills/4 roles/11 templates/5 package IDs；缺失、多出、重复命名失败；每 description≤200、合计≤2400，中文按字符计数。4核心自动、plan评审后自动、7按授权路由正确。 | content 单测+语义 check |
| T2 | frontmatter 缺字段/坏类型、未知占位、渲染后遗留必需占位、本地资源死链/越界 symlink 报可定位诊断；外链只校格式，不伪造网络可用性。 | content 单测 |
| T3 | 默认 prd/design 六槽位和 plan 条目可提取；改标题/语言/ID 写法及 explicit 自定义边界仍成功；缺槽位/空必需值/重复槽位/缺失或重复 marker/颠倒或交叠区间/重复ID/坏关联失败；reviewer空值可表达未评审，review_state 不推导 acceptance。 | content 单测 |
| T4 | JSON语法的 mapping.yaml 拒绝重复键/未知版本/NaN/可执行表达式/不支持 YAML；配对解析按任务>项目>用户>默认，选中层坏映射不静默降级；whole-file 模式必须显式且报告粒度。 | content 单测，resolver 集成由 package |
| T5 | 将 content 生成的 artifact_map 交 core EvidenceService；同一正文 LF/CRLF 核对 core 规范化；改单条仅其及依赖 stale；映射/ID删除报错；关联变化重新核对；整文件模式保守失效。content 不另算 sha256，不写平行元数据。 | core + content 契约集成 |
| T6 | 场景推演：无 .fstar 最小闭环实际要求 implement→独立check→修复→用户确认；五包独立、裁剪不破三底线、拒绝不重问、规划获准不暗建任务、自动 plan 无第二次批准；回忆不恢复历史。 | 语义 check；实际宿主留 runtime/e2e |
| T7 | doc 全部后台 editor、同文件排队、讨论/基础版本绑定、旧稿冲突返回；clarify/plan/research/check 自己维护所属产物；check 可修生产/测试、五态/实际证据/耗时、按影响复查及最终整体检查；实现者交接停止同范围写入。 | 语义 check；并发实测留 runtime |
| T8 | 三知识模板符合唯一格式说明；缺枚举/错类型负例；superseded/unreviewed 不加载的运行验证交 knowledge-base。entry 对齐 ProjectContext/TopicReference、真实引用、语言键；未生成目录不造链接、INDEX_PRESERVED不声称已更新。 | content 静态检查 + project/knowledge 集成 |
| T9 | init 探全项目/缺背景才问/无臆测规范；learn 先归口/授权不重复问/正文索引引用整组/暂缓不生效；仅 archive 提醒，continue/session无巡检；无旧phase、test审批、review-log、finish/recall/ui skill行为。 | 语义 check；真实事务归对应模块 |
| T10 | 模板升级不改已有文档/用户模板；来源提交/章节7影响范围、8配置、9附录正确；help/doctor使用真实资源索引。验证所有读取函数前后文件内容/目录集合不变。 | content 纯读单测 + package/e2e更新测试 |

负例不机械检测禁词：允许正文解释“不支持旧流程”，禁止的是新增旧入口/旧状态/旧审批前置。对图文关键条件、语义覆盖、规范适用范围和来源真实性人工检查，不把哈希或模板存在当正确性证明。

## 实际执行时的验证命令

在项目根执行；目前仅规划，以下命令尚未运行，也不预填通过：

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_content.py' -v
python3 -m py_compile src/fstar/content.py tests/test_content.py
```

Python 3.9 兼容性须在实际 3.9 解释器运行同一套件（如该解释器缺失，明确未验证，不用新版本 py_compile 冒充）。上游交付后运行其相关 core/project 套件及 T5 fixture；接口变化扩大受影响回归，稳定后无需反复运行无关全库检查。没有实际配置的 lint/typecheck 不写成功记录。两个宿主事件/派发/listing 的真实验证属于 runtime/e2e，静态内容测试不替代。

每项记录命令、环境/版本、实际结果、未覆盖原因与证据位置；未运行/失败/阻塞/跳过不能算 passed。检查报告写任务约定的实际位置，不为本次规划刷新新建报告文件。

## 交付、回退与依赖清单

- 本任务只写 `resources/{skills,agents,runtime,templates,references}` 中 design §2 精确清单、`src/fstar/content.py`、`tests/test_content.py`；不改 cli.py、evidence.py、project.py、config.py 或宿主设置。
- 对 core 交付 marker/ID/依赖提取，消费 core 当前 `meta.templates` 内 artifact_map 外壳；core 持有哈希、来源与状态事务。外壳/dependencies 实际类型须在 I1/I5 联调固定。
- 对 project-layout 交付正式索引/init 文本；消费 initialize_project/initialize_user/load_config 和 ProjectContext，不增加 API 内扫描工具行为。
- 对 runtime 交付12 skills/4 roles/routing/checklist，运行时负责真正后台派发、基线冲突拒绝和 hook 注入；两宿主能力尚待实测。
- 对 knowledge-base 交付唯一格式说明/3模板/learn 流程；权威 validator 和原子更新 API 尚须交付，不在 content 分叉实现加载器。
- 对 package-install 交付只读 validate_resources 与逻辑路径；资源 resolver、版本/hash、入口索引、安装映射/doctor 仍由安装器交付。来源模板全文与许可在 I2 实核。
- 工具扫描/绑定真实 API 由 tool-binding/classifier 交付；init/tools 保留调用边界与失败报告，不编造成功。

回退仅撤销本任务默认资产/代码；不追溯改写任务、知识或用户模板。若映射破坏兼容，停止产新证据、保留旧记录并修复适配，不静默退到猜指针/整文件模式。当前没有新增产品问题需要审批；以上为技术实施与集成交付依赖。
