# check-identity-lock-001：身份切换锁 A+B+C 独立复查

- 检查者：独立 fstar-check，只读，changed_paths: []。隔离根 /tmp/fstar-check-lock.tnj1da（adv.json、regress.log、full.log）。
- 基线（起止 8 项全部一致）：project.py 58dbffca…、crossproject.py ca37518e…、store.py f08c8b1d…（未动）、test_worktree_identity.py 42236b20…、test_crossproject.py e993b835…、dispatch.py 38a8dd94…（未动）、test_dispatch_context.py a883555d…（未动）、package-assets.json 555a380b…（实施者未重建）。

| 判定 | 依据 |
|---|---|
| A 转换锁 | 通过：_transition_locks（project.py:573-614）排序去重、非阻塞 flock+截止、lock_timeout；锁内复核全部前置（678-705）；数据/注册/marker 同组（706-716）；dry-run 无锁（773-775）；runtime_root 贯通（756/776-779/919-940/1051-1056）；同进程自锁风险有注释 |
| B 注册表顺序 | 通过：项目锁先持（678），_rebind_registry_lock 在内、注册前获取（707-714），与 TaskStore.rebind 一致，无反序 |
| C 跨项目锁后复查 | 通过：crossproject.py:113-114 全部锁取得后、yield 前逐 store _check_writable_layout |
| 禁止项 | 通过：D 未引入；无崩溃/非协作安全声称；WORKTREE_IDENTITY_EXISTS 语义保留（782-791） |
| 新测试真实性 | 通过：5+2 项断言真实有效（测试2/3 断言逐字节零变化；测试5 以 LOCK_NB 证实项目锁已持），无恒真、无跳过 |
| 对抗 | 通过：反序双锁 0.51s lock_timeout 无挂起；dry-run 不加锁；转换 vs 注册表锁并发无死锁；跨项目正向放行；无意外裸异常 |
| 回归 | 六模块 41+24+14+92+12+34 全 OK；全量 discover 1115 项 OK（175s），与实施者口径一致 |

发现：仅 1 条低级备忘——lock_timeout 时已创建空 projects/<sha>/ 锁目录（project.py:589），数据零写入，与 TaskStore 惰性创建行为一致，不构成缺陷。

结论：A+B+C 交付验证成立。遗留待办不变：D（遗留 worktree 认领）待用户决定；E（marker 重复裸 FileExistsError）低级未修。
