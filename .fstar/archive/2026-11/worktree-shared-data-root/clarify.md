# 澄清：工作树共享项目数据根与规范

## 背景与目标

用户原话（2026-11-20）：
> 对了在开发过程中还遇到了个场景就是创建一个工作树不会把之前那个项目中的沉淀的fstar文件夹下的规范都带过去因为是git那个忽略提交的那个文件就忽略了 所以新开个工作树就没有带过去有没有办法去解决这个场景呢

用户后续指令：
> 这个问题你先创建一个修复的任务 然后 等当前任务做完了开这个任务

即：本任务独立建立，等 `host-abstraction-magpie-router` 验收完成后再启动实施。

## 已核实事实（2026-11-20，codebase 与 git 对照）

- 本仓库 `.fstar/specs`、`.fstar/tasks`、`.fstar/archive` **都在版本控制内**（`git ls-files .fstar` 共 184 个跟踪文件）；仅 `.fstar/runtime/`、`.fstar/*.local.yaml`、`.fstar/.identity` 被忽略（根 `.gitignore` 与 `.fstar/.gitignore` 双重规则）。因此**本仓库**新开 worktree 不受影响。
- 受影响的是 **project-local 存储模式**的项目：`.fstar/` 通过 `.git/info/exclude`（或仓库 `.gitignore`）排除，不进版本库——这正是"不想上传到仓库"的用户所选模式，代价是新 worktree 内完全没有 `.fstar`，规范/索引/身份全丢。
- `src/fstar/store.py:54 find_project_root(start)` 已能识别 `.git` 为**文件**（linked worktree 指针）的形态：向上查找 `.fstar/.schema-version` 或 `.fstar-pointer.json`，命中即返回该 worktree 自身为 project_root；**不会**沿 git commondir 回到主工作树。
- `src/fstar/store.py:_pointer_path_matches` 明确要求指针的 `bound_path` 与当前 project_root 解析后一致才生效（"指针不跟随仓库搬家"），worktree 路径不同 → 即使放指针也不匹配。
- `src/fstar/project.py` 已有 git worktree 指针处理逻辑（project-local 模式用 local exclude），基础设施可复用。
- `src/fstar/runtime/inject.py:370 locate()` 只做 `find_project_root` → `TaskStore(project, user_home, runtime_root)`，没有任何跨 worktree 回溯。
- 上一批 `cross-project-task-lifecycle` 的 P-004 已实现"跨 worktree 查任务"（能定位兄弟 worktree 的任务），但**"新 worktree 自己没有 .fstar"**这一缺口未堵。

## 候选方案与取舍

**方案 A（推荐）：linked worktree 沿 git commondir 共享主工作树数据根**
- 检测到 `.git` 是文件且内容指向 `<main>/.git/worktrees/<name>` 时，解析 `commondir` → 主工作树根 → 取其 `.fstar` 作为数据根。
- 优点：规范/索引/身份只维护一份，任何 worktree 打开即用，天然杜绝双份规范漂移；改动集中在 `store.py` 数据根解析。
- 代价：worktree 内的任务数据也共享（任务在主树可见），需要与"各 worktree 独立任务"的产品预期对齐；若用户希望任务各自独立，则规范共享 + 任务本地化需要两套路径。

**方案 B：新 worktree 自动复制一份 .fstar**
- 优点：完全隔离，语义简单。
- 代价：产生双份规范必然漂移；与"沉淀的规范只维护一份"的诉求相悖。

**方案 C：写 `.fstar-pointer.json` 指向主工作树数据根**
- 现状 `_pointer_path_matches` 会因 `bound_path` 不匹配而拒绝解析，需要放宽语义（允许 worktree 族共享），属于对既有安全约束的放宽，风险高于 A。

## 已确认结论

- 方案方向以 A 为主（用户已在上一轮对话中被告知"最顺手的实现路径是扩展 find_project_root/store 的数据根解析——检测到 linked worktree 时沿 commondir 回溯主工作树的 .fstar，主工作树没有再回退当前行为（报未初始化并引导 init）"）。
- 本任务与 `host-abstraction-magpie-router` 无耦合，独立分支、独立验收；按用户指令在其完成后再启动。

## 开放问题（2026-11-20 用户已确认）

1. **任务数据是否也共享**：**全部共享**（方案 A 整体共享数据根；规范/索引/身份/任务都维护一份，任何 worktree 打开即用）。
2. **主工作树也没有 `.fstar` 时的行为**：**报未初始化并引导 `fstar init`**（与现状一致，不隐式写入）。
3. **是否需要用户显式开关**：**自动共享 + doctor 如实报告**（检测到 linked worktree 即共享，doctor 报告"当前 worktree 共享自 <主工作树路径>"，无需 `--worktree-shared` 类开关）。
4. **user-directory 存储模式**：数据在 `~/.fstar`，与 worktree 无关；本任务只需回归确认无影响。

## 下一步

1. ~~待 `host-abstraction-magpie-router` 验收完成后启动本任务~~（该任务已于 2026-11-20 验收合并归档，本任务已在 `feat/worktree-shared-data-root` 分支启动）。
2. ~~开放问题确认~~（已确认，见上）。
3. PRD/design（R-001..R-00N）→ plan → implement → 独立 check → 用户验收。
4. 验证用真实临时 git 仓库 + `git worktree add` 建临时 worktree，不动本仓库工作树。

## 相关资料

- `src/fstar/store.py`（`find_project_root`、`_pointer_path_matches`、`_safe_pointer_data_root`、`STORAGE_MODES`）
- `src/fstar/project.py`（既有 git worktree / local exclude 处理）
- `src/fstar/runtime/inject.py:locate`
- 本仓库 `.gitignore`、`.fstar/.gitignore`
