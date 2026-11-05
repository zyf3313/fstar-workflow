# implement — install 默认项目级宿主根

## 执行序

1. [x] `roots_from_args`：新增 `user_level` 解析 + 项目级默认 + 非项目
       目录报错（含修复指引）。
2. [x] CLI：install/uninstall 加 `--user-level`；`--host-root` 帮助文本更新。
3. [x] `_handle_install`：TTY 确认（stdin.isatty + Y/n；aborted 零写入）。
4. [x] uninstall manifest 归属收紧：owned settings 路径集合与解析根的
       精确匹配（plan_install:544 一带）。
5. [x] 测试（tests/test_installer.py + CLI 面）：
   - 项目内默认项目级；非项目目录报错零写入
   - `--user-level` 用户级；`--host-root` 覆盖优先
   - TTY 确认 y/n；非 TTY 直通；dry-run 永不写
   - 用户级旧安装 uninstall `--user-level` 正确卸载；项目内裸
     uninstall 不误碰用户级条目
6. [x] README 安装章节 + `fstar install --help` 文本核对。
7. [x] 全量回归 → trellis-check（Agent）。

## 验证命令

```bash
PYTHONPATH=src python3 -m unittest tests.test_installer -v
PYTHONPATH=src python3 -m unittest discover -s tests -t .
node --test tests/test_package.cjs
```

## 风险与回滚

- `roots_from_args` 是所有 CLI 命令的根解析入口：改动必须保持
  `--host-root` 语义与现有 fixture 测试全绿；未提供 host 的命令
  （doctor/version/migrate）不受 host_roots 缺失影响——只对显式
  `--host` 的 install/uninstall 校验项目归属。
- TTY 确认不能阻塞 CI/管道：一切非 isatty 输入路径直接执行。
- 回滚点：单一提交；失败 revert 即可（本仓库已有 git）。

## start 前检查

- [x] prd/design/implement 三件套
- [x] inline 执行（上下文即设计依据）
- [ ] 用户批准后 start
