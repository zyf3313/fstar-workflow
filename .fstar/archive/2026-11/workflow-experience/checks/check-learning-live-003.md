# 后台学习：缺卡阻断独立验证

- dispatch_id: check-learning-live-003
- 检查者: af36704c4a7853d41（独立于实施者）
- 范围: A-001/A-005 的角色缺卡处理和相关回归，不代表全部标准通过
- 生产工作区只读: true；changed_paths: []
- 结果: 指定范围 passed

## 基线

固定隔离快照基于 HEAD 3acd9ce94a374f110dc3519cdfe6d2d3a610ec77；原 tracked diff SHA256 5e63782048fe49b52e2f6952b27dfc27ae8653b8e0ba9be10de0231ac17dce02。只更新 runtime/__main__.py 为 SHA256 aceaae555a00044554d28e1adc01cad5a9f2a94fa81116cafda1185ce5dd78d0；测试文件 test_worker_hook_failure.py 为 24a6be47b1ab5b43acb0a20c17a75b47617a0fbb1631d8e2113ac67b5ed24bec。本证据不能代表并行工作区最终版本。

## 独立检查者报告的执行证据

- 31 项针对性测试通过：tests.test_worker_hook_failure、tests.test_learning_role、tests.test_integration_wiring，耗时 0.682 秒。
- Node launcher 对缺卡 PreToolUse Agent 返回 2，stdout 空，stderr 含 role_card_unavailable。
- 实际 Claude CLI 2.1.81，默认权限，临时项目角色和 skill，复制的旧版10资源，显式提示后台派发一次。
- session: 82474344-3cc8-4f47-bf3a-6f6808f3cdef；hook 观察记录时间 2026-11-25T15:36:22.645003+00:00，event PreToolUse、tool Agent、exit 2。
- 宿主工具返回 is_error=true，协调者收到并转述缺卡原因；未出现 task_started、async_launched 或第二次派发。
- CLI 退出0仅表示会话正常结束，不表示派发成功。模型验证成本 $0.063719、duration_ms 8630、重试0。

## 限制与其他证据

正常资源后台启动、读取skill和返回结果见检查者 check-learning-live-002 报告。当前测试只证明明确派发下的宿主行为，不证明自然语义自动触发或真实全局安装；未写用户知识，未运行全量回归。其他宿主和Task工具名仅有单元测试覆盖。实际用户配置和权限均未修改。
