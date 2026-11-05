# 项目布局与配置设计

## 1. 目标与边界

对应 PRD PL-01–04。未来实现采用 Python 3.9 标准库；当前只刷新规划。`project.py` 管布局与无覆盖写入，`config.py` 管解析/验证/合并；`cli.py` 由 core-commands 独占。无现有产品模块可复用，不复制 Trellis 实现。

父 `prd.md` 与 `design.md` 是当前自包含依据，父 `implement.md` §2 定义 kickoff；历史 research 只补充背景且不得覆盖它们。任务三态/26 字段、doc 仅 prd/design、任务根 clarify/plan、知识两目录是消费边界，不另建版本。

## 2. 模块与调用契约

使用 Python 3.9 类型写法，不使用 3.10 的联合类型语法。

```python
# src/fstar/project.py
initialize_project(
    path: Path,
    user_root: Path,
    *,
    context: Optional[ProjectContext] = None,
    dry_run: bool = False,
) -> InitResult

initialize_user(user_root: Path, *, dry_run: bool = False) -> InitResult

# src/fstar/config.py
load_config(
    project_root: Optional[Path],
    user_root: Path,
    *,
    defaults: Optional[Mapping[str, object]] = None,
) -> ConfigResult
```

- `path/project_root` 是项目根，不是 `.fstar`；`user_root` 是实际用户数据根，调用方默认传 `Path.home() / '.fstar'`，测试显式传临时根。API 不隐读环境变量、不更改 cwd、不搜索祖先项目；定位属 core。
- 项目根须已存在且为目录；显式根可规范化，但受控 `.fstar` 及待写文件不可为符号链接。用户根可缺失，其直接父目录须存在；只有显式 `initialize_user` 创建它。
- `ProjectContext` 含 `project_summary: str`、`topics: Sequence[TopicReference]`、`authority_refs: Sequence[DocumentReference]`、`knowledge_refs: Sequence[DocumentReference]`。TopicReference 含 `id/title/applies_to/read_when/path`，DocumentReference 含 `title/path`。数据由 init skill 根据事实形成；context=None 只生成明确待补的导航。
- 引用采用项目根相对 POSIX 路径，可带 Markdown fragment；拒绝绝对路径、`..`、NUL、越界符号链接。文件必须存在；fragment 保留，不声称通用锚点验证。尚未落盘的主题建议留在 skill 讨论中，不作为有效引用。
- `InitResult` 含 `root: Path`、`created: Tuple[Path, ...]`、`preserved: Tuple[Path, ...]`、`warnings: Tuple[InitWarning, ...]`、`context_complete: bool`、`dry_run: bool`。dry-run 的 created 表示拟创建；context_complete 只表示输入背景/导航完整并被使用，不等于语义检查通过。已有索引未更新时不得据新 context 声称接入已更新。
- `InitWarning` 含稳定 `code/path/message`，如 `CONTEXT_REQUIRED`、`INDEX_PRESERVED`、`IGNORE_RULES_MISSING`、`SCHEMA_MARKER_MISSING`。`InitError` 含 `code/path/message/created`，保留实际失败前创建清单；不返回虚假全成功。
- `ConfigResult` 含独立副本 `values: Dict[str, object]`、已加载 `sources: Tuple[Path, ...]`、叶键来源 `origins: Dict[str, str]`、结构化 `warnings`。默认来源标记 `<defaults>`；列表作为整体记录来源。异常 `ConfigError` 含 `code/path/line/key/message`，CLI 映射输出和退出码，不在模块 print/exit。
- core 以 `init [path]` 调用项目接口，以 `init --user` 调用用户接口，`--dry-run` 透传。模块不可反向 import cli。扫描由 init skill 在基础接入之后按工具模块实际接口调用，不在此 API 执行外部命令。

## 3. 最小布局与初始化算法

新项目仅创建以下文件；不预建任何空目录：

| 文件 | 初始内容 |
|---|---|
| `.fstar/index.md` | 中文短概况与导航；已有权威文档优先声明；context 缺失时显式待补 |
| `.fstar/config.yaml` | `schema_version: 1` 和 `project.id`（UUID4）；语言等使用默认值，不复制全部默认配置 |
| `.fstar/.gitignore` | `/runtime/`、`/*.local.yaml`、`/.identity`、`/identity` |
| `.fstar/.schema-version` | `1` 加换行，表示数据格式，不是包版本 |

显式用户初始化只创建 `index.md`、`config.yaml`（schema_version: 1）、`.gitignore`。用户索引列 rules、memory、本地定制入口的职责说明；未存在的目录不渲染为有效文档链接，不建规则或记忆正文。

1. 规范化根，检查路径类型、受控路径符号链接和目标冲突；先解析已有配置并验证 schema，再规划所有缺失文件。已有 `.schema-version` 非 1 或与配置不一致，返回不兼容错误，不迁移。旧配置存在却缺 schema 标记时，只在 schema_version=1 明确可识别后补标记，否则报告需迁移检查，不猜版本。
2. 对新配置仅生成一次 project.id；已有配置缺 project.id 时保留并返回明确配置错误，不换身份、不静默修复。用户配置及 local 文件不得覆盖项目身份：project.id 仅允许来自项目 config.yaml。
3. 渲染内容、校验引用和配置后再写。新文件以排他创建（`O_CREAT|O_EXCL`，支持时加 `O_NOFOLLOW`）写 UTF-8；绝不先 exists 后用普通覆盖打开。使用目录描述符和 no-follow 检查受控目录，避免检查后切换符号链接造成越界写入。竞争发现目标已创建时重新验证并归入 preserved，不覆盖。
4. 已有文件逐字节保留，包括 CRLF、注释和格式。已有 `.gitignore` 缺上述明确规则时只告警，不实现完整 Git ignore 语义判定、不改根 `.gitignore`。没有 Git 也可 init。
5. 中途失败仅清理由本次持有文件描述符创建、尚未完成的文件；已完成文件留待重试补齐。不得删除整个 `.fstar`，不承诺跨四文件事务。I/O 错误返回已完成清单，重复执行补缺不重写。
6. dry-run 完成同样输入检查但无 mkdir/write、无运行状态、无资源安装；拟生成 UUID 不作为持久身份承诺。

`.schema-version` 初始值是本设计与 core/package-install 的接口约定，迁移属 package-install。创建标记不能充当迁移实现；未来不兼容版本必须拒绝而非改写。

## 4. 配置数据与五层合并

默认映射首先定义：

```yaml
schema_version: 1
auto_commit: false
language:
  interaction: zh-CN
  artifacts: zh-CN
  specs: en
```

字段名是本子任务的具体配置 API；下游模板和 runtime 使用同一映射，不另立语言配置。安装包完整默认配置后续可通过 defaults 参数接入；未传时内置最小默认值保证无资产依赖。

顺序为 defaults、user/config.yaml、user/config.local.yaml、project/.fstar/config.yaml、project/.fstar/config.local.yaml。project_root=None 时仅前三层；缺失文件跳过，权限/编码/格式错误明确失败。读取不建目录、缓存、身份或 marker。

合并采用深拷贝：mapping+mapping 递归，列表整体替换，标量整体替换；不存在键直接加入。不同非空类型冲突报 `CONFIG_TYPE_MISMATCH`，bool 与 int 明确分开；int/float 也不隐式转换。null 为显式值，不表示删除键；普通可扩展键允许 null 与任意类型互相替换，已知非空字段经 schema 校验拒绝 null。空映射对已有映射不清空，空列表替换旧列表。

schema_version 必须为整数 1（bool 不合格），auto_commit 为 bool，language 为映射且三个已知叶键 `interaction/artifacts/specs` 为非空字符串；rules/memory 的英文要求属于知识内容契约，不增加独立语言键。语言标识允许有效的 ASCII 字母数字分段并以连字符连接，不把格式校验声称为完整 IANA 注册表校验。project.id 必须是有效 UUID 字符串且仅在项目 config.yaml 声明。可扩展配置保留未知键和类型并给出来源，不由当前模块解释 tools/knowledge/evidence 等后续 schema；本设计不恢复旧 journal、dispatch.inline 配置行为。

配置覆盖与知识冲突裁决是两件事：`enforced` 用户规则、项目 specs、memory 的语义优先级交知识加载器处理，load_config 不合并自然语言正文。

## 5. YAML 子集的可执行定义

不引入依赖，不实现完整 YAML。解析器仅服务 fstar config；接口/报错明确称为“fstar YAML subset”。其他 tools.yaml、frontmatter 不自动承诺复用。

- UTF-8 文本，允许首字符 BOM、LF/CRLF、空行、整行注释；缩进只允许空格且每级恰好 2 格。顶层必须为 mapping；空文件视为 {}。禁止 Tab 缩进和多文档标记。
- block mapping：未引号键匹配 `[A-Za-z_][A-Za-z0-9_-]*`，冒号后须空白或行结束。同一层重复键直接报错。键无值时必须有下一层 mapping/list；不把裸 `key:` 偷换成 null，null 须显式写出。
- block sequence：每项 `- scalar`，元素仅 scalar，缩进层级同上。不支持 block 列表中的 mapping 或嵌套列表；需要复杂列表时使用下一条的 JSON flow 子集。
- flow collection 仅支持合法 JSON 对象/数组（通过 json 标准库解析，object_pairs_hook 检出重复键、parse_constant 拒绝 NaN/Infinity）。JSON 字符串键也须符合配置键规则；尾逗号、单引号 flow、未引号键均拒绝。支持 `[]` 和 `{}`。
- scalar：`true/false`、`null` 精确小写；十进制整数遵循 JSON 数字规则，有限浮点遵循 JSON 数字规则（允许指数）；无隐式日期、八进制或 yes/no/on/off 布尔解释。`yes` 等作为普通字符串；数字样式不合法（如 01、1_000、.inf）报错，避免悄悄改类型。
- 双引号字符串按 JSON 转义解码，单引号字符串支持双单引号转义；字符串必须同一行闭合。普通字符串为非空单行，不得含 `: `、起始 YAML 指示符或控制字符。字符串内 `#` 仅在引号外且前有空白时开始注释；引号/flow 内的 # 保留。冒号、#、换行需求可用 JSON 引号字符串表达。
- 拒绝 anchors/aliases/tags/merge key、`|`/`>` 多行块、复杂 key、指令、文档分隔符及不匹配的括号/引号；所有未覆盖语法报 `CONFIG_UNSUPPORTED_SYNTAX`，包含文件和行号。解析须按引号状态扫描，不靠按冒号或 # 全局 split。
- 写出的最小 config 是本子集兼容文本；不为合并而重写原文件。测试覆盖接受与拒绝样例，不能用“遇到不认识的就当字符串”伪装支持。

## 6. init skill 与后续资产

完整接入流程是：读取项目事实/既有对话 → 必要时澄清 → 拟主题职责和已有权威引用 → 调 initialize_project → 校验实际导航 → 按授权范围维护已有索引及所需规范 → 可选工具扫描提案。

单独启用 planning-review 时，调用方可通过同一套受控相对路径验证与排他创建原语按授权写 `clarify.md`、`plan.md` 和按需 `doc/prd.md`、`doc/design.md`，但不得隐式创建 `task.json`、租约或 `.fstar/tasks/` 持久任务目录。持久任务布局为 `.fstar/tasks/<任务>/...`，整树归档落 `.fstar/archive/<YYYY-MM>/<主任务>/`；具体任务创建和归档事务仍由 core 所有。

低层 CLI 不遍历项目执行脚本、不调用 AI、不创建推测规范。新索引可直接消费事实 context；已有索引保持，由 skill 在明确修改范围内维护。索引简洁导航，不强制规范正文骨架。默认技术规范英文且遵循实际主题，learn 复用同一归属；长期知识仅 context/references。

正式 init/索引/知识模板由 workflow-content 提供；最小文本是基础协议兜底，不复制整套模板。该子任务以后用契约测试验证索引所需字段；不存在模板安装目录不得阻塞 init。工具服务后续可从 skill 调用，失败以独立诊断返回，不回滚已完成基础接入，不自动写 tools.yaml。

## 7. 影响范围

- 项目接入：新增安全的最小布局创建，保留现有文档及配置。
- 配置消费：core、runtime、workflow-content、工具及知识功能共享五层结果与来源。
- 内容治理：init 提供真实导航；learn 沿用主题归属和语言，已有权威内容优先。
- 安装升级：项目数据版本与包版本分离，安装器负责升级，不借 init 重置内容。

## 8. 验证与回退

用 tempfile/unittest 验证真实磁盘副作用，读前后字节对比而非仅测函数调用次数。覆盖五层合并、类型/错误语法、空项目/已有内容/重试、符号链接越界与目录冲突、显式用户 init、只读零写入。失败修复后局部回归，最终跑完整子任务套件及 core init 集成。

当前无产品发布或迁移负担。实现回退仅撤销本子任务代码变更；不能用删除用户 `.fstar` 作为回退。底层写入失败的已完成项按 InitResult/Error 报告并可重试。

## 9. 尚未交付的上游条件

1. core 的包入口/CLI 尚未实现，需导入上述 API 并统一退出码；本子任务不得改 cli.py 争写。
2. package-install 需共享 schema 初始版本 1 并提供未来迁移；目前只识别并拒绝不兼容版本。
3. workflow-content 尚未提供 init skill 与正式资产；可先验收模块，完整项目结构规划须在该子任务与 e2e 中验证。
4. 工具扫描接口尚未交付，保留 skill 调用挂点，不虚构调用成功或新增强依赖。
5. 现有 backend spec 为待填模板，没有实际 lint/typecheck 命令；本轮不修改 spec。实现以 Python 3.9 编译及 unittest 为真实验证，后续有命令再按事实补充。

这些是跨子任务交付条件，不改变已批准范围，不要求用户再次批准。
