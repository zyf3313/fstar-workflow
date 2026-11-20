<!-- fstar:slot:artifact_type:start -->design<!-- fstar:slot:artifact_type:end -->
<!-- fstar:slot:version:start -->0.1<!-- fstar:slot:version:end -->
<!-- fstar:slot:review_state:start -->draft<!-- fstar:slot:review_state:end -->
<!-- fstar:slot:author:start -->FrancisZhang<!-- fstar:slot:author:end -->
<!-- fstar:slot:date:start -->2026-11-20<!-- fstar:slot:date:end -->
<!-- fstar:slot:reviewer:start --><!-- fstar:slot:reviewer:end -->

# 技术设计：工作树共享项目数据根与规范

## 1. 理解与范围

在 `store.py`（`find_project_root`、`_pointer_path_matches`、STORAGE_MODES）与 `project.py` 既有 worktree 指针处理之上，实现 linked worktree 沿 git commondir 共享主工作树 `.fstar` 数据根。全部共享（含任务数据）；自动生效；doctor 报告共享来源；user-directory 模式回归确认。

## 2. 总体技术方案与全景流程

解析流程：`find_project_root(start)` 向上查找时若命中 linked worktree 的 `.git` 文件（内容 `gitdir: <main>/.git/worktrees/<name>`），读取该 gitdir 的 `commondir`（相对路径，如 `../..`）解析出主仓库 gitdir → 主仓库 gitdir 的父目录即主工作树根 → 若 `<主工作树根>/.fstar/.schema-version` 存在则数据根取主工作树的 `.fstar`（project_root 也解析为主工作树根，保证任务、规范、身份一致）；不存在则维持"未初始化"错误路径并引导 `fstar init`。非 worktree 或普通 `.git` 目录场景完全走现状逻辑。`commondir` 读取失败按无 commondir 处理回退现状。文本等价：无图；流程以本节与 R-001 验收条件文字覆盖。

## 3. 实体、状态与存储结构

- 无新增持久化实体；共享是解析期行为，不写任何指针/登记文件。
- `TaskStore` 的 project_root/user_root/runtime_root 解析结果在共享场景下与主工作树完全一致。
- doctor 报告为只读输出，不新增配置键。

## 4. 模块技术设计

<!-- fstar:item:D-001:start -->
### D-001 数据根解析沿 commondir 回溯（R-001）

机制：`find_project_root` 在识别 `.git` 文件形态时新增一步——读取 gitdir 文件得到 worktree gitdir，读取其 `commondir` 文件（若存在）解析主 gitdir（`os.path.realpath` 归一），主 gitdir 父目录即主工作树根；主工作树 `.fstar/.schema-version` 存在则以主工作树为 project_root 返回，否则继续现有行为（返回未初始化/原 worktree 路径，由调用方报未初始化引导 init）。`_pointer_path_matches` 的 bound_path 语义不动：指针仍只绑定其写下的路径。失败与兼容：gitdir/commondir 读取任何异常（OSError/格式不符）都回退现状解析，不抛出；symlink/realpath 差异以 realpath 归一为准。
<!-- fstar:item:D-001:end -->

<!-- fstar:item:D-002:start -->
### D-002 doctor 共享报告（R-002）

机制：doctor 在 project-local 模式下检测当前 project_root 是否来自 commondir 回溯（解析层返回共享来源路径或在 store 上暴露判定辅助），是则输出"当前 worktree 共享自 <主工作树路径>"信息项；主工作树未初始化的报错文案引导 `fstar init`。健康判定不变。实现位置（与实际交付一致）：报告辅助函数 doctor_worktree_report / uninitialized_init_hint 位于 project.py（纯报告逻辑）；接线位于 installer.py——`Roots.invoke_root` 记录命令执行目录（find_project_root 已把 worktree 折叠到主树根，仅凭 project_root 无法判断"从哪里打开"），`_schema_report` 追加 worktree 条目，显式 `--project` 时 invoke_root 为 None 以保持既有输出。失败与兼容：判定辅助为纯函数；非共享场景输出不变。
<!-- fstar:item:D-002:end -->

<!-- fstar:item:D-003:start -->
### D-003 测试、回归与文档（R-003）

机制：测试用真实临时 git 仓库 + `git worktree add`（subprocess，隔离 TMPDIR），覆盖：主树有 `.fstar`（project-local 模式，git exclude 排除）时 worktree 内 locate/task 可见性与主树一致；主树无 `.fstar` 时 worktree 内报未初始化；非 worktree 项目零行为变化；user-directory 模式回归；本仓库 tracked 模式回归；两层影响检查（上一任务 host/magpie 交付路径 + 既有 Claude 安装回归）。README 增补 worktree 共享行为说明。发布：版本/manifest 同步按仓库规范。失败与兼容：所有新路径失败回退现状，不阻断既有安装/命令。
<!-- fstar:item:D-003:end -->

## 5. 专项技术设计（按实际类型选择）

纯文件读取解析（gitdir/commondir 均为普通文件）；无子进程依赖；无超时需求。

## 6. 迁移、发布与回滚

- 迁移：无数据迁移；共享即时生效于解析层。
- 发布：README/版本/manifest 同步；回滚即代码回退，无状态残留。

## 7. 影响范围

| 项目模块 | 受影响功能或范围 | 本次改动及影响 |
|---|---|---|
| src/fstar/store.py | find_project_root/数据根解析 | linked worktree 沿 commondir 回溯主工作树；其余场景零变化 |
| src/fstar/project.py / installer.py | 状态报告 | project.py 报告辅助函数；installer.py 接线（invoke_root + _schema_report）；共享来源信息项与未初始化引导文案 |
| src/fstar/runtime/inject.py | locate 注入 | 共享数据根下行为与主工作树一致（无逻辑改动，验证） |
| tests/、README.md | 回归与文档 | worktree 共享用例组 + 三模式回归 + README |

## 8. 配置与字典（适用时）

无新增配置；行为自动生效。既有 FSTAR_ 测试隔离环境变量不变。

## 9. 附录、评审与版本

设计撰写时已核实：git worktree 的 `.git` 文件与 `commondir` 文件格式（git 标准布局）；`find_project_root` 现状行为（store.py:54）。版本 0.1，draft，评审人空。
