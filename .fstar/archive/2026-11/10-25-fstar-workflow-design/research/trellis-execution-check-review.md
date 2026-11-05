# Trellis 规范加载、派发及 check 耗时核查

日期：2026-10-29。规划调研，不授权实现。

## 用户本轮明确要求

- execute/check 以 Trellis 的流程为参考。
- 执行完全交给子 Agent，去掉工作流层的 inline/subagent 切换设置；主 Agent 负责讨论与协调。
- plan 明确可并行工作，由主 Agent 派多个实施子 Agent；plan.md 展示正在执行的工作。
- 重点核查规范加载时机，以及 check 常耗时 20 分钟以上的可能原因。

## 本地证据

- `.trellis/config.yaml:113-130`：当前 Codex 默认 auto，派发 implement/check/research；inline 是显式选项，旧 sub-agent 是 auto 的别名。不能将用户旧版体验推断为当前版本默认值。工作流开关与宿主是否提供子 Agent 能力是两回事。
- `.trellis/workflow.md:396-435`：规划 1.3 整理 implement.jsonl/check.jsonl，启动前要有真实规范/调研条目。
- `.claude/settings.json:38-58`：Task/Agent 调用前运行 inject-subagent-context.py。
- `.claude/hooks/inject-subagent-context.py:483-589`：读取角色 jsonl 所列资料，再注入 prd/design/implement；空清单会要求子 Agent 补读规范。check 同理（592 起）。注入有大小预算，超限可能截断或变成路径索引。
- `.claude/agents/trellis-implement.md:19-24`、`trellis-check.md:19-24`：根据注入标记区分已加载与自行读取 fallback；不能重复全量加载，也不能把注入标记当成截断内容已完整读取。
- `.claude/skills/trellis-before-dev/SKILL.md:10-51`：读取任务依据、发现包/层、读相关索引的 Pre-Development Checklist、再读实际规范及共享指南；写代码前必做。workflow 的 inline 路径显式调用该 skill；子 Agent 路径通过注入与角色加载实现。
- `.claude/skills/trellis-check/SKILL.md:19-41`：检查前按变更范围读索引 Quality Check 及具体规范；运行 lint/typecheck/tests。
- `.trellis/workflow.md:568`：最后一轮覆盖全部受影响包，区别于中间局部检查。

## check 慢的源码可解释因素（未测量，非用户现场根因）

1. agent 角色卡使用完整未提交 git diff，未明确本轮计划项范围；多轮积累变更可能反复审查。
2. implement 和 check 均要求 lint/typecheck；check 自修后再跑，验证成本可能叠加。
3. check 是审查+直接修复+验证循环（agent 第 35-84 行），不是只读审查。迭代次数未在该角色卡明确封顶。
4. agent 与 skill 的规则有差异：agent 强调直接自修，skill 限机械局部修复，设计判断需停下；后者还有测试、跨层、复用与规范同步。不能把两者检查范围混为一谈。
5. 注入任务全套资料和规范有阅读成本；角色正文又多次要求读取，存在重复读取诱因，但是否发生需会话日志证明。
6. 测试本身、环境启动、模型响应、工具等待的耗时需实测，不能由静态指令判断比例。

## 公开资料

- https://github.com/mindfold-ai/Trellis/issues/240 （closed）：Trellis 0.5.4/Codex 子 Agent 被注入工作流带偏，执行无关任务初始化并等待。证明曾存在跑偏/等待问题，不能当作当前 check 的根因。本地角色卡已有递归保护。
- https://github.com/mindfold-ai/Trellis/issues/238 （closed）：0.5.3 的 Codex 配置兼容问题，含 min_wait_timeout_ms=480000 示例；等待参数不等于每次强制空等 8 分钟。
- https://github.com/mindfold-ai/Trellis/blob/main/.claude/skills/trellis-meta/references/claude-code/ralph-loop.md ：参考文档描述 SubagentStop 重跑 verify 并最多 5 轮阻止停止，单命令超时 120 秒。本地项目 settings.json 未注册 SubagentStop，不能把该机制归因为本项目耗时；上游参考文档存在也不等于所有发行版启用。
- GitHub issue 搜索 `repo:mindfold-ai/Trellis is:issue check slow` 无结果，不宣称已找到普遍 20 分钟问题。

## fstar 适配建议（除用户明确要求外待核对）

- 不新增必须手动触发的规范加载 skill；execute 派发前选择规范，implement/check 开始前确认已读取适用正文。切换模块或规范变更时补读。
- 按项目 specs 主题归口规则选资料，不照搬包/前后端目录；按当前分工给子 Agent 必要上下文。
- plan.md 由主 Agent 协调更新执行进度，工作者回报不并发改同一计划；显示计划项、依赖、状态、执行者和结果摘要。规划内容仍由 plan 负责，执行进度由 execute 维护；详细状态字段留设计。
- 并行仅在依赖、写入范围与共享资源允许时派发，不等于另建自动依赖调度器；宿主子 Agent 能力缺失不能靠删配置解决。
- 中间检查约束到本轮工作及关联影响，最终检查覆盖完整需求；复查围绕修复与受影响验证展开。
- 记录上下文准备、审查、测试/构建、修复复查的耗时，先区分模型与命令耗时，再优化；通过后无新变化/发现不要反复重跑。

## 已解决：check 自修权限（2026-10-29）

用户明确「check 也可以直接修改代码」，撤销此前 fstar check 禁改生产代码、生产缺陷必须交 implement 的限制。check 可在已确认任务范围内直接修复生产代码和测试代码，修复后验证并报告。需求或方案变化仍返回主 Agent 讨论；实施与检查角色分离以及用户验收保留。
