# design — 宿主侧 skill/agent 适配安装

## 1. 架构与边界

沿用 installer 既有「plan → apply → journal/backup → manifest」事务模型，
新增第三类 plan 条目 `host_files`，与现有 `files`（版本 cache）、
`settings_entries`（宿主 settings.json）并列。

### plan 结构扩展（`plan_install`）

```
plan["host_files"] = [
  {
    "host": "claude",
    "kind": "skill" | "agent",
    "source": "resources/skills/fstar-execute/SKILL.md",   # bundle 内相对路径
    "destination": "<host_root>/skills/fstar-execute/SKILL.md",
    "expected_hash": <bundle sha256>,
    "current_hash": None | <sha256>,      # 已存在时
    "action": "append" | "reuse_external" | "reuse_owned" | "keep_modified" | "remove_owned" | "remove_missing",
    "owned": bool,                          # manifest ownership
    "canonical_hash": <整文件 sha256>,
  }, ...
]
```

- **来源映射**：`resources/skills/fstar-<name>/SKILL.md` →
  `<host_root>/skills/fstar-<name>/SKILL.md`；`resources/agents/fstar-<role>.md`
  → `<host_root>/agents/fstar-<role>.md`。名单来自 `content.SKILLS` /
  `content.ROLES`，不扫描目录（防 bundle 被塞入未声明文件）。
- **只针对 claude**：`target_hosts` 含 codex 时，codex 不产生 host_files
  条目（plan 的 unsupported 说明沿用 F4 reason）。

### 所有权与冲突

- ownership 判定复用 `_owned_setting` 的模式：manifest
  `host_file_entries` 记录 `{"destination", "canonical_hash", "ownership":
  "owned"}`；hash 匹配才算 owned，用户改过即视为外部文件。
- action 判定完全对齐 `_file_action` 语义：相同 hash → reuse（不写）；
  不同 hash → conflict（keep 默认，报告不覆盖）；owned+modified →
  keep_modified；uninstall → remove_owned。
- 路径安全：destination 必须等于 `_host_file_destination(host, source)`
  的推导结果（`_validate_plan_paths` 增校验），且 `_reject_symlink_ancestors`
  覆盖宿主根；拒绝 `skills/fstar-foo/../..` 逃逸（`_safe_relative` 已有）。

### 应用与事务（`_apply_*`）

- `_apply_host_file(entry, ...)`：append/reuse/remove 三态；写入走
  `_atomic_write_bytes`（自动进入 journal）+ `_backup`（宿主文件在 user_root
  之外，落 `_external/` 标记名，restore 不越界——现机制已支持）。
- remove_owned：删除文件；随后若 `skills/fstar-*` 目录空则删目录，`agents/`
  为空且由本安装创建则删目录。空目录创建权记在 journal（首次 mkdir 时
  record）。

### manifest / doctor

- `.install-manifest.json` 新增 `host_file_entries`（install 时写入，
  uninstall 后清空对应项）。
- doctor 诊断：遍历 manifest host_file_entries，目标缺失 →
  `HOST_FILE_MISSING`；存在但 hash 不符 → `HOST_FILE_MODIFIED`。

## 2. 数据流

```
plan_install (纯读)
  → CLI 打印 plan（dry-run 在此终止）
  → _validate_plan_paths（新增 host_files 校验）
  → _reverify（新增 host_files current_hash 复核）
  → apply：files → settings_entries → host_files（同事务、同 journal）
  → manifest 写入 / uninstall 清理
```

## 3. 兼容与迁移

- 旧安装（manifest 无 `host_file_entries`）：uninstall 退化为现状——只撤
  settings 与 cache，不猜宿主文件（对齐「不猜」原则）。
- 版本不变（resource_version 仍为 1），无迁移。
- `update` 操作：host_files 视同 install 重新校验，hash 相同 reuse。

## 4. 取舍记录

- **逐文件而非整目录复制**：让所有权、冲突、回滚都以文件为粒度，和
  settings 条目同一心智模型；目录只作为空容器管理。
- **不注入 skill 清单进 session-context**：宿主目录的 SKILL.md 本身就是
  发现机制，注入清单会重复占预算（父设计 §4.4 体积边界）。
- **名单驱动（SKILLS/ROLES 常量）**：与 `validate_resources` 同源，防止
  bundle 内容漂移导致宿主出现未声明文件。
- **`~/.claude/agents/` 目录是否被宿主识别**：实测该目录当前不存在。若
  live 验证发现 Claude Code 不加载该目录，如实记录宿主限制并停止 agents
  侧的 live 断言（AC 已含此出口），不强行兼容。
