#!/usr/bin/env python3
"""
PidginHost 免费 VPS 自动续期脚本
================================
流程（与手动操作一致）：
  1. 打开 https://www.pidginhost.com/panel/account/login
  2. 输入账号邮箱 → 点击 Log in / Sign up
  3. 输入密码 → 点击 Login
  4. 进入 Dashboard，找到服务器，点击 Manage
  5. 点击 Extend 30 days 按钮延长 VPS
  6. 打开 Activity 页，确认出现延长记录
  7. 发送 Telegram 报告

用法：
  python3 renew_pidginhost.py                # 正常执行（每 10 天一次）
  python3 renew_pidginhost.py --dry-run      # 只登录并汇报状态，不点延长
  python3 renew_pidginhost.py --debug        # 保留浏览器可见 + 打印详细日志
  python3 renew_pidginhost.py --headless-off # 有头模式（便于排障）

配置：所有凭据一律从环境变量读取（PIDGIN_EMAIL/PIDGIN_PASSWORD），
      通知复用 notify.py 模块（TG_BOT_TOKEN/TG_CHAT_ID/SMTP_CONFIG 双通道，未配置自动跳过）。
      脚本内不保存任何敏感信息。未设置必需环境变量时直接报错退出。
"""

import argparse
import datetime
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# 配置（只读环境变量，不写死任何敏感信息）
# ---------------------------------------------------------------------------
BASE_URL = "https://www.pidginhost.com"
LOGIN_URL = BASE_URL + "/panel/account/login"

# 北京时间（UTC+8）
TZ_CN = datetime.timezone(datetime.timedelta(hours=8))


def now_cn() -> datetime.datetime:
    """当前时间（北京时间，带 tz）。"""
    return datetime.datetime.now(TZ_CN)

# 必需的环境变量
REQUIRED_ENV = {
    "PIDGIN_EMAIL": "PidginHost 登录邮箱",
    "PIDGIN_PASSWORD": "PidginHost 登录密码",
}
# 可选的环境变量
OPTIONAL_ENV = {
    "TG_BOT_TOKEN": "Telegram bot token（发报告用）",
    "TG_CHAT_ID": "Telegram 接收报告的 chat id",
    "RENEW_INTERVAL_DAYS": "续期间隔天数（默认 10）",
    "STATE_FILE": "状态文件路径（默认 .last_renew）",
    "SMTP_CONFIG": "SMTP 邮件通知配置（JSON，可选，与 notify.py 对齐）",
}


def get_env(name: str) -> str:
    """读取环境变量，缺失则报错（TG 相关允许为空则跳过通知）。"""
    val = os.environ.get(name, "").strip()
    if not val:
        if name in REQUIRED_ENV:
            raise RuntimeError(f"缺少必需环境变量 {name}（{REQUIRED_ENV[name]}）")
        return ""
    return val


def get_conf() -> dict:
    """统一读取全部配置，只来自环境变量。"""
    return {
        "pidgin_email": get_env("PIDGIN_EMAIL"),
        "pidgin_password": get_env("PIDGIN_PASSWORD"),
        "tg_bot_token": get_env("TG_BOT_TOKEN"),
        "tg_chat_id": get_env("TG_CHAT_ID"),
        "base_url": BASE_URL,
        "renew_interval_days": int(os.environ.get("RENEW_INTERVAL_DAYS", "10")),
        # 状态文件：记录上次成功续期时间（默认与脚本同目录）
        "state_file": os.environ.get("STATE_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".last_renew")),
    }


CONFIG = get_conf()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
class PidginRenewer:
    def __init__(self, headless=True, dry_run=False, debug=False):
        self.headless = headless
        self.dry_run = dry_run
        self.debug = debug
        self.email = CONFIG["pidgin_email"]
        self.password = CONFIG["pidgin_password"]
        self.results = []          # (时间, 事件)
        self.extended = False
        self.activity_lines = []
        self.server_name = None
        self.server_url = None
        self.server_id = None

    def log(self, msg):
        line = f"[{now_cn().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        print(line)
        self.results.append(line)

    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
                viewport={"width": 1440, "height": 900},
                locale="en-US",
            )
            page = ctx.new_page()
            page.set_default_timeout(30000)

            try:
                self._login(page)
                self._find_server(page)
                if self.server_url:
                    self._open_server(page)
                    if not self.dry_run:
                        self._extend(page)
                    self._check_activity(page)
            except Exception as e:
                self.log(f"❌ 流程异常: {e}")
                if self.debug:
                    import traceback
                    traceback.print_exc()
                try:
                    page.screenshot(path="error_screenshot.png", full_page=True)
                    self.log("已保存 error_screenshot.png")
                except Exception:
                    pass
            finally:
                browser.close()

        return self._build_report()

    # ---- 登录 ----
    def _login(self, page):
        self.log(f"🔓 打开登录页 {LOGIN_URL}")
        page.goto(LOGIN_URL, timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2000)

        # 处理 cookie 弹窗（如出现）
        try:
            reject = page.locator("button:has-text('Reject non-essential')")
            if reject.count() > 0:
                reject.click(timeout=5000)
                page.wait_for_timeout(800)
                self.log("🍪 已关闭 cookie 弹窗")
        except Exception:
            pass

        # 第一步：邮箱
        email_input = page.locator("input[name=email]").first
        email_input.fill(self.email)
        self.log(f"📧 输入账号: {self.email}")
        page.locator("button[type=submit], button:has-text('Log in / Sign up')").first.click()
        page.wait_for_timeout(2500)

        # 第二步：密码
        pw_input = page.locator("input[type=password]").first
        if pw_input.count() == 0:
            raise RuntimeError("未找到密码输入框，登录流程异常")
        pw_input.fill(self.password)
        self.log("🔑 输入密码并登录")
        page.locator("button[type=submit], button:has-text('Login')").first.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(4000)

        if "/panel/account/" in page.url and "login" in page.url:
            raise RuntimeError(f"登录未成功，仍在登录页: {page.url}")
        self.log(f"✅ 登录成功 → {page.url}")

    # ---- 找服务器 ----
    def _find_server(self, page):
        links = page.locator("a[href*='/panel/cloud/servers/']").all()
        # 过滤掉 create/ 链接
        server_links = [l for l in links if not (l.get_attribute("href") or "").endswith("/create/")]
        if not server_links:
            # 也许需要去 Cloud 页面
            self.log("Dashboard 未直接显示服务器，尝试打开 Cloud 列表")
            page.goto("https://www.pidginhost.com/panel/cloud/", timeout=60000)
            page.wait_for_timeout(3000)
            server_links = [l for l in page.locator("a[href*='/panel/cloud/servers/']").all()
                            if not (l.get_attribute("href") or "").endswith("/create/")]
        if not server_links:
            raise RuntimeError("未找到任何 Cloud Server")
        href = server_links[0].get_attribute("href")
        # 统一成 .com 域名
        if href.startswith("https://www.pidginhost.ro"):
            href = "https://www.pidginhost.com" + href.split("/panel")[1]
        elif href.startswith("/"):
            href = CONFIG["base_url"] + href
        self.server_url = href
        self.server_id = href.rstrip("/").split("/")[-1]
        self.server_name = server_links[0].text_content().strip()
        self.log(f"🖥️ 找到服务器: {self.server_name} → {self.server_url}")

    # ---- 打开服务器管理页 ----
    def _open_server(self, page):
        self.log(f"🔧 打开管理页 {self.server_url}")
        page.goto(self.server_url, timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        # 检查是否显示免费服务器到期信息
        expire_text = page.locator("text=expires in").all_text_contents()
        if expire_text:
            self.log(f"⏳ 服务器状态: {expire_text[0].strip()}")

    # ---- 点 Extend 30 days ----
    def _extend(self, page):
        # 1. 先记录当前 Activity（点击前基线，用于延长后对比）
        before = self._fetch_activity(page)

        # 2. 回服务器管理页（确保按钮可见）
        try:
            page.goto(self.server_url, timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2500)
        except Exception as e:
            self.log(f"⚠️ 回到管理页失败: {e}")

        # 3. 找按钮（可能在普通位置，也可能在 Actions 下拉里）
        btn = page.locator("button:has-text('Extend 30 days')").first
        if btn.count() == 0:
            # 尝试展开 Actions 菜单再找
            try:
                actions = page.locator("button:has-text('Actions')").first
                if actions.count() > 0:
                    actions.click(timeout=5000)
                    page.wait_for_timeout(800)
                    btn = page.locator("button:has-text('Extend 30 days')").first
            except Exception:
                pass
        if btn.count() == 0:
            self.log("⚠️ 未找到 'Extend 30 days' 按钮（可能已延长或页面结构变化）")
            # 兼容：若服务器仍显示有效（expires in N days），视为无需续期/已续期成功
            expire_text = page.locator("text=expires in").all_text_contents()
            if expire_text:
                self.log(f"ℹ️ 服务器状态: {expire_text[0].strip()} → 无需续期，视为成功")
                self.extended = True
                return True
            return False

        # 4. 点按钮
        btn.click()
        self.log("🔄 已点击 'Extend 30 days'，等待处理...")
        page.wait_for_timeout(4000)

        # 确认按钮消失或页面重新加载
        try:
            page.wait_for_url(re.compile(r"/panel/cloud/servers/\d+/"), timeout=10000)
        except PWTimeout:
            pass
        page.wait_for_timeout(2000)

        # 5. 点击后抓 Activity 对比基线
        page.wait_for_timeout(3000)
        after = self._fetch_activity(page)
        new_lines = [l for l in after if l not in before]
        if new_lines:
            self.log(f"✅ Activity 确认新增 {len(new_lines)} 条续期记录:")
            for l in new_lines:
                self.log(f"    {l}")
            self.activity_lines = after
            self.extended = True
        else:
            self.log("⚠️ Activity 未出现新记录，等待后重试...")
            page.wait_for_timeout(5000)
            after = self._fetch_activity(page)
            new_lines = [l for l in after if l not in before]
            if new_lines:
                self.log(f"✅ Activity 确认新增 {len(new_lines)} 条续期记录:")
                for l in new_lines:
                    self.log(f"    {l}")
                self.activity_lines = after
                self.extended = True
            else:
                # 再兜底：按钮点击后可能已成功但 Activity 延迟，检查页面是否还有按钮
                try:
                    page.goto(self.server_url, timeout=30000)
                    page.wait_for_timeout(2500)
                    btn2 = page.locator("button:has-text('Extend 30 days')").first
                    if btn2.count() == 0:
                        self.log("✅ 按钮已消失（续期成功，Activity 延迟未显示）")
                        self.extended = True
                    else:
                        self.activity_lines = after
                        self.log("⚠️ Activity 中仍未确认到新记录，可能延迟或未成功")
                except Exception as e:
                    self.log(f"⚠️ 兜底检查失败: {e}")
                    self.activity_lines = after
                    self.log("⚠️ Activity 中仍未确认到新记录，可能延迟或未成功")
        return self.extended

    # ---- 抓取 Activity 记录 ----
    def _fetch_activity(self, page):
        try:
            act_url = self.server_url.rstrip("/") + "/activity_tab/"
            page.goto(act_url, timeout=30000)
            page.wait_for_timeout(1500)
            body = page.locator("body").inner_text()
            lines = [l.strip() for l in body.split("\n") if "renewal" in l.lower() or "extend" in l.lower()]
            return lines
        except Exception as e:
            self.log(f"⚠️ 抓取 Activity 失败: {e}")
            return []

    # ---- 检查 Activity ----
    def _check_activity(self, page):
        if not self.server_url:
            return
        self.activity_lines = self._fetch_activity(page)
        if self.activity_lines:
            self.log("📋 Activity 中的续期记录:")
            for l in self.activity_lines:
                self.log(f"    {l}")
        else:
            self.log("📋 Activity 中暂无续期记录")

    # ---- 报告 ----
    def _build_report(self):
        # 执行时间用北京时间
        now = now_cn().strftime("%Y-%m-%d %H:%M:%S")
        status = "✅ 成功" if self.extended else ("🔍 仅检查(DRY-RUN)" if self.dry_run else "❌ 失败/未延长")
        # 精简版：只发核心状态，Activity/执行日志只用于本地判断，不进 TG
        lines = [
            f"🤖 PidginHost 免费 VPS 自动续期报告",
            f"🕐 执行时间: {now}",
            f"📮 账号: {self.email}",
            f"🖥️ 服务器: {self.server_name or '未知'}",
            f"📊 状态: {status}",
        ]
        # 仅失败时附一句原因（成功/检查不需要）
        if not self.extended and not self.dry_run:
            if self.activity_lines:
                lines.append(f"⚠️ 最近续期记录: {self.activity_lines[0]}")
            else:
                lines.append("⚠️ 未能确认续期，请查看完整日志")
        report = "\n".join(lines)
        return report


def main():
    ap = argparse.ArgumentParser(description="PidginHost VPS 自动续期")
    ap.add_argument("--dry-run", action="store_true", help="只登录检查，不点延长")
    ap.add_argument("--debug", action="store_true", help="调试模式（打印异常堆栈）")
    ap.add_argument("--headless-off", action="store_true", help="有头模式运行")
    ap.add_argument("--no-tg", action="store_true", help="不发送通知（TG/SMTP）")
    ap.add_argument("--force", action="store_true", help="忽略 10 天间隔，强制续期")
    args = ap.parse_args()

    # ---- 10 天间隔控制 ----
    state_file = CONFIG["state_file"]
    interval = CONFIG["renew_interval_days"]
    now = now_cn().replace(tzinfo=None)  # 北京时间（naive），与 .last_renew 保持一致
    if not args.force and not args.dry_run:
        last_ts = None
        if os.path.exists(state_file):
            try:
                raw = open(state_file).read().strip()
                # 兼容带时区(offset-aware)的 ISO 时间，统一转 naive
                if raw.endswith("Z"):
                    raw = raw[:-1] + "+00:00"
                last_ts = datetime.datetime.fromisoformat(raw)
                if last_ts.tzinfo is not None:
                    last_ts = last_ts.replace(tzinfo=None)
            except Exception:
                pass
        if last_ts is not None:
            days_since = (now - last_ts).days
            if days_since < interval:
                print(f"[SKIP] 上次续期 {last_ts.strftime('%Y-%m-%d %H:%M')}，距今 {days_since} 天 < {interval} 天，跳过本次执行")
                return 0

    renewer = PidginRenewer(
        headless=not args.headless_off,
        dry_run=args.dry_run,
        debug=args.debug,
    )
    report = renewer.run()

    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)

    if not args.no_tg:
        try:
            from notify import send_notification
            send_notification(report, title="PidginHost 续期报告")
        except ImportError:
            print("[notify] 未找到 notify.py，跳过通知")
        except Exception as e:
            print(f"[notify] 通知发送异常: {e}")

    # 成功续期后记录状态时间
    if renewer.extended and not args.dry_run:
        try:
            with open(state_file, "w") as f:
                f.write(now.isoformat())
            print(f"[STATE] 已记录续期时间 → {state_file}")
        except Exception as e:
            print(f"[STATE] 写入状态文件失败: {e}")

    # 退出码：成功=0（dry-run 视为成功，仅检查），失败=1
    if args.dry_run:
        return 0
    return 0 if renewer.extended else 1


if __name__ == "__main__":
    sys.exit(main())
