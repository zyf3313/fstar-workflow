# design — install 默认项目级宿主根

## 1. 目标根解析（roots_from_args 重写）

```
host_roots 解析顺序（对每个 SUPPORTED_HOSTS 成员）：
1. --host-root HOST=PATH     → 显式覆盖，最高优先
2. --user-level              → Path.home()/".claude"
3. 项目级默认                → find_project_root(cwd)/".claude"
   - cwd 在 fstar 项目内   → 项目根
   - 不在项目内 + 无 --user-level + 无 --host-root
     → DomainError("host_root_required", 提示 --user-level 或 fstar init)
```

要点：

- `roots_from_args` 需要新增可选参数 `user_level: bool`（从 args 读取）
  与 cwd（`Path.cwd()`）。它已有 `--project` 参数可传项目根，但项目根
  应该由 **`.fstar/.schema-version` 标记探测**（`find_project_root`），
  与运行时 hook 的定位逻辑同源，而非 `--project` CLI 参数（那是显式
  覆盖，保留）。
- `--project` 显式指定时同样作为项目级默认的根来源（优先于 cwd 探测）。
- 错误是**计划前**的（roots 解析即失败），保证零写入。

## 2. uninstall 的 manifest 归属回退

现有代码（plan_install:544-546）已经从 manifest 的 `settings_entries`
推导 `owned_hosts`，但过滤条件是 `host in resolved.host_roots`——只要
`resolved.host_roots` 含该 host 就算命中。需要收紧为**路径级匹配**：

```
owned 路径集合 = {record["settings_path"].parent for record in settings_entries
                  if ownership == "owned"}
host root 命中 = resolved.host_roots[host] in owned 路径集合
```

即：uninstall 只针对「manifest 记录的宿主根 == 当前解析出的宿主根」的
条目操作。这样用户级旧安装在项目内跑 uninstall（解析为项目根）时不会
误判；用户要卸用户级安装就加 `--user-level`，路径精确匹配。

`host_file_entries` 的 doctor 检查（:1877）已经是路径级 `_within` 匹配，
无需改。

## 3. TTY 确认（仅 install）

- `_handle_install` 在 apply 前：`sys.stdin.isatty()` 且非 `--dry-run`
  且 plan 含宿主写入（settings_entries 或 host_files 非空）时，打印
  宿主根清单 + "Proceed? [Y/n]"。
- 任何否定回答 → 返回 `{"aborted": True, "reason": "user_declined",
  ...plan}`，零写入。
- 非 TTY / `--json` / dry-run：跳过确认。
- 不引入新依赖（不用 inquirer 类库，Python 内置 input 即可）。

## 4. CLI 参数变更

- `install`/`uninstall` 新增 `--user-level`（store_true）。
- `--host-root` 帮助文本更新：从 "fixtures/advanced targets" 改为
  "explicit host root override; default is the current fstar project's
  host dir, --user-level targets ~/.claude"。
- `doctor` 不加 `--user-level`：doctor 报告所有已记录条目，它的
  host_roots 需同时含项目根与用户根才能如实诊断两处（见 5）。

## 5. doctor

doctor 的 roots 需要看到**两个**可能位置才能完整诊断。做法：
`roots_from_args` 给 doctor 传入 `doctor_mode=True`，claude 的
host_roots 用一个诊断专用列表——但这会破坏 Roots 类型。更简单：
doctor 用两遍扫描（项目根 + 用户根）合并诊断。取简单方案：
doctor 保持现状（按解析出的根报告），README 注明卸载残留检查方式。
**不改 doctor**——避免为边缘场景复杂化 Roots 生命周期。

## 6. 兼容性

- `--host-root` 原有语义不变（测试 fixture 全靠它，不受影响）。
- 已有用户级安装：uninstall `--user-level` 精确匹配其记录路径，可
  正常卸载。
- `version`/`doctor` 无行为变化。
