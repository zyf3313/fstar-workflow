# S-5 独立检查报告（最终检查）

- dispatch_id: s5-check-001
- 检查者：fstar-check 全新实例（read_only，零改动；检查前后 git status 均为 49 条、交付指纹前后一致）
- 对照规格：[s5-spec.md](../s5-spec.md) S5-A01..S5-A10
- 实施派发：s5-implement-001
- environment: macOS Darwin 27.0、python3、node v24.14.0、分支 chore/general-workflow-design
- baseline: HEAD 6032b52365926104b07154b1358fd5a733718084 + S-1..S-5 未提交工作树
- measured duration / retries: Python 全量 906 tests / 110.0s（OK，1 次）；node --test 16/16 / 8.5s；build-package ×2 幂等；/tmp 探针约 10 次运行（3 次为探针自身时钟/租约构造问题修正后重跑，非交付缺陷）

## 基线核对（独立重算，全部一致）

- s5-spec.md sha256 = aabfac3e158c9920be4f6ed53cb96afa3969a1da401a348e181bdfd4790844ee，与派发值一致（实施者曾误报不符，协调者与本检查均复核一致）。
- 派发所列 11 个文件指纹逐一重算全部匹配（capability_adapters.py 81d2a13c…、dispatch.py 9398f96b…、hooks.py 3bef0241…、installer.py 842c5552…、magpie.py 0eda775f…、routing.md 8400d271…、prompt-states.md d8e13347…、capabilities.md 8206eb19…、fstar-execute/SKILL.md 9e03c615…、package-assets.json 45375d1b…）。
- git diff HEAD -- src/fstar/magpie.py 为空：magpie.py 确实零改动。
- 角色卡/测试文件独立指纹：fstar-implement.md 8f9c6bc2…、fstar-check.md e5f3d50e…、fstar-editor.md 83fc191e…、fstar-research.md adca7934…、test_skill_routing.py 60d6dc19…、test_capability_adapters.py d4d5f8b6…、test_dispatch.py 8494ab34…、test_hooks.py 46e52cef…、test_magpie.py 674f7c9d…；资源类与 package-assets 内嵌哈希一致，manifest 重生成 64/64 匹配，内部自洽。

## 逐条结果（S5-A01..A10）

| 条目 | 协议/可用性 | 真实宿主 |
|---|---|---|
| S5-A01 点名技能 | passed（user-named 来源、prompt 渲染、理由必填） | 未验证 |
| S5-A02 逐轮提醒 | passed（四状态 + no_task + completed/dropped 全带 `<skill-reminder>`，原 `<prompt-state>` 仍在；降级保留提醒；未初始化项目零写盘；轻量单文件读 ≤12 行无扫描） | **已验证**（见下） |
| S5-A03 无匹配/多候选 | passed（空列表合法、选择惰性不扩权、routing 无匹配不阻断与 C-23 一致） | 未验证 |
| S5-A04 派发传递与回执 | passed（两条 harvest 路径探针实测：persistent 落 evidence 溯源且明示 "not verified by harvest"；session-only 携带 skill_usage；旧形状兼容；not_used/failed 缺 reason 三层拒收） | 未验证 |
| S5-A05 防递归/不扩权 | passed（状态分离、failed 不报成功、反递归文本三处一致） | 未系统验证 |
| S5-A06 能力接口合同 | passed（fake adapter 四类输入 + 调用次数 + 零副作用；结果无 authorized/granted） | —（fake 合同为规格指定的验证方式） |
| S5-A07 缺席降级 | passed（四类降级与规格逐字对应；空注册表核心流程正常；无调度器/herdr/第二知识权威） | — |
| S5-A08 Magpie 适配 | passed（installer 经 adapter 透传参数与直调一致；native_only 绕过 probe；magpie.py 零 diff） | — |
| S5-A09 无绑定/无推理 | passed（Python 侧零关键词路由/意图推理/全盘扫描/自动安装；content.py 的 skills glob 为安装期完整性校验，既有行为） | — |
| S5-A10 测试与分层 | passed（906 OK、16/16、幂等、manifest 64/64；未测项如实保留） | — |

## 真实宿主证据（分层）

- **已验证**（来源：协调者会话观察 + 本检查独立复现成因）：协调者会话 UserPromptSubmit hook 确实注入新技能提醒，注入的是降级短句（与 SKILL_REMINDER_DEGRADED 逐字一致）。成因：宿主注册的两条 prompt-context hook 之一指向仓库 bin/fstar-hook.cjs（含 S-5 代码），而全局资源仍为 v0.9.0（prompt-states.md 无 [skill-reminder] 标签），故真实宿主走"新代码 + 旧资源"降级路径且提醒未丢——A02 降级半边的活证据。完整长版需 install/update 新版本后生效（发布未发生，符合规格）。
- **未验证**（不以 fixture 冒充）：A01 宿主点名实际调用、A03 宿主无匹配/多候选、A04 真实 worker 补选并用技能、A05 连续回合案例。

## 影响面（第二层）

- 提醒与状态块同走 inject.resource_root()（同文件同信任级），无新信任面；prompt_context 输出本就不计预算（S-5 前亦然），约 700 字符/轮，非回归。
- acceptance_status/_validate_current/compact_events/_validate_archive_tree 均不消费 validation_facts 文本或 skill_usage_reported 新字段，无误消费路径。
- package-assets 64/64 与磁盘一致；capability_adapters 全模块无 IO 写原语，mutating 仍只在既有 install/update 调用点。

## Repairs and reruns

无修复，零改动。探针在 /tmp/s5-check-probe-* 运行；其中 /tmp/s5-check-probe-87143 因权限未删成，仅含探针脚手架，可手动删除。

## Uncovered scope and blockers

无"必须修复才能验收"问题。建议改进（不阻断）：

1. prompt_context 中 installer.resources_root 自身抛异常（损坏 pin 的既有"诚实报错"设计）会穿透 hook 退出 1 而非降级——S-5 前后一致非回归，建议被动入口层捕获。
2. 下次 install/update 后补记完整长版提醒的宿主观察，闭合 A02 非降级半边。
3. A01/A03/A04/A05 宿主语义场景在后续真实任务中自然发生时补录。

## 三线检查结论

- 理解线：十条标准语义与实现对应清楚。
- 符合线：全部 passed，无 failed/blocked。
- 可用线：全量回归、独立探针、幂等、manifest 一致性全部通过。

结论：S-5 协议与可用性已验证、真实宿主语义部分未验证（清单如上），可进入用户验收流程。
