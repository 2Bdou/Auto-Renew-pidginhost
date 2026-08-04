# Auto-Renew-pidginhost

自动续期 PidginHost 免费 VPS（CloudV 0）的脚本。每 10 天运行一次，登录面板 → 点 "Extend 30 days" 延长免费服务器 → 检查 Activity 确认成功 → 发送 Telegram 报告。

## 原理

PidginHost 免费 Cloud Server 有效期 30 天，到期前可无限次点 "Extend 30 days" 续期。本脚本用 Playwright 驱动浏览器，完全模拟手动操作流程：

1. 打开 `https://www.pidginhost.com/panel/account/login`
2. 输入账号邮箱 → 点 "Log in / Sign up"
3. 输入密码 → 点 "Login"
4. 进入 Dashboard 找到免费服务器（如 `asmdmma`），点 Manage
5. 在管理页点 "Extend 30 days"
6. 抓取 `/activity_tab/` 确认出现新的 "Free VM renewal extended for 30 days" 记录
7. 发送 Telegram 报告

## 环境要求

- Python 3.8+
- `pip install -r requirements.txt`
- 首次运行需安装浏览器：`python3 -m playwright install chromium-headless-shell`

## 配置

脚本内 `CONFIG` 字典已有默认值；也可以通过环境变量覆盖（更推荐，避免硬编码）：

```bash
export PIDGIN_EMAIL="REMOVED_CREDENTIAL"
export PIDGIN_PASSWORD="your-password"
export TG_BOT_TOKEN="123456:ABC..."
export TG_CHAT_ID="123456789"
```

| 环境变量 | 说明 |
|---|---|
| `PIDGIN_EMAIL` | PidginHost 登录邮箱 |
| `PIDGIN_PASSWORD` | PidginHost 登录密码 |
| `TG_BOT_TOKEN` | Telegram bot token（发报告用） |
| `TG_CHAT_ID` | Telegram 接收报告的 chat id |

## 用法

```bash
# 正常执行（登录 + 延长 + 检查 Activity + 发 TG）
python3 renew_pidginhost.py

# 只登录检查，不点延长（安全演练）
python3 renew_pidginhost.py --dry-run

# 不发送 TG 报告
python3 renew_pidginhost.py --no-tg

# 调试模式（打印异常堆栈）
python3 renew_pidginhost.py --debug

# 有头模式（能看到浏览器窗口，排障用）
python3 renew_pidginhost.py --headless-off
```

退出码：`0` = 延长成功，`1` = 失败/未延长。

## 定时运行（每 10 天一次）

本机 crontab（示例，每天 8:00 检查一次，用文件锁保证每 10 天才真正执行一次）：

```cron
0 8 */10 * * cd /path/to/pidgin_renew && /usr/bin/python3 renew_pidginhost.py >> renew.log 2>&1
```

> 注意：cron 里写 `*/10` 表示每月的 1、11、21、31 号，间隔其实不均匀（31 号到次月 1 号只隔 1 天）。
> 更稳妥的做法是每天跑一次、脚本内部判断距上次成功延长是否 ≥ 10 天再执行。

QwenPaw 环境也可以直接用 cron skill 建 agent 任务：

```bash
qwenpaw cron create --agent-id default --type agent --schedule-type cron \
  --cron "0 8 */10 * *" \
  --channel telegram --target-user 7592034407 --target-session telegram:7592034407 \
  --text "运行 pidgin_renew/renew_pidginhost.py 自动续期 pidginhost VPS，完成后把报告发给我" \
  --timeout 600
```

## 文件结构

```
pidgin_renew/
├── renew_pidginhost.py   # 主脚本
├── requirements.txt      # Python 依赖
└── README.md             # 本文件
```

## 注意事项

- 免费服务器 30 天到期，续期窗口期内点按钮即可无限续，不需要付费
- 脚本每 10 天运行一次，相当于每次延长 30 天、留 20 天余量
- Activity 记录由服务端写入，偶尔有延迟（几秒~几十秒），脚本会等待重试一次
- 登录页有 cookie 弹窗，脚本会自动点 "Reject non-essential" 关闭
- 若 PidginHost 改版导致选择器失效，用 `--debug` + `error_screenshot.png` 排查
