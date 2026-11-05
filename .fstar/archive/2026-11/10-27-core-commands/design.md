# 核心命令技术设计

## 1. 约束与实现默认

以本子任务 `prd.md` 与父任务 `design.md` 当前跨子任务契约为权威，父 `implement.md` §2 规定 kickoff；research 仅提供来源和历史，不覆盖父设计。以下是已批准行为的具体实现默认，不增加产品功能：Python >=3.9、仅标准库；`from __future__ import annotations`，不使用 match 或 3.10+ 专属运行时 API；argparse、pathlib、hashlib、json、dataclasses、uuid、datetime、tempfile、os。测试使用 unittest/临时目录/真实子进程。无现存 fstar 数据需要兼容迁移；本仓库 `.trellis/` 管理数据不修改。

安装入口稍后由 Node 包装转发 `python -m fstar`；此子任务开发运行 `PYTHONPATH=src python3 -m fstar`。不得硬编码工作目录或当前用户 home。API 接收 project_root 和可注入 user_home/runtime_root，默认 user_home 为 `Path.home()/'.fstar'`。不隐式创建项目、安装内容或解析 YAML；project-layout 稍后负责配置与 init，core 只接收已解析的选项。

## 2. 模块与共享边界

| 模块 | 单一职责 |
|---|---|
| `src/fstar/__init__.py` | 最小包元数据；导入无写盘副作用 |
| `src/fstar/__main__.py` | 调用 cli.main，传回退出码 |
| `src/fstar/models.py` | 26 字段、子结构校验、默认值、DomainError 与纯状态判据 |
| `src/fstar/store.py` | 路径解析、项目锁、JSON 原子替换、任务树扫描、会话指针读写 |
| `src/fstar/tasks.py` | 创建/生命周期/聚合/租约/恢复/扩展/归档事务与事件；不执行 worker |
| `src/fstar/evidence.py` | 条目映射、SHA-256、交付快照、证据记录/新鲜度/验收观察 |
| `src/fstar/cli.py` | argparse 和 JSON/人读输出；薄命令适配、延迟注册其他子模块命令 |

库函数返回可 JSON 编码的 dict/list 或 Path，不直接 print/exit；DomainError 携带 `code/message/details`。CLI 支持 `--project PATH`、`--session ID`、`--json`，写者身份通过显式 Actor 对象传到服务；只将校验错误翻译为简明消息，不吞文件损坏。退出码默认 0 成功（包括明确 no_task/session_only 结果）、2 输入/缺目标/格式错误、3 闸门未满足、4 锁/租约/目标冲突、1 IO 错误。JSON 错误形状 `{"error":{"code":...,"message":...,"details":...}}`。

最小共享接口（实现可将复杂参数建 dataclass；不得改变含义）：

```python
# models.py
class DomainError(Exception): ...
def new_task(name: str, title: str, description: str, *, creator: str, now: str) -> dict: ...
def validate_task(data: dict) -> None: ...

# store.py
class TaskStore:
    def __init__(self, project_root: Path, *, user_home: Path | None = None): ...
    def resolve(self, task_ref: str, *, archived: bool = False) -> Path: ...
    def read(self, task_ref: str) -> dict: ...
    def transaction(self): ...  # context manager，项目级锁
    def write(self, task_dir: Path, data: dict, *, expected_hash: str | None = None) -> None: ...

def atomic_write_json(path: Path, data: dict) -> None: ...
def find_project_root(start: Path) -> Path | None: ...

# tasks.py
class TaskService:
    def __init__(self, store: TaskStore, *, clock=None): ...
    def create(self, *, name: str, title: str, description: str, actor: dict,
               parent: str | None = None, related: list | None = None) -> dict: ...
    def start(self, ref: str, *, actor: dict, confirmation: dict) -> dict: ...
    def accept(self, ref: str, *, actor: dict, confirmation: dict) -> dict: ...
    def drop(self, ref: str, *, actor: dict, confirmation: dict, reason: str, disposition: str) -> dict: ...
    def archive(self, ref: str, *, actor: dict, confirmation: dict) -> dict: ...
    def state(self, ref: str) -> dict: ...
    def continue_task(self, ref: str | None, *, session_id: str | None = None,
                      action: str | None = None, actor: dict | None = None,
                      confirmation: dict | None = None, reason: str | None = None) -> dict: ...
    def acquire_lease(self, ref: str, *, holder: str, role: str, takeover_reason: str | None = None) -> dict: ...
    def renew_lease(self, ref: str, *, token: str) -> dict: ...
    def release_lease(self, ref: str, *, token: str, reason: str) -> dict: ...
    def set_blocked(self, ref: str, *, actor: dict, reason: str | None) -> dict: ...
    def enable_extension(self, ref: str | None, *, authorization: dict, actor: dict) -> dict: ...
    def archive_candidates(self, *, older_than_days: int = 30) -> list: ...

# evidence.py
class EvidenceService:
    def __init__(self, store: TaskStore, *, clock=None): ...
    def snapshot(self, ref: str, *, artifact: str, items: list[str]) -> dict: ...
    def delivery_snapshot(self, paths: list[str]) -> dict: ...
    def record(self, ref: str, *, evidence: dict, lease_token: str) -> dict: ...
    def invalidate(self, ref: str, *, file: str, actor: dict) -> dict: ...
    def freshness(self, ref: str) -> dict: ...
    def acceptance_status(self, ref: str) -> dict: ...

# cli.py
# 每个子模块 register_commands(subparsers)；core 无需导入其内部实现。
def register_core_commands(subparsers) -> None: ...
def main(argv: list[str] | None = None) -> int: ...
```

类型签名里的 `|` 在 postponed annotations 下用于表达类型，不在运行时构建 union；如项目选择更保守形式可改 Optional/List。`find_project_root` 只查 `.fstar/.schema-version`（v1 值 `1`），配置读取和 `init` 归 `src/fstar/project.py`。先向 project-layout 提供这三个共享约定：schema marker、原子 JSON 写入、`register_commands(subparsers)`。CLI 仅在目标模块确实存在时注册其命令；模块内部 ImportError 应暴露，不能被误判为未安装。计划模块名 `project` / `runtime` / `tools`，后续子任务可协商调整；核心不预创建空实现。

## 3. 数据契约

### 3.1 task.json 顶层（恰好 26）

| 字段 | 类型/默认 |
|---|---|
| id | UUID 字符串，不随移动变化 |
| name, title, description | 非空字符串；name 是安全机器目录名，title 可中文/空格 |
| phase | planning（初始）、in_progress、completed |
| blocked | null 或 `{reason,since}`；设置者、解除来源与核验依据写统一 events |
| evidence | 数组，初始 [] |
| lease | null 或租约对象 |
| acceptance | null 或当前验收对象；旧记录转为验收事件，不覆盖历史 |
| completedAt, archivedAt | UTC ISO-8601 字符串或 null |
| children | 直接子目录 name 数组，初始 [] |
| priority | P0/P1/P2/P3，默认 P2 |
| creator, assignee | creator 非空；assignee 可 null |
| createdAt | UTC ISO-8601 |
| branch, base_branch, worktree_path, commit, pr_url | 可空字符串；core 不创建分支/worktree/PR |
| notes | 字符串，默认空 |
| meta | 对象，初始 {} |
| capabilities, extensions, events | 各自数组，默认 [] |

不得增加 revision/schema 顶层；格式版本在项目 marker，写入乐观校验使用读取内容哈希。保留 name/title/worktree_path 等已确认字段，即使 core 不使用也不丢弃。拒绝未知顶层键与未知 phase；读损坏 JSON 给路径和修复指引，不重置为默认对象。

`meta` 中 core 管理的键以父契约为准：`disposition`（遗弃戳，含 at/by/reason/action/confirmation）、`templates`（产物来源与显式映射）、`related_tasks[]`（id、archive_path、relation、reason）、`reminders`（去重/暂缓记录）。实现需要的 `artifact_map` 放在 `meta.templates` 的映射记录内；检查覆盖、未决问题及当前交付路径以结构化证据、plan/report 引用表达，不再私定额外顶层字段。其他合法扩展 meta 保留；这些字段不是新的顶层 schema。

历史关联引用使用稳定 id + 当时 archive_path，路径只可指项目归档根内的已存在任务。旧任务不移动、不改状态、不写反向指针；关系不产生调度依赖。

### 3.2 状态判据

- 叶节点：planning → start → in_progress → accept → completed；`continue --action replan` 带明确原因回 planning，使**全部当前证据** stale、旧验收失效并释放租约；`continue --action revise` 在用户否决下继续 in_progress。未归档 completed 由 `continue --action reopen` 在用户确认后回 in_progress。`drop --action revive` 清 `meta.disposition` 回 planning。历史 disposition/acceptance 保留事件。
- `meta.disposition` 覆盖 phase 的可执行性，任何普通写入/派发拒绝，drop revive 除外。drop 清租约并保留必要证据，不立即删除 task 目录；discard 的执行处置仅清理显式声明的任务临时产物，路径清单/确认不足则只记录待处理，不触碰源码/worktree/用户文档。knowledge 处置将材料交 learn，未经知识授权不写正式知识。
- 容器的 `effective_phase` 根据子任务最靠前非终态推导，不添加落盘进度；容器显式 phase 仍承载规划与最终 accept。全部子节点 completed/dropped 才可整体验收；容器仍需覆盖整树的整体检查和用户确认。children 丢失/多出或目录不一致时拒绝推进并报差异。
- `blocked` 按写入来源解除：用户标的只接受用户解除；Agent 不能同一 actor 自写自解，主协调者/其他有权限 actor 可在核实原因后解除。actor 声明属于流程校验而非强身份认证。
- fresh check + 无租约产生 awaiting_acceptance 派生值；completed 因依据变化失效则有效态 in_progress、旧 acceptance 标 stale。read 不自动写，后续受锁写入先同步这些差异，清当前 completedAt/acceptance 并保留原验收事件。

## 4. 存储、并发与路径

路径：`.fstar/tasks/<name>/task.json`、`subtasks/<name>/task.json`、`.fstar/archive/YYYY-MM/<name>/task.json`。name 默认由显式 `--name` 或安全 slug 生成，冲突报错；创建日期可加前缀但不靠日期保证唯一。task_ref 支持 UUID 或 tasks 下相对路径，单独名称歧义时列候选；不默认选第一个。

用一个项目级短事务锁串行化状态写入和目录操作，锁放用户 runtime 下 project 规范绝对路径哈希目录，避免归档移动锁。默认锁采用 POSIX `fcntl.flock`，等待上限 5 秒；进程死亡由系统释放，不能按任务 30 分钟 lease 超时删除锁。Windows 不在当前两个宿主实现验证范围，若使用需单独平台锁实现，不能静默无锁。只读查询不创建 runtime/锁文件。

持锁后重新读取并校验 task、当前租约 token、证据以及 expected_hash，生成新对象与 events；同目录 tempfile 写 UTF-8 JSON → flush/fsync → os.replace → 可用时 fsync 父目录。失败保留原文件并清自身 temp。原子替换避免半截 JSON，锁避免 read-modify-write 丢失；不能将原子替换表述为跨多个文件/目录的全局事务。

新建子任务涉及 child 目录与父 children：持同一锁，先 staging 子目录，再发布目录，再原子更新父；任一步失败回滚自身新建目录，绝不覆盖旧数据。崩溃可能留未登记子目录，state/continue 明确报不一致，后续事务在确认该目录 task.id/归属后可恢复登记；未核对前阻止 accept/archive。无需另建永久交易日志。

所有路径先拒绝绝对路径、`..`、空段、不合法 name；resolve 后必须在允许根内。任务目录、archive 路径及写入父目录若含 symlink 则拒绝；证据引用允许项目内已解析普通文件，但不跟随项目外 symlink。read/write/archive 均复核边界，不能只靠字符串前缀判断。目录移动在同一文件系统用 rename；归档目的必须不存在，持锁再次检查；外部无视锁的写入不受本协议保护。

会话指针默认 `~/.fstar/runtime/projects/<project-hash>/sessions/<session-hash>.json`，记录 project/task_id/task_path；仅显式 create/start/成功恢复动作更新，current 无 session 返回 no_current，不用最后一个全局任务。归档后以 task_id 识别并清该树指针；指针是可重建提示，不是状态权威。

## 5. 证据与来源

### 5.1 条目哈希与交付快照

artifact_map 由模板/plan 交接显式提供：artifact 是相对项目路径；每条 item 的稳定 ID 映射到唯一 `start_marker`/`end_marker`。安装默认模板可使用 HTML 注释边界，用户模板保存一次映射后沿映射提取；core 不依赖标题语言或语义猜测。提取范围含边界间全部正文，统一 CRLF→LF 后 UTF-8 SHA-256。标记缺失/重复、ID 冲突/删除均报 invalid；支持显式整文件保守模式，但需输出 granularity=file，不能宣称条目级精确。文档适用性/图文一致性仍由 check 角色判断。

每个 validates 项形如 `{artifact, items:[{id,sha256}], dependencies:[...]}`；dependencies 明确列出关联条目，闭包追踪失效。未改变条目对应的记录保持 valid；旧记录一旦 stale 不可复用改回 valid，只能新一轮生成新证据。artifact_map 本身变更也重核引用条目。

交付快照不只用 Git commit：显式受检路径相对项目根排序，逐文件字节 SHA-256（含测试、共享配置），再对路径+哈希的规范 JSON 计算 snapshot digest；保存存在/缺失信息以检出删除、增补必需路径。commit 可附作定位但不能代替脏工作区内容。路径集合来自当前 plan 的变更/验证范围和派发结果；变更集合会使覆盖不全，不遍历无关 .git/runtime/报告等。测试 report 自身哈希存 report 字段，不能放进其自我引用的交付集合。

### 5.2 evidence 结构与通过判据

共有字段：`id/kind/producer/produced_at/state/validates`；kind 为 delivery/check/review，producer 为 `{role,id,session_id}`。check 增 `run_id/environment/report{path,sha256}/delivery/items[]/scope`；scope 为 incremental/final。items 中每项包含 requirement_ids/plan_item、test_refs、command、result（passed/failed/blocked/skipped/not_run）、exit_code、log_refs、可测量的 duration/retries。无执行时明确 not_run、不可编造耗时。可纯人工审查的条目需记录 review 方法与发现，不假装存在测试命令；要求运行的条目必须有真实命令/结果引用。

record 在锁内核对 token、snapshot、报告存在和当前 scope。过期结果保留为 stale/history 并报告原因，不放行 completed。record check 可由 check 角色修复后提交新 snapshot，但必须与实际最终运行基线一致。校验 final check 覆盖当前 plan/需求验收范围、相关子任务版本与整体范围；最新当前轮 fail/blocked 等未解决结果阻止用更早的 passed 充数。passed 条目必须来源 check 角色，执行和检查的 producer id 不同；仅有 implement delivery 永不算 check。

acceptance_status 从当前覆盖和证据计算逐检查项五态及 stale 原因、交付 digest/run/report 引用；不依赖不存在的 test-cases 文件。不执行 shell 命令、不创建检查报告。record 是 runtime 内部 API；不新增 `evidence record` CLI。

### 5.3 确认来源

统一 Source 封套遵循父设计：`{source_id,type,at,actor,reference,quote,scope,validates}`；type 至少支持 `command | conversation | review`，actor 记录声明的 role/id/session。任务 acceptance 在此封套之外增加 `confirmed_at/confirmed_by:'user'/evidence_refs`。conversation 必须有原话和可定位 reference；review 要引用有效 review evidence，approved 且回链用户确认、范围与当前指纹一致；同事建议不能自行当用户批准。command 表示宿主可定位的用户命令调用来源；Agent 代记只允许 conversation/review，内部 actor role 不可默认 user。

CLI 使用 `--confirmation FILE` 输入结构化确认（与现有对话授权匹配）；直接用户命令可用显式 `--confirm-user` 并记录宿主 invocation reference。两个通道都要求绑定 snapshot，不能有无条件 yes 绕过检查的入口。host 已有授权可代记，不新增审批往返。进程的 actor/type 来自宿主或用户声明，脚本无法防同权限进程伪造；测试证明缺字段/来源不匹配被拒，不能命名成“阻止 AI 伪造用户”的安全测试。

start 的批准写 started 里程碑事件的 source 封套并绑定当前必要 prd/design/plan 指纹，不额外私存 `meta.start_confirmation`；规划评审未启用时不得要求 prd/design。验收对象引用同一 source 封套及 `evidence_refs`，旧版保留事件。review record 只追加 evidence，不改变 phase，也不自动批准所有后续版本。

## 6. 租约、事件与扩展

lease：`holder/acquired_at/expires_at/takeovers[]`，holder 自含 role/id/session；实现可用当前 lease token 做 compare-and-write，但不改变公开字段语义。时间 UTC。同 holder/token 的有效回报在本次写事务续至 now+30m；过期 token 不得悄悄续活，显式接管生成新 token。活跃别人的 lease 拒绝写；用户显式接管可使旧 token 失效并记录理由，不以超时删除任务数据。租约获取、续期、接管和释放的完整历史写统一 events；当前 lease 的 takeovers 保留接管链，不另私定 meta 历史键。租约仅负责 task writer；文件范围协调和多个 worker 并行由 runtime 主协调者管理，不能让多个 worker 各自成为任务写者。

事件统一封套 `{id,at,source,type,data}`，source 使用 §5.3 的来源封套或其稳定引用；是否里程碑由 type 的固定集合判定，不增加自由 milestone 真值。type 至少覆盖 created/started/replanned/blocked/unblocked/evidence_added/evidence_invalidated/lease_acquired/lease_renewed/lease_taken_over/lease_released/review_recorded/accepted/dropped/revived/archived/extension_enabled/extension_changed/doc_changed。review、start 批准、验收、放弃/复活、归档、扩展授权及接管来源属于保留记录。超过软 200 后合并最老普通事件成 summary（范围、按类型数量、首末时间、必要来源、被合并 ID 范围）；不删除里程碑，也不让 summary 每次无限膨胀。摘要是计数追踪，不能宣称保留普通事件全部 payload。

扩展 ID 默认 `planning-review/persistent-task/multi-agent/project-governance/tool-capability`；记录严格是 `id/enabled_at/source/scope/included/excluded/reason`。source 为统一可追溯来源封套；scope=full 或 custom，include/exclude 不重叠，成员按五包能力表验证。当前有效配置保留 extensions，同 ID 的裁剪/停用由 `extension enable --scope custom` / `extension disable` 显式动作更新当前快照，旧值入里程碑事件；停用停止后续能力但不删除资料/在途记录。persistent-task 被裁剪不能取消已启用的证据/验收底线；project-governance 要求已 init。无持久 task 时动作返回 authorization 和 `persistence:'session_only'`，由调用方保存会话上下文；core 不新建隐藏会话持久授权库。

## 7. 命令契约（可执行最小面）

所有 `<task>` 可省略后按当前 session 定位；定位不唯一/缺失时写命令报错；只读 state/current/continue 可返回 no_task，不静默伪装变更成功。

| 命令 | 关键输入 | 结果与写入 |
|---|---|---|
| task create TITLE | --name、--description、--parent、--related；持久任务授权 | 创建 planning，登记嵌套关系，返回 id/path；不自动 start |
| task list | --active（默认）/--archived/--all，--query | 只读；日期/标题/状态/验收/归档链接，含 nested 归属 |
| task current | --session | 只读会话指针或 no_current |
| start [task] | 确认输入 | 验证规划有效/无阻塞/未 dropped，planning→in_progress；同一确认版本重复调用不重复事件 |
| accept [task] | 确认输入 | 重核整体 check、当前来源/子树/未决项，无 lease；completed + acceptance |
| drop [task] | --action drop/revive、--reason、--disposition keep/discard/knowledge、确认 | drop 写 meta.disposition、释放 lease、记录处置；revive 清当前遗弃戳回 planning；不执行未授权删除 |
| archive [task] | 确认输入 | 整树校验后移动并返回其他候选事实；不自动归档其他任务 |
| state show [task] | 无 | 只读 phase/effective_phase/blocked/disposition/evidence/lease/待验收 |
| continue [task] | 默认无 action；显式 --action takeover/replan/revise/reopen/unblock、--reason、确认 | 默认核对后返回下一步；动作仅修改本任务，不派发 worker、不做巡检；revive 归 drop |
| extension list | 可选 task | 五包有效授权或 session_only 提示 |
| extension enable/disable ID | --scope、--include、--exclude、--reason、确认 | enable/crop/disable 都为显式动作；已有 task 原子保存，无 task 返回待宿主保留的 session 授权 |
| review record [task] | --record FILE | 结构化用户产物评审证据补录，验证来源与指纹；不改变完成状态 |
| review list [task] | 无 | evidence.kind=review 筛选，显示 verdict/validity/source |
| evidence invalidate [task] | --file PATH | 重算对应条目和交付哈希，只标受影响 stale，幂等；外部改动也可检出 |
| acceptance status [task] | 无 | 只读五态覆盖、stale 原因、当前运行证据 |

未交付的 dispatch/interrupt/doc-edit、tools scan、init 由独立模块延迟注册；核心帮助只列可用命令。不重新增加 lease/state-set/reminder/inspect/doc-check/spec-check 顶层入口。

## 8. 归档与恢复

普通归档要求 completed、新鲜最终 check + acceptance、所有子节点 completed/disposition、无 blocked/lease/未解决正确性问题；遗弃任务的归档按用户放弃处置完备性校验，不要求为被放弃任务伪造通过证据。只处理最外层任务，连子树移动；归档后不可 start/revive，后续新任务关联历史。

持项目锁预检目标；归档操作用唯一 operation_id 写入普通操作事件，事件 data 含 target、确认来源和预期 archivedAt，随后 rename 整树，再在目标原子写 archivedAt 和 archived 里程碑。失败保留可诊断源或目标，不能只写 archivedAt 就宣称移动成功。重复同一次归档时仅在稳定 task id + operation_id/目标匹配且无冲突时完成剩余步骤；已归档同 ID 返回原结果，其他同名目标一律拒绝。这是 IO 失败恢复默认，不提供“重开历史任务”功能。阶段间中断由 task id、两侧事件和目录事实诊断，显式重试 archive 恢复；不额外私定 `meta.archive_pending`。

归档巡检默认长期阈值 30 天无活动、默认暂缓 7 天（可配置技术默认，不称用户指定）。依据最近实质事件/createdAt，不以文件 mtime 代表任务进展。key 由 task_id + 状态/缺失条件摘要 + 最近活动版本组成；相同 key 暂缓期内不重复，状态/缺失条件/活动版本变化形成新 key。读取候选不写；archive 流程实际展示后经服务接口更新 `meta.reminders`，避免 continue 产生提醒副作用。候选错误不回滚已成功归档；返回 warnings。

## 9. 验证与限制

实现顺序及 unittest 场景见 implement.md。主要风险是文件树发布/归档的中断边界、交付集合漏项和条目映射失效；通过故障点注入、真实进程竞争、外部文件编辑及负例验证。mock 仅用于可控时间/IO 故障，不用 mock 授权“证明身份安全”。核心确保声明与当前文件版本一致，无法证明操作者身份、测试实际执行或语义覆盖充分；这些由宿主来源、检查报告和最终用户验收共同承担。文件系统没有共同权限边界，直接恶意改数据不在本地 CLI 可防范范围。
