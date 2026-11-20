# 检查报告：worktree-shared-data-root（check-of worktree-impl-1）

- dispatch_id: worktree-check-1
- role: check
- 分支: feat/worktree-shared-data-root
- 日期: 2026-11-20
- 结论: **通过（done）**。全部强制验证通过，未发现缺陷。

## 输入基线核验

16 个 input_versions 全部 `shasum -a 256` 核对一致（prd/design/plan/clarify、AGENTS/CONTRIBUTING、3 个 specs index、routing.md、store.py/project.py/inject.py/installer.py、test_worktree_shared_root.py、README.md）。task.json 未读取（按 dispatch 指示）。

## 强制验证结果

### 1. 全量 Python 套件

- 命令: `PYTHONPATH=src python3 -m unittest discover -s tests -t .`
- 结果: `Ran 806 tests in 107.729s` / `OK`（含新增 18 个 worktree 用例）。

### 2. Node 套件

- 命令: `node --test tests/test_package.cjs`
- 结果: `pass 16 / fail 0`（16/16）。

### 3. R/D 追溯

- **R-001 / D-001（P-001）**：`src/fstar/store.py:70-76`（find_project_root 内 commondir 回溯）、`store.py:80-117`（`_linked_worktree_main_root`：仅 `.git` FILE 形态、gitdir/commondir 读取、realpath 归一、OSError/ValueError 一律回退 None、`main_root == candidate` 排除）；`_pointer_path_matches`（store.py:138+）未改动，bound_path 语义保持。独立验证见第 4 节 (a)(b)(d)。tests/test_worktree_shared_root.py:58-146 覆盖回溯、身份一致、任务可见、未初始化、非 worktree、普通 `.git` 目录、corrupt 回退、pointer 兼容。通过。
- **R-002 / D-002（P-002）**：`src/fstar/project.py:344-376`（`doctor_worktree_report`：共享生效输出「当前 worktree 共享自 <主路径>」；未初始化输出 `uninitialized_init_hint`，project.py:379-386，引导 `fstar init`；非 worktree/显式 --project 返回 None）+ `src/fstar/store.py:120-135`（`worktree_shared_main_root` 纯函数）+ `src/fstar/installer.py:100-111,158-173`（Roots.invoke_root 记录调用目录、`invoke_root=None if project else invoke_root` 使 --project 覆盖不触发报告）+ `installer.py:2508-2515`（doctor `_schema_report` 仅在报告非 None 时挂 storage.worktree，非 worktree 输出字节不变）。README.md:249-268 说明共享行为并给出 doctor 输出示例。
  - **已批准偏差**：doctor 挂接位于 installer.py（Roots/invoke_root 管道）而非计划写的 project.py——协调者已批准，属实现位置偏差而非缺陷；报告内容与验收条件完全一致。
- **R-003 / D-003（P-003）**：三模式回归（tests:202 user-directory、219 tracked、226 pointer 数据根）全量通过；两层影响见第 5 节；README 增补完成；package.json 保持 0.8.0（未发布，符合仓库规范）；manifest 幂等见第 5 节。通过。

### 4. 独立临时 git 仓库验证（隔离 TMPDIR=/tmp/fstar-wt-check.Hl6kOH，GIT_CONFIG_GLOBAL/SYSTEM=/dev/null，未触碰本仓库工作树/真实 ~/.claude/~/.codex/~/.fstar/Magpie）

- **(a) 共享可见性**：`git init` + `fstar init --storage project-local`（.fstar 进 .git/info/exclude）+ `git worktree add` + 主树 `task create --name main-task`；在 worktree 内 `python3 -m fstar task list` 列出 main-task；`find_project_root(wt) == find_project_root(main) == 主树根`；TaskStore 数据根 = 主树 `.fstar`。同一身份/任务/规范。
- **(b) 未初始化零写入**：主树未 init 的 linked worktree 内 `task list` → `project_not_initialized` 错误；doctor 输出 `worktree: {shared:false, message:"未在 <主树> 找到已初始化的 fstar 数据根；…fstar init…"}`；`find -name .fstar` 前后均为 0（零隐式写入）。
- **(c) 非 worktree 一致**：普通 project-local 项目 doctor 输出中 `worktree` 出现 0 次（与现状一致）。
- **(d) 损坏回退**：`.git` 文件写为 "garbage" → 回退现状解析（project_not_initialized，不抛异常）；写为 `gitdir: /nonexistent/xyz` → 同样回退，无异常。
- **(e) doctor 共享来源**：共享生效时 doctor.storage.worktree = `{shared:true, main_root:"<主树>", message:"当前 worktree 共享自 <主树>"}`；主树 doctor 无 worktree 条目；未初始化时见 (b)。

### 5. 两层影响

- 命令: `PYTHONPATH=src python3 -m unittest tests.test_global_resources tests.test_magpie tests.test_installer tests.test_hooks`
- 结果: `Ran 301 tests / OK`（上一任务 host/magpie 批次与既有 Claude 安装路径无回归；全量 806 亦绿）。
- manifest 幂等: 备份 resources/package-assets.json 后 `node scripts/build-package.cjs` 重建，`diff` 完全一致（确定性通过，工作树无残留变化）。

## 已披露残余风险（与实现者披露一致，均不构成缺陷）

- 显式 `--project <worktree-path>` 不共享（保持 pre-change 行为，PRD 未要求覆盖）。
- 直接构造 `TaskStore(worktree_path)` 保留本地布局（解析共享经由 find_project_root 路径生效）。
- user-directory 模式 linked worktree 保持未初始化（按用户确认「只需回归确认无影响」）。

## 最终复查：文档同步（worktree-check-docs-1，2026-11-20）

用户选择「文档同步」处理 P-002 doctor 接线位置偏差，协调者已更新 plan.md 与 design.md。本节记录 doc-sync 后的复查结论；上文 check-1 全部验证结论继续有效。

### 输入核验（16/16 sha256 一致）

与 /tmp/fstar-worktree-check-docs-1-payload.json 逐项核对通过。仅 design.md（2c618c37…）与 plan.md（e3da247a…）较 worktree-check-1 更新，其余 14 项不变。

### 运行交付未变（复用 check-1 证据）

以下文件与 worktree-check-1 输入基线哈希逐一比对，完全相同，故不重跑套件、直接复用 check-1 的全量验证证据（806 Python OK、16/16 Node、独立临时 worktree 场景 (a)-(e)、两层影响 301 OK、manifest 幂等）：

- src/fstar/store.py `dbcb4a4390af53da9608274abc681b7b7b763a302fab798263b93db4fa5090f9`
- src/fstar/project.py `b534caba13f602126c53a0e3ced589c11fbf6919742afaeb00734a5e4ffa65a4`
- src/fstar/installer.py `e39806c18b70ccb3e5fce986201de158aab4f26f8ffdc2afae9df289df858d60`
- src/fstar/runtime/inject.py `e5a0eb8e5409087a22b603417645d1d3f60e9e7bb8b919196ae148009f845406`
- tests/test_worktree_shared_root.py `d4caf31f2760711a5ca31da713ae86985ac91aab1253503b0b66cf91ebbd68f4`
- README.md `1d24e82f9cc6bcdc6656ec6157ec7010304ae83afdca3cea2a7fc0d6741123fa`
- doc/prd.md `a958c8d2d590b016c42bdbcaa174824426cd442fcf8c2f9dff4b209f43a4566d`（PRD 未改，R-002 原文只约束输出内容，与实现位置无矛盾，继续一致）
- 另 AGENTS.md / CONTRIBUTING.md / 3 个 specs index / routing.md / clarify.md 哈希均与 payload 一致且未改。

### 文档一致性核对

- **plan.md**：Files to Change 与 P-002 现明确「辅助函数在 project.py（doctor_worktree_report/uninitialized_init_hint）；接线在 installer.py（Roots.invoke_root 记录执行目录……显式 --project 时为 None；_schema_report 追加条目）」——与交付代码完全一致（installer.py:100-111、158-173、2508-2515；project.py:344-386）。P-001/P-002/P-003、R/D 交叉引用、优先级与依赖关系、slot 注释均保留。无剩余矛盾。
- **design.md**：D-002 新增「实现位置（与实际交付一致）」段落，含为何需要 invoke_root（find_project_root 已把 worktree 折叠到主树根，仅凭 project_root 无法判断从哪里打开）；§7 影响表改为「src/fstar/project.py / installer.py：project.py 报告辅助函数；installer.py 接线（invoke_root + _schema_report）」。D-001/D-003 未改，与代码一致。fstar:item D-001..D-003 标记与头部 slot 完整保留。无剩余矛盾。
- **README.md**：哈希未变（1d24e82f…），check-1 已核对 worktree 章节（README.md:249-268）与 doctor 输出示例准确，继续有效。
- **PRD**：未变；R-002 只约束 doctor 输出内容与非 worktree 输出不变，不指定实现文件，无矛盾。

### 结论

文档同步完成且与交付一致，运行交付零变化，check-1 结论全部成立。P-002 偏差已由「已批准偏差」转为「文档已记录的实际设计」，不再是偏差。状态：通过（done），无缺陷，建议进入验收等待用户确认。

## 结论（check-1）

P-001/P-002/P-003 全部通过；无缺陷；建议进入验收等待用户确认。
