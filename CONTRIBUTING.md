# 贡献与发布规范

本仓库的分支命名、版本号与 npm 发布遵循本文档。2026-11-05 起生效。

## 分支命名

| 前缀 | 用途 | 示例 |
|---|---|---|
| `feat/` | 新功能 | `feat/project-default-host` |
| `fix/` | 缺陷修复 | `fix/journal-recovery` |
| `chore/` | 工具、文档、依赖、CI | `chore/npm-publish` |
| `release/` | 发版专用（bump 版本 + tag） | `release/0.1.1` |

规则：

- 一律小写短横线命名，不含空格与中文。
- 一个分支对应一个可独立验收的交付；混合内容拆成多个分支。
- 分支合入 `main` 前需要用户验收（fstar 工作流的 accept 步骤）。

## 版本与 npm 对齐

版本号遵循语义化版本（semver），三处必须一致：

1. `package.json` 的 `version`
2. git tag（`v0.1.1` 形式）
3. npm registry 上的 `fstar-workflow` 版本

```
当前基线：0.1.0（2026-11-05 发布）

feat 合入 main  → 次要版本 +1（0.2.0）
fix  合入 main  → 修订版本 +1（0.1.1）
破坏性变更      → 主版本 +1（1.0.0），需用户明确确认
chore 不发版，除非它改变了包内容（此时按 fix 处理）
```

## 发布流程

发布只在 `main` 上进行，永远不从未合并的分支发版：

```bash
# 1. main 上确认要发版的内容已合入
git checkout main && git pull

# 2. 建发版分支，bump 版本
git checkout -b release/0.1.1
npm version patch   # 自动改 package.json + 打 tag（需先在 package.json 提交干净）
git push origin release/0.1.1 --follow-tags

# 3. 验收后合回 main
git checkout main && git merge --no-ff release/0.1.1
git push origin main --follow-tags

# 4. 发布（需要 OTP）
npm publish

# 5. 验证
npm view fstar-workflow version        # 应等于 package.json
npm install -g fstar-workflow@latest   # 真实安装验证
```

## 纪律

- npm 版本号一经发布永久占用；同版本号不可重复发布。
- 发布后 72 小时内可 unpublish 单个版本；超时只能 deprecate。
- `resources/package-assets.json` 记录每个交付文件的 SHA-256 与出处；
  改动 `src/` 或 `resources/` 后必须跑 `node scripts/build-package.cjs`
  重新生成，测试会校验其真实性。
- 全量回归绿（Python + Node 测试套件）是合入 main 的前置条件。
