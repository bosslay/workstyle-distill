# workstyle-distill

从用户确认过的工作与沟通方式中蒸馏协作规则。按情境使用，支持增量纠正，不把业务事实或每次临时选择累积成永久规矩。

## 使用

将本仓库放到 `~/.codex/skills/workstyle/`，或已配置的 skills 目录。技能在宿主重新扫描后可发现；当前会话也可显式引用该目录的 `SKILL.md`。

```text
$workstyle
$workstyle update
$workstyle show
$workstyle auto
$workstyle publish
```

“更新”会重新取证、归纳、去重并处理纠正，不只是追加文字。`profile.md` 是去标识的公开默认值；如有不同偏好，以当前用户明确要求为准。

## 隐私

本地个性化内容保存在 `$CODEX_HOME/private/workstyle-distill/`，未设置时使用 `~/.codex/private/workstyle-distill/`。也可通过可信环境变量 `WORKSTYLE_PRIVATE_DIR` 指定仓库外目录。规则依据、会话定位、任务状态与发布目标都不进入本仓库。公开的是协作规则，不是聊天记录。

## 静默更新

由宿主调度器调用同一技能。示例：每天当地时间 00:30 检查，其他任务忙碌、无法确定空闲或连接不可用时跳过。后台只更新本地，最多每 24 小时写入一次，没有变化不写文件；不自动提交或发布 GitHub。

技能本身不会常驻或定时执行。自动任务仍受宿主运行状态、权限与连接条件约束；安装技能不等于调度器已经配置。

## 验证

```text
python -X utf8 -m unittest -v test_workstyle
python -X utf8 workstyle.py check-public --root .
```

隐私扫描检测常见地址、凭据与非公开文件；不能代替人工审阅。详细更新和发布边界见 [update-guide.md](update-guide.md)。
