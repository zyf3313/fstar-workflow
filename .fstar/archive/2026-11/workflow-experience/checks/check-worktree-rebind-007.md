# check-worktree-rebind-007：worktree rebind 交付独立检查

- 检查者：独立 fstar-check，只读，changed_paths: []。隔离根 /tmp/fstar-check-rebind.3PBhgI（日志、对抗脚本 f1_repro.py / adv_separate.py / adv_dup.py 均在其中）。
- 基线（起止一致）：store.py f08c8b1d…、project.py 91569a43…、test_worktree_identity.py f1866c5a…。HEAD 3acd9ce。

| 判定 | 依据 |
|---|---|
| 写入前拒绝身份分裂 | 通过：transaction/write/set_current/clear_tree_pointers 均先查 writable-layout；rebind 两入口先 _check_rebind_target（含 main 布局一致性，冲突即 worktree_data_conflict） |
| 普通错误恢复、条件性回滚仅限自己写入字节 | 通过：_rebind_write_group 失败回滚只覆盖自己写入的字节，外部并发编辑保留并报 rebind_recovery_failed（对抗验证） |
| 不夸大安全声明 | 通过：无 crash/concurrent/deadlock 声明 |
| 锁身份按 identity_root | 通过：worktree 与 main 共享锁路径，有用例断言 |
| 定向与回归 | test_worktree_identity 36/36、storage_modes 34/34、project 14/14、user_directory_resolution 8/8 全过；其 dispatch 合跑见到的 F-1 ERROR 系 F-1 修复落地前状态，F-1 已另行修复并由协调方隔离复跑 12 项 OK |

研究 5 根因现状：A 已处理；B 部分（marker+init 前置检查，init 全程无锁，属后续 A+B+C）；C 未处理（cross_project_locks 拿锁后不复查，正是后续任务）；D 部分（部分遗留有出路，窄场景——worktree 已含被跟踪的 main 侧 .fstar skeleton 时 force-separate 被拒，无出路，记遗留）；E 未处理（record_explicit_separate_worktree 重复抛裸 FileExistsError，低）。

结论：rebind 交付与设计要求一致，通过。遗留项转入 A+B+C 实施或记录。
