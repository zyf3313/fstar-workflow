# 安装器多 host root 更新修复

## 背景

`fstar update` 在项目内执行时报 `uninstall_host_root_mismatch`：

```
fstar: uninstall_host_root_mismatch
recorded: ["/Users/zhangyangfan/AgentWorkspace/.claude"]
resolved: {claude: ".../vibecoding/fstar/.claude"}
```

用户诊断（2026-11-11，确认为真）：

- `~/.fstar/.install-manifest.json` 只保存最后一次安装的 settings 记录；
- 在项目里 update 时，命令校验"记录中的 host root 是否等于当前解析出的
  host root"，不一致即报错；
- 即使显式传 `--host-root` 也不改变这项校验。

代码复核后确认还有第三个缺陷：

- `settings_entries` 以 `host:event` 为 key（`claude:SessionStart`），多个
  host root 的同一 host/event 记录会互相覆盖，manifest 永远只剩最后一个
  root 的 settings 记录；
- `host_file_entries` 以 destination 为 key，反而是全量累积的（本机
  manifest 中三个 root 各 16 条都在）。

三个缺陷叠加的后果：曾安装过的项目，其 `.claude` skills 副本无法再通过
`fstar update` 刷新；显式指定 root 的逃生口也被堵死。

## 范围

### R-001 显式 root 选择绕过 mismatch 校验

`--host-root HOST=PATH` 或 `--user-level` 是用户显式指定，语义应为"用户
指哪就操作哪"。`plan_install` 增加 `explicit_roots` 参数，CLI 在用户给出
上述任一参数时置真；显式选择时跳过 host root mismatch 拒绝。

隐式解析（当前项目 `.claude`）仍保留校验，但归属判定改为合并
`settings_entries` 与 `host_file_entries` 两处记录中的 owned root——任一
命中即视为本机曾安装该 root。

验收：

- Given manifest 的 settings 记录指向 root A、host_file 记录含 root A/B
- When 在 root B 所在项目执行 `fstar update`（隐式解析到 B）
- Then 不再报 mismatch，正常规划 B 的更新
- When 显式 `--host-root claude=<C>` 指向任意 root C
- Then 跳过 mismatch 校验，按 C 规划

### R-002 settings 记录按 root 区分（数据模型修复）

`settings_entries` 的 key 从 `host:event` 改为 `host:settings_path:event`，
同 host 不同 root 的记录并存：

- `_owned_setting` 匹配时要求 `settings_path` 与当前规划目标一致，避免
  把另一个 root 的记录误判为本 root 的 owned 记录；
- 读取旧 manifest 时按新 key 归一化（旧记录已含 `settings_path` 字段，可直接重键）；
- uninstall 只移除当前 root 的 settings 记录，不误删其他 root 的记录。

验收：

- Given 先安装 root A，再安装 root B（同 host）
- Then manifest 同时保留 A 与 B 的 settings 记录
- When 在 A 上 uninstall
- Then A 的记录被移除、B 的记录仍在

### R-003 回归测试

覆盖：显式 root 绕过、隐式 root 按 host_file 记录放行、双 root settings
记录并存、单 root uninstall 不影响另一 root、旧 key 迁移。

## 不做

- 不改 `tools.yaml`、hook 协议、数据 schema。
- 不回填/猜测 manifest 中已丢失的历史 settings 记录（显式 root 更新时
  按 `reuse_external` 正常复用现有 hooks 即可）。
- 不新增 CLI 参数或命令。

## 验证

- `PYTHONPATH=src python3 -m unittest discover -s tests -t .` 全绿
- `node --test tests/test_package.cjs` 全绿
- 本机真实场景：`~/workspace/projects/vibecoding/fstar` 内执行
  `fstar update --host-root claude=<该目录>/.claude --modified overwrite`
  成功刷新 skills
