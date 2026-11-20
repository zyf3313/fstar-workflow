# 澄清：全局资源管理与 Magpie 集成

## 已确认需求

用户批准全局管理方案，并追加：
> 好 没问题 ，然后再加个安装初始化相关的因为现在有好多用户都有magpie这个app 在安装的时候能不能写个脚本做个将 skills还有hooks还有agets工作流里面的都集成到 magpie里面 如果发现用户没有magpie这个app就不用做了

此前用户确认：资源统一按全局版本，项目只保留任务、规范及身份配置；开启项目会话时检查旧项目与全局是否一致，不一致自然语言询问用户是否迁移。迁移后不再逐项目更新。用户批准所有权保护、备份、重复 hook 防护、拒绝后不重复提醒、会话重启提示、全局损坏诊断及数据迁移与资源更新分离。

## 已核实事实

- src/fstar/installer.py 当前默认在已初始化项目内写项目级宿主目录。resolve_resources 优先显式/项目配置，其次用户版本文件，最后 bundled。
- SessionStart/session-context 是检查入口；现有 session-context 在非初始化项目中仍可输出最小工作流上下文，不能宣称所有 hooks 静默。
- 本机 Magpie CLI 不在 PATH，但 /Applications/magpie.app/Contents/MacOS/magpie 存在，版本 0.1.4380。
- 只读运行 library --help 与 --help：公开支持 library skill hand-over <name…>（从 ~/.agents/skills 接管），skill agents、skill router <name> direct、skill how、library sync；无通用 hook 或子 agent 定义导入命令。不得编辑 Magpie 私有 library.json/providers.json。
- Magpie 的 agents 代表编码工具，不等同于 fstar-implement 等子 agent 定义。

## 实现默认值

- 安装器默认全局宿主入口；旧项目迁移需用户真实对话同意。只读启动检查不做升级、不清理、不写任务状态。提醒决定存全局 runtime，按项目身份+目标版本去重，由显式确认/延后操作记录。
- Magpie 缺失正常跳过；App 存在但不在 PATH 要能检测；功能不足/命令失败明确报告降级，不阻断基本 fstar 安装。只使用受支持的公开命令，不改模型、账号、provider、其他技能路由设置。
- skills 可通过命名接管和按技能 direct 分发（若该版本支持）接入 Magpie。hooks/子 agents 保持对应工具的全局原生配置并与 Magpie 共存；不宣称导入了 Magpie 不支持的能力。
- 测试仅临时 HOME/user/runtime/host 根与伪 CLI，不修改真实 Magpie/宿主配置。真实本机写入不属于本次开发验证。

## 本轮边界

完整工作流实施、独立检查、影响检查、README 更新；不自动验收、提交、合并、发布新任务。前次 npm 发布拒绝与本任务无关，不重试。

## 待决问题

无阻塞产品问题。公开能力若无法实现具体细节，报告真实限制，不通过私有文件或未公开接口绕过。
