# 工作流内容资产

## 目标与当前授权

将父任务已批准的工作流落实为可安装、可校验的内容资产，使主 Agent、四类执行角色和两宿主共享同一套路由、文档及验证约定。父任务 `../10-25-fstar-workflow-design/{prd,design,implement}.md` 为当前权威，研究稿只补来源。用户已授权第一版全部十个子任务；本轮仅刷新本目录五个规划文件，不启动任务、不写产品、不做 git，不重复审批。

前置依赖为 core-commands 的命令/证据/映射接口与 project-layout 的配置/接入接口。当前允许并行准备内容规划，实施集成须核对上游实际 API。若父 design 的注入被截断，必须用 Read 补齐全文，不能用摘要、旧 policy 或本子设计代替。

## 需求

### WC-01 固定清单与资源归属

交付恰好 **12 skills、4 roles、11 templates**，以及唯一 routing、知识格式参考、模板映射、共享文档检查清单和内容校验模块。源码位于 `resources/{skills,agents,runtime,templates,references}`，校验位于 `src/fstar/content.py`，测试位于 `tests/test_content.py`。安装器以后将源码资源映射为父设计的逻辑发布路径，不将资源复制进项目作为程序。

| 类别 | 完整清单 |
|---|---|
| 核心自动 skills（4） | fstar-execute、fstar-check、fstar-debug、fstar-help |
| 评审后自动 skill（1） | fstar-plan |
| 按授权路由 skills（7） | fstar-init、fstar-clarify、fstar-doc、fstar-continue、fstar-archive、fstar-learn、fstar-tools |
| roles（4） | fstar-research、fstar-implement、fstar-check、fstar-editor |
| doc 模板（2） | prd.md、design.md |
| task 模板（4） | plan.md、clarify.md、research.md、check.md |
| knowledge 模板（3） | rule.md、memory.md、spec.md |
| entry 模板（2） | user-index.md、project-index.md |

mapping、profiles 和 references 不计作产物模板。产品计划为 `plan.md`；本 Trellis 子任务的 `implement.md` 仅是实施准备。

### WC-02 路由与授权

默认最小闭环为澄清→原生 implement→独立 check↔修复→用户确认；不写 fstar 元数据，允许写用户任务需要的交付文件，不退回主 Agent 写生产代码。会话节点不持久化。五包 ID 固定为 `planning-review/persistent-task/multi-agent/project-governance/tool-capability`；各自授权、默认整包可裁剪，一次推荐一个，拒绝后无新事实不重问，已有授权直接复用。基础 implement/check 分离不依赖 multi-agent 包。

routing 只含调用前判断；持久任务三态由 core 命令校验，内容不直写 task.json。回忆是查询知识/归档的路由意图，continue 只恢复当前任务；仅 archive 成功后巡检其他长期未归档任务。help 按实际安装入口只读解释，不推断未安装能力。

### WC-03 文档与实施闭环

- clarify 按证据与决策依赖展开讨论，自行维护 clarify.md，区分事实/建议/确认/未决/被替代结论；复杂依据进 research。默认骨架为背景与目标、开放问题、候选方案与取舍、已确认结论、下一步、相关资料。
- doc 专管 doc/，全部写作交后台 editor，主线程继续讨论。同文件排队，绑定讨论修订和基础指纹，旧稿冲突返回主 Agent 合并/重派。editor 只改指定文件/条目，不自行增删 ID、不裁决需求或批准；回读后由独立 check 做一致性检查。
- 用户评审确认后自动 plan；plan 读取当前有效正文、研究、适用规范及代码/测试，自行维护 plan.md。采用 ECC 七段骨架，补 ID、来源指纹、优先级、依赖、并行条件、逐项完成判据及每组测试/文档责任。影响范围/方案/拆分的未决返回 clarify；无额外 plan 批准。
- execute 只协调，按依赖和文件/共享资源限制派原生 implement，主 Agent 单写 plan 进度。交 check 的范围停止实施写入；对话与文件变更均传导，结果回收重新核对基线。
- check 可自修本范围生产和测试代码，不能修改需求/预期掩盖问题。按影响复查，最后整体检查；报告覆盖条目/plan 项、测试路径和标识、真实命令/环境/run id/基线、修复、耗时及重跑数。通过/失败/阻塞/跳过/未执行明确区分。阻塞或无进展如实返回，必要时 debug；不递归派另一 check 作为自修前置。
- research、plan、check、learn、init 各自维护所属产物，不交 doc 统一落笔。角色卡是执行协议，不能声称安全沙箱。

### WC-04 可替换模板与统一提取

prd/design 采用个人仓库固定提交 `674bea37cf2f6f25cd20dab93e1a54ae1f13ce66`；章节及适配按 `personal-template-review.md`，design 第7章仅“影响范围”，配置和附录顺延第8/9章，profiles 为按需参考。

解析优先级为任务显式指定>项目>用户>安装包默认。语义槽位 `artifact_type/version/review_state/author/date/reviewer`、稳定唯一 ID 与显式关联必须可提取；允许换标题、布局、语言和 ID 写法，缺失/歧义报错，不猜批准。默认映射提供唯一 start/end markers 给 core artifact_map，条目哈希与新鲜度由 core 计算，不能另造边界不同的哈希。记录模板来源/ref/hash；升级模板不追溯改写已有产物。

### WC-05 init、learn 与知识格式

init 先探索整个项目及已有权威资料，缺背景才问，形成真实概况/主题/读取条件/权威路径，调用 project-layout API 后核验导航。已有内容优先引用，不生成臆测规范；工具扫描是独立提案，未确认不绑定，未启用工具包仍能接入。

learn 展示候选内容/来源/归属及冲突；已明确授权直接保存，否则先确认。先查完整索引和适用正文，优先归已有主题，新主题需理由；正文+索引+引用作为一组更新，失败恢复。忙时或复杂整理交通用后台 Agent，小改可直接处理，不新增角色。可选候选暂缓不阻塞合法归档；正确性问题仍需解决。

仅维护 `references/knowledge-format.md` 一份格式说明：rule/memory/spec 共用 `fstar.knowledge.v1`、schema/type/status；rule 必填 strength=enforced|default；memory 必填 kind=preference|lesson、trust=confirmed|unreviewed；status=active|superseded。非法/缺失值报错；superseded/unreviewed 不加载；memory 不自动成为规则。有效适用知识按 enforced rule>项目明确规范>default rule>confirmed memory 裁决，已有权威文档优先，冲突说明。

先读概况、完整索引、全局约束，再完整读取适用主题和上下游/共享契约，注入摘要不能替代正文。skills/routing 英文为主、description 精简中英双语；每条≤200字符、12条正文合计≤2400，宿主名称/分隔成本另算。任务默认中文；rules/memory 英文；specs 默认英文可配置；引用 `language.interaction/artifacts/specs`，不另造语言键。

## 验收标准

- [ ] AC-01：固定清单逐路径校验，无多余 skill/role/产物模板；frontmatter、链接、占位符可检查，description 限额正确。（WC-01/05）
- [ ] AC-02：路由场景覆盖最小闭环、五包独立授权/裁剪/拒绝、评审后自动 plan、回忆和当前任务恢复、archive-only 提醒。（WC-02）
- [ ] AC-03：角色交接和内容审查证明后台 editor、旧稿冲突、原生 implement、独立 check 自修复查与最终整体检查均有明确步骤。（WC-03）
- [ ] AC-04：默认及改标题/语言/ID 写法的自定义模板可提取；缺槽位、重复/缺失边界、重复 ID、坏关联明确失败；core 消费同一 artifact_map，编辑一条不误算其他条目。（WC-04）
- [ ] AC-05：模板固定来源及章节调整可追溯；模板更新不改旧文档，review_state 不替代用户确认。（WC-04）
- [ ] AC-06：知识格式、语言、有效性/冲突及 init/learn 所有权指引一致；索引模板与 ProjectContext 字段兼容。（WC-05）
- [ ] AC-07：校验函数只读，错误可定位；真实 unittest 结果与语义检查结果分开记录，未运行集成不记通过。（全部）

## 范围外与交付依赖

不实现 core 状态/证据/租约/验收事务、project 配置和初始化 IO、hooks、宿主派发适配器、知识加载/原子更新后端、安装器或 doctor 命令。内容模块提供可复用校验 API，接入由对应所有者完成。

不恢复旧 phase、测试用例审批/独立 test-cases、review-log、finish/recall/ui skill、UI 模板、独立历史台账、第五个 hook 或自动 git。当前无新的产品决策阻塞；上游实际 artifact_map 封装、资源版本定位、知识运行时验证及两宿主入口/后台行为仍须在实施集成时核实，详见 design §7。
