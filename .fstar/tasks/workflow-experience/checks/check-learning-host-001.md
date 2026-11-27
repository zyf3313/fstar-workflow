# check-learning-host-001：真实宿主自然触发验证（协调方执行，非独立检查）

- 时间：2026-11-26。环境：Herdr 桌面端（`herdr-app`）→ `herdr-core`（`hc`）→ AgentWorkspace 空间；仓库临时副本 `/tmp/fstar-host-verify.U5zMYIp1/repo`；隔离 `FSTAR_USER_ROOT`、`FSTAR_RUNTIME_ROOT`、`TMPDIR`；真实 HOME 仅提供 Claude Code 鉴权与全局配置。
- 手段：用 `herdr-app do tab.new` 在 AgentWorkspace 空间新开标签页，`hc send`/`hc read` 投递并取回。旧版全局 hook 仅在用户明确授权后，用临时 PATH 垫片在该验证会话内屏蔽；新版 hook 由仓库 `bin/fstar-hook.cjs` 通过 `--settings` 注入。未修改任何真实配置。
- 真实数据核对：验证前后真实项目 `.fstar`（289 个文件）和真实用户 `~/.fstar`（2587 个文件）逐文件 SHA256 完全一致；副本 `.fstar/knowledge` 未写入。

## 已验证

- 自然识别：多个会话都主动识别了用户陈述的长期约定，并按授权规则说明范围、收益和成本。
- 授权边界：没有在未获授权时写入知识、规则或宿主 memory；给出了项目级/用户级范围建议。
- 会话正确引用了新版 routing 中“自动派发 fstar-learn 角色”的段落。

## 未通过

用户陈述长期约定后，协调者在主会话内联完成候选整理与授权建议，**没有自动派发后台 fstar-learn 子 agent**，主会话在整理期间被占用（约 45 秒）。

- 干净环境会话 t1v：routing 只注入新版；会话原样引用了 “automatically dispatch the installed fstar-learn role … and continue the current work without waiting”；随后明确回答“当前可用 Agent 类型列表里包含 fstar-learn”；在给出一条长期约定并附带一个小问题后，仍在主会话内联给出建议，未派发、也未报告角色不可用。
- 旧环境会话 t1m、t1n 表现相同（其 routing 为旧版，按旧版“提出候选”行为，可作为对照）。
- 影响：A-001 要求“自动触发专门后台子 agent 梳理与处理，不阻塞主会话，报告实际派发和处理结果”，该场景不满足。

## 限制与未覆盖

- 这是模型行为层结果；单次场景，未覆盖多种措辞、任务进行中触发、显式拒绝派发等分支。
- 归档复盘（A-001 后半）未验证：真实归档需要已验收任务，测试副本中的验收仍需用户确认，不能用假造确认替代。
- 测试使用 `--settings` 加垫片模拟“仅新版 hook”，不是一次真实的全局安装；正式安装后应由最终检查复核。

## 证据位置

终端 t1v（干净环境）、t1m/t1n（旧环境对照）；`hc read t1v` 可复看原文。临时环境 `/tmp/fstar-host-verify.U5zMYIp1/`。真实数据前后哈希清单位于同目录 `baseline-real.txt`。
