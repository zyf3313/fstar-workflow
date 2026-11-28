# 包结构体系重构设计（design.md）

- 依据：clarify.md（2026-11-28 收敛）、criteria.md（A-001~A-005）。
- 本文标注方式：`[事实]` 指已在当前代码（分支 feat/antigravity-adoption）中核实的内容，附 file:line；其余为设计提案（含取舍理由）。
- 分支基线：feat/antigravity-adoption @ 0997742（含未提交的 P-004 相关工作区改动；实施本任务前应先落定或基于其继续）。

---

## 1. 现状盘点（[事实]）

### 1.1 模块清单与规模

src/fstar/ 共 19 个顶层 .py + runtime/ 子包（`wc -l` 实测）：

| 文件 | 行数 | 说明 |
|---|---|---|
| installer.py | 3370 | 安装器：资源分发 + host 绑定 + doctor |
| knowledge.py | 3214 | 知识沉淀 |
| dispatch.py | 2009 | 派发服务 |
| project.py | 1072 | 项目初始化 |
| store.py | 1155 | 任务存储 |
| tasks.py | 1868 | 任务服务 |
| global_resources.py | 819 | resource-inspect / resource-migrate 命令、迁移事务 |
| magpie.py | 823 | Magpie 集成（无 fstar 内部依赖） |
| crossproject.py | 767 | 跨项目能力 |
| evidence.py | 617 | 证据服务 |
| cli.py | 587 | 薄壳，参数解析转发（不拆，clarify 已定） |
| content.py | 379 | 资源校验 + 产物提取 |
| config.py | 329 | 配置加载 |
| capability_adapters.py | 217 | 能力适配器接口（S-5） |
| learn_bridge.py | 249 | learn 子命令桥 |
| models.py | 239 | 数据模型 |
| extensions.py | 37 | grants 读取 |
| __init__.py / __main__.py | 3/4 | |
| runtime/ | hooks.py 1319、inject.py 533、registration.py 408、__main__.py 122 | hook 文本入口、注入、host 注册计划 |

### 1.2 依赖图（[事实] 读 import 语句得出）

- models →（无 fstar 内部依赖）
- store → models（store.py:16）
- evidence → models, store（evidence.py:9-10）
- tasks → evidence, models, store（tasks.py:12-15）
- dispatch → evidence, models, store, tasks, content（dispatch.py:22-31；content 为惰性 import 取 ROLES）
- project → config（project.py:17）
- knowledge → config, models, project, store（knowledge.py:45-48）
- crossproject → evidence, models, store, tasks（crossproject.py:34-37）
- learn_bridge → knowledge(k), extensions, models, store（learn_bridge.py:12-15）
- config →（纯 stdlib）
- content →（纯 stdlib）
- extensions → models, tasks（extensions.py:7-8）
- installer → config, content, models, runtime.registration, store（installer.py:38-42）+ 惰性 import magpie、capability_adapters
- global_resources → installer（global_resources.py:38 起）
- magpie →（纯 stdlib，零 fstar 内部依赖，magpie.py:51-58）
- capability_adapters →（纯 stdlib）
- runtime/hooks、runtime/inject → 独立可导入（dispatch.py:192,241-242 惰性引用）
- runtime/registration →（被 installer.py:41 引用）
- cli → 全部惰性 import（cli.py:10-13 + 命令注册处）

### 1.3 入口与打包机制（[事实]）

- bin/fstar.cjs 与 bin/fstar-hook.cjs 都指向同目录的 bin/fstar-bootstrap.py（fstar.cjs:5,19；fstar-hook.cjs:6,13）。
- bootstrap 用 `python -I` 运行，把包内 `src` 目录插入 sys.path，然后按模块名分发：`cli` → fstar.cli、`runtime` → fstar.runtime.__main__、其余 → `fstar.<name>.main`（fstar-bootstrap.py 全文，`_SRC = parent.parent/"src"`）。
- cli.py 的可选模块注册表：`("project", "runtime", "dispatch", "installer", "crossproject", "global_resources", "magpie")`（cli.py:488），magpie 是其中唯一的外部工具模块。
- package.json `files` 含 `src/fstar/**/*.py` 与 `resources/**/*.md|yaml|json`；`fstar.resource_version: "11"`。
- scripts/build-package.cjs：RESOURCE_DIRS 白名单 `['skills','agents','templates','references','runtime']`（与 package.json files 同步维护），从 ROOT 相对路径收集文件生成 resources/package-assets.json（每文件含 source/destination/sha256）。
- installer 的资源定位全部经 `_package_root() / "resources"`（installer.py:207,269,287,297,327,3149）；用户侧缓存为 `user_root/resources/<version>/`（installer.py:269,561,1560,2207）。

### 1.4 用户侧安装现状（[事实] 本机实测）

- `~/.fstar/resources/` 下堆放 8 个版本目录：1,2,3,4,8,9,10,11；每个目录含 agents/manifest.json/references/runtime/skills/templates；另有顶层 `~/.fstar/resources/version` 文件内容 `11`。
- host 适配：`SUPPORTED_HOSTS = ("claude", "codex")`（installer.py:47）；claude 写 `~/.claude/settings.json`，codex 写 `~/.codex/hooks.json`（installer.py:513-519、registration.py:64-217 各 host 的注册条目数据）。
- resource-inspect / resource-migrate / migrate 命令实际注册在 global_resources.py（register_commands，global_resources.py:656-695）与 installer.py（migrate 子命令，installer.py:3094-3103）；global_resources.py 自带迁移事务（快照/回滚/中断恢复：apply_migration :485、recover_interrupted_migrations :416、resource-migration.json 记录）。
- doctor 结构：_doctor_host_files（installer.py:2603）、_doctor_magpie_ownership（installer.py:2669）、_doctor_resource_extra_hints（installer.py:2708），汇总于 doctor()（installer.py:2747）。

### 1.5 magpie 调用方（[事实] grep 全量）

- installer.py：doctor 的 ownership 检查（:2677-2694 惰性 `from . import magpie`）、路由解析（:3147 `from .magpie import default_agents_source, route_skills`）、指令分享（:3179 `from .magpie import share_instructions`）。
- capability_adapters.py：MagpieDistributionAdapter 以 route_skills 为注入实现（docstring :10、构造 :116 起）。
- cli.py:488：magpie 作为可选命令模块注册（magpie.py 自带 register_commands）。
- scripts/integrate-magpie.cjs：通过 fstar CLI 子进程调用，不直接 import Python 模块（脚本头注释），不受包内路径影响。
- tests/test_magpie.py:19：`from fstar import magpie`。

---

## 2. 目标结构（设计提案）

### 2.1 完整文件映射表

```
src/fstar/
  __init__.py            # 保留：包标识 + PACKAGE_LAYOUT_VERSION
  cli.py                 # 不拆（clarify 已定）
  core/
    __init__.py
    models.py            ← models.py
    store.py             ← store.py
    evidence.py          ← evidence.py
    tasks.py             ← tasks.py
    dispatch.py          ← dispatch.py
    config.py            ← config.py
    project.py           ← project.py
    knowledge.py         ← knowledge.py
    crossproject.py      ← crossproject.py
    learn_bridge.py      ← learn_bridge.py
    content.py           ← content.py（拆分见 2.3）
    extensions.py        ← extensions.py
  skills/
    __init__.py          # 数据包：SKILL.md 们 + 校验/加载入口
    registry.py          ← content.py 中 skills 校验部分（新模块，见 2.3）
    resources/fstar-*/SKILL.md   ← resources/skills/fstar-*/SKILL.md
  agents/
    __init__.py          # 数据包：角色定义 + hooks/inject 运行时
    hooks.py             ← runtime/hooks.py
    inject.py            ← runtime/inject.py
    __main__.py          ← runtime/__main__.py
    resources/fstar-*.md ← resources/agents/fstar-*.md
    resources/runtime/{routing,prompt-states,capabilities}.md  ← resources/runtime/（见 2.4）
  install/
    __init__.py
    installer.py         ← installer.py（host 绑定部分外移后剩余）
    global_resources.py  ← global_resources.py
    layout.py            # 新：布局版本定义与迁移（见第 4 章）
    migrate.py           # 新：一次性布局迁移脚本（见第 5 章）
  plugins/
    __init__.py          # get_plugin() 工厂 + PLUGIN_REGISTRY
    base.py              # 新：插件固定接口（见第 3 章）
    capability_adapters.py ← capability_adapters.py
    registry/
      __init__.py        # 插件目录清单
      magpie/
        __init__.py      # MagpiePlugin(base) 装配
        integration.py   ← magpie.py 主体
integrations/            # 与 src/ 并列（clarify 已定）
  __init__.py
  base.py                # 新：host 适配公共协议（settings 读写、备份、幂等键）
  claude-code/
    __init__.py
    registration.py      # claude 条目（registration.py 中 host=="claude" 数据 + installer 的 claude 专属 plan/apply）
  codex/
    __init__.py
    registration.py      # codex 条目（registration.py:134-217 的 codex 部分等）
resources/               # 保留（纯资产与生成物）
  package-assets.json    # 重建
  templates/  references/   # 保留在 resources/（见 2.4 取舍）
```

### 2.2 归包判定与理由（每模块一条）

- **core**：clarify 点名 tasks/store/models/project/knowledge/dispatch。补入 config/evidence/extensions/crossproject/learn_bridge/content——理由：它们是 core 域的支撑层（依赖图 1.2 显示只被 core/installer 消费，无独立体系）；不单列"support"包，避免 clarify 之外的体系增殖。
- **skills / agents**：数据为主的包。skills 放 SKILL.md 与其校验逻辑；agents 放 hooks/inject（运行时文本入口）与角色 md（clarify 点名）。runtime/ 包整体消失：hooks+inject+__main__ → agents/，registration.py → integrations/（理由：registration 输出的是 host 侧注册条目，本质是 host 适配数据，与 hooks 文本入口不同体系；dispatch.py:192,241 的 `from .runtime.inject` 改为 `from ..agents.inject`）。
- **install**：installer + global_resources + 新 layout/migrate。理由：布局版本与迁移是安装器体系的一部分，A-003/A-004 都挂在 install 生命周期上。
- **plugins**：base 接口 + registry 目录 + magpie + capability_adapters。理由：capability_adapters.py 本就是"外部能力适配"接口（其 docstring 明确 4 个能力类），与插件接口同体系，合并入 plugins/ 可让 MagpieDistributionAdapter 直接复用 base 的 detect。
- **integrations/（与 src 并列）**：host=claude-code/codex 分目录。从 installer.py 外移的函数（见第 6 章切分表）。不进 src/fstar 的理由（clarify 已定）：host 适配是外部边界，未来加 host 不应改核心包。

### 2.3 content.py 拆分（提案）

[事实] content.py 现有两类职责：a) SKILLS/ROLES 常量 + validate_resources/validate_links 资源校验（content.py:11-12,280,338）；b) extract_artifact/build_artifact_map 产物提取（dispatch 用）。
提案：a) 迁入 skills/registry.py 与 agents（ROLES 常量迁 agents/__init__.py），b) 留 core/content.py。理由：校验逻辑与被校验数据同包，资源搬迁后校验跟着走；产物提取是任务域不是资源域。ROLES 从 agents 包 re-export 到 core/dispatch 使用点，避免 core → 数据包反向依赖（实际方向是 skills/agents → 无反向；dispatch import ROLES 改从 agents 取，依赖方向 core→agents 可接受，因 agents 无 core 依赖）。

### 2.4 resources/ 保留项（取舍）

用户决策（2026-11-28，包结构探讨收敛后补充确认）：resources/ 中所有有体系归属的内容全部迁出到各自包下——"resources 就相当于 src 里面的内容都要迁出来放到各自的位置"。保留项只剩纯资产（templates/、references/）与生成物（package-assets.json）。

runtime/ 三件套（routing.md、prompt-states.md、capabilities.md）迁入 `src/fstar/agents/resources/runtime/`。理由：[事实] 三件的消费方是 runtime/hooks.py（hooks.py:1065,1104 读 prompt-states.md）与 runtime/inject.py（inject.py:124,135-136 读 routing.md/capabilities.md）——即本次已定为迁入 agents/ 的 hooks/inject 模块本身（另 content.py:351 的校验也引用 routing.md）；"文本 + 读取它的代码"同包放置，与 skills 的 SKILL.md 迁 skills/resources 同一原则，避免安装器从 resources/ 单独捞这组文件。注意：这是**源码仓库侧**布局；用户侧安装产物路径不变（hooks/inject 按 `root/runtime/...` 相对已解包缓存根读取，缓存布局由 installer 维持，见 2.7）。

package-assets.json 仍由 build-package.cjs 从仓库相对路径生成，其 source 路径随 skills/agents/runtime 搬迁自动更新。

### 2.5 import 重写方案

- 全部包内相对导入：core 内部 `from .models import ...`；跨包 `from ..core.store import ...`（plugins/integrations 引 core 时）。
- 惰性 import 保持惰性（dispatch.py:192 等改为新路径，行为不变）。
- 顶层 shim 不做（被否决项，见第 8 章）：所有消费方一次改净，包括测试。
- `__init__.py`（fstar 顶层）导出 `PACKAGE_LAYOUT_VERSION`（见第 4 章）。

### 2.6 bin/ 与 fstar-hook.cjs 适配

[事实] 启动器只依赖 bootstrap 的模块名字符串（fstar-bootstrap.py）。
- bin/fstar.cjs / fstar-hook.cjs：零改动（它们只找同目录 bootstrap.py，与包内布局无关）。
- fstar-bootstrap.py：`cli` / `runtime` 分支不变；泛型分支 `fstar.<name>` 需映射更新：可选模块名从点路径改为新位置（`magpie` → `plugins.registry.magpie` 等）。设计：bootstrap 内加一个短映射表 `{name: full_module}`，或更简单——cli.py:488 的可选模块清单改为传入完整模块路径，bootstrap 泛型分支按 `fstar.plugins.registry.magpie` 直接 import_module（点号安全检查已存在）。取后者：改动集中在 cli.py 注册表一处，bootstrap 仅放宽首段白名单。
- scripts/integrate-magpie.cjs：走 fstar CLI 子进程（事实 1.5），若它以 `fstar <magpie子命令>` 调用则命令名不变即零改动；实施时核对其 spawn argv，命令面（`fstar install/update` 等）不变。

### 2.7 package.json files 与 package-assets 重建

- files：`src/fstar/**/*.py` 不变（子目录自动覆盖）；新增 `integrations/**/*.py`；`resources/**/*.md` 等保留（templates/references/package-assets 仍在）；skills/agents 的 md（含 agents/resources/runtime 三件套）从 resources glob 消失，改由 `src/fstar/**/*.md` 覆盖（需在 files 中新增该 glob）。
- build-package.cjs：RESOURCE_DIRS 由 `['skills','agents',...]` 改为 `['templates','references']` + `src/fstar/skills/resources`、`src/fstar/agents/resources`（含 agents/resources/runtime/ 三件套）两个新的收集根；SRC_DIR 收集范围扩到 src/fstar 全部 .py（现状已如此）。生成后 `npm run build:package` 重建 package-assets.json，`fstar.resource_version` 提升为 "12"（resource 版本与布局版本联动，见 4.2）。
- 注意 [事实]：package-assets 的 destination 是用户缓存相对路径（installer 按 resources/<v>/ 解包），skills md 的 destination 从 `resources/skills/...` 变为 `resources/skills/...` 保持不变；runtime 三件套同理，destination 保持 `resources/<v>/runtime/...`（用户缓存布局由 installer 定义，不必跟源码布局走）。理由：用户侧 ~/.fstar/resources/<v>/ 是已发布契约（A-005 兼容），只动源码侧布局，缓存侧目录名不改，老任务 pin 的资源仍按缓存路径解析；项目侧 `.fstar/runtime/` 安装产物路径同样不变（hooks/inject 按 root 相对路径读缓存，消费代码与数据一起迁 agents/ 但读取逻辑的相对路径不变，用户侧无感）。

---

## 3. 插件接口设计（A-002）

### 3.1 plugins/base.py 固定接口

```python
# src/fstar/plugins/base.py（提案）
class Plugin(Protocol):
    name: str                 # 注册名，如 "magpie"
    version: str              # 插件自身版本
    capabilities: Sequence[str]  # 声明的能力，取值见下

    def detect(self, *, user_root: Path) -> DetectResult: ...
    def assist_install(self, *, user_root: Path, choice: str) -> InstallResult: ...
    def bind(self, *, user_root: Path, **kwargs) -> BindResult: ...
```

- capabilities 词表：本期复用 capability_adapters.CAPABILITY_CLASSES（session-management/distribution/memory/scheduling，capability_adapters.py:26）作为统一能力词表，插件声明子集。理由：已有词表经过 S-5 设计评审，不另造一套。
- detect：只读探测（装没装、版本、可用性）——语义对齐现有 probe() 的只读契约（capability_adapters.py:32-38 的规则：probe 成功不构成授权）。
- assist_install：按用户选择配合安装（choice ∈ {"install","skip"}，必须有用户显式选择输入，插件不得自作主张安装——对齐 clarify"没装则按用户选择配合安装"）。
- bind：接入动作（分发 skills、分享 instructions 等），只在既有授权调用点被 core/install 调用。

### 3.2 工厂与注册（不绕过 grants）

- `plugins/__init__.py`：`get_plugin(name)` 工厂 + `PLUGIN_REGISTRY`。registry/ 目录下每个子目录一个插件，`registry/__init__.py` 显式 import 各插件的 `register()`（无动态扫描、无 entry_points 机制——理由：stdlib-only 约束（package.json 描述）+ 避免运行时导入不受审代码）。
- 授权链：插件没有独立命令面。bind 的调用点只有两类：install/update 流程（installer，用户已用 `fstar install` 显式授权）与 doctor 只读检查。extensions.grants（extensions.py:11）的语义不变：grants 仍由 core 在 dispatch 时读取，插件不读取也不影响 grants。设计上明确写入 base.py docstring：插件失败一律降级到 CLASS_FALLBACKS（capability_adapters.py:33 的现有规则），绝不阻塞核心流程。
- 对应 cli.py:488 的 `magpie` 可选模块：改为由 plugins 注册表驱动——cli 可选模块清单中 `magpie` 项指向 `fstar.plugins.registry.magpie`（该模块保留 register_commands 以挂子命令）。

### 3.3 magpie.py（823 行）迁入适配

[事实] magpie.py 对外 API：MagpieStatus/default_discovery/probe（:75-137）、default_agents_source/load_record（:139-170）、integrate/route_skills/share_instructions/uninstall_local（:185-728 主体，文件尾隐藏约 3 个函数）、_library_state/_prune_* 等内部函数。

拆解映射（提案，行为不变）：

| 现函数 | base 接口实现 | 说明 |
|---|---|---|
| default_discovery + probe | `detect()` | 只读探测，输出 DetectResult（available/version/reason） |
| install 时按选择执行 magpie 安装提示 | `assist_install()` | 本期 magpie 是"用户已装才接入"，assist_install 返回 guidance（安装指引用户自己装），不做包管理器调用 |
| integrate / route_skills / share_instructions | `bind()` 的内部函数 | bind 不合并三者签名（参数差异大），bind 作为门面按 kwargs 分派；installer 的三个调用点（installer.py:3147,3179,2677）改调 bind 或保留直接调用具体函数——**取舍：保留具体函数签名，bind 只做薄门面**，避免为接口统一而改内部签名引入行为风险（A-002 要求"既有 magpie 功能行为不变"） |
| uninstall_local | `unbind()`（base 可选方法） | doctor/uninstall 路径使用 |
| _library_state/load_record 等内部 | 原样迁入 integration.py | |

调用方 import 改动：installer.py 三处惰性 import 改为 `from ..plugins.registry.magpie.integration import ...`（或经 get_plugin("magpie")）；capability_adapters.py 的 MagpieDistributionAdapter 改从新路径注入 route；tests/test_magpie.py:19 改 import 路径。

### 3.4 验证（对 A-002）

- test_magpie.py 全量改路径后通过；
- 新增 test_plugins.py：a) get_plugin("magpie") 返回实现 base 接口的实例；b) detect→assist_install(choice="skip")→bind 的冒烟链路（fake runner 注入，沿用 test_magpie.py 现有 fake 模式）；c) 插件抛异常时 install 降级不失败（对齐 capability_adapters 的降级规则）。

---

## 4. 布局版本机制（A-004）

### 4.1 版本号定义

- 常量：`PACKAGE_LAYOUT_VERSION = 2` 写在 `src/fstar/__init__.py`（包顶层，任何子包可 `from .. import PACKAGE_LAYOUT_VERSION`，无循环依赖）。layout 1 = 现状（平铺 + resources/skills）。
- 变更规则写入常量旁注释：凡 package-assets 的 source 路径集合或 src/fstar 顶层结构变化，必须 bump。

### 4.2 安装记录（写在哪）

- 用户级：写入 `~/.fstar/resources/<v>/manifest.json`（现有缓存清单，[事实] 每版本目录已有 manifest.json）新增字段 `layout_version`；同时顶层 `~/.fstar/resources/version`（[事实] 现存文件，内容 "11"）旁新增 `~/.fstar/layout-version` 文件作为快速探测点。理由：update 需要在解包新缓存前就能判断旧布局，顶层单文件最便宜。
- 项目级：`.fstar/config.yaml`（[事实] 用户根已有 config.yaml，schema_version:1）新增可选键 `layout_version`，在 `fstar init`/install 绑定项目时写入。作用：doctor 能同时校验两侧。

### 4.3 update 自动迁移 / doctor 校验

- `fstar update`（_handle_update，installer.py:3065 注册处）：在 plan_install 前比对 `~/.fstar/layout-version` 与当前 PACKAGE_LAYOUT_VERSION；落后则先执行 layout 迁移（第 5 章），再走正常 update。`--dry-run` 时只报告将迁移什么。
- doctor：新增 `_doctor_layout` 检查项（与 _doctor_host_files/_doctor_magpie_ownership 并列，汇总进 doctor() installer.py:2747）：a) layout-version 文件与代码常量一致；b) 缓存目录结构与 layout 声明一致；c) 项目 config.yaml 的 layout_version 不高于已装版本。

### 4.4 ~/.fstar/resources/ 版本目录清理

[事实] 本机堆放 1,2,3,4,8,9,10,11 共 8 个目录。
方案：update 迁移完成后，保留"当前生效版本 + 上一版本（回滚窗口）"，其余目录**移动**（非删除）到 `~/.fstar/install-backups/stale-resources-<date>/`（[事实] install-backups 目录已存在）。触发方式二选一，设计取**显式确认**：update 输出提示"检测到 6 个过期资源目录，运行 `fstar resource-migrate --prune-stale` 归档"；`--prune-stale` 命令执行时先 dry-run 列目录，需 `--confirm` 或交互 y/n 才移动。理由：criteria 要求不静默删用户数据；备份移动而非删除保证可恢复；交互确认与 installer 现有冲突策略（CONFLICT_POLICIES，installer.py:3058 等）的"用户明示"风格一致。

---

## 5. 一次性迁移设计（A-003）

### 5.1 机制（扩展现有命令）

[事实] global_resources.py 已有完整的 resource-migrate 迁移事务体系（快照/回滚/中断恢复：apply_migration :485、recover_interrupted_migrations :416）。设计：布局迁移**复用这套事务机制**，新增 `install/migrate.py` 实现布局迁移逻辑，并：

- 挂到 `fstar resource-migrate` 命令（global_resources.py:656 register_commands）下作为新的迁移类型（`--layout`），同时被 `fstar update` 自动调用（4.3）。
- 迁移内容（对老安装）：
  1. 解包新版本资源缓存（正常 update 路径已有，不变）；
  2. 写入 ~/.fstar/layout-version 与 manifest.layout_version；
  3. 触发 stale-resources 提示（4.4）。
- 幂等：迁移前检查 layout-version，已达标则 no-op。
- 回滚：复用 resource-migration.json 事务记录（[事实] 顶层已有该文件）。

### 5.2 卸载重装路径文档化

`fstar uninstall` → 删除 `~/.fstar/resources/`（保留 install-backups）→ `fstar install`。写入 README 或 docs 的一节"布局升级：自动迁移或卸载重装"，说明两条路径等价性、各自前提（自动迁移保留用户 pin；重装会重置 pin）。

### 5.3 验证（对 A-003）

- 测试环境用旧布局 fixture（手工构造 layout 1 的 ~/.fstar 树，含 1~11 堆放目录）跑 `fstar update` → doctor 通过 + 功能正常（用现有 test_installer.py 的 fake-roots 模式，[事实] 其大量用 roots_from_args 显式根）。
- 卸载重装路径至少一条集成测试 + 文档存在性检查。

---

## 6. integrations/ 切分（A-001 的一部分）

[事实] host 绑定代码现状分布（installer.py）：
- SUPPORTED_HOSTS（:47）、default_host_root/default_codex_host_root（:181-203）；
- _settings_file（:513）、_plan_host_settings（:761）、_owned_setting（:800）、_host_file_kinds（:828）、_link_state（:902）、_plan_host_files（:930）、_upgradeable_external（:1080）、_plan_stale_host_files（:1107）；
- _apply_host_file（:1833）、_prune_empty_host_dir（:1975）、_doctor_host_files（:2603）；
- runtime/registration.py 的 capabilities/plan/_hooks_cell（:260-408）与各 host 条目常量。

切分提案：

| 目标 | 内容 |
|---|---|
| integrations/base.py | HostAdapter 协议：host 名、settings 路径、hook 条目构造、owned 判定、文件 apply 的 host 无关部分 |
| integrations/claude-code/ | claude 条目数据（registration.py:58-133）+ claude 专属 settings.json 读写合并策略 |
| integrations/codex/ | codex 条目数据（registration.py:134-217）+ hooks.json PascalCase 适配（[事实] :135-163 注释记录的 TUI 信任语义一并迁移） |

- installer.py 保留资源分发主体；对 host 的 plan/apply/doctor 通过 `integrations.get_adapter(host)` 调用。理由：installer.py 3370 行的最大块状复杂度就是 host 绑定，外移后 installer 回到"资源 + 编排"。
- 用户侧命令不变（A-001 隐含）：`fstar install --host claude` 等命令面、参数、输出 schema 均不动，只动内部模块归属。
- 事务/备份机制（apply_plan 的 _Lock/Journal，installer.py:1200-1355）保留在 install/，integrations 只产出 plan 条目与 apply 动作——理由：备份与原子写是安装器的事务责任，不属于任何一个 host。

---

## 7. 迁移顺序与风险（A-005）

### 7.1 提交序列（原子性划分）

1. **commit 1（可独立）**：integrations/ 切分 + installer 改造（host 绑定外移）。测试面：test_installer/test_external_host_upgrade 等。
2. **commit 2（可独立）**：plugins/base + registry + magpie 迁入（A-002 全部）。依赖 commit 0 无。其实可与 1 并行/任意先后。
3. **commit 3（必须一个提交完成）**：core/skills/agents/install 分包 + resources/skills、resources/agents、resources/runtime 三件套迁入 + 全部 import 重写 + build-package/package.json/package-assets + 测试 import 重写。理由：包结构是全局不变量，半迁移状态（如 core/tasks.py 存在而 cli.py 还 import fstar.tasks）必然红，无中间可提交态。这是任务的最大原子提交，需预排好 `git mv` 清单后一次成型。
4. **commit 4（可独立）**：layout 版本机制 + update 自动迁移 + doctor 布局项 + stale-resources 清理（第 4、5 章）。依赖 commit 3。
5. **commit 5（可独立）**：文档（卸载重装路径）+ README 结构说明。

### 7.2 测试基线策略（1135+ 测试如何保持）

- import 重写：机械替换 `fstar.tasks → fstar.core.tasks` 等映射（grep 统计现状：`from fstar.models` 20 处、`from fstar.store` 13 处、`from fstar.tasks` 若干、`from fstar import installer` 5 处、`from fstar import magpie` 1 处……测试内嵌的代码字符串（[事实] test 中有 `"from fstar.tasks import TaskService\n"` 这类字符串注入，5 处）**必须一并替换**——这是最容易漏的点，列入 checklist。
- skills/agents 路径：test_installer 中构造 resources 树的 fixture 改为在新路径构造（含 resources/runtime 三件套迁 agents/resources/runtime 后的源路径变化）；validate 相关断言（content 校验，含 content.py:351 的 routing.md 引用）指向新模块/新源路径。
- 顺序保障：commit 3 落地前先跑全量基线记录通过数（当前 grep "def test" 计 1125 个，加 cjs 侧 test_package 总量以 pytest 实跑输出为准）；commit 3 后数量不减、全绿。
- A-005 兼容验证：老任务数据测试（现有 storage/acceptance 套件不动数据格式）+ 新增一条"layout 1 项目数据在新包下读写正常"的回归用例（用归档任务 fixture）。

### 7.3 风险清单

| 风险 | 缓解 |
|---|---|
| commit 3 原子提交体量大（~40 文件移动+改写） | 先 `git mv` 得到纯移动提交语义（git 保 follow history），再做 import 改写，review 时分开看 |
| bootstrap 泛型模块名分支失效 | commit 3 显式更新 cli.py:488 注册表 + bootstrap 白名单，并跑 bin 冒烟（fstar version / hook plan） |
| 用户已发布 npm 包的旧布局升级失败 | 迁移走既有事务机制（快照/回滚）；dry-run 先行；A-003 测试用旧布局 fixture 覆盖 |
| magpie 行为漂移 | bind 门面不改内部签名（3.3 取舍）；test_magpie 全量不改断言只改 import |
| build-package 白名单与 package.json files 漂移 | [事实] 两者需手工同步（脚本注释），本次同时改并在 CI/npm test:package 验证 |

---

## 8. 被否决的备选（记录）

1. **保留 resources/ 兼容层（顶层 shim / 旧路径重导出）**：否决。用户原则"重构就要彻底"；shim 会让 `fstar.magpie` 等旧路径长期存活，未来每个读者都要分辨真假入口；且 npm files 收紧后 shim 反而制造双路径。代价是一次性改测试，可接受。
2. **渐进迁移（先迁 magpie，其余下个版本）**：否决。与"不能漏的漏"原则直接冲突；且包结构半态会让 layout 版本机制无法定义（layout 只能对完整结构编号）。
3. **plugins 用 entry_points/setuptools 动态发现**：否决。项目是 stdlib-only Python + Node 启动器（package.json 描述），且动态导入绕过代码评审；显式 registry 清单足够。
4. **用户缓存 ~/.fstar/resources/<v>/ 目录结构随源码布局改**：否决。缓存路径是已发布契约（老任务 pin 按缓存路径解析），改它违反 A-005；源码布局与用户缓存布局解耦。
5. **bind 统一 magpie 三大入口签名为一个方法**：否决（3.3）。签名差异大，强行统一是行为风险，违背"既有功能行为不变"。
6. **runtime 三件套留在 resources/**：否决。曾作为 2.4 原方案（"clarify 只点名 skills 与 agents"），被用户 2026-11-28 决策推翻——"resources 就相当于 src 里面的内容都要迁出来放到各自的位置"；三件套有明确消费方（runtime/hooks.py、runtime/inject.py，即 agents/ 模块），属有体系归属内容，随消费代码迁 `src/fstar/agents/resources/runtime/`；仅用户侧安装产物路径因缓存契约（A-005）保持不变。

---

## 9. criteria 覆盖对照

- A-001：第 2 章（映射表/归包理由）、第 6 章（integrations）、2.6（cli 薄壳与 bin 不动）。
- A-002：第 3 章（base 接口/工厂/registry/magpie 适配/验证）。
- A-003：第 5 章（迁移机制/卸载重装文档/验证）。
- A-004：第 4 章（版本定义/记录位置/update 自动迁移/doctor/清理）。
- A-005：第 7.2、7.3（测试基线与兼容回归）、8.4（缓存契约不动的理由）。
