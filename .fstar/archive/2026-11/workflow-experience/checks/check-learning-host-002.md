# check-learning-host-002：后台学习自然触发的宿主复测

- 结论：本次场景观察到通过；不是 A-001 全范围或归档流程的验收结论。协调方通过 Herdr 操作，非独立检查。
- 基线：临时项目副本 `/tmp/fstar-host-verify.U5zMYIp1/repo`；`resources/runtime/prompt-states.md` SHA256 `d7bf5cc0a4f26bfa2cd38cc0ec1b6080c872137f35938e79990cb272cd38a2a0`。用户此前明确授权该临时会话屏蔽全局旧 fstar hook；使用项目新版 hook、临时用户根和运行目录。不是全局实际安装验证。
- 过程：用户模拟输入一条与项目测试有关的长期约定，同时询问测试文件的用途。宿主通过原生 `fstar-learn` Agent 显示 `Backgrounded agent`；协调者在仍显示 `1 local agent still running` 时回答测试问题、说明尚未保存和授权要求，随后宿主显示该后台 Agent completed。终端地址 t1w，位于 AgentWorkspace 的 fstar-recheck 标签页。
- 结果：此场景证实了实际后台派发、主会话在子代理仍运行时继续回答，以及未声称已经持久保存。未独立核实后台结果具体内容、角色拒绝/不可用路径、其他语义措辞或真实全局安装；归档复盘另行验证。模拟约定仅为测试输入，并非真实用户授权建立的持久规则。
- 对照：此前 check-learning-host-001 在类似场景未观察到后台派发；本次修复后观察到明确的宿主启动与完成提示。静态独立复查 check-learning-dispatch-002 报告 206 项测试通过，其范围不等于真实宿主复测。
