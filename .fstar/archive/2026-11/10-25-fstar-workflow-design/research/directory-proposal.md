# fstar 目录设计草案

> **状态（2026-10-29）**：本文件为历史草案，以下内容已被取代，现行以 `prd.md` 与 `policy-decisions.md` 为准：独立 `knowledge/decisions/` **已删除**（长期决定并入 `specs/`）；`knowledge/` 仅 `context/` 与 `references/`，不设 `history.md`（任务历史改为 `fstar task list --archived` 派生视图）；`implement.md` 更名 **`plan.md`**（任务根目录）；`doc/` 为 `prd.md` + `design.md`（`test-cases.md` 暂缓、`review-log.md` 已移除）；新增任务根 `clarify.md` 与 `acceptance/check-<n>.md`；journal/workspace 不采用。

状态：待用户评审。命名与两级归属已获认可，以下精简方案、文件名与创建时机尚未批准。仅规划，不创建产品目录、不修改宿主配置。源码 fork 与 CLI 依赖的具体边界由架构设计另行确定。

## 精简原则

- 产品安装包承载默认工作流、角色、技能和模板；用户目录只存个人内容与覆盖项，不复制安装包所有文件。
- 项目内已有 README、docs 和规范优先引用；同一事实只维护一处。
- 人可读 Markdown 保存知识与报告，JSON 保存状态和证据关联，YAML 保存配置。
- 运行状态与持久知识分离；用户级和项目级分别保留各自必要的运行文件，避免重复保存任务状态。
- 以下为完整可用布局，非初始化时全部生成的目录。

## 用户级：~/.fstar/

| 路径 | 内容 | 创建时机 |
|---|---|---|
| index.md | 个人内容索引：条目摘要、适用情形、路径；不复制正文 | 首次配置个人内容 |
| config.yaml | 用户默认配置、所用工作流版本/来源、平台选择；不存凭证 | 首次需要保存配置 |
| .gitignore | 忽略 runtime/、机器本地配置 | 个人仓库初始化 |
| config.local.yaml | 本机路径、平台可执行文件位置等覆盖项；不入库 | 按需 |
| rules/<主题>.md | 用户明确确认的跨项目规则，记录适用范围、来源、要求及原因 | 首次确认规则 |
| memory/<主题>.md | 个人偏好或跨项目经验，记录类型、适用范围、来源及内容；不作为强制规则 | 首次沉淀 |
| workflows/<名称>.md | 用户自定义或明确覆盖的流程；未覆盖则使用安装包默认流程 | 按需 |
| skills/<能力>/SKILL.md | 自定义能力的触发条件与执行指引 | 按需 |
| skills/<能力>/references/<主题>.md | 该能力的参考资料 | 按需 |
| skills/<能力>/scripts/<脚本> | 该能力确实需要的脚本；不是核心 CLI 副本 | 按需 |
| templates/<产物>.md | 用户自定义文档模板，如 prd.md、design.md、implement.md、check.md | 按需覆盖 |
| runtime/projects.json | 已知项目 ID 与本机路径，作为定位索引，不存项目任务状态 | 首次登记项目 |
| runtime/sessions/<会话ID>.json | 未进入正式项目时的会话定位信息；不复制项目会话记录 | 按需 |

用户已确认 rules/ 与 memory/ 独立。rules/ 保存明确要求遵守的规则；memory/ 保存默认偏好和参考经验。记忆不能自动升级为规则；升级需用户明确确认，并迁移内容、保留来源，避免两处重复维护。详细冲突处理与确认流程另行设计。

内置技能、工作流与模板随产品安装包分发；这些目录仅用于个人定制，不要求用户维护两套默认内容。用户个人仓库可安装/关联到 ~/.fstar/，具体安装策略待定。

Hooks、skills、角色与模板的完整职责/文件清单见 `hooks-skills-templates.md`。内置 hook 逻辑随安装包提供，按宿主配置注册，不默认新增用户级 hooks/。宿主不会天然发现 ~/.fstar/skills/，需由安装适配器生成或关联平台入口；自定义模板建议与安装包模板使用相同的分类相对路径（entry/task/knowledge/optional）。以上为本轮补充提案。

## 项目级：<项目>/.fstar/

| 路径 | 内容 | 创建时机 |
|---|---|---|
| index.md | 项目短背景、关键入口、文档与规范路径、适用范围；引用已有产品文档 | 正式项目初始化 |
| config.yaml | 稳定项目 ID、配置格式版本、工作流选择/版本及项目覆盖配置 | 正式项目初始化 |
| .gitignore | 忽略 runtime/ 与 config.local.yaml | 正式项目初始化 |
| config.local.yaml | 本机项目配置覆盖，不入库 | 按需 |
| specs/<主题>.md | 已确认的项目规范，如 coding.md、testing.md、architecture.md；仅创建需要的主题 | 首次沉淀 |
| specs/<领域>/index.md | 某领域条目变多后的子索引；不默认预建 frontend/backend 等分层 | 规模需要时 |
| tasks/<任务ID>-<名称>/ | 活跃主任务及其内部子任务，详见任务布局 | 启用持久任务包（用户同意持久化） |
| archive/<年份月份>/<任务目录>/ | 主任务整棵目录移入，不再复制摘要或单独归档子任务 | 首次归档 |
| runtime/sessions/<会话ID>.json | 当前会话选中的任务、执行者引用及最近活动信息；无全局唯一 current-task 文件 | 首次绑定任务 |
| runtime/leases/<任务ID>.json | 单写者租约的 owner、代次与有效期；具体锁实现另行设计 | 推进任务时 |
| runtime/reminders.json | 本机提醒去重、暂缓时间；删除只影响提醒节奏 | 首次提醒 |

runtime/ 为本机状态，不入库。运行时被删除后，不能仅据此认定执行者已停止或立即重派；应核查底层 worker 状态。跨机器同时修改同一任务的协调不由本地租约自动解决。

已有 docs/architecture.md 或 docs/decisions/ 等时直接引用，不要求迁入 .fstar/ 或双份维护。宿主入口如 AGENTS.md、CLAUDE.md 仅按平台需要添加受管理的入口引用，保留用户原有内容；不属于产品通用目录的强制文件。

## 每个任务：tasks/<任务ID>-<名称>/

| 路径 | 内容 | 创建时机 |
|---|---|---|
| task.json | 稳定 ID、标题、阶段、阻塞/依赖、文档修订与交付版本、证据引用、扩展包授权 extensions[]；由命令更新 | 启用持久任务包 |
| doc/prd.md | 用户问题、目标、范围、验收条件、未决问题 | 启用规划评审包 |
| doc/design.md | 技术边界、数据和接口、取舍、兼容性 | 规划评审包内按需 |
| doc/test-cases.md | 稳定用例 ID、条件/步骤/预期、关联与版本/指纹；开发完成进入 checking 后由 check 据已写代码 + prd 生成逐条目/场景链用例，或用户提供/修改；approved 且新鲜才驱动测试 | 启用测试评审包（用例准备时） |
| doc/review-log.md | 需求变更 / 技术方案变更 / 用例审阅三类事件的变更留痕投影，源自 events[] / evidence[]，不手改 | 相关事件发生时再生 |
| implement.md | 执行步骤、验证方式、检查点与回退安排 | 复杂任务按需 |
| implement.jsonl | 实施时注入的上下文清单：每行 `file` + `reason`；只放 spec/research 文档 | 首次派发前 |
| check.jsonl | 检查时注入的上下文清单，同上格式 | 首次检查前 |
| research/<主题>.md | 本任务调研、来源、结论和未决问题 | 实际调研时 |
| acceptance/check-<序号>.md | 稳定用例 ID → 测试代码/测试标识 → 实际运行命令、结果与证据；含交付/用例版本与指纹、环境、run id；生成用例不等于通过 | 每轮检查 |
| acceptance/acceptance-<序号>.json | 用户验收决定、范围、关联版本/检查报告、时间、可追溯确认来源 | 用户验收时 |
| acceptance/artifacts/<附件> | 必须保留的截图、短日志等；大体积产物优先外部引用 | 按需 |
| subtasks/<子任务ID>-<名称>/ | 子任务使用同样的最小结构，各自 PRD/状态/检查/验收；不复制父任务完整背景 | 实际拆分时 |

implement.jsonl / check.jsonl 沿用 Trellis 已验证的形状（每行 file + reason），fstar 直接采用同一格式，不做适配层转换。注入场景只有「实施」和「检查」两处，不再另立按 role 的 context.jsonl。

事件追踪并入 task.json 的 events[]（阶段变化、租约、文档修订引用），需求变更正文留在 doc/design.md 的修订章节，验收引用落 task.json.acceptance 与 acceptance/acceptance-<序号>.json。不再单独维护 history.jsonl，因此不存在两文件事务一致性难题。验收 JSON 本身不能证明真实用户授权；必须有宿主输入来源或其他可核验的确认记录。证据需覆盖需求/设计/用例修订与实际交付版本（含运行所用测试代码）；用例改动使对应 review/check evidence stale，仅检查文档指纹不足以证明代码未变。

子任务共用状态机和验收闸门；父任务整体检查与验收覆盖子任务组合。无子任务时不创建 subtasks/。检查文件按轮次保留，避免覆盖历史证据。

## 相对上一版的删减

1. 保留独立 rules/ 与 memory/（用户已确认），不采用合并建议。
2. 不单设 project.md：短背景放 index.md，长背景引用已有 docs。
3. workflows/、skills/、templates/ 仅按需创建个人覆盖项。
4. 用户已确认第一版去掉独立 decisions/ 及 decision.md 模板；长期决定与原因写入对应 specs/，任务内取舍留在 design.md 或 research/。已有项目决策文档仅引用，不迁移、不删除。
5. 不预建 specs/frontend/、backend/ 等项目类型目录。
6. 不新增 journal/、workspace/、独立 notes/：任务历史与调研先满足需要。
7. 不复制 channel 的事件日志、worker 状态到 .fstar/runtime/，若使用该运行时只存必要引用。
8. 不把完整 spec/skills/workflows 拷贝到每个项目。

## 最小创建量

- 用户持久内容初始化：index.md、config.yaml、.gitignore；rules/ 在首次确认规则时出现，memory/ 在首次沉淀偏好或经验时出现，运行状态另行按需产生。
- 正式项目初始化：index.md、config.yaml、.gitignore，三个文件。
- 启用持久任务包：task.json；同时启用规划评审包则加 doc/prd.md；事件记录进 task.json 的 events[]，不产生第三个文件。
- 最小闭环（未加载任何扩展包）：**不落任何盘**——不初始化项目、不建任务目录；用户确认保留在会话内（2026-10-28 更新，取代旧「按轻量进入策略决定」）。

## 待用户评审

已确认：用户级 rules/ 与 memory/ 独立。其余精简结构仍为草案，并非整体批准或实施授权。下一项待决策：项目规范与适用的用户级规则冲突时，如何处理项目例外。
