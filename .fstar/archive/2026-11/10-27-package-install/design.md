# 安装包技术设计

## 1. 边界与现状

以父 prd/design/implement 当前全文及本子 PRD 为准。Python 3.9 标准库内核；Node 薄启动器。只规划五文件，不运行产品或宿主安装。项目只数据，程序与宿主资源用户级安装。公开资源相对路径保持 `skills/agents/runtime/templates/references/capabilities/registry/schemas`。

已读实际接口：`cli.py:157/248/274` 的 optional handler 契约及注册表；`content.py:11–17/337` 的清单/纯校验；`config.load_config(project_root,user_root)` 的逐项覆盖与 `auto_commit=False`；`runtime.inject.resource_root()`、`tool_classifier._resource_root()` 当前仅按源码父目录定位；`runtime.registration.plan(host)` 只返回注册形状；`runtime.__main__.main(argv)` 输出宿主注入文本，而 `fstar hook` 是机器 JSON。dispatch 已在主 CLI 注册 prepare/harvest/retry/orphan/interrupt/doc-edit，CLI 不负责真正派原生 Agent。

## 2. 源码、构建与启动

拟定独占路径（尚未创建）：

| 文件 | 责任 |
|---|---|
| `package.json` | 暂用本地包名 fstar-workflow、bin.fstar、files 白名单、Node engines、版本；名称未查可用性 |
| `bin/fstar.cjs` | Node 内置 child_process 启动 Python，零 npm runtime 依赖 |
| `bin/fstar-hook.cjs` | 内部宿主文本 hook 启动器，不新增手动流程别名 |
| `bin/fstar-bootstrap.py` | 只把本包绝对 `src` 放入 sys.path，分发 main；不读 checkout/PYTHONPATH |
| `scripts/build-package.cjs` | 本地构建/清单校验，标准 Node API，无联网、宿主设置或生命周期安装 |
| `src/fstar/installer.py` | 注册六命令、resolver、清单/事务、版本、doctor、迁移 |
| `resources/package-assets.json` | 资源来源/所有者/相对路径/版本/兼容信息的索引；构建产物补实际哈希 |
| `tests/test_installer.py`、`tests/test_package.cjs` | Python 隔离 fixture 与 Node wrapper/pack smoke |

npm tarball 保持 `bin/`、`src/fstar/`、`resources/` 相邻，避免重排后现有相对路径立即断裂；逻辑发布布局不强迫源码目录改名。files 白名单只含运行文件、必要元数据、来源/许可材料，排除 `.trellis/.claude/.codex`、测试、私有数据、缓存和 pyc。Node 技术默认最低 18，实际版本记录到测试；Python 最低 3.9。不设 postinstall/preuninstall 自动改设置。build 校验清单与路径，npm pack 只打本地文件，不表示发布完成。

主启动器按自身真实路径（兼容 npm bin symlink）定位 bootstrap，spawn 参数数组，`shell:false`、`stdio:inherit`、保留调用 cwd；`process.argv.slice(2)` 原样转发，处理 spawn error/退出码/信号，POSIX 透传终止信号，其他平台明确映射，不能误报 0。解释器按显式 `FSTAR_PYTHON` 单一可执行路径、否则 python3 探测；用固定 argv 验证版本，不拆解用户 shell 字符串。缺失/过旧报 `python_unavailable/python_version_unsupported`，提示安装 Python3.9+ 或设置解释器路径；JSON 请求给稳定错误封套。

bootstrap 用 Python `-I` 启动，从 `__file__` 定位本包 src 后导入；不使用 cwd、用户 site 或 PYTHONPATH 搜索本包。主入口委托 `fstar.cli.main`；hook 启动器委托 `fstar.runtime.__main__.main`，原样转发 JSON stdin 与注入 stdout。绝不把机器 JSON hook 响应替代宿主文本响应。dispatch helper 通过已打包 `fstar dispatch ...` 访问，包括 harvest 的 result/payload/lease-token；不要求用户运行 `python -m` 或手设环境。

## 3. 公共 API 与命令

installer 暴露 `register_commands(subparsers)`，每个 parser 设置 `OPTIONAL_HANDLER_ATTR`，handler(args) 返回 JSON 可编码结果、失败抛 DomainError；在 core TaskService 查找前执行，任意目录可用。全局 `--json/--project/--user-data-root/--runtime-root` 放子命令前。内部 API 技术合同：

- `resolve_resources(*, project_root, user_root, requested_version=None) -> ResourceSelection`：version/root/source/manifest_digest，纯读。
- `plan_install(*, operation, roots, bundle_root, hosts, conflict_policy) -> dict`：完整 action/conflict/expected-hash 清单，纯读。
- `apply_plan(plan, *, roots) -> dict`：重新核验哈希、加锁、事务写；不信任任意 JSON 给出的越界路径。
- `doctor(*, roots, host_observations=None) -> dict`：读现状，分别返回 expected/observed/estimated/unknown。

| 命令 | 行为 |
|---|---|
| install | `--host claude|codex` 可重复，`--dry-run`；安装当前包内资源与已核实的用户级入口 |
| update | `--dry-run`、`--modified keep|overwrite|new` 默认 keep；从当前已安装 npm 包导入资源，不自动联网更新 npm |
| uninstall | `--host` 可限定、`--dry-run`；精确撤自身未修改条目，不卸载 npm 本体/用户资料 |
| doctor | 只读结构化体检，异常非零；不自动 repair |
| migrate | 显式 `--project` 或 `--user`、`--to-schema`、`--dry-run`；`--rollback <transaction-id>` 恢复受控备份 |
| version | CLI/resources/schema 分列，含来源、pin、实际解析根及兼容性 |

用户先经包管理器获得 CLI，再显式 install 配置宿主；update 不假称更新 CLI 本身。无宿主参数时列目标及诊断，不推测应该修改哪家配置。`--host-root` 仅显式 fixture/高级目标覆盖，roots 含 user/runtime/project/各 host，路径由调用方注入而非全局 monkeypatch。未知参数保持 argparse 非零；错误细节含操作/路径/冲突/恢复建议，不回显配置秘密。

## 4. 所有权、哈希与事务

用户根下 `version` 记录选择的资源版本；`.asset-hashes.json` 记录资源安装基线；新增 installer 自有 `.install-manifest.json`、`entry-index.json`、`resources/<version>/`、`install-backups/<operation-id>/`。这是安装器元数据，不是任务、记忆或知识台账。resource cache 不自动 GC，以免破坏其他项目 pin。

manifest (`fstar.install.v1`) 含安装 ID/事务状态、CLI/资源版本、目标根身份、files[] 与 settings_entries[]。文件记录 resource_id/相对源/目标根+相对目标/source_hash/installed_hash/版本/是否本次创建/备份引用；settings 条目记录宿主版本、配置路径、事件+matcher+完整 hook 值、canonical SHA-256、插入位置上下文与创建身份。`.asset-hashes.json` 是同事务的基线投影，不能以当前用户内容重建哈希冒充安装原样。

识别既有同值 hook：可复用但标 externally-owned，卸载不删；安装器新增才 owned。去重比较规范化 event/matcher/type/command/options 全值，不仅 event+command；绝不执行 planner 的“command contains fstar.runtime”删除建议。共享数组只删确切且仍匹配的 owned hook；外层组若仍有其他 hook/字段则保留。条目被用户改写、重复造成身份歧义或位置证据不再唯一时保留并诊断，不能任删一个同名项。

更新三方比较：baseline/current/incoming。current=baseline 才正常替换；current!=baseline 默认 keep，显式 overwrite 备份，new 写 `.new`，若 `.new` 已存在则冲突保留。保留的旧文件不能标为新版本原样；entry index 记实际版本/modified。未拥有同名路径不自动接管。uninstall 也比对 baseline，保留用户改动与所有 user-owned 数据；只清已知空的自建目录，不 rmtree 用户根或项目根。

事务顺序：读取并验证→纯计划→用户根锁→重读比较防并发→写备份与事务记录→同文件系统暂存→校验→逐文件原子 replace→manifest/hash/version/index 最后提交。多个文件不能假称一次 rename 原子；事务日志记录每一步，故障按备份回滚。回滚前再比对事务写入后的哈希，有新用户修改则保留并报告恢复冲突，不能整份旧 settings 覆盖并发修改。损坏/缺失 manifest 不做猜测删除；doctor 报损坏，repair 由重复 install 的显式计划恢复可验证项目。拒绝路径穿越、越根 symlink、非法版本与包内链接逃逸。

## 5. 版本解析与迁移

包索引分别声明 cli_version/resource_version/supported_data_schemas，当前核心数据 schema=1，不私增 task 顶层字段。实际资源版本选择：显式请求 > 合并 config 的 `resources.version`（项目层优先）> 用户 version > 当前 bundled 版本。只接受明确版本 ID，不把 latest/范围解析成网络请求。若显式版本等于 bundled 且哈希/兼容匹配可直接用包内资源，否则读用户 `resources/<version>`，缺失/坏哈希/不兼容返回 `resource_version_unavailable/resource_integrity/resource_incompatible`。解析纯读，不偷偷创建缓存。

install/update 从包资源复制完整只读版本缓存，核对清单哈希后原子提交；相同版本却不同内容拒绝，禁止污染历史版本。任务/项目/用户自定义模板仍按父优先级独立覆盖默认，不把用户覆盖并入不可变缓存。用户级宿主 skill listing 有一个实际安装版本，无法同时显示多个项目的 listing；version/doctor 如实显示宿主安装版本与项目默认资源选择。项目 pin 要真实影响 routing/role/template/registry 消费，不能只在 version 输出一个标签；宿主固定 skill 正文与旧 pin 若不兼容须明确报错，不能承诺宿主动态 listing。

迁移 registry 用明确 `(from_schema,to_schema)` 转换函数，读写仅指定数据根，备份包含原字节/哈希/引用清单。暂存转换→schema/引用校验→切换，marker 最后写；失败恢复，幂等 operation-id。当前只有 schema1：同版本 no-op；无转换实现的路径拒绝。测试可注入合成 v1→v2 转换和中途失败验证事务，不声称产品已支持 schema2。知识 schema 由 knowledge-base 交付，接入其公开校验；未交付显示 pending，禁止硬编码虚构格式通过迁移。

## 6. 宿主适配与入口索引

实施先记录实际宿主版本与用户级 skills/agents/设置支持证据。读取目标配置后追加/去重，保留不相关值。JSON 保留未知字段；如宿主实际要求 TOML，Python3.9 无 tomllib，采用经核实的保留式局部编辑/宿主官方接口，不新增第三方 Python 依赖，不实现有损全文件重写；无法安全解析则拒绝并显示计划。

当前 Claude planner 参考用户 settings.json，但 verified 标记只算 observed-schema；Codex planner 的 `<project>/.codex/hooks.json` 不能用于本任务用户级安装。验证版本支持的全局路径后才提供适配器；否则输出 unsupported 与已有边界回退，交协调者，不改项目宿主目录、不降低第一版双宿主验收条件。测试和规划只操作临时 host roots，不写真实 settings/config。

hook 配置使用本包可执行绝对路径。宿主若只接收 command 字符串，由 adapter 对固定程序/路径按该宿主平台规则逐参数编码；payload 仅 stdin，不拼用户文本、cwd 或 shell substitutions。wrapper 自身永远 argv+shell:false。测试空格/中文/引号/元字符路径；不支持的平台拒绝错误编码。npm 包迁移/删除后入口可能失效，doctor 识别并提示重新显式 update；不假设 PATH 含 npm bin。

entry-index (`fstar.entries.v1`) 从实际成功动作生成：entry id/host/version/kind/source/installed_path/invocation/ownership/status；每流程一个手动入口。内部 hook launcher 不算额外流程入口。索引附四语义 hook→宿主事件/边界回退/证据等级；没有 live-delivery 证据时明确 unknown。fstar-help 应读取此索引再查实际文件，不凭预期清单声称已安装。

## 7. doctor 与测试边界

复用 content.validate_resources 并补五 capability、registry/schema、四语义 hook 和 executable 检查；不把 validator 尚未覆盖项视为通过。分别报告 bundled/cache/host 的计数、缺失/多余/改动/损坏、兼容范围、auto_commit 默认与实际来源，不重置用户显式配置。

listing 描述实际字符数从已安装 frontmatter 计算，完整 listing 含名称/分隔开销只能估算，除非有对应宿主版本和可追溯真实观测。现有历史 888 字符不是恒定基线；不写 skillUsage，不擅自设置 skillOverrides，不以 4 hook 代码入口存在证明宿主投递。schema/API pending 列未完成检查。

所有单测与 smoke 使用临时 HOME/host/user/runtime/project/npm cache/prefix；无全局安装、真实设置修改、联网。pack 解包到独立空目录，驱动脚本放在另一个可信目录，读取归档的 Python 用 -I。无需安装即可通过 tarball 的 Node bin 验证，再用临时本地 prefix、offline/ignore-scripts 验证 npm bin 链接（无外部依赖）；不得使用 npm -g。真实双宿主 e2e 交后续 e2e-verify，在隔离宿主 profile/fixture 内取得证据，不以本任务测试授权写真实用户 settings。

## 8. 协调者交接与发布闸门

| 所有者 | 最小必要共享接入（本子不直接写） |
|---|---|
| core-commands | cli.build_parser optional 列表增加 installer；保持 handler 先于 TaskService |
| runtime-hooks | resource_root 委托版本 resolver 并传 project/user 上下文；planner 引用已安装 launcher、修正 observed/live 语义及 substring 卸载提示 |
| tool-classifier | `_resource_root` 消费同一 resolver/所选根，scan 不再固定 bundled registry；不改 tools.py |
| workflow-content / project-layout | 默认模板/role/routing 等实际消费者接入 resolver；help 指向 entry-index；内容不由安装器私改 |
| knowledge-base | 公共 schema/validator 与迁移契约交接，允许 pending 先组合包 |
| e2e-verify | 用户级两宿主发现/事件投递/原生派发回收证据，fixture 不能替代 |

共享接口未接好可做 installer 单测和 pack 组合，不可宣称 pin、整体 CLI 或 host 验收完成。发布还需核实 npm 名称/命令冲突、模板固定提交 `674bea37cf2f6f25cd20dab93e1a54ae1f13ce66` 的原文适配及实际许可；清单记录 source_ref/license_status，未核实标 unresolved 并阻止 release-ready。不因本地 pack 成功而豁免来源/许可或悄然改模板方案。当前无发布授权，本次不联网核名、不发布。
