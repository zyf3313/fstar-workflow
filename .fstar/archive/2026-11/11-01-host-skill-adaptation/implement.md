# implement — 宿主侧 skill/agent 适配安装

## 执行序

1. [ ] `installer.py`：新增 `_host_file_destination`、plan 循环生成
       `host_files` 条目（名单 = `content.SKILLS`/`ROLES`；仅 claude）。
2. [ ] `_validate_plan_paths` / `_reverify` 增加 host_files 校验。
3. [ ] `_apply_host_file` + 空目录 journal 记录 + uninstall 清理 +
       manifest `host_file_entries`。
4. [ ] doctor：HOST_FILE_MISSING / HOST_FILE_MODIFIED 诊断。
5. [ ] `tests/test_installer.py`：AC 对应回归（见验证命令）。
6. [ ] 全量回归 → `trellis-check`（Agent 形式）。
7. [ ] 真实宿主 live 验证（沿用 e2e-verify 协议：备份→install→新会话识别
       断言→uninstall→字节级还原；evidence 追加记录）。
8. [ ] spec 更新（`trellis-update-spec`）+ 提交（Phase 3.4）。

## 验证命令

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t .   # 全量
PYTHONPATH=src python3 -m unittest tests.test_installer -v  # 安装器专项
node --test tests/test_package.cjs                          # 打包侧不回归
```

新增测试（对齐 AC）：

- install 后 12 SKILL.md + 4 agents 落宿主根，sha256 与 bundle 一致
- 无关 skill 全程原样；伪 fstar 条目冲突 keep 不覆盖
- uninstall 恢复 pre-install 状态；dry-run 宿主零写入（树快照）
- journal 中途异常回滚宿主文件；doctor 两个诊断码
- codex host 无 host_files 条目；旧 manifest（无 host_file_entries）uninstall
  不猜宿主文件

## 风险与回滚点

- 触碰真实宿主 `~/.claude/`：live 阶段单独执行，先备份（协议已有），
  出错即 `_restore` journal 回滚；deny 规则会拦 `rm -rf`，清理用 python。
- `installer.py` 是事务核心：改动全部走既有 `_TRANSACTION` journal，不新开
  写路径；失败自检以 `_tree_snapshot` 断言。
- 回滚点：git 无仓库（本目录 detached），以 tests 全绿 + journal 回滚为
  安全网；live 阶段失败立即还原 settings + 宿主文件。

## start 前检查

- [x] prd/design/implement 三件套齐
- [ ] implement.jsonl / check.jsonl 填充（inline 模式可跳过；本任务计划
      inline 执行，因上下文高度依赖本会话实测证据）
- [ ] 用户批准最终规划摘要

## 执行记录（2026-11-02）

- 实现完成：host_files 全链路（plan/apply/journal/manifest/entry-index/doctor），674→676 Python（+13 回归）+ 16 Node 全绿。
- trellis-check 独立复查（4 安全类别全过）+ 4 项修复：
  symlink 误报 stale（含 _reverify is_file-follows-symlink 细节）、doctor healthy
  纳入 host-file 诊断、死代码清理、mkdir 记录顺序（最小复现确认 innermost-first
  导致 skills/ 目录回滚残留，改 outermost-first 修复）+ owned+bundle 变更时
  overwrite（对齐 _file_action）。
- live 验证（真实 ~/.claude）：备份 sha256 bd2695cb… → 安装 12 skills+4 agents
  （16 文件 hash 全对，340 原有条目未动）→ doctor healthy、20 注册项 active →
  **skills 被宿主识别实锤**（本会话 skill 列表出现 12 个 fstar-*，独立子代理
  交叉确认）→ **agents 被宿主识别实锤**（系统推送 "New agent types:
  fstar-check/editor/implement/research"；fstar-research 实弹派发按定义运行，
  frontmatter 逐字一致；首次探测"看不到"为时序竞争，非宿主限制）→
  卸载 op-c1e99e6547cf → 字节级还原完成。
- **F6（新发现，格式级）**：uninstall 后 settings.json 内容语义相同（7 键、无
  hooks）但字节差 1（json.dumps 格式化 vs 原文件尾换行）。install 写入用
  _atomic_write_json 的规范化格式；卸载还原内容不还原字节格式。修复方式：
  live 用 pre-install 备份恢复字节。后续改进候选：uninstall 对
  settings_file_created 文件直接删（已实现）；对 pre-existing 文件回写时
  保留原始字节格式。
- 环境完全还原：settings.json sha256 = bd2695cb…（与 pre-install 一致），
  skills 340 条无 fstar，agents 目录不存在，~/.fstar 仅剩 pre-existing
  runtime/。
