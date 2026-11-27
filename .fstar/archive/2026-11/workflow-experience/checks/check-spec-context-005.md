# check-spec-context-005：回执修复（本轮 005/006 重名轮）独立复查

- 检查者：独立 fstar-check（第二次派发，只读）。第一次派发零验证（检查者误判无原生工具），结论作废。
- 基线（起止一致，检查期间未变）：dispatch.py 38a8dd94…、test_dispatch_context.py 00192f6e…、fstar-execute SKILL.md 7a460a96…、crossproject.py 33c86ba8…、test_crossproject.py 1b3fa271…、evidence.py 7c45267c…。HEAD 3acd9ce。
- 检查环境：/tmp/fstar-check-005.mBHl5p（隔离 HOME/FSTAR_USER_ROOT/FSTAR_RUNTIME_ROOT/TMPDIR）。changed_paths: []。

| 判定 | 依据 |
|---|---|
| malformed_receipts 有界不复制正文 | 通过：非数组只记类型；逐项只记 index+reason；上限 10 条计 omitted；对抗用例（列表/字典字段、超长 text、15/30 条非法）输出 253–1038 字节，不含正文；不泄漏到持久 evidence |
| modern context 缺 root 拒绝；root 严格 project/user；legacy 无回归 | 通过：1312-1317 行；四个 subTest 覆盖；crossproject 33 项 OK 保持 not_applicable |
| 文本一致性 | 通过：1720 行 "omitted root means project" 指载荷条目（1307/1314 一致），回执条目另按 551-562 与 SKILL.md 第 17 行要求显式 root，三者描述对象不同，不矛盾 |
| 对抗用例无未处理异常 | 通过：类型检查先于元组入集合，无 TypeError unhashable；混合合法+非法为 worker_reported，非法项计入 malformed 不阻断状态 |
| crossproject 锁超时关闭流 | 通过：test_crossproject 33 项 OK，含锁超时回归测试 |

测试：test_dispatch 21 + test_crossproject 33 OK；test_worktree_identity + test_storage_modes 70 项 OK；test_dispatch_context 126 项中 125 过、1 ERROR（F-1）。

## 发现

- **F-1（中）**：`test_linked_worktree_evidence_tracks_source_checkout`（test_dispatch_context.py:234）确定性 ERROR：setUp 在写入 `.fstar/config.yaml` 前构造 TaskStore（缓存 project_id=None），测试补写 config.yaml 后 `_check_writable_layout`（store.py:972-981）观测到新 project_id，抛 `worktree_data_conflict`。单独运行、全套、无环境覆盖均复现。涉及交付集内 store.py（rebind 修复引入或暴露）与测试本身；本次只读未修复。dispatch.py 回执修复本身不受影响。

结论：回执修复（本轮 implement-005 目标）通过；F-1 转入修复流程。
