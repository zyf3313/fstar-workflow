# 宿主侧 skill/agent 适配安装

## Goal

关闭 F5（live-host-2026-11-01.md）：install 目前只把 skills/agents 放进
`~/.fstar/resources/<v>/`，宿主（Claude Code）从 `~/.claude/skills/`、
`~/.claude/agents/` 发现入口，因此 routing 注入引用的 `fstar-*` skill 在宿主侧
不可见。本任务让 installer 把 12 个 skills 与 4 个角色卡适配安装到 Claude
宿主用户目录，并完成真实宿主 live 验证（第 3 点遗留项）。

## Background（证据，2026-11-01 确认）

- `installer.plan_install` 的 files 循环只复制 `resources/` 前缀文件到版本
  cache（`~/.fstar/resources/<v>/`）；launchers/程序文件不进用户根。
- 实测 `~/.claude/skills` 339 个条目、零 fstar 条目；`~/.claude/agents` 不存在。
- 父任务 design.md:46「宿主用户目录：skills/agents 与必要的入口适配、hook
  注册；安装器仅管理自身文件/配置条目」；:294「Claude 用户 skills/agents/
  settings」。本任务即补上这个未实现的适配步骤。
- 内容本身已被 `validate_resources` 静态校验（12 skills、描述限额）；
  skill/agent frontmatter（name/description）格式已确认与宿主要求一致
  （fstar-execute SKILL.md、fstar-implement.md 实读）。
- 12 个 SKILL.md 与 4 个 agent .md 已在 package-assets.json 有 sha256 记录。

## Requirements

1. **安装**：`install --host claude` 在写 settings.json hook 条目之外，把
   - `resources/skills/fstar-*/SKILL.md` → `<host_root>/skills/fstar-*/SKILL.md`
   - `resources/agents/fstar-*.md` → `<host_root>/agents/fstar-*.md`
   逐文件复制到 Claude 宿主用户目录。
2. **所有权边界**：只管理 `fstar-` 前缀路径；宿主目录中的任何非 fstar 文件
   绝不触碰。目录级清理只删由本安装创建且仍为空的目录（`skills/fstar-*`、
   空的 `agents/`）。
3. **冲突策略**：目标已存在且内容 hash 相同 → reuse；内容不同 → 按
   conflict_policy（keep 默认，报告冲突，绝不覆盖用户修改）；与现有 settings
   条目同一套 `canonical_hash`/journal/backup 机制，可事务回滚。
4. **卸载**：只撤自有（manifest ownership=owned 且 hash 匹配）的宿主文件；
   用户修改过的保留并报告；从未写过宿主目录时零写入零删除。
5. **计划先行**：宿主文件写入进入 plan_install 的 plan 与 dry-run 报告，
   `--dry-run` 绝不写宿主。
6. **Codex**：本次不实现 Codex 侧适配（其用户级 hooks 受信任门控已记 F4；
   skills/入口适配同样依赖交互审查）。plan 中对 codex 保持现状说明，不新增
   文件写入。父 design「按实际支持适配」——Codex 实测不支持的部分不强行
   兼容（用户约束：别强行兼容）。
7. **doctor**：宿主文件存在性/一致性进入 doctor 诊断（HOST_FILE_MISSING、
   HOST_FILE_MODIFIED），listing 仍区分估算/核实。
8. **live 验证（授权已给）**：真实宿主 `~/.claude` 走完整闭环——备份 →
   install → 新会话确认 12 skills + 4 agents 被宿主识别 → 卸载 → 字节级
   还原。沿用 e2e-verify 既有协议。

## Out of Scope

- Codex skills/agents 用户级适配（信任门控，另行任务）。
- `skillOverrides` / skillUsage 等宿主配置项（prd 明确未交付）。
- 修改注入文本（session-context 不新增 skill 清单注入；宿主目录里存在
  SKILL.md 本身就是发现机制）。
- settings.json hook 注册逻辑改动（已交付）。

## Acceptance Criteria

- [ ] install 后 `<host_root>/skills/` 下出现 12 个 `fstar-*/SKILL.md`、
      `<host_root>/agents/` 下 4 个 `fstar-*.md`，内容 sha256 与 bundle 一致
- [ ] 预先在 `<host_root>/skills/` 放一个无关 skill，install/uninstall 全程
      该文件原样保留
- [ ] 预先放一个内容不同的 `fstar-foo`（伪 fstar 条目），默认 keep 策略下
      install 报告冲突且不覆盖
- [ ] uninstall 后宿主目录恢复到 pre-install 状态（非自有文件不动的断言 +
      真实宿主字节级还原）
- [ ] dry-run 对宿主目录零写入（树快照断言）
- [ ] journal/backup 覆盖宿主文件写入，注入失败可回滚（模拟中途异常）
- [ ] doctor 对缺失/被改的宿主文件给出对应诊断码
- [ ] 全量回归绿（Python + Node）
- [ ] 真实宿主 live 验证：新 Claude 会话中 fstar skills 可被识别/调用，
      证据记入 e2e-verify evidence，闭环还原

## Open Questions

无——用户已确认 A 方案并知晓 skills 进入宿主会全局可见；agents 一并安装
（用户上一轮问题中我一并询问，选择 A 即包含）。执行中如发现 Claude Code
不识别 `~/.claude/agents/` 目录，如实记录为宿主限制，不强行兼容。
