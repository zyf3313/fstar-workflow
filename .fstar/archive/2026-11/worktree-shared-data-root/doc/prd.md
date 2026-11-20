<!-- fstar:slot:artifact_type:start -->prd<!-- fstar:slot:artifact_type:end -->
<!-- fstar:slot:version:start -->0.1<!-- fstar:slot:version:end -->
<!-- fstar:slot:review_state:start -->draft<!-- fstar:slot:review_state:end -->
<!-- fstar:slot:author:start -->FrancisZhang<!-- fstar:slot:author:end -->
<!-- fstar:slot:date:start -->2026-11-20<!-- fstar:slot:date:end -->
<!-- fstar:slot:reviewer:start --><!-- fstar:slot:reviewer:end -->

# 产品需求文档：工作树共享项目数据根与规范

> 来源：任务 clarify.md（用户原话、2026-11-20 核实事实、用户对 4 个开放问题的确认）。上一任务 host-abstraction-magpie-router 已归档，与本任务无耦合。

## 1. 背景与范围

用户场景（原话）：创建一个工作树不会把之前那个项目沉淀的 fstar 文件夹下的规范都带过去，因为 git 忽略提交的文件被忽略了，新开的工作树没有带过去。project-local 存储模式下 `.fstar/` 不进版本库，linked worktree 内完全没有规范/索引/身份。现状 `find_project_root` 识别 linked worktree 的 `.git` 指针后以该 worktree 自身为 project_root，不回溯主工作树。

用户确认（2026-11-20）：linked worktree **自动**共享主工作树 `.fstar` 数据根（全部共享，含任务数据）；主工作树也没有 `.fstar` 时报未初始化并引导 `fstar init`，不隐式写入；doctor 如实报告共享来源；user-directory 模式只需回归确认无影响。

<!-- fstar:item:R-001:start -->
### R-001 数据根沿 commondir 共享

- 业务结果：检测到 linked worktree（`.git` 为文件指向 `<main>/.git/worktrees/<name>`）时，数据根解析沿 git commondir 回溯到主工作树根，取其 `.fstar` 作为本 worktree 的项目数据根；规范、索引、身份与任务数据全部共享一份。
- 模块与优先级：store/project 解析层，P1。
- 范围：`find_project_root` 及 TaskStore 数据根解析；主工作树 `.fstar` 存在即启用共享；`.fstar-pointer.json` 既有 bound_path 安全语义不变。
- 不做：不复制 `.fstar`；不放宽 pointer 匹配语义；不改 user-directory 模式行为。
- 验收条件：Given project-local 模式主工作树已 init 且有规范，When 在其 linked worktree 内运行 fstar 命令，Then 读取的是主工作树 `.fstar`（同一身份、任务可见、规范一致）；Given 主工作树无 `.fstar`，When 在 linked worktree 内运行，Then 报未初始化并引导 `fstar init`，不隐式写入。
<!-- fstar:item:R-001:end -->

<!-- fstar:item:R-002:start -->
### R-002 自动共享与 doctor 报告

- 业务结果：共享为自动行为，无新增显式开关；`fstar doctor` 在共享生效时如实报告"当前 worktree 共享自 <主工作树路径>"，主工作树未初始化时给出引导提示。
- 模块与优先级：doctor，P1。
- 范围：doctor 输出新增共享来源信息；不改变既有健康判定。
- 不做：不新增 CLI 开关；不改变非 worktree 场景的 doctor 输出语义。
- 验收条件：Given 共享生效，When doctor，Then 输出共享来源路径且判定与主工作树一致；Given 非 worktree 环境，When doctor，Then 输出与现状相同。
<!-- fstar:item:R-002:end -->

<!-- fstar:item:R-003:start -->
### R-003 存储模式回归与文档

- 业务结果：project-local、user-directory、本仓库 tracked 三类场景回归通过：user-directory 与 tracked 模式行为与现状一致；README 说明 worktree 共享行为与未初始化引导。
- 模块与优先级：tests / docs，P1。
- 范围：全量 Python + Node + manifest 幂等；真实临时 git 仓库 + `git worktree add` 验证，不动本仓库工作树。
- 不做：不自动验收提交合并发布。
- 验收条件：Given 三类存储模式测试与隔离 worktree 验证通过且两层影响检查无回归，When 实施完成，Then 进入验收等用户确认。
<!-- fstar:item:R-003:end -->

## 2. 业务流程

角色：fstar 用户、git worktree（linked）、主工作树。

共享流程（目标）：命令启动 → locate/find_project_root 解析 → 检测 `.git` 为文件 → 读 commondir 定位主工作树 → 主工作树 `.fstar` 存在则以其为数据根（doctor 报告共享来源）→ 不存在则报未初始化并引导 init → 非 worktree 场景维持现状。

## 3. 模块与逐功能要求

- store：`find_project_root`/数据根解析识别 linked worktree 并沿 commondir 回溯；pointer 安全语义不变。
- project/doctor：共享状态报告与未初始化引导；不影响既有诊断。
- runtime/inject：共享数据根下注入与任务可见性与主工作树一致。

## 4. 跨模块要求与影响

- 兼容：非 worktree 项目行为零变化；上一任务（host 抽象/Magpie）交付路径不受影响（两层影响检查）。
- 非功能：gitdir/commondir 为普通文件读取，无新增子进程依赖；解析失败回退现状，不中断基础命令。

## 5. 待确认、评审与版本

- 无产品阻塞。版本 0.1，draft，评审人空。文档完成不等于实现、检查或用户验收。
