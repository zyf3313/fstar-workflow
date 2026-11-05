# 安装包与版本管理

## Goal 与权威

交付可本地打包验证的 npm 包：Node 薄 CLI 包装器 + Python 3.9+ 标准库内核，命令名 `fstar`。用户级安装一次跨项目使用；项目 `.fstar/` 只放数据。显式安装、更新、卸载、体检和迁移可预览、可恢复，保护已有资源、宿主设置和用户资料。

权威为父 `../10-25-fstar-workflow-design/{prd,design,implement}.md`，重点 design §4.1/4.3/4.4/6、implement #9 与集成 #27–32。三份父文档必须完整读取，design 超出自动注入限额时补读全文。历史 research 与 project-context 不覆盖当前父契约。十子任务已有实施授权；本次仅刷新本目录 prd/design/implement/implement.jsonl/check.jsonl，不 start、不写产品代码、不做 git、安装、真实设置修改、联网发布或派 Agent，不重开审批。

## 已核实背景与依赖

- project-layout、workflow-content、runtime-hooks 已有实现与独立检查记录。CLI 已提供 optional handler，但模块列表尚未注册 installer；两处资源根目前按源码相对路径定位，尚无版本缓存解析。
- 现有资源为 12 skills、4 roles、11 templates、5 capabilities，另有 routing、references、mapping、schema、registry。4 hooks 是语义数量，不等于磁盘上必须有四个脚本或恰好四条宿主事件注册。
- registration planner 为只读形状；Claude Code 2.1.312、Codex 0.165.0 的历史观察不等于 live delivery。Codex 当前记录为项目 `.codex/hooks.json`，不能由此推断全局支持或违反“项目只数据”。实施须按实际宿主版本核对用户级设置/skill/角色/入口惯例。
- knowledge-base 正并行规划：其 schema/API 最终交接可待定，不阻塞已有 Python/资源组合与本地 pack；最终 schema 体检和父级验收需消费真实交付。
- 默认模板原文及许可核对仍未完成；署名或结构化改写不能代替固定提交原文/许可验收。npm 包名可用性及命令冲突尚未核实，不能宣称已发布或名称可用。

## 需求

### PI-01 可安装包与入口

npm 元数据、构建清单包含全部 Python 内核与公共资源，`npm pack` 可在隔离 fixture 中构建、解包并运行，不依赖源码 checkout、Trellis 或外部 PYTHONPATH。Node 只定位已打包入口、检查 Python、传递 argv/stdin/stdout/stderr/退出状态；不重实现任务逻辑，不拼 shell 命令。Python 缺失/版本低于 3.9 给可操作诊断和非零结果，不自动安装 Python。包安装生命周期不修改宿主或用户配置；配置写入只由显式 `fstar install/update/uninstall/migrate` 发起。

### PI-02 用户级资源与宿主注册

安装到用户级，任意 cwd 可调用；不在项目放程序、skills、角色或宿主注册副本。每流程每宿主一个手动入口，支持 skill 就不再造同义 command。运行时内部 hook 文本入口、机器 JSON hook 入口和 dispatch 辅助命令都须有真实可执行的打包路径；不能把 Python import 路径当成用户必须自行配置的运行环境。

实际读取目标已有配置后逐项合并，保留其他 hooks、权限、环境、插件及用户项。坏文件/未知宿主版本或未证实的设置格式不盲写；列出支持边界与待办。Codex 若无已核实用户级机制，明确报告不支持/阻塞，交协调者解决；不伪造全局能力、不以项目安装暗中替代。

### PI-03 所有权与更新保护

安装器记录精确文件/配置条目身份、安装基线 SHA-256、版本及来源；不得靠路径前缀、`fstar` 名称或 command substring 判断所有权。重复 install 幂等，update 预览差异；未改的自有资源可更新，用户改动默认保留，可显式选覆盖或生成 `.new`，覆盖前备份，已有 `.new` 同样不覆盖。用户已有同名资源不自动接管。

uninstall 仅移除仍匹配所有权及当前安装基线的自身文件/条目；修改过的保留并报告。永不删除用户 rules/memory/specs/knowledge/tasks/archive/tools.yaml/registry.d/绑定/模板覆盖，永不递归删除整个 `~/.fstar` 或项目 `.fstar`。不因回滚代码撤销用户绑定。`auto_commit=false` 默认不变，无隐式 git。

### PI-04 三种版本与资源固定

分别报告 CLI 包版本、资源版本、数据 schema 版本。项目明确资源版本必须解析到该版本缓存并校验内容；缺失/不兼容/损坏报错，绝不静默 latest。更新保留仍可能被项目引用的旧缓存；全局宿主入口的安装版本与当前项目实际解析版本分开显示。模板任务>项目>用户>安装包优先级保持，更新不改既有评审产物。

### PI-05 显式迁移与恢复

迁移限定明确目标根和支持的版本路径：预检、备份、暂存转换、校验、切换，失败保留或恢复原字节和引用。重复执行安全；无已实现迁移链就报 unsupported，不改 marker 冒充迁移。v1 同版本可明确 no-op；不迁移 Trellis 数据。更新/安装中断须可检测和恢复，不以留下部分设置或 manifest 当成功。

### PI-06 doctor、help 与证据诚实

doctor/version/预览只读，不初始化项目、不修设置、不扫描安装工具、不伪造 skillUsage。检查 12 skills/4 roles/4 semantic hooks/11 templates/5 capabilities、routing、映射/schema、资源哈希/版本、入口可执行路径、宿主注册与缺口。help 消费安装器入口索引并核对实际存在性。

listing 每条 description ≤200 字符、12 条正文合计 ≤2400；名称和分隔开销另算。真实宿主可观察 listing 与静态估算分栏，缺观测写 unknown；字符不等于 token。按 observed-schema / fixture-test / live-delivery 标证据，规划与 fixture 不产生真实宿主通过结论。

## 验收标准

- [ ] AC-01 / PI-01：隔离 `npm pack` 产物包含完整程序/资源；源码不可见、PYTHONPATH 清空、任意临时 cwd 下 CLI/hook/dispatch helper 可用，argv、流、状态及 Python 故障路径有验证。
- [ ] AC-02 / PI-02：临时 HOME/用户/宿主/项目根完成 fresh/repeat install；项目无程序副本、其他设置逐项保留、入口无同义重复；未知格式拒绝写入。
- [ ] AC-03 / PI-03：原生/修改/同名未拥有文件及嵌套混合 hook 数组的更新/卸载正确；精确 manifest 与基线有回归，默认保留、覆盖备份、`.new` 冲突不丢数据。
- [ ] AC-04 / PI-04：A/B 两资源版本实际读到不同内容；项目 pin A、全局 B 不混淆；缺失/坏哈希/不兼容明确失败；旧缓存保留。
- [ ] AC-05 / PI-05：安装/更新故障注入、设置并发变化、迁移中断可恢复；备份还原字节与引用；同版本 no-op 与未知版本拒绝均验证。
- [ ] AC-06 / PI-06：doctor 计数/诊断、entry index 和实际安装一致；listing 实际/估算边界、4 语义 hook 的支持级别正确，无数据或配置副作用。
- [ ] AC-07 / 全部：测试只用临时 HOME、host/user/runtime/project 根；无全局 npm install、真实设置变更、网络发布或用户数据删改；实际命令/结果/未覆盖项如实记录。
- [ ] AC-08 / 发布：名称/命令冲突、模板固定提交原文与许可、两宿主用户级可用方式和剩余 live-delivery 有真实证据后才满足发布/父级整体验收；未核实项不能静默豁免。

## 所有权、范围外与真实阻塞

本子任务独占 Node bin/package/build 元数据、`src/fstar/installer.py`、安装器/pack 测试、资源所有权索引；不修改 runtime/core/tools/classifier/内容源。最小共享改动交协调者按 design §8 分配：installer 注册、统一资源 resolver 的消费者接入、help 引用与宿主 planner 修正。

不实现知识治理、分类器、任务状态机或新 hook；不加入自动安装外部工具、市场、第三宿主、独立调度器。产品任务计划仍为 plan.md，本文件组的 implement.md 是 Trellis 管理产物。

规划可完成、包组合可先做。实际发布/整体集成仍受用户级 Codex 路径证据、共享 resolver 接入、模板原文/许可、包名核实与真实双宿主交付证据约束；知识 API 待交接只阻塞相关最终联调，不阻塞 pack 骨架。以上不构成新审批请求。
