# 工作流内容独立检查报告

- scope: final
- 检查时间：2026-10-29
- 环境：macOS (darwin 27.0.0)，Python 3.9.6（`python3 --version`），标准库 unittest；工作区不是 git 仓库
- 交付基线：`resources/{skills,agents,runtime,templates,references}`、`src/fstar/content.py`、`tests/test_content.py`
- 未覆盖范围见文末“阻塞与限制”，不计为通过

## 结果总览

| 项 | 命令 / 方法 | 结果 |
|---|---|---|
| 本子任务测试 | `PYTHONPATH=src python3 -m unittest tests.test_content` | passed，24 tests OK |
| 全库测试 | `PYTHONPATH=src python3 -m unittest discover -s tests` | passed，78 tests OK（原 54 + content 24） |
| 编译 | `python3 -m py_compile src/fstar/content.py tests/test_content.py`、`python3 -m compileall -q src/fstar tests` | passed |
| Python 3.9 | 以上套件实际运行于 Python 3.9.6 | passed（实现记录曾称无 3.9 解释器；本环境实测为 3.9.6） |
| 资源校验 smoke | `validate_resources(resources)` | 0 diagnostics |
| 真实模板→core | prd/design/plan 模板 + 映射 → `build_artifact_map` → `EvidenceService.persist_artifact_map` → `snapshot` | passed，条目级粒度与依赖闭包正确 |
| 纯读 | 全部读取 API 前后对 resources 55 个文件逐字节 SHA-256 | 完全一致 |

## AC / T 核对

| 验收项 | 结论 | 证据 |
|---|---|---|
| AC-01 精确清单 12/4/11 + 唯一 routing/mapping/references | passed | `validate_resources` 逐路径集合校验；实际 12 skills、4 roles、11 模板、3 mapping、1 routing、3 references；无 finish/recall/ui skill，无 test-cases/review-log，无 workflow.md 副本 |
| AC-01 description ≤200/条、≤2400/12 条 | passed | 实测 max 88、total 888（中英双语） |
| AC-01 frontmatter/链接/占位符可检查 | passed（本次修复后） | 新增占位符声明与格式校验；`validate_links` 校本地链接；frontmatter name/description 必填 |
| AC-02 最小闭环、五包独立/裁剪/拒绝、评审后自动 plan、回忆、archive-only | passed（静态） | `routing.md` 逐项含固定包 ID、一次一包、拒绝不复问、复用已有授权、不建 task.json、导入有效成果、archive-only 巡检、recall 为意图；`fstar-debug` 核心自动路由已补 |
| AC-03 editor 后台/旧稿冲突/原生 implement/独立 check 自修与整体检查 | passed（静态） | doc/check/execute skill、4 角色卡；check 与 editor 共用 `document-checklist.md` |
| AC-04 默认+自定义模板可提取、坏槽位/边界/ID/关联失败、core 同 map、改一条不误算其他 | passed | 实测六槽位、markers/explicit、任意 ID/语言；缺槽位 MARKER_COUNT/SLOTS_REQUIRED、空值 EMPTY_VALUE、重复 ID DUPLICATE_ID、坏关联 INVALID_REFERENCE、缺失目标 REFERENCE_TARGET_MISSING；core 实测条目级隔离：证据仅绑定 R-001 时，改 R-001 正文使其 stale，改条目外文字不使条目证据 stale；CRLF→LF 后哈希不变 |
| AC-05 固定来源/章节调整、升级不改旧文档、review_state 非批准 | partial（来源全文受限） | prd/design/profiles 均注明提交 `674bea37…` 与“非同字复制”；design 7/8/9 章正确；review_state 非批准见 checklist 与 prd 模板；逐字来源/许可未核实（见限制 1） |
| AC-06 知识格式/语言/init/learn/索引兼容 | passed（静态） | `knowledge-format.md` 字段与优先级、三知识模板 frontmatter、entry 模板字段对齐真实 `ProjectContext/TopicReference/DocumentReference`；知识运行时未交付（限制 4） |
| AC-07 校验只读、错误可定位、真实与语义结果分开 | passed | 纯读逐字节一致；Diagnostic 含 code/path/line/message；本报告区分实测与静态语义 |

## 本次修复

1. `src/fstar/content.py`：`load_mapping` 拒绝未知 `references.mode`/空 `separator`；`extract_artifact` 按声明 separator 规范化关联（原实现忽略 separator 且把无效关联留在结果中）；新增 explicit 关系来源缺失诊断；新增模板占位符声明/格式校验；`validate_resources` 增加 `runtime/routing.md` 与三份 references 的必需存在校验，并对每个 `*.mapping.yaml` 与其同名模板实际提取（默认模板/映射不再只验文件存在）。
2. `resources/templates/task/research.md`、`task/check.md`、`entry/project-index.md`：补“Allowed placeholders”声明注释。
3. `resources/skills/fstar-doc/SKILL.md`：补 planning-review 授权门与“已批准未变范围同步不再审批”。
4. `resources/skills/fstar-check/SKILL.md`：补共用 `document-checklist.md`、检查报告模板与持久任务 `acceptance/check-<n>.md` 落点。
5. `resources/agents/fstar-editor.md`：回读复用共用 checklist。
6. `resources/skills/fstar-init/SKILL.md`：优先引用已有权威，不生成臆测规范。
7. `resources/skills/fstar-learn/SKILL.md`：事务失败恢复原内容。
8. `resources/skills/fstar-clarify/SKILL.md`、`fstar-plan/SKILL.md`、`resources/agents/fstar-research.md`：引用对应 research/plan 模板。
9. `resources/runtime/routing.md`：补核心自动 `fstar-debug` 的进入条件（派发第 2 次失败/无进展，最多自动重试 1 次）。此前 routing 未提及 debug，12 个 skill 未全部被路由覆盖。
10. `tests/test_content.py`：新增 6 个测试（separator 生效、非法 references 映射、必需单件资源校验、占位符声明、坏映射诊断、真实映射/模板成对提取）。

## 未修复（跨所有权，需对应模块处理）

1. 整文件模式 `granularity=file` 无法经 core `EvidenceService.persist_artifact_map` 持久化：content 按 core `snapshot` 读取方式输出顶层 `mode: "file"`，但 core persist 把每个顶层键当 artifact 且要求值为对象，字符串 `"file"` 被 `mapping_invalid` 拒绝。core 侧约定不一致，属 core-commands 所有权，未改 core，也未 mock 成通过。
2. 其余上游集成（project 索引接点、knowledge 原子事务/加载器、package resolver/doctor、tool 扫描/绑定、runtime hooks/dispatch、双宿主实际行为）未执行，依赖模块尚未交付。

## 阻塞与限制（不得计为通过）

1. **来源全文与许可**：本环境无法访问网络（对 `raw.githubusercontent.com` 的固定提交请求连接被重置），也无本地克隆；`.trellis` 研究稿仅含结构核对摘要，无许可文本与可复制全文。因此 prd/design/profiles 是按已批准结构改写并保留来源/非逐字声明，不是逐字复制；来源全文核验与许可核对未完成。不得据此声称模板已逐字落地。
2. **未做 git diff 证明所有权**：工作区非 git 仓库，无法输出 diff。以修改时间顺序、core/config/project 测试数未变（36/8/10）及全库 78 tests 通过作为旁证，但不能替代 diff。
3. **description 合计口径**：按“12 条 description 合计 ≤2400”实现（实测 888）；若“正文”指 12 个 skill 正文，则正文合计超限。需求文字可作两种解读，未擅自改正文。
4. **语义审查为静态推演**：关键词/字符串断言不能证明工作流真实正确；两宿主派发、事件、listing、后台行为属 runtime/e2e 证据。
5. **Python 3.9**：本环境实测 3.9.6，套件通过；未在其他 3.9 补丁版本或 3.10+ 上重复验证。
