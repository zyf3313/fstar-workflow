# 目录与配置实施计划

## 当前状态与来源

用户已批准 v1 范围；本轮只刷新五份规划文件，不执行本计划、不运行 start、不改产品代码或 Git。实施依据为父任务当前 `prd.md`、自包含 `design.md`、`implement.md` §2 kickoff，以及本子任务 PRD PL-01–04 / design §1–9。历史 research 仅按需补充且不得覆盖当前父契约。未来 fstar 任务执行计划叫 `plan.md`；本文件是当前 Trellis 所需 `implement.md`。

## 交付边界

本子任务独占 `src/fstar/project.py`、`src/fstar/config.py`、`tests/test_project.py`、`tests/test_config.py`。core 独占 `src/fstar/cli.py`、`src/fstar/__init__.py`、`src/fstar/__main__.py` 及其任务模块；不得为注册 init 争写入口。具体测试文件若已有同职责文件则优先合并，不造第二套。

无产品代码现状下不假设已有解析器、模板、测试运行器或安装资源。核心模块可独立开发，核心 CLI 集成顺序在最后；不存在“先等 core 全部实现才能写配置”的循环依赖。

## 顺序、依赖与验证

| 项 | 优先级 | 前置 | 并行条件 | 工作与完成判据 | 对应验收 |
|---|---|---|---|---|---|
| P1 | P0 | 当前设计 | 与 core 的非共享文件可并行 | **完成并检查通过**：固定 API/结果/错误结构、五层与语言键；core 已接通可选模块 handler；只读加载不隐式 init | AC-05/06/10 |
| P2 | P0 | P1 | config 独立写者 | **完成并检查通过**：YAML 子集、验证、未知键、深拷贝合并、来源及接受/拒绝测试 | AC-05/06 |
| P3 | P0 | P1，调用 P2 前接口可用 | project 独立写者，不与 P2 写同文件 | **完成并检查通过**：引用验证、最小索引、排他写入、schema/身份、dry-run、失败清单 | AC-01/02/04/07/08/09 |
| P4 | P0 | P2/P3 | 同一写入范围停止实施后交 check | **完成并检查通过**：显式用户骨架、边界测试、默认读取零写入 | AC-03/06/10 |
| P5 | P0 | P4 + core CLI 入口可用 | 由 core 独占 cli.py；本子任务提供结果协议 | **完成并集成验证通过**：init、--user、--dry-run、JSON 成功/失败及 help 均以临时根实跑 | AC-10 |
| P6 | P0 | P5 | 实施/检查分离 | **完成**：独立检查、自修、18 个范围测试、编译及真实 CLI 临时根场景通过；详见 `check-report.md` | 全部 |

同一文件只允许一位写者；交 check 后暂停修改该范围。没有有效进展或环境阻塞时返回事实，不盲目重复测试。已批准范围内不增加额外计划审批。

## 必要测试

1. 新项目：只有四文件；无模板安装、无用户根仍成功。两次调用：第二次 created 为空，全部字节及 UUID 不变。首次故障后补缺；已有 config 缺身份/版本时明确错误而非生成替代身份。
2. 已有项目：README/docs/配置/索引/ignore 字节保持；引用事实包含多个真实模块，不预建 frontend/backend。已有索引传新 context 仍 preserved，不声称更新；不兼容 schema 在写入前拒绝。
3. 用户级：未显式请求时用户根不存在；显式 initialize_user 仅三文件；二次幂等，无规则/记忆正文与宿主资源。
4. 配置：五层同键和嵌套键优先级；用户-local 仍低于项目普通配置；列表整体替换、空列表、空映射、null、布尔/int 区分；deep-copy 后修改结果不影响 defaults。只读缺失全部配置不写任何文件。
5. 子集：引号内 #/冒号与转义、CRLF/BOM、嵌套映射、标量序列、JSON flow、Unicode 字符串。重复键、错误缩进、Tab、锚点/别名/tag、块字符串、未闭合引号、多个文档、非有限数字和 01 均有路径/行号错误；invalid 不被当缺失。不能只对解析器自身输出做 round-trip。
6. 路径：`.fstar`/目标符号链接、越界引用、`..`、文件目录冲突；outside sentinel 字节不变。受控目录被替换/并发目标出现的写入行为无覆盖；权限失败用可控故障注入，不能依赖 root 环境一定 PermissionError。
7. I/O：注入第二/第三个写失败，错误含已完成项，重试不覆盖已完成文件；不删除既有内容。dry-run、配置读取和最小闭环消费均零新增文件。
8. 集成：core init 在临时项目成功/重复/失败的输出和退出码；未交付工具和正式模板不影响基本初始化。完整 skill 的零启动澄清/真实主题规划由 workflow-content + e2e 续验，不将模块测试冒充语义验收。

## 实施时验证命令

以下为目标代码就绪后运行的命令，当前规划阶段不运行不存在的测试。使用 Python 3.9 运行验证（若 `python3.9` 未安装，报告环境缺口；其他版本通过不能冒称 3.9 通过）。

```sh
PYTHONPATH=src python3.9 -m unittest discover -s tests -p 'test_config.py' -v
PYTHONPATH=src python3.9 -m unittest discover -s tests -p 'test_project.py' -v
python3.9 -m compileall -q src/fstar/config.py src/fstar/project.py
PYTHONPATH=src python3.9 -m fstar init --help
```

最终集成由 core/e2e 运行现有完整测试命令；若按当前 stdlib 方案建立 tests，则为 `PYTHONPATH=src python3.9 -m unittest discover -s tests -v`。命令在临时项目与临时用户根执行初始化，不写真实 home。仓库 backend 指南尚无实际 lint/typecheck 设置，不杜撰 npm/ruff/mypy 命令。

## 交接与回退

- core：签名及异常见 design §2；CLI 仅适配参数与结果。project.id 只从项目 config.yaml 获取，不允许 user/local 覆盖。配置数据版本 1 与 task.json 26 字段无字段数耦合。
- workflow-content：使用 language 三键 `interaction/artifacts/specs`、ProjectContext 结构与 authority 优先声明；init skill 主持真实结构规划与零启动澄清；正式模板缺失不阻塞模块。
- package-install：认领后续 schema 迁移、Node 包装和资源安装；不可升级包时顺便重写项目用户内容。
- tools：后续由 init skill 显式调用扫描提案，不给 initialize_project 加自动绑定/安装副作用。
- 回退只撤销代码变更，不删除用户数据；初次初始化部分完成可重复补缺。check 记录范围、基线、修复、命令与结果；不需要独立 test-cases/review-log 文件或审批才写测试。

## 规划验证

本轮校验五份文件存在且 JSONL 可解析、路径为仓库相对且目标存在。manifest 只列规范/研究资料，不放将实现的源码。父计划正在并行整合，不以旧章节行号为硬依赖，冲突始终按 policy 最新决定解决。
