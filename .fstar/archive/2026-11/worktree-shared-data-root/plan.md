# 工作树共享项目数据根与规范计划

## Summary

linked worktree 自动沿 git commondir 共享主工作树 `.fstar` 数据根（全部共享含任务）；主树未初始化则引导 init；doctor 报告共享来源。来源：clarify.md 用户确认（2026-11-20）。

## Patterns to Mirror

复用 store.py 既有 `.git` 文件识别与 pointer 安全语义、project.py worktree 处理、隔离临时 git 仓库测试模式。

## Files to Change

src/fstar/store.py、src/fstar/project.py（doctor 报告辅助函数）、src/fstar/installer.py（doctor 接线：Roots.invoke_root 管道与 _schema_report 条目——实际报告中 doctor 结构在 installer 组装，project.py 只放纯辅助）；tests/（新增 worktree 共享用例 + 三模式回归）；README.md、package.json、resources/package-assets.json。不写真实宿主配置。

## Tasks

<!-- fstar:item:P-001:start -->
### P-001 数据根沿 commondir 回溯（R-001/D-001）
`find_project_root` 识别 linked worktree 的 `.git` 文件后，读 gitdir 与 commondir 解析主工作树根；主树 `.fstar/.schema-version` 存在则以其为 project_root/数据根，否则维持未初始化引导。gitdir/commondir 读取异常一律回退现状解析。pointer bound_path 语义不动。测试：临时 git 仓库 + `git worktree add`，主树有/无 `.fstar` 两分支、异常回退、pointer 兼容。优先级 P1，依赖无。
<!-- fstar:item:P-001:end -->

<!-- fstar:item:P-002:start -->
### P-002 doctor 共享报告（R-002/D-002）
doctor 在共享生效时输出"当前 worktree 共享自 <主工作树路径>"信息项；未初始化文案引导 `fstar init`；健康判定与非 worktree 输出不变。实现位置：报告辅助函数在 project.py（doctor_worktree_report/uninitialized_init_hint）；接线在 installer.py（Roots.invoke_root 记录命令执行目录——find_project_root 已把 worktree 折叠到主树根，只有执行目录能判断"从哪里打开"；_schema_report 追加条目，显式 --project 时为 None 保持既有输出）。测试：共享/非共享/未初始化三场景 doctor 输出。优先级 P1，依赖 P-001。
<!-- fstar:item:P-002:end -->

<!-- fstar:item:P-003:start -->
### P-003 回归、两层影响与文档（R-003/D-003）
三类存储模式回归（project-local 共享、user-directory 无影响、tracked 零变化）；两层影响检查（上一任务 host/magpie 交付路径 + 既有 Claude 安装回归）；全量 Python + Node + manifest 幂等；README 增补 worktree 共享行为。优先级 P1，依赖 P-001、P-002。
<!-- fstar:item:P-003:end -->

## Validation

真实临时 git 仓库 + `git worktree add`（隔离 TMPDIR）；不动本仓库工作树；fake/真实宿主零接触。

## Risks

commondir 格式差异（子模块/绝对路径）；realpath 归一与 symlink；共享任务数据带来的并发写（既有 lease 机制覆盖）。

## Acceptance

完整检查后进入验收中，等待用户确认；不自动提交合并发布。
