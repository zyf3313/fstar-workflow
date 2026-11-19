<!-- Allowed placeholders: 1, FrancisZhang, 2026-11-19, FrancisZhang -->
<!-- Required placeholders must be replaced; unknown facts belong in 待确认. -->
<!-- fstar:slot:artifact_type:start -->prd<!-- fstar:slot:artifact_type:end -->
<!-- fstar:slot:version:start -->1<!-- fstar:slot:version:end -->
<!-- fstar:slot:review_state:start -->draft<!-- fstar:slot:review_state:end -->
<!-- fstar:slot:author:start -->FrancisZhang<!-- fstar:slot:author:end -->
<!-- fstar:slot:date:start -->2026-11-19<!-- fstar:slot:date:end -->
<!-- fstar:slot:reviewer:start -->FrancisZhang<!-- fstar:slot:reviewer:end -->

# 产品需求文档

> 来源：zyf3313/fstar-trellis-ext @ 674bea37cf2f6f25cd20dab93e1a54ae1f13ce66；当前环境仅持久化了来源核对摘要，未取得可合法逐字复制的固定全文。本模板按已批准结构改写，不声称逐字复制。

## 1. 背景与范围

<!-- fstar:item:R-001:start -->
### R-001 需求条目

- 业务结果：主会话每次收到开发类请求时，agent 必须先输出本轮流程判断（大/小/讨论/只读），大任务强制走完整 fstar 工作流
- 模块与优先级：runtime hooks + installer 注册 + 资源文本，P1
- 范围、不做、依赖与约束：新增 UserPromptSubmit→prompt-context 第五种 hook 语义；新增 prompt-states 资源（Trellis workflow-state 式标签块）；不做 PreToolUse 拦截；不变更既有四语义
- 验收条件（Given / When / Then）：Given 已初始化项目 When 每条用户消息 Then 注入一行状态面包屑与流程判断要求；Given workflow-states 资源缺失 Then 输出降级提示而非静默；Given 未初始化目录 Then 不输出
<!-- fstar:item:R-001:end -->

## 2. 业务流程

记录角色、输入、判断、输出、异常恢复，并区分现状与目标。

## 3. 模块与逐功能要求

覆盖职责、协作、正常流程、规则、异常、交互、字段与字典引用。

## 4. 跨模块要求与影响

按需记录权限审计、非功能、兼容迁移、UI 资产及实际检查证据。

## 5. 待确认、评审与版本

文档状态必须对应真实用户确认；文档完成不等于实现、检查或用户验收。
