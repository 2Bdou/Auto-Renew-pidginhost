# Auto-Renew-pidginhost

🤖 自动续期 PidginHost 免费 VPS（CloudV 0）的脚本。

免费服务器有效期只有 **30 天**，手动续期太麻烦。本项目用 GitHub Actions **每 10 天自动登录面板点一次 "Extend 30 days"**，无限续期，续期结果通过 Telegram 通知你。

> PidginHost 免费 Cloud Server 到期前可无限次点 "Extend 30 days" 续期，不需要付费。

---

## 🚀 快速开始（别人/自己部署都按这个来）

只需要 3 步，全程在 GitHub 网页上完成，**不需要本地装任何东西**：

### 第 1 步：Fork 本仓库

点右上角 **Fork** 按钮，把这个仓库复制到你的 GitHub 账号下。

### 第 2 步：配置 Secrets（关键！不配会运行失败）

进入你 Fork 出来的仓库，打开：

> **Settings → Secrets and variables → Actions → New repository secret**

逐个添加下面 4 个变量（点一次 New repository secret 添加一个）：

| Secret 名称 | 必需 | 填什么 | 去哪拿 |
|---|---|---|---|
| `PIDGIN_EMAIL` | ✅ | 你的 PidginHost 登录邮箱 | [pidginhost.com](https://www.pidginhost.com) 注册邮箱 |
| `PIDGIN_PASSWORD` | ✅ | 你的 PidginHost 登录密码 | 同上 |
| `TG_BOT_TOKEN` | ❌ | Telegram bot 的 token | 找 [@BotFather](https://t.me/BotFather) → `/newbot` 创建机器人后获得 |
| `TG_CHAT_ID` | ❌ | 你的 Telegram 用户 ID | 找 [@userinfobot](https://t.me/userinfobot) 发任意消息即可看到 |
| `SMTP_CONFIG` | ❌ | SMTP 邮件通知（JSON，可选） | 与 dnshe-renewal 同格式：`{"host":"smtp.qq.com","port":465,"user":"you@qq.com","pass":"授权码","from":"you@qq.com","to":"recv@example.com","ssl":true}` |

> **注意**：Secret 名称必须**完全一致**（全大写、下划线），值填完就看不到了，输错只能删掉重加。
>
> `TG_BOT_TOKEN` / `TG_CHAT_ID` 不填也可以跑，只是收不到 Telegram 通知。
>
> 通知走通用 `notify.py` 模块（TG + SMTP 双通道，可并存）：配了 `SMTP_CONFIG` 就同时发邮件，都未配置则自动跳过不报错。

### 第 3 步：运行一次试试

1. 打开你仓库的 **Actions** 标签页
2. 左侧选 **Auto Renew PidginHost VPS** 工作流
3. 点右侧 **Run workflow** 按钮 → 绿色 **Run workflow** 确认

等 1~2 分钟跑完，看到绿色 ✅ 就说明配置成功，之后每 10 天会自动运行一次，无需再管。

---

## ⚙️ 工作原理

脚本用 Playwright 驱动浏览器，完全模拟手动操作：

1. 打开 PidginHost 登录页
2. 输入邮箱 → 输入密码 → 登录
3. 找到免费服务器 → 进入管理页
4. 点 **"Extend 30 days"** 续期
5. 抓取 Activity 确认出现新的 `Free VM renewal extended for 30 days` 记录
6. 发送通知（执行时间、账号、服务器、状态；TG + SMTP 双通道，未配置自动跳过）

### 定时与清理

- **每 10 天自动运行一次**（`schedule` 定时，UTC 00:00 = 北京时间 08:00）
- 每次运行后把当前时间写入 `time.txt` 并提交，**顺带作为"上次运行"的活证据**
- 自动清理旧的 workflow 记录，只保留最近 1 条，避免 run 列表堆积

### 报告示例（Telegram 收到的消息）

```
🤖 PidginHost 免费 VPS 自动续期报告
🕐 执行时间: 2026-08-04 16:47:20   （北京时间）
📮 账号: your-email@example.com
🖥️ 服务器: asmdmma
📊 状态: ✅ 成功
```

---

## 📦 本地运行（可选）

不想用 GitHub Actions，也可以在自己电脑/服务器上跑：

```bash
# 1. 装依赖
pip install -r requirements.txt
python -m playwright install chromium --with-deps

# 2. 配置环境变量（或用 .env，见 .env.example）
export PIDGIN_EMAIL="your-email@example.com"
export PIDGIN_PASSWORD="your-password"
export TG_BOT_TOKEN="123456:ABC..."      # 可选
export TG_CHAT_ID="123456789"            # 可选

# 3. 运行
python3 renew_pidginhost.py              # 正常执行
python3 renew_pidginhost.py --dry-run    # 只检查不续期
python3 renew_pidginhost.py --debug      # 调试模式
```

退出码：`0` = 续期成功，`1` = 失败/未延长。

本机 crontab 定时（每天 8:00 检查，脚本内部判断距上次成功 ≥ 10 天才真正执行）：

```cron
0 8 * * * cd /path/to/pidgin_renew && /usr/bin/python3 renew_pidginhost.py >> renew.log 2>&1
```

### 环境变量说明

| 环境变量 | 必需 | 说明 |
|---|---|---|
| `PIDGIN_EMAIL` | ✅ | PidginHost 登录邮箱 |
| `PIDGIN_PASSWORD` | ✅ | PidginHost 登录密码 |
| `TG_BOT_TOKEN` | ❌ | Telegram bot token（不填则跳过通知） |
| `TG_CHAT_ID` | ❌ | Telegram 接收报告的 chat id（不填则跳过通知） |
| `RENEW_INTERVAL_DAYS` | ❌ | 续期间隔天数（默认 10） |
| `SMTP_CONFIG` | ❌ | SMTP 邮件通知 JSON（与 dnshe-renewal 对齐，可选） |

> 🔒 **安全**：脚本内**不保存任何敏感信息**，凭据一律从环境变量 / GitHub Secrets 读取；缺少必需变量时直接报错退出。

---

## 📁 文件结构

```
.
├── renew_pidginhost.py        # 主脚本
├── notify.py                  # 通用通知模块（TG + SMTP 双通道）
├── requirements.txt           # Python 依赖
├── .env.example               # 本地环境变量模板（不含真实值）
├── time.txt                   # 每次运行自动更新时间戳
└── .github/workflows/renew.yml  # GitHub Actions 工作流
```

## ❓ 常见问题

**Q: 运行失败，日志显示缺少 Secrets？**
→ 回到第 2 步，确认 `PIDGIN_EMAIL` 和 `PIDGIN_PASSWORD` 两个 Secret 都已配置且名称完全一致。

**Q: 收不到 Telegram 通知？**
→ 确认 `TG_BOT_TOKEN` / `TG_CHAT_ID` 已配置。`TG_CHAT_ID` 是**数字 ID**（不是 @用户名），用 @userinfobot 查。

**Q: 续期失败/找不到续期按钮？**
→ 可能是 PidginHost 改版。失败时 Actions 会保留 `error_screenshot.png` 截图（在 Artifacts 里），下载看看页面结构，或提 issue。

**Q: 多久续一次？**
→ 每 10 天一次。服务器 30 天到期，每次续 30 天，相当于留 20 天余量，很稳。

**Q: 免费服务器会被收钱吗？**
→ 不会。免费套餐续期是官方提供的功能，点 "Extend 30 days" 免费延长，不产生任何费用。
