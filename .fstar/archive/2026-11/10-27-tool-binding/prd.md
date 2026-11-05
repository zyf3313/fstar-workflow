# 能力契约与工具绑定

## 目标与当前授权

落实父任务已批准的五能力契约、tools.yaml、逐项绑定解析、确认来源、三层可用性与调用 provenance。第一版十子任务已有实施授权；本轮只刷新本目录 prd/design/implement 与两个 JSONL，不 start、不写产品代码、不改 runtime、不做 git、不新增产品审批。

当前权威是 `../10-25-fstar-workflow-design/{prd,design,implement}.md`，尤其 PRD §5/§12、design §3.4–3.6/§4.1–4.5、implement #6/#7 与集成 #11/#25/#26。父 design 如被注入截断，实施和检查都必须 Read 补齐全文。研究稿只补充五维度判定及降级，不能恢复旧包数、code-text 第六能力、turn-context、AI 分类或额外命令。

## 依赖与所有权

前置 `core-commands` 与 `project-layout` 已交付并通过独立检查；`mode:"file"` artifact_map 缺陷已修复，runtime 开始前全套基线为 Python 3.9.6 的 79 项通过，无此旧阻塞。当前 runtime 联合检查与本次规划互不写入。

本子任务负责五契约、绑定 schema/解析/已确认变更、结构化缺口和 provenance 接口，预留 `src/fstar/tools.py`（或保持同一公开导出的 tools/ 包）及唯一 tools 命令注册。后续 tool-classifier 必须使用独立 `src/fstar/tool_classifier.py`，依赖本任务 API，不重复注册命令。本任务不实现完整扫描/注册表匹配/探针，不改 runtime-hooks/dispatch。

## 需求

### TB-01 五个契约

固定 `code-structure`、`web-research`、`knowledge-retrieval`、`data-access`、`test-execution`。每份含定义、可判定要点、三层验证、推荐实现、常见不合格实现、降级、记录要求。指标描述工具能做什么，不用产物质量冒充能力；UI 不是第六契约。

### TB-02 tools.yaml 与逐项解析

支持项目 `.fstar/tools.yaml` > 用户 `~/.fstar/tools.yaml` > 安装包默认推荐，按能力事项覆盖。项目只配置一项不得抹掉其他用户项；显式确认的空绑定遮蔽低层该项，缺键继承。默认推荐不能伪装用户确认或自动成为已授权绑定。缺文件与坏文件严格区分，未知版本/非法枚举/重复标识/悬空工具引用/未知能力必须定位报错，不能默默回退掩盖错误。

配置存工具标识、版本与分类快照、detected_at、绑定及确认/变更历史；当前可用性是运行事实，留返回结果或用户 runtime，不将本机路径、凭据与实时验证状态写入可共享绑定。更换机器须重新验证，配置存在不证明当前可用。

### TB-03 匹配与可用性独立

`match=strong|weak|none`；注册表依据或真实用户能力确认才可 strong；通用探针命中只能 weak，未命中 none。选中工具不自动提升 match，也不证明可用性。

分别报告 discoverable（可发现）、client_loaded（客户端加载）、minimal_call（真实最小调用）。每层区分 verified/failed/unknown，含时间、范围、证据或原因；未知不能写通过。仅配置存在不等于客户端加载；版本未知如实为 null。外部能力调用由宿主适配器提供真实结果，Python CLI 不假称能够直接调用会话 MCP/skill。

### TB-04 确认后才变更

扫描、解析、提案不安装工具、不建索引/集合、不改绑定。确认来源包含可定位用户输入、时间、原话或引用、目标作用域、精确变更和旧内容指纹。工具包启用、分类 strong、推荐排名均不替代绑定授权。已有明确授权直接复用，不重复审批；仅在成功提交确认后的变更时保存授权及历史，拒绝/冲突/失败不留“已授权/已变更”记录。声明式来源校验不是防止同权限伪造的安全隔离。

### TB-05 缺口与降级

输出能力、选定工具/来源、匹配依据、缺失层、失败/未知原因、建议出处及该能力降级路径。不得静默换低优先级工具、自动安装或把弱匹配当结构查询等价物。降级是否能完成任务由调用方按需求判断，不自动写 blocked 或通过验收。绑定操作说明继续归现有 `fstar-tools`。

### TB-06 provenance 与核心存储

仅实际发生的调用生成 provenance，保留能力/实际工具/版本/调用标识与来源/验证事实/结果及降级情况。`task.capabilities[]` 是调用事实，不是 `extensions[]` 授权；扫描候选与绑定提案不得写成调用事实。持久任务通过核心事务/校验/写入边界保存，不直接改 task.json；无持久任务只返回会话数据，不创建工作流元数据。调用成功不等于独立 check 或用户验收。

### TB-07 接口及技术约束

Python 3.9 标准库。复用 `config.parse_config` 的实际支持子集，复杂数组/对象使用 JSON flow 值，不新建通用 YAML 解析器。给 classifier、init、knowledge 与 installer 一个窄公共 API、schema 和可解析示例。唯一新增用户命令为父批准的 `fstar tools scan`；bind/status/validate/install 等不变成新用户命令。classifier 未交付时 scan 明确报告未就绪，不能伪造成功；分类交付后通过同一入口调用。`fstar-tools` 承接绑定指导与确认后的内部 API 调用。

## 验收标准

- [ ] AC-01：恰五份七段契约，判定可观察；各维度最小验证与降级具体，不将数据写入或任意项目测试当安全探针。
- [ ] AC-02：schema 和示例经实际 parser 解析并语义校验；复杂 flow 数组可往返；不支持的块映射序列明确给迁移提示。
- [ ] AC-03：项目单项覆盖、其他项继承、显式空绑定遮蔽、默认仅推荐均可验证；工具元数据不跨层混成虚假记录。
- [ ] AC-04：缺文件返回 missing；空/非法/不可读/编码错误/坏 schema 分别报错；不忽略坏高层配置。
- [ ] AC-05：strong/weak/none 与三层 verified/failed/unknown 独立；无适配器/无调用证据保持 unknown，真实失败有原因。
- [ ] AC-06：未确认、错作用域、缺来源、旧指纹、并发冲突和落盘失败均不改原文件或保存新授权；确认成功只改目标事项并追加对应历史。
- [ ] AC-07：缺口报告有层级、原因、来源建议和降级；扫描/提案/读操作不安装、不联网探针、不创建元数据、不静默换绑定。
- [ ] AC-08：provenance 经真实核心存储往返到 capabilities[]，extensions/phase/acceptance 不变；旧/过期租约拒绝；session-only 零元数据。
- [ ] AC-09：只有 tools scan 注册且 handler 在核心项目服务发现前分派，未 init 可报告；classifier 缺失给明确非零错误，后续注入固定扫描快照可验证协议。
- [ ] AC-10：全部测试用临时项目/用户/runtime 根、固定时钟和适配器桩，不访问开发者工具配置或外部服务；真实宿主验证另交 classifier/e2e 留证。

## 范围外

不实现分类器、工具安装、AI 分类、第六能力、新 skills/hooks、运行时改动、任务状态机变更、独立审批系统。后续 init 首次提案、session 轻检查、installer 分发和真实两宿主验证由对应所有者消费接口，不在本任务跨文件包办。代码/契约回滚不自动更改用户绑定。
