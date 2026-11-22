# S-4 验收协议改动：实现规格

来源：[技术设计](../doc/design.md) §5 与 §9、[实施计划](../plan.md) S-4、用户审定的自验收规则 `~/.fstar/rules/self-acceptance.md`。

本规格是派发给实施 Agent 的唯一依据。任何与现有行为冲突且无法在本规格内判定的点，先回报再改，不得自行扩大范围。

## 整体思路

验收协议现在有三个硬缺口：

1. **打回全量作废**：`report_problem` 与 `continue --action rework` 把任务上所有 valid 证据一律置为 stale。改一条标准就要重跑全部检查，与"按标准条目局部复查"的目标相反。
2. **最终检查没有只读约束**：内核不校验最终检查是否改动了交付文件，检查者可以在"最终检查"里顺手改代码，验收基线随之漂移。
3. **规则验收不引用 criteria**：自验收规则要求逐条判定 criteria.md，但 `accepted_via_rule` 只能引用规则路径与用户原话，事件里没有标准条目，事后无法核验"到底验了哪几条"。

本步按"内核可强制 + 协议可审计"的原则改动：

- 局部作废以证据与受影响范围求交，交集为空则证据保留；默认仍是全量作废，保证旧流程零回归。
- 最终检查只读做成内核门禁：必须声明 `read_only`，不得声明任何改动，且交付证据必须仍然新鲜。
- 规则验收引用 criteria 条目，未知条目号直接拒绝。

资源侧同步落地：criteria.md 补判定方式并可进入 artifact_map，execute Skill 写清自验收收尾程序。

## 步骤

### K-1 打回按标准条目局部作废

- 范围：`src/fstar/tasks.py`（`report_problem`、`continue_task` 的 `rework` 分支）、`src/fstar/evidence.py`（新增按范围作废的方法）、`src/fstar/cli.py`（新增 `--scope-file`）。
- 行动：
  1. 新增局部作废能力，范围对象形状 `{"mode": "localized"|"full", "artifacts": [...], "paths": [...], "criteria_refs": [...]}`。`mode` 缺省视为 `full`。
  2. `mode="full"` 保持现有行为：所有 valid 证据置 stale。
  3. `mode="localized"` 时，证据与范围有下列任一交集即置 stale，否则保留 valid：证据 `validates[].artifact` 命中 `artifacts`；证据 `validates[].items[].id` 或 `dependencies[].id` 命中 `criteria_refs`；证据 `delivery.paths[].path`、`input_files[].path`、`report.path` 命中 `paths` 或 `artifacts`；check 类证据的 `items[].requirement_ids` 与 `criteria_refs` 有交集。
  4. `mode="localized"` 但三个范围列表全空 → 拒绝（`invalid_rework_scope`），不得静默退化成全量作废。
  5. 两条 rework 入口（`report_problem` 与 `continue --action rework`）必须走同一段逻辑，不允许一条局部一条全量。
  6. `rework_requested` 事件数据增加 `scope`、`invalidated_evidence_ids`、`retained_evidence_ids`，让"哪些证据被保留"可审计。
  7. CLI：`fstar accept --rework` 与 `fstar continue --action rework` 支持 `--scope-file FILE`（JSON，即上述范围对象）；不传时行为与现在完全一致。
- 产出：局部作废内核能力 + CLI 入口 + 事件审计字段。
- 完成判据：
  - 打回一条标准只作废相关证据，其余证据保持 valid（用例覆盖）。
  - 不带范围的旧调用路径行为不变，旧测试零回归。
  - 空范围被拒绝。
- 遇阻处理：现有事件结构或 CLI 参数与规格冲突 → 先回报，不擅自改事件 schema 语义。

### K-2 最终检查只读

- 范围：`src/fstar/evidence.py`（`_validate_check`）、`src/fstar/dispatch.py`（check harvest 路径）。
- 行动：
  1. `scope="final"` 的检查证据必须带 `read_only: true`，否则拒绝（`invalid_check`）。`scope="incremental"` 不受此约束。
  2. 最终检查 harvest 时，检查者声明的 `changed_paths` 必须为空，否则拒绝（`final_check_not_read_only`）。这是"检查者自己改了东西"的直接证据。
  3. 最终检查 harvest 时，任务上已有的交付证据必须仍然新鲜（用现成的 `_validate_current` 判定）。交付文件在最后一次交付记录之后被改动过，说明交付基线与检查对象已不一致，最终检查必须被拒绝（`final_check_stale_delivery`），由协调者补一次新的交付记录后再做最终检查。
  4. 最终检查不得来自交付者的同一实例（现有 `check_not_independent` 保持不变）。
- 完成判据：
  - 缺 `read_only` 的 final 检查被拒。
  - 声明了改动的 final 检查被拒。
  - 交付证据陈旧时 final 检查被拒；交付证据新鲜时正常通过。
  - incremental 检查仍可带改动（不被误伤）。
- 遇阻处理：第 3 条若使既有合法流程失败（例如修复后未补交付记录），先回报该流程与失败用例，再决定放宽为"标记陈旧"还是保留硬门禁；不得静默放宽。

### K-3 规则验收引用 criteria 条目

- 范围：`src/fstar/tasks.py`（`accept`、`accept_unified`）、`src/fstar/cli.py`（`--rule` 文件解析无需新增参数）。
- 行动：
  1. `rule` 对象保留必填的 `rule_ref` 与 `quote`，新增可选 `criteria_refs`（字符串数组）、`report`（报告路径字符串）、`scope`（范围描述字符串）。
  2. `criteria_refs` 给出时必须是非空字符串数组，否则 `invalid_acceptance_rule`。
  3. `criteria_refs` 里的每个条目号必须存在于任务 artifact_map 的条目并集里，不存在则 `invalid_acceptance_rule` 并列出未知条目号。
  4. `accepted` 事件数据里的 `accepted_via_rule` 增加 `criteria_refs`、`report`、`scope`（给出才写）；`task["acceptance"]` 同步记 `rule_ref` 与 `criteria_refs`。
  5. 不传 `rule` 的验收路径行为完全不变；传 `rule` 但不带新字段的老式规则文件仍可用。
- 完成判据：
  - 带 criteria_refs 的规则验收成功后，事件与 acceptance 字段都能查到条目号与报告路径。
  - 未知条目号被拒。
  - 无规则验收路径零回归。

### K-4 criteria 判定方式与条目提取

- 范围：`resources/templates/task/criteria.md`、新增 `resources/templates/task/criteria.mapping.yaml`。
- 行动：
  1. criteria.md 每条标准增加「判定方式」一项，取值 `machine`（可由测试命令、独立检查或来源核实客观判定）或 `user-judgment`（需要用户判断）。
  2. 模板内写明：含 `user-judgment` 条目的任务不得走自验收规则。
  3. 新增 `criteria.mapping.yaml`，形状与 `plan.mapping.yaml` 一致（markers 模式，起止标记 `<!-- fstar:item:{id}:start -->` / `<!-- fstar:item:{id}:end -->`），使 A-xxx 标准条目可进入 artifact_map。
  4. 模板的标准条目块保留 `fstar:item` 标记，写手复制标准时按顺序编号。
- 完成判据：资源校验通过（`validate_resources` 无新增诊断）；标准条目可被条目提取拿到。

### K-5 execute Skill 的自验收收尾程序

- 范围：`resources/skills/fstar-execute/SKILL.md`、`resources/agents/fstar-check.md`。
- 行动：
  1. execute Skill 中现有的"规则豁免"段落改写为完整收尾程序：适用前提（用户规则覆盖该任务类别且处于 active/enforced）→ 逐条判定 criteria.md（含证据链接，出现 `user-judgment` 条目即转 waiting_user 找用户）→ 门槛核对（独立检查与最终只读检查均通过、检查者与交付者不同实例、证据新鲜、无未解决 blocker）→ 生成 `checks/self-acceptance.md`（逐条判定表 + 门槛核对 + 引用证据）→ 以 `fstar accept --rule RULE.json` 完成验收（rule 文件含 `rule_ref`、`quote`、`criteria_refs`、`report`、`scope`）→ 下一轮对话主动向用户汇报结论与报告位置。
  2. 写明永不覆盖清单：版本发布与 npm publish、git push 与分支合并、删除数据与破坏性变更与 schema 迁移、对外发布内容、修改验收机制本身（accept 语义、evidence 校验、routing 硬规则）、密钥账号付款——这些必须用户亲验。
  3. 写明防漂移：自验收报告可被用户抽查；用户质疑任一报告时该结论回到待验收；用户在场要求亲验的任务退出自验收资格。
  4. check 角色卡补最终检查只读要求：最终检查的 allowed_paths 为空、只回报问题不自行修复、发现交付被改动必须说明而不是修改。
- 完成判据：Skill 与角色卡文本可直接照做，无需再解释规则语义。

### K-6 遗留路径清理

- 范围：`src/fstar/tasks.py`。
- 行动：`_REVISIT_DOCS` 中的 `doc/prd.md`、`doc/design.md` 已随模板迁移失效（默认模板集改为 scenarios/software 下的 prd/design），从重访列表移除，保留仍存在的 `plan.md`、`clarify.md`。
- 完成判据：重访列表不再包含已不存在的默认文档；`continue --action replan` 行为不变。

## 验证与交付

- 每个 K 项都要有对应测试：K-1..K-3 落在新增测试文件 `tests/test_acceptance_protocol.py`（内核），K-4..K-5 落在资源测试（可扩展 `tests/test_content.py`）。
- 全量回归：`PYTHONPATH=src python3 -m unittest discover -s tests -t .` 与 `node --test tests/test_package.cjs`。
- 资源改动后必须 `node scripts/build-package.cjs` 重建清单，并验证清单幂等（重复执行结果不变）。
- 影响面检查：按 `.fstar/specs/guides/impact-check-guide.md` 两层检查（调用方签名兼容 + 机制间交互），结论写进交付报告。K-1/K-2/K-3 改的是验收内核，必须核对 `acceptance_status`、`enter_awaiting_acceptance`、`accept`、`accept_unified`、`archive` 对证据状态与阶段迁移的消费关系。

## 依赖与调整

- K-1 与 K-2 都改验收内核，需在同一批次完成后再做独立检查，避免检查者读到半成品语义。
- K-4 的 criteria 条目化是 K-1（criteria_refs 定位）与 K-3（规则验收引用条目）能真正生效的前提：条目号必须先能被 artifact_map 识别。
- K-2 第 3 条若证明会破坏既有合法流程，允许降级为"标记陈旧 + 明确错误信息"，但必须在交付报告里写明降级理由与影响。
- 任一项无法在本规格内判定 → 停止该项并在回报中列出待决问题，不得自行扩范围。

## 维护

- 本规格的每一条在实施后都要能被测试或可审计记录验证；无法验证的条目不得标记完成。
- 实施完成后由独立检查方（fstar-check，全新实例）按 `resources/templates/task/check.md` 出具检查报告，报告存入任务目录 `checks/`。

## 沉淀

- 验收协议的任何改动都要同步更新 `resources/runtime/routing.md` 的硬规则里与"变更后重估验收结论"相关的那一条，避免规则与内核行为漂移。
