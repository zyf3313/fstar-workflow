# 工具绑定实施计划

> 本文件是 Trellis 子任务 implement.md；产品任务执行计划仍为 plan.md。

## 当前状态与必读

2026-10-29 仅完成本目录五份规划文件刷新；未 start、未写产品代码、未改 runtime、未运行工具探针或 git。第一版十子任务已有实施授权，未变范围不新增批准。下列项全部是待实施，不能据本文称功能已交付。

实施/check 均须完整 Read 父 `../10-25-fstar-workflow-design/{prd,design,implement}.md`，父 design 注入如被截断必须补读全文；再读本子 prd/design/implement、JSONL 的规范/研究依据。研究稿的旧包数、code-text/第六能力、AI 分类、turn-context 不覆盖当前父契约。用例审批已撤回，check 直接按需求补测试并运行，可自修本范围生产/测试代码。

开工定点核对实际代码（不放入 JSONL）：`src/fstar/config.py` 的 parse_config；`src/fstar/cli.py` 的 optional 模块表、register_commands 与 `_fstar_module_handler`；`src/fstar/store.py` 的 transaction/read/resolve/write；`src/fstar/tasks.py` 的来源封套、make_event/compact_events；`src/fstar/models.py` 的 task 验证；`src/fstar/evidence.py` 的 record 仅写 evidence 的边界。不要假定存在 record_capability。父子设计给定的 API 若因并行工作改变，核对差异再消费，不修改 runtime。

前置 core-commands、project-layout 已交付并过独立 check；workflow-content 的 fstar-tools 已存在，可协调补充其单一入口指引。整文件 mode:file 缺陷已修复；runtime 前 79 项 Python 3.9.6 测试通过，是历史基线，不把它当当前全套数量或新阻塞。runtime 联合检查独立推进；本任务与其文件不重叠。

## 所有权与依赖交接

| 所有者 | 本任务承诺/边界 |
|---|---|
| tool-binding | tools.py 或同导出 tools/ 包；test_tools.py；五 capabilities 文档；tools.schema.json；tool-bindings reference；协调后补 fstar-tools 引用 |
| tool-classifier（后续，依赖本任务） | 独立 tool_classifier.py，scan_tools 回调与 fstar.tools.scan.v1；registry/probes；不得覆盖 tools 模块或再注册 CLI |
| core | 复用 TaskStore 事务/校验/原子写、make_event/compact_events；不新增 task 字段，不私造核心服务 API |
| init / project-layout | 后续用 scan_tools 取候选、build_binding_proposal 取提案，apply_binding 只在明确确认后；本任务不改 project.py |
| knowledge-base | 消费 knowledge-retrieval resolution 与真实调用 provenance，不存扩展授权 |
| package-install | 分发 capabilities/schema/reference 与后续 registry，保留用户绑定；不因安装写已确认配置 |
| runtime / e2e | 后续按接口消费轻检查/真实宿主观察与 provenance；本任务零 runtime 修改，不在单测宣称真实宿主验证完成 |

## 执行顺序

| ID | 工作/完成判据 | 依赖与验证 |
|---|---|---|
| TB-I1 | 核对公开 API 与 Python 3.9；锁定 tools/classifier 模块所有权及资源路径；与内容所有者交接 fstar-tools 指引修改 | 首先；不动 cli/runtime；回写落实细节 |
| TB-I2 | 五契约各七段，明确安全最小调用、弱匹配/缺口/降级；形成 tools.schema.json 与单一 reference 的可解析示例 | I1；AC-01/02；结构测试+语义检查 |
| TB-I3 | tools.py 纯 schema validator、load_tools、逐能力 resolve；缺文件独立状态、坏文件显式错误；复用 parse_config；schema 专用序列化往返 | I2；T1–T3；不造 YAML parser |
| TB-I4 | proposal/apply_binding：完整 diff+旧 digest、来源范围/指纹校验、目标锁、重读冲突、原子替换、同文件授权/history；不重复问已存在授权 | I3；T4/T5；失败无新授权/部分变更 |
| TB-I5 | assess_availability/gap、build_provenance；host observations 三层分别验证，不执行外部调用 | I3；T6/T7；unknown 如实报告 |
| TB-I6 | record_provenance 薄桥接核心 transaction/read/resolve/write，有效租约、幂等 ID、统一 events，session-only 不落盘 | I5；T8；真实 TaskStore 往返，不仅 mock |
| TB-I7 | 唯一 tools scan optional 注册；lazy classifier 回调、缺模块明确未就绪；固定快照接口测试；更新现有 fstar-tools 绑定指导 | I4–I6；T9；不加 bind/status/install 命令 |
| TB-I8 | 目标测试、受影响核心/内容回归、实际 CLI 临时根 smoke、compileall；交独立 check，检查交接后停止同范围实施写入 | I7；全部 AC；无网络/真实 HOME；真实 classifier/宿主留后续集成 |

本任务不提前实现 classifier，scan 壳缺依赖的明确错误是本任务应验行为；端到端全量扫描完成判据仍属于 classifier/e2e，报告须区分。五契约与绑定实施使用原生 implement 执行，独立 check 由协调者派发，不在本次规划启动它们。

## 测试矩阵

统一 unittest、TemporaryDirectory、固定 clock、显式 project/user/runtime 根，宿主与扫描用固定快照；任何测试不碰 ~/.fstar、不装工具、不联网、不运行任意未知可执行文件。

| ID | 场景与预期 |
|---|---|
| T1 | 实际 parse_config 解析示例与写回内容：JSON flow tools/capabilities/history、嵌套 binding、引号/#/Unicode/冒号；块映射序列、非法缩进、重复键/ID、NaN、未知 schema/能力/枚举、错误类型明确拒绝，错误保留 path/line/key |
| T2 | 缺文件返回 missing，存在的空文件/乱码/目录代文件/读取失败分别出错；坏项目层不能静默取用户默认；不得因 reads/proposal 创建任何目录 |
| T3 | 项目只覆盖 code-structure、用户其他能力仍保留；确认 tool=null 遮蔽；缺键继承；默认仅 recommended；同名工具跨层版本/确认不拼接；悬空引用拒绝 |
| T4 | 无确认/错 actor/缺引用/缺原话/错目标作用域/错 changes/旧 proposal digest/只有 approved 字样均拒绝；工具包授权与 strong 分类不代替绑定确认；probe 不可 strong，选择 weak 不自动提升 |
| T5 | 已确认变更只改目标事项、同时记录 confirmation/history；未授权与 stale 不留下记录；锁内并发替换冲突、原子 replace 失败、临时文件清理、路径穿越/符号链接拒绝；原文件字节与历史不变；成功后 parser 往返 |
| T6 | 三层可观察状态分别 verified/failed/unknown；存在≠加载≠调用；缺 evidence_ref/call_id、不同工具/项目/会话事实不可拼通过；过期事实标 unknown，版本未知 null；没有适配器不捏造成功 |
| T7 | 每维度缺口包含层级/原因/建议来源/降级；data-access 不写、test-execution 不将未运行算通过；只扫描/提案不能产生调用 provenance；实际失败调用仍可如实记录，秘密不写入 |
| T8 | 临时真实 TaskStore planning/start/lease fixture：有效调用入 capabilities 与事件；extensions/phase/acceptance 不变；重复同 ID 相同内容幂等、不同内容拒绝；缺/过期租约与 dropped 拒绝；ref=None 前后目录集合不变 |
| T9 | CLI 从未 init 临时目录调用 tools scan，optional handler 在 _service 前执行；没有 classifier 稳定非零 tools_classifier_unavailable；固定回调返回 scan.v1，导入内部故障不得吞掉；help 只有 scan；JSON 错误含 code/message/details |
| T10 | 五契约七段+单一指导入口结构、Python3.9 compileall、全库回归；classifier/init/knowledge/installer 所需导出与示例一致，未新增资源数量/命令/runtime 写入 |

parser 校验覆盖输入格式，不能证明五契约语义；独立 check 需核对每个推荐、不合格实现与降级是否符合父需求。真实宿主调用另由 classifier/e2e 记录宿主版本、范围、命令或 tool call ID、证据和 unknown；桩通过不当成宿主通过。

## 实施期验证命令

工作目录明确为项目根；以下只供实施/check 执行，本次规划不跑产品测试：

- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_tools.py'`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `python3 -m compileall -q src/fstar tests`
- 实际 Python 3.9 解释器核对；CLI 子进程使用临时 cwd 与全局选项在子命令前的实际语法：`python3 -m fstar --json --user-data-root <temp-user> --runtime-root <temp-runtime> tools scan`，不假设 `--json` 可放尾部。

记录实际环境、命令、结果、耗时/重跑数与未执行项；不得预填“通过”。后续 schema/API 若变，先同步本 design/reference 与所有消费者再验证，不能偷偷增加公共命令。

## 收工与回滚

独立 check 按全部 AC 检查并修本范围，按影响回归；最终核对父 implement #6 及集成 #11/#25/#26。交付说明列五契约、API/schema/示例、注册所有权、消费者待接入事项与真实测试证据。代码/资源回滚不自动改用户 tools.yaml；已确认用户变更不能由卸载或扫描重置。核心/运行时接口冲突报协调者，常规实现细节不重新申请产品批准。子任务随父整体检查与归档，不单独归档。
