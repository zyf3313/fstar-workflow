# 跨仓库任务、项目数据存放与验收阶段实施计划

## Summary

同一任务交付六个关联目标：跨仓库主子协调、各仓库规范加载与初始化、三种数据位置、验收中正式阶段、分支/工作树定位、自然语言确认。旧任务和旧项目必须可读；不发布、不改宿主真实配置。

## Patterns to Mirror

复用 TaskStore 的锁与原子文件写入、TaskService 的确认来源/事件、EvidenceService 的 snapshot 与 freshness、knowledge 的授权写入和索引、runtime 的只读上下文注入、installer 的所有权清单。不得直接改证据 state 或伪造用户命令来绕过核心校验。

## Files to Change

预计涉及 src/fstar 下项目定位/配置/store/任务/证据/dispatch/knowledge/runtime/installer 与对应 tests；resources 下 schema、模板、routing、相关 skills；README；必要时 bin 启动入口兼容；package.json 仅资源版本及 package-assets 重建。实施前完整读取每个受影响模块，不能只改一个入口遗留硬编码路径。

## Tasks

<!-- fstar:item:P-001:start -->
### P-001 项目标识与数据存放

- 来源：PRD R-002（登记时绑定文档快照）及 clarify.md 的已确认模式
- 优先级：P1；依赖：无；并行条件：本批共享基础数据根，不并行修改
- 完成判据：shared/local/user 三种模式实际贯通 CLI、store、config、spec/knowledge、hooks、证据、归档、installer。user 模式无需仓库内 .fstar；同名不同目录互不串数据。稳定 project_id 与路径绑定可查询、可明确重绑。local 模式不改共享 .gitignore，用本机 Git 排除；非 Git 不假装忽略成功。
- 测试责任：implement 添加临时多项目回归；check 验证没有真实用户目录污染、跨根路径/符号链接越界和旧数据兼容。
- 文档责任：README/init skill 说明三种模式与本机路径绑定边界。
<!-- fstar:item:P-001:end -->

<!-- fstar:item:P-002:start -->
### P-002 跨仓库任务协调与上下文

- 来源：PRD R-001/R-003；优先级：P1；依赖：P-001；并行条件：无共享写入并行
- 完成判据：主任务和各仓库任务有稳定双向引用；显式创建/关联/查看，主任务可分发目标任务；目标项目未初始化时明确进入初始化流程。实施者使用目标项目规范、任务文档与权限，不能拿主仓库规范替代。父子循环、重复关联、失联仓库有明确处理。跨项目写入有锁顺序与可恢复机制。
- 测试责任：至少两个真实临时 Git 仓库完成关联、派发、状态查询，含失败/重复/并发场景。
- 文档责任：可执行流程与职责/失败恢复说明。
<!-- fstar:item:P-002:end -->

<!-- fstar:item:P-003:start -->
### P-003 验收中阶段与统一验收

- 来源：PRD R-004/R-005；优先级：P1；依赖：P-001/P-002
- 完成判据：fresh final independent check 成功后进入 awaiting_acceptance，保持 completedAt 为空；失败/过期不进入且不能完成。返工回 planning，重新规划/执行/检查；未归档 completed 可按确认 reopen。统一验收使用一个真实用户确认覆盖明确的主子任务版本，验证全部证据与可达性后写入；部分失败可恢复，不伪装全成功。只读 hook/state 不能偷偷写任务状态。
- 测试责任：阶段/租约/证据失效/父子/归档/重启兼容回归；通过后篡改交付、断连子仓库、子任务未完成等必须拒绝。
- 文档责任：新四态和返工流转、兼容限制。
<!-- fstar:item:P-003:end -->

<!-- fstar:item:P-004:start -->
### P-004 分支绑定与 QA 任务定位

- 来源：PRD R-006；优先级：P1；依赖：P-001/P-003
- 完成判据：创建/启动任务记录实际 branch/worktree/base 信息；不伪造 detached HEAD 分支。显式 ref 优先，session 指针需与当前项目/工作树一致，唯一分支候选可提示/定位。多候选列可识别信息供自然语言选择。完成/归档任务仍可检索用于 QA；归档只能关联 follow-up，不自动解档或重开。
- 测试责任：同名分支不同项目、同 repo 多 worktree、同分支多任务、detached HEAD、完成与归档命中；不得自动切分支。
- 文档责任：自然语言 QA 示例和歧义处理。
<!-- fstar:item:P-004:end -->

<!-- fstar:item:P-005:start -->
### P-005 自然语言交互、影响检查与交付

- 来源：PRD 的交互要求；优先级：P1；依赖：P-001..P-004
- 完成判据：routing/execute/archive/continue/init/prompt-states 以自然语言解释阶段、结果、确认；内部 CLI 保留但默认不要求用户输入命令。修正已有 skill 边界中的循环或错误限制。规范和知识读取不绕过授权。README 与实际行为一致；资源版本升级，manifest 重建。
- 测试责任：实现者跑针对性与全量 Python/Node；独立 check 做调用方和机制交互影响检查、跨项目端到端测试，发现缺陷修复后复测。
- 文档责任：交付报告明确实现/测试/未实测项，不能把文本指令当机械保证。
<!-- fstar:item:P-005:end -->

## Validation

必须使用独立临时 user root/runtime/project，禁止真实宿主配置测试。运行 Python 全量 unittest 和 Node package 套件；新跨项目生命周期用 CLI/API 端到端实测，覆盖本地及 user 数据模式。独立检查原有单项目 minimal loop、知识审批、安装更新卸载、archive/recovery、hook 只读与预算。

## Risks

项目数据根涉及全局路径假设；跨仓库一致性不能依赖一个仓库的 flock；新 phase 会影响 lease、check 和归档条件；分支名不唯一；只读 hook 不得成为状态机写入口；用户授权必须绑定交付版本，不可复用历史验收制造新同意。

## Acceptance

用户以自然语言确认本次交付后由协调者记录 conversation 来源并执行验收。未确认前保持验收中，不代替用户确认，不合并本新分支、不发布。
