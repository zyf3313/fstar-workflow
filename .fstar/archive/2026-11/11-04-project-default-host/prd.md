# install 默认项目级宿主根

## Goal

修复安装默认值的歧义缺陷：`fstar install --host claude` 当前默认写用户级
`~/.claude/`，与 fstar 的项目为单位协商模型不自洽，且与用户对标的产品
（Trellis）行为相反。改为**默认项目级**，用户级变成显式选项。

## Background（证据，2026-11-03 实测）

- `roots_from_args`（installer.py:117）在无 `--host-root` 时默认
  `host_roots["claude"] = ~/.claude`——用户级成为隐式默认。
- Trellis `init` 实测（pty 驱动完整流程）：交互问开发者名 → 多选平台 →
  所有平台文件写**项目级** `.claude/`。Trellis 没有用户级安装概念。
- 2026-11-03 真实迁移时踩坑：`fstar install --host claude` 装到了用户级，
  只能靠 `--host-root claude=<项目>/.claude` 才能装项目级——该参数无法被
  自然发现。
- fstar 的 specs/tasks/knowledge/扩展协商全部以 `.fstar/` 项目根为单位；
  hooks 注入按项目路由（`find_project_root`）。宿主配置默认用户级与该
  模型矛盾。

## Requirements

1. **默认项目级**：`install --host claude` 在一个已初始化的 fstar 项目内
   运行时，默认写 `<project>/.claude/`。
2. **非项目目录的诚实行为**：不在 fstar 项目内运行且未显式指定时，
   **报错说明可选路径**（提示 `--user-level` 或先 `fstar init`），
   不静默落到用户级。
3. **显式用户级选项**：新增 `--user-level` 开关（install/uninstall），
   显式写 `~/.claude/`。`--host-root HOST=PATH` 保留，作为高级覆盖。
4. **优先级**：`--host-root` > `--user-level` > 项目级默认。
5. **uninstall 对称**：卸载同样按上述优先级解析目标根，保证能卸载
   两种安装位置。
6. **向后兼容不猜**：已有用户级安装（manifest 记录了 `~/.claude` 目标）
   的 uninstall 依然要能工作——按 manifest 记录的 settings_entries 的
   host root 归属判断，而非仅凭当前解析。
7. **交互确认（TTY）**：install 执行前打印将写入的宿主根路径并要求
   确认；非 TTY（脚本/管道）跳过确认直接执行（dry-run 仍可先看计划）。
   确认提示只针对 install 写操作；uninstall 不加交互（幂等、且默认保守）。
8. **doctor/README/help 同步**：帮助文本与新语义一致；README 安装章节
   更新。

## Out of Scope

- Codex 宿主行为不变（unsupported-for-unattended，沿用 F4 reason）。
- 不引入多平台选择界面（fstar 只有两个宿主，Trellis 的 20 平台多选
  不适用）。
- 不改 hook 语义、资源缓存位置（`~/.fstar/resources` 用户级缓存保留，
  那是共享资源池，不是宿主配置）。

## Acceptance Criteria

- [x] 在 fstar 项目内 `install --host claude`：写入 `<project>/.claude/`
      （settings + 12 skills + 4 agents），计划报告的 destination 全部
      在项目内
- [x] 在非项目目录裸跑 `install --host claude`：报错含修复指引
      （`--user-level` / 先 init），零写入
- [x] `install --host claude --user-level`：写入 `~/.claude/`
- [x] `--host-root claude=PATH` 仍然精确覆盖
- [x] TTY 下 install 打印宿主根并确认；echo 管道（非 TTY）直接执行；
      `--dry-run` 从不写
- [x] 用户级旧安装的 `uninstall`（manifest 记录 `~/.claude`）在项目内
      运行仍能正确卸载用户级条目（按 manifest 归属）
- [x] 全量回归绿；新增测试覆盖上述每条
- [x] README/help 文本更新

## Open Questions

无。方案要点已与用户确认（对齐 Trellis 项目级默认 + 显式用户级开关）。
