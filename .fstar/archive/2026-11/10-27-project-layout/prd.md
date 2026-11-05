# 目录结构与初始化

## 目标

为 fstar v1 提供安全、可重复的项目接入与配置读取。项目保留自己的权威文档和真实结构，用户内容跨项目复用；任意目录下的最小闭环无需初始化，也不产生工作流元数据。

## 依据与当前事实

- 最新确认以父任务 `research/policy-decisions.md` 为准，尤其 2026-10-29 的 init、索引、语言、知识格式决定及 2026-10-28 的三态 / 26 字段决定。旧研究正文冲突处仅作历史。
- 当前没有 fstar 产品代码。首批实现采用 Python 3.9 标准库、`src/fstar/` 布局，Node 包装与宿主安装由后续子任务承接。
- 用户已批准 v1 实施；本轮仅刷新本子任务五份规划文件，不运行 start、不写产品代码、不操作 Git，不重复申请已批准范围。
- 本文件及 `design.md` / `implement.md` 是开发本产品的 Trellis 产物；未来 fstar 产品任务执行计划名为 `plan.md`，两者不混改。

## 范围与需求

### PL-01 按需初始化与数据边界

- 显式项目初始化只补齐 `.fstar/index.md`、`config.yaml`、`.gitignore`、`.schema-version`。缺失时创建，已有文件不覆盖、不截断、不静默迁移；重复执行保留身份与内容。
- 用户级初始化须明确请求，仅补齐用户根的 `index.md`、`config.yaml`、`.gitignore`；不预装个人规则、记忆或默认模板，不因项目初始化顺便建立用户目录。
- 安装包承载程序和默认资源；用户根承载个人内容及覆盖；项目 `.fstar/` 只承载数据。项目初始化不写宿主 skills、角色卡、hooks、命令、AGENTS.md 或 CLAUDE.md。
- `runtime/`、本机配置及本机身份文件不入库。新建 `.fstar/.gitignore` 提供规则；已有忽略文件不修改，缺规则则清楚报告。`specs/`、`knowledge/` 等持久内容不默认忽略。
- 初始化不生成任务、租约、运行状态、归档、工具绑定、Git 仓库或提交。最小闭环不调用初始化，也不创建上述元数据。

### PL-02 配置优先级与类型

- 从低到高固定为：安装包默认值 → 用户 `config.yaml` → 用户 `config.local.yaml` → 项目 `config.yaml` → 项目 `config.local.yaml`。
- 嵌套映射递归合并，标量和列表整体覆盖；不拼接列表，不把字符串强制转换为布尔或数值。输入对象和磁盘文件均保持原样。
- Python 标准库实现明确界定的 YAML 子集；支持/不支持语法、重复键、类型冲突、空值、错误位置均有确定规则，不能宣称支持完整 YAML。损坏配置不得静默当作缺失配置。
- 语言配置统一为 `language.interaction/artifacts/specs`，默认 `zh-CN/zh-CN/en`；rules/memory 固定英文，由知识契约而非独立配置键控制。技术符号与 schema 键不翻译，不生成双语副本。`auto_commit` 默认 `false`。

### PL-03 根据项目事实规划接入结构

- init skill 先了解项目整体目标、类型、技术栈、模块、已有文档与约束，再形成适用的主题职责、目录建议和索引。已有对话明确的信息直接复用。
- 空项目缺背景时由 skill 澄清；确定性 CLI 不发起 AI 调研、不推测技术栈，不把未定选型写成规范。低层 CLI 可先建立最小骨架并报告背景待补，不宣称已完成完整接入。
- 不预建固定空 `frontend/` / `backend/`。主题按实际适用范围归属，共享规则一处权威、多处引用；主题可拆目录，标识与入口保持稳定。
- 项目索引仅含短概况、主题标识/Applies to/读取条件/权威路径、长期知识入口和已有权威文档位置，并明确既有权威文档优先于 fstar 规范。用户索引导航 rules（含 strength）、memory（含 kind/trust）和定制入口，不复制正文。
- 默认读取已有权威文档并引用；改动已有内容属于另行明确范围的操作，初始化不得擅自迁移或重写。索引中未落盘的主题建议须显式标为规划，不伪造可用链接。

### PL-04 共享目录与后续集成

- 持久任务由 core 创建并管理，三态为 `planning/in_progress/completed`，`task.json` 权威字段数 26；归档是命令并整树移动到项目 `.fstar/archive/<YYYY-MM>/`。本子任务不重复实现状态机。
- 未来任务布局支持根 `clarify.md`、`plan.md`、按需 `research/`、`acceptance/check-<n>.md`、内嵌 `subtasks/`；规划评审包按需建立 `doc/prd.md` 与 `doc/design.md`。初始化不预建这些文件。
- 规划评审包即使未启用持久任务包，也可按已授权范围创建规划产物而不隐式生成 `task.json` 或租约；具体产物创建由内容/任务流程调用本子任务的安全路径能力，项目 init 本身不预建任务目录。
- 项目长期知识仅 `knowledge/context/` 与 `knowledge/references/`，不建立 decisions、history、journal/workspace；rules/memory/spec 共用 `fstar.knowledge.v1`，正文及模板由后续所有者维护。
- 首次工具探测为 init skill 的后续可选调用点：工具子任务可用时运行 L1/L2 并形成提案；探测不可用或未启用工具能力包不阻塞基础接入，不自动绑定或安装。

## 依赖与职责

- 本子任务拥有未来 `src/fstar/project.py`、`src/fstar/config.py` 及对应测试，提供 `initialize_project(path, user_root, ...)`、`initialize_user(user_root, ...)` 和 `load_config(...)`。
- `core-commands` 拥有 `src/fstar/cli.py`、包入口、任务数据和命令分派；按本子任务接口注册 `init`。双方可并行实现独立模块，CLI 集成在模块接口就绪后进行，无相互等待源码的循环依赖。
- `workflow-content` 拥有 init skill、正式索引/知识模板及语言适配；本子任务内置最小导航文本，不能依赖尚不存在的已安装资源才能初始化。
- `package-install` 拥有 Node 包装、宿主安装和升级迁移；`.schema-version` 的初始写入由本子任务执行，版本协议由双方共享。
- `tool-classifier/tool-binding` 提供可选扫描提案；`knowledge-base` 与 learn 负责后续知识及索引维护。

## 验收条件

- [ ] AC-01 / PL-01：空项目只生成四个最小文件；无已安装模板、无用户目录时仍可成功，用户目录保持不存在。
- [ ] AC-02 / PL-01：连续两次初始化输出第二次无新增；已有文件逐字节保持，project ID 不变；中断后重试只补缺失项。
- [ ] AC-03 / PL-01：用户显式初始化只补三文件，不生成 rule/memory 正文、宿主资源、runtime、任务或 Git 内容。
- [ ] AC-04 / PL-01：新忽略规则覆盖本机配置与 runtime；已有缺规则文件保持原样并返回可执行诊断。
- [ ] AC-05 / PL-02：五层同名/嵌套键、列表替换、布尔/数字/字符串/null 均有可验证结果；合并不修改输入，类型错误、重复键、非法 YAML 明确报错。
- [ ] AC-06 / PL-02：只读加载无项目、无用户配置仍得到默认语言与 auto_commit=false，不创建任何文件；缺失与读取失败不同处理。
- [ ] AC-07 / PL-03：已有项目样例索引引用真实权威文档并保留其原内容；多模块主题由提供的事实决定，不出现固定前后端空目录。
- [ ] AC-08 / PL-03：空项目无背景时最小骨架明确待补；提供事实后可首次生成完整导航；已有索引需由 skill 按明确范围更新，CLI 不覆盖。
- [ ] AC-09 / PL-01：受控目录符号链接、越界路径、文件/目录冲突、无权限及不兼容 schema 不导致越界写入或已有数据损坏；诊断包含路径及已完成/未完成项。
- [ ] AC-10 / PL-04：core 的 init CLI 能调用模块并呈现结果；工具服务与正式模板未实现时无硬依赖；最小闭环调用配置读取无落盘副作用。

## 非目标

不实现完整 YAML、AI 项目分析器、模板安装/更新、知识语义冲突裁决、单独 `spec list/spec check` CLI、用例评审文件、review-log 投影、自动绑定/安装、任务或宿主状态机。后续接入内容质量由 init/learn/check 的技能流程验证，不以目录存在代替接入完成。

## 权威引用

- 父任务 `prd.md`：当前产品范围和实施授权。
- 父任务 `design.md` §2.3/§3.11/§4.2–4.5/§9：自包含的当前目录、配置、索引、语言和子任务接口契约；与历史材料冲突时优先。
- 父任务 `implement.md` §2、§3 #2：子任务 kickoff、manifest 与 project-layout 验收要求。
- `research/directory-proposal.md`、`research/data-formats.md`：仅补充布局/格式研究依据；不得覆盖父 prd/design 的当前规则。

无待用户重新裁决的范围问题。尚未交付的上游资产与接口衔接列于 design/implement，不作为重复审批理由。
