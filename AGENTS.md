# AGENTS.md

## 项目

fstar-workflow：跨项目 AI 编码代理工作流系统。npm 包 `fstar-workflow`，
GitHub `zyf3313/fstar-workflow`，MIT。Python 3.9+ 标准库内核 + Node 启动器。

## 工作流

本项目使用 **fstar 自身的工作流**（2026-11-05 由 Trellis 迁移自举）。

- 项目数据根：`.fstar/`
  - 任务：`.fstar/tasks/`（活跃）与 `.fstar/archive/<YYYY-MM>/`（归档）；
    每个迁移任务目录保留 `trellis-task.json` 原件
  - 规范：`.fstar/specs/`（backend / frontend / guides）——写代码前读对应层 index
  - 项目索引：`.fstar/index.md`
- CLI：全局安装的 `fstar`（`npm install -g fstar-workflow`）
  - `fstar task create/list` / `fstar start` / `fstar accept` / `fstar archive`
  - `fstar state show <task>` / `fstar doctor`
- 会话开始时 SessionStart hook 注入 fstar 路由与项目索引
- 扩展包（planning-review / persistent-task / multi-agent /
  project-governance / tool-capability）按需协商启用，不默认全开

## 分支与发布

遵循 `CONTRIBUTING.md`：`feat/` `fix/` `chore/` `release/` 前缀分支；
版本号与 npm 严格对齐；只在 main 上发版；合入前全量回归绿 + 用户验收。

## 开发

- 测试：`PYTHONPATH=src python3 -m unittest discover -s tests -t .`（Python）
  与 `node --test tests/test_package.cjs`（Node）
- 改动 `src/` 或 `resources/` 后：`node scripts/build-package.cjs` 重新生成
  资源清单（测试校验其真实性）
- 权威决策记录在归档任务树（`.fstar/archive/`，父任务
  `10-25-fstar-workflow-design`）；不要把示例设计当作已批准的实现需求
- 对外说明以 `README.md` 为准
