# check-final-impact-001：发布前最终影响检查（只读）

- 检查者：独立 fstar-check，只读，changed_paths: []。隔离根 /tmp/fstar-impact.tkqrlF。
- 基线：package-assets.json b8a186da… 起止未变；git status 前后一致（39 条）。

## 核对结论

| 项 | 判定 | 依据 |
|---|---|---|
| 非 linked 普通项目不被误伤 | 通过 | ensure_writable_layout 对非 worktree 直接返回（store.py:293-298）；身份稳定全放行；三种模式生命周期用例覆盖 |
| 旧合法调用方不被新校验破坏 | 通过 | 旧 payload not_applicable；旧 evidence root 默认 project 同旧行为；session-only/持久两路径过；ROLES 扩 5 个三处同源一致 |
| 锁超时语义 | 通过 | transaction 轮询语义与 HEAD 一致，本轮只加锁前后复查；crossproject 异常路径关流+锁后复查，-W error::ResourceWarning 无告警 |
| cross_project_locks 新复查点 | 通过 | 身份未变放行、可重试用例过 |
| rebind 拒绝语义 | 通过 | 仅拒身份分裂等四种情况，普通移动仍成功；锁序统一项目→注册表 |
| 资源清单 | 通过 | 64 项哈希逐条与文件一致；rv11 与 package.json、cli 0.11.3 一致；fstar-learn agent 卡在清单 |
| dispatch×transaction×身份组合 | 通过 | 双重复查自洽；checkout 越权显式拒绝有测试 |

抽样复跑 427 项（worktree 41、cross+dispatch 128、e2e/installer/integration 209、learning/misc 49）全过。

## 发现

- 【中低，组合才会出现】`project_file`/`_project_layout` 的"仓库本地 .fstar 优先"规则不限 worktree：user-directory（指针）项目若仓库里残留早期 project-shared 的 .fstar/.schema-version+specs，会形成任务读 data root、知识/spec 读仓库残留的分裂读面，且不会放行拦截（非 worktree 主检出 store.py:296-297 直接放行）。本轮测试未出现该场景。建议后续：doctor 报告该残留（已记遗留）。
- 【低，性能】每次写路径布局复查重建 TaskStore；tracked shared worktree 每次 _shared_worktree_layout 跑 2 个 git 子进程，一次 transaction 至少 2 次+各写入口再加。正确性无问题，大批量写会变慢。
- 【低，交付完整性】resources/agents/fstar-learn.md 等 6 个未跟踪文件（agents 卡 + 5 个新测试文件）已被清单引用/要求，**提交交付集时必须一并 git add**，否则清单校验破裂。

## 未覆盖

Node 16 项与 Python 全量 1115 项由协调方已跑（本检查未复跑）；真实宿主钩子阻断效果、installer 迁移手工场景、大仓库 git 耗时未实测。

结论：本轮交付无缺陷级跨功能影响；三条观察记录如上，提交时注意未跟踪文件一并入库。
