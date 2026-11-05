# 项目索引

## 概况

fstar-workflow：跨项目 AI 编码代理工作流系统（Python 3.9+ 标准库内核 +
Node 启动器，零第三方运行时依赖）。npm 包 `fstar-workflow`，GitHub
`zyf3313/fstar-workflow`。

本目录为 fstar 工作流的项目数据根（任务、规范、知识）。

历史说明：2026-11-05 由 Trellis 迁移至 fstar 自身工作流。规范位于
`.fstar/specs/`（原 `.trellis/spec/`，内容未改）；历史任务位于
`.fstar/tasks/`（活跃）与 `.fstar/archive/`（已归档），每个任务目录内
保留 `trellis-task.json` 原件。

## 主题

- id: backend
  title: 后端开发规范
  Applies to: `src/fstar/` Python 内核
  Read when: 修改 installer、store、tasks、dispatch 等内核模块前
  Authority path: `.fstar/specs/backend/index.md`
- id: frontend
  title: 前端/包入口规范
  Applies to: bin/ 启动器与包交付面
  Read when: 修改启动器、打包、发布配置前
  Authority path: `.fstar/specs/frontend/index.md`
- id: guides
  title: 通用工程指南
  Applies to: 全项目
  Read when: 开始任何实现或评审前
  Authority path: `.fstar/specs/guides/index.md`

## 长期知识与已有权威资料

- 发布与分支规范见仓库根 `CONTRIBUTING.md`（feat/fix/chore/release +
  语义化版本对齐 npm）。
- README.md 为对外安装与阶段说明的权威入口。
