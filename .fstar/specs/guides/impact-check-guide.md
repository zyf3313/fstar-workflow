# 交付影响面检查指南

> 每次修复或功能开发完成后、报告"完成"之前,必须执行本检查。跑过相关测试不等于影响检查。

## 为什么需要

fstar 内核是紧耦合状态机(tasks/evidence/lease/archive/events 共享 task.json)。局部改动会静默改变相邻行为——2026-11-19 的实例:correction 事件没有加进 MILESTONES,事件压缩机制会静默丢弃它,单看调用方签名和单测完全发现不了,直到按机制交互扫描才抓到。

## 检查清单(两层,缺一不可)

### 第一层:调用方核对(签名兼容)
- 用 codegraph callers/impact 找出改动符号的全部调用方
- 新参数必须带默认值或显式核对每个调用点
- 既有调用方零改动通过 ≠ 安全,继续第二层

### 第二层:机制间交互(真实缺陷藏在这里)
- **事件类型**:新增事件 type 是否需要进 `MILESTONES`?(不进会被 `compact_events` 超限折叠,`src/fstar/tasks.py:18`)
- **注入路径**:hook 注入的文件是否走了 `_safe_context_path`(符号链接/越界检查)?
- **归档/验收校验**:`_validate_archive_tree`、`acceptance_status` 消费哪些字段?新增的事件 data 键、task.json 字段是否被它们隐式依赖?
- **预算与压缩**:新注入是否受 budgets 约束?新记录是否会无界增长(参考 rejected 账本的索引行方案)?
- **installer manifest**:资源文件改动后必须 `node scripts/build-package.cjs`,否则测试报 package-assets 不匹配

### 收尾
- 全量测试(`PYTHONPATH=src python3 -m unittest discover -s tests -t .` + `node --test tests/test_package.cjs`)
- 影响结论写进交付报告,发现的每个真实影响点配回归测试

## 发版合并时附加:README 检查

合并发版前读一遍 README 的工作流/阶段/特性段落,对照本次变更日志更新落后描述;README 编辑放进 release commit。

## 关联

- 触发条件与本仓库 `AGENTS.md` 的交付要求一致;本指南给出具体操作标准
- 事件压缩细节见 `src/fstar/tasks.py` 的 `compact_events`
