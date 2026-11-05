# 项目长期知识库

> **状态（2026-10-29）**：以下内容已被取代，现行以 `prd.md` 与 `policy-decisions.md` 为准：独立 `knowledge/decisions/` **已删除**，长期决定与原因并入对应主题 `specs/`；`knowledge/` 最终仅 `context/`（领域事实、术语、FAQ）与 `references/`（外部资料与来源），**不设 `history.md`**，「项目做过什么」改为 `fstar task list --archived` 派生视图；`knowledge/` 与 `specs/` 入 git，`runtime/` 与 `config.local.yaml` 不入库。

状态：规划草案，2026-10-27。**不构成实现授权。**

> **定位（2026-10-28 最小内核 + 扩展包定案）**：知识库 + specs 主题归口 + rules/memory 共同构成**「项目治理包」**——六个扩展包之一，**要求项目已 init**。未加载该包时 fstar 仍可用最小闭环走完闭环，只是不做长期沉淀。加载该包时默认整包加载、用户可裁剪，授权记 `task.json.extensions[]`。见父任务 `prd.md` §12、`design.md` §2.4。

用户 2026-10-27 提出：旧扩展项目里还有「项目长期知识库」的概念，一并讨论。

来源：`personal-trellis/README.md:199-217`（「需求与长期资产」）、`README.md:211-217`（布局）、`README.md:26`（「长期资产有入口」）。

---

## 一、旧项目的原始形态

```text
docs/requirements/YYYY-MM-DD-slug/
  README.md                 # 身份、状态、任务与权威源引用
  product-requirements.md
  technical-design.md
  test-cases.md
  test-runs/<run-id>.md
docs/requirements/archive/YYYY-MM/YYYY-MM-DD-slug/
design/ui/                  # 长期设计源、tokens、组件与页面
design/prototypes/          # 真实原型源码与状态
review/                     # 可选评审运行器
```

旧项目 README 的核心主张：

- 「**一项需求可关联多个原生任务**，任务链接需求版本与负责模块，不复制正文。」
- 「**需求归档时保留长期 UI/原型资产**，并记录其不可变版本。」
- 「产品需求说明、技术方案是面向用户的附加产物，**不替代**原生 `prd.md` / `design.md`。」

---

## 二、为什么 fstar 需要重新定位它

fstar 已定「**一个完整需求 = 一个主任务**，子任务在主任务内部」。所以旧项目的 `docs/requirements/<slug>/` 和 fstar 的 `tasks/<id>-<名称>/` **职责重叠**——不该搬过来。

但旧项目还有一类东西是 fstar 当前结构里**没有对应物**的：跨任务累积、不随单个任务归档而消失的知识。

### 三个必须分清的概念

| 概念 | 生命周期 | fstar 里的位置 |
|---|---|---|
| **任务产物** | 一次任务内，任务归档时进 `archive/` | `tasks/<id>/` |
| **项目规范** | 长期有效，被所有任务引用 | `.fstar/specs/` |
| **长期知识** | 跨任务累积，**不随单个任务归档而消失** | ← 缺这一层 |

第三类就是「项目长期知识库」。

### 与 `specs/` 的区别

| | `specs/` | 长期知识库 |
|---|---|---|
| 内容 | 约束与做法（「测试怎么写」「命名规则」） | 事实与历史（「为什么当初这么定」「当时的结论」） |
| 变更频率 | 偶尔改，改了影响所有任务 | 持续追加，**不覆盖旧条目** |
| 读者 | 写代码时 | 遇到相似问题时回溯 |

---

## 三、落点（2026-10-27 用户已确认：项目级）

```text
<项目>/.fstar/knowledge/
  decisions/            # 长期决定与原因（时间序，不覆盖）
    2026-10-27-选择-codegraph.md
  references/           # 外部资料快照 + 来源
  context/              # 领域上下文、术语表、常见问题
```

**用户级不放知识库。** 跨项目经验走已定的 `~/.fstar/memory/`；项目特有知识留在项目内，避免与「项目规范优先于全局」规则打架。

### 与被砍掉的 `decisions/` 不矛盾

2026-10-26 砍掉的是**任务级**决定记录（每个任务目录下一个 `decisions/`）。这里的是**项目级长期知识**里的决定时间线。两者生命周期不同：

| | 任务级决定 | 项目长期决定 |
|---|---|---|
| 位置 | 任务 `design.md`（原 `decisions/` 已砍） | `.fstar/knowledge/decisions/` |
| 生命周期 | 随任务归档 | 永久留存 |
| 作用 | 解释本次取舍 | 解释项目为何如此 |

---

## 四、和能力维度的闭环

维度 3「本地知识检索」的工具（QMD 等）检索的对象，**主要就是 fstar 自己的知识库 + 项目 specs**。

```
知识库（累积的项目历史）
    ↑
    │ 维度 3 的工具去查它
    ↓
查到以前的相关决定 → 避免重复踩坑
```

这不是巧合：旧项目 `knowledge-search.md` 的 Verified baseline 索引的 85 个 Markdown 文件，正是 `spec/guides` 那些。

---

## 五、怎么被写进去

复用已定的 `fstar-learn` 流程，**不另开一条路**：

| 内容 | 去向 |
|---|---|
| 长期有效的项目规范 | `.fstar/specs/<主题>.md` |
| 长期决定与原因 | `.fstar/knowledge/decisions/` |
| 领域术语、上下文、常见问题 | `.fstar/knowledge/context/` |
| 外部资料快照 | `.fstar/knowledge/references/` |
| 任务内的取舍 | 任务 `design.md`（随任务归档） |
| 个人跨项目经验 | `~/.fstar/memory/` |

写入前仍走已确认的流程：**先列候选 → 用户确认内容及全局/项目归属 → 再保存**。未确认候选不参与加载。

---

## 六、和旧项目布局的差异

| 旧项目 | fstar | 说明 |
|---|---|---|
| `docs/requirements/<slug>/` | 任务的 `prd.md` / `design.md` / `implement.md` | 需求 = 主任务，不再平行建目录 |
| `docs/requirements/archive/` | `archive/<年月>/<任务目录>/` | 归档按任务整棵移入 |
| `design/ui/`、`design/prototypes/` | 尚无对应 | **待定**，见下 |
| `review/`（Storybook） | 不在第一版范围 | 属扩展市场/门户类，非目标 |

### 待定：长期设计资产

旧项目把 UI 设计源、tokens、组件、真实原型放在项目 `design/` 下，作为**长期资产**保留。fstar 当前只有「可选 UI 能力」（`fstar-ui-design` + 两份模板），产物落在 `specs/ui-baseline.md` 或任务 `design/ui-feature.md`。

两个问题尚未解决：

1. **原型源码算不算长期资产？** 旧项目明确「真实原型源码与状态」是长期保留的，fstar 没有对应容器。
2. **UI 基线放 `specs/` 还是 `knowledge/`？** 它是「约束」（怎么设计）还是「事实」（历史基线）？按上面的区分，基线更像规范，但 prototypes 更像长期资产。

第一版可以不解决——原型与设计资产属于较重场景，fstar 的第一版范围是工作流闭环。但要在 `design.md` 里明确写「未覆盖」，不留模糊。

---

## 七、遗留问题

| # | 问题 | 状态 |
|---|---|---|
| 1 | 知识库与 `specs/` 的边界在实际使用中会不会模糊 | 待实际使用验证 |
| 2 | 决定条目要不要索引/检索 | 建议由维度 3 的工具承担，不另建 |
| 3 | 知识库要不要版本控制 | 建议入 git（项目级），但需确认用户是否愿意把知识库纳入版本控制 |
| 4 | 旧项目的 `docs/requirements/` 已有内容如何迁移 | **仅引用，不迁移**（与已有决策一致） |
| 5 | 长期设计资产与原型的落点 | 见第六节，第一版可不解决 |
