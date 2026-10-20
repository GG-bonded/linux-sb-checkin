#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""linux.sb 轻量任务：仅使用标准库；首次使用请先确认站点允许自动化。"""

import argparse
import getpass
import hashlib
import html
import http.cookiejar
import json
import os
import re
import secrets
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener


SITE = "https://linux.sb/"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
MAX_BODY = 2 * 1024 * 1024
VERSION = "2.0"
RED_DOT_COUNT = 3


def log(message):
    """只记录状态，不打印 Cookie、CSRF 或页面全文。"""
    print("[{}] {}".format(datetime.now().astimezone().isoformat(timespec="seconds"), message), flush=True)


def same_site(url):
    """仅允许本站 HTTPS 地址，禁止把请求发送到广告商或其他主机。"""
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.netloc == "linux.sb"


class SiteRedirect(HTTPRedirectHandler):
    """跨站重定向立即停止，且不跟随领取 POST 的重定向。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not same_site(newurl) or req.get_method() != "GET":
            raise RuntimeError("收到跨站或领取请求重定向，已停止；请检查登录状态。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HomePage(HTMLParser):
    """从当天页面读取用户卡片、领取表单和未完成红点，不硬编码广告位。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.name_parts = []
        self.has_user_card = False
        self.visitor = False
        self.has_board = False
        self.has_wrap = False
        self.hidden_board = False
        self.forms = {}
        self.all_slots = {}
        self.slots = []

    def inside_class(self, name):
        return any(name in attrs.get("class", "").split() for _, attrs in self.stack)

    def inside_attr(self, name):
        return any(name in attrs for _, attrs in self.stack)

    def handle_starttag(self, tag, items):
        attrs = dict(items)
        classes = attrs.get("class", "").split()
        if "user-card" in classes:
            self.has_user_card = True
        if ("visitor-avatar" in classes or "side-auth" in classes) and self.inside_class("user-card"):
            self.visitor = True
        if "data-sidebar-promotions-board" in attrs:
            self.has_board = True
        if self.inside_attr("data-sidebar-promotions-board"):
            if "data-sidebar-promotions-wrap" in attrs:
                self.has_wrap = True
                self.hidden_board = "hidden" in attrs or "is-hidden" in classes
            for kind in ("click", "show", "hide"):
                marker = "data-sidebar-promotions-{}-form".format(kind)
                if tag == "form" and marker in attrs:
                    self.forms[kind] = {
                        "action": urljoin(SITE, attrs.get("action") or ""),
                        "method": attrs.get("method", "get").lower(), "fields": {},
                    }
                if tag == "input" and self.inside_attr(marker) and kind in self.forms:
                    # 与 FormData 一样排除禁用和未勾选的表单项。
                    checked = attrs.get("type") not in ("checkbox", "radio") or "checked" in attrs
                    if attrs.get("name") and "disabled" not in attrs and checked:
                        self.forms[kind]["fields"][attrs["name"]] = attrs.get("value", "")
        if tag == "a" and self.inside_attr("data-sidebar-promotions-board"):
            if attrs.get("data-sidebar-promotions-lottery-slot") == "1":
                key = attrs.get("data-promotion-id", "")
                order = attrs.get("data-sidebar-promotions-order-id", "")
                if key and order:
                    done = attrs.get("data-sidebar-promotions-lottery-done") == "1"
                    self.all_slots[key] = done
                    if not done:
                        self.slots.append({"placement_key": key, "order_id": order})
        if tag not in VOID:
            self.stack.append((tag, attrs))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        # 容忍 HTML 内部嵌套变化，但不把其他表单字段误认为领取参数。
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.inside_class("user-card") and self.inside_class("user-name"):
            self.name_parts.append(data)

    @property
    def logged_in(self):
        name = "".join(self.name_parts).strip()
        return self.has_user_card and bool(name) and name != "访客" and not self.visitor

    @property
    def form(self):
        """保留领取表单的便捷访问方式。"""
        return self.forms.get("click")


def confirmed(value):
    """兼容明确的布尔值及常见 0/1 编码，不把字符串 false 当作成功。"""
    return value is True or (type(value) is int and value == 1) or (
        isinstance(value, str) and value.strip().lower() in ("1", "true")
    )


def number(value):
    """把非负整数或十进制数字字符串转换为整数，未知格式返回 None。"""
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}", value):
        return int(value)
    return None


def safe_summary(result, sensitive=()):
    """只输出白名单状态字段；删除凭证、控制字符、HTML 和长令牌。"""
    if not isinstance(result, dict):
        return "响应不是 JSON 对象"
    parts = []
    for key in ("ok", "code", "error", "message", "rewarded", "points", "already_drawn", "triggered", "hidden"):
        if key not in result:
            continue
        value = result[key]
        if isinstance(value, (dict, list)):
            parts.append(key + "=[复杂字段已省略]")
            continue
        text = str(value)
        for secret in sorted(set(sensitive), key=len, reverse=True):
            if secret:
                text = text.replace(secret, "[已隐藏]")
        text = re.sub(r"(?i)(cookie|authorization|_?csrf|token|password|session(?:id)?)\s*[:=]\s*[^\s;,]+", r"\1=[已隐藏]", text)
        text = re.sub(r"[A-Za-z0-9_+/=.-]{32,}", "[长令牌已隐藏]", text)
        text = re.sub(r"<[^>]*>", "", text)
        text = " ".join("".join(char if char.isprintable() else " " for char in text).split())
        parts.append("{}={}".format(key, text[:240]))
    return "; ".join(parts) or "没有可识别的状态字段"


def multipart(fields):
    """用标准库构建与网页 FormData 相同类型的 multipart 请求。"""
    boundary = "----LinuxSb" + secrets.token_hex(16)
    chunks = []
    for name, value in fields.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise RuntimeError("表单字段名异常，已停止。")
        chunks.append('--{}\r\nContent-Disposition: form-data; name="{}"\r\n\r\n{}\r\n'.format(boundary, name, value))
    chunks.append("--{}--\r\n".format(boundary))
    return "multipart/form-data; boundary=" + boundary, "".join(chunks).encode("utf-8")


def seed_cookie(jar, raw):
    """将浏览器 Cookie 请求头导入受域名限制的 CookieJar，不保存明文密码。"""
    raw = raw.strip()
    if raw.lower().startswith("cookie:"):
        raw = raw[7:].strip()
    if not raw or "\n" in raw or "\r" in raw:
        raise RuntimeError("Cookie 必须是浏览器请求头中的一整行值。")
    pairs = []
    for item in raw.split(";"):
        name, separator, value = item.strip().partition("=")
        if not separator or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
            raise RuntimeError("Cookie 格式不正确；请复制 Cookie 请求头的值，不是 Set-Cookie。")
        pairs.append((name, value))
    jar.clear()
    for name, value in pairs:
        jar.set_cookie(http.cookiejar.Cookie(
            version=0, name=name, value=value, port=None, port_specified=False,
            domain="linux.sb", domain_specified=False, domain_initial_dot=False,
            path="/", path_specified=True, secure=True, expires=None,
            discard=True, comment=None, comment_url=None, rest={}, rfc2109=False,
        ))


def save_jar(jar, path):
    """用原子替换保存服务器更新的 Cookie，文件仅当前账号可读写。"""
    temporary = path.with_suffix(".tmp")
    try:
        jar.save(str(temporary), ignore_discard=True, ignore_expires=False)
        os.chmod(str(temporary), 0o600)
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


class Client:
    """复用会话；所有请求均不自动重试，避免超时后重复领取。"""

    def __init__(self, jar):
        self.jar = jar
        self.opener = build_opener(SiteRedirect(), HTTPCookieProcessor(jar))

    def sensitive(self):
        """返回仅用于脱敏的 Cookie 值，不记录这些值。"""
        return [cookie.value for cookie in self.jar]

    def request(self, url, fields=None):
        if not same_site(url):
            raise RuntimeError("页面表单地址不属于本站，已停止。")
        headers = {
            "User-Agent": "linux-sb-checkin/{} (Python standard library)".format(VERSION),
            "Accept": "application/json" if fields is not None else "text/html",
        }
        data = None
        if fields is not None:
            headers.update({"X-Requested-With": "XMLHttpRequest", "Origin": SITE.rstrip("/"), "Referer": SITE})
            headers["Content-Type"], data = multipart(fields)
        try:
            response = self.opener.open(Request(url, data=data, headers=headers), timeout=20)
        except HTTPError as error:
            # HTTP 4xx/5xx 也可能携带具体 JSON 原因，但绝不输出页面全文。
            with error:
                body = error.read(MAX_BODY + 1)
            detail = "非 JSON 响应，可能需要人工登录或安全验证"
            try:
                if len(body) <= MAX_BODY:
                    private = self.sensitive() + [str(v) for k, v in (fields or {}).items() if re.search(r"csrf|token|password|session", k, re.I)]
                    detail = safe_summary(json.loads(body.decode("utf-8")), private)
            except (ValueError, UnicodeError):
                pass
            raise RuntimeError("HTTP {}：{}；未自动重试。".format(error.code, detail)) from None
        with response:
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise RuntimeError("响应过大，已停止，不保存页面。")
            text = body.decode("utf-8", errors="strict")
            if fields is not None and "json" not in response.headers.get("Content-Type", "").lower():
                raise RuntimeError("操作返回非 JSON，可能需要登录或安全验证；未重试。")
            return text

    def home(self):
        text = self.request(SITE)
        page = HomePage()
        page.feed(text)
        if not page.logged_in:
            raise RuntimeError("未确认登录：Cookie 可能失效、IP 被验证或页面结构已改变；请人工检查。")
        return page, text


def notice(text):
    """只确认明确的签到回执；缺少提示时不宣称签到成功。"""
    match = re.search(r'window\.__pageFlash\s*=\s*("(?:\\.|[^"\\])*")', text)
    message = ""
    if match:
        try:
            message = html.unescape(json.loads(match.group(1)))
        except (ValueError, TypeError):
            pass
    if "已帮您完成自动签到" in message:
        log("签到：收到网站明确的自动签到回执。")
    else:
        log("签到：已登录并访问首页，但未取得明确签到回执；首次部署请在站内核对。")


class DailyProgress:
    """仅保存当天流程进度，不保存凭证；避免同一天重复执行显示/隐藏步骤。"""

    def __init__(self, path=None):
        self.path = path
        self.state = {}
        if path is not None and path.exists():
            try:
                self.state = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(self.state, dict):
                    raise ValueError("状态不是对象")
            except (ValueError, UnicodeError):
                raise RuntimeError("本地 progress.json 损坏，请人工备份检查；未重置以免重复操作。") from None

    def begin(self, day, account):
        if self.state.get("day") != day or self.state.get("account") != account:
            self.state = {"day": day, "account": account, "targets": [], "claimed": [], "steps": [], "completed": 0}
        if (not all(isinstance(self.state.get(key), list) and all(isinstance(item, str) for item in self.state[key])
                    for key in ("targets", "claimed", "steps"))
                or number(self.state.get("completed")) is None):
            raise RuntimeError("本地进度字段格式异常，未继续执行。")
        self.save()

    def save(self):
        if self.path is None:
            return
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.chmod(str(temporary), 0o600)
            os.replace(str(temporary), str(self.path))
        finally:
            if temporary.exists():
                temporary.unlink()

    @property
    def completed(self):
        return max(len(set(self.state["claimed"])), number(self.state["completed"]) or 0)

    def observe(self, page, result=None):
        """合并页面已领取标记及服务端计数，绝不以 hidden 代替完成计数。"""
        if not page.has_board or not page.has_wrap:
            raise RuntimeError("未识别到广告区域或显示状态，可能是权限或页面结构变化。")
        targets = set(self.state["targets"]) | set(page.all_slots)
        claimed = set(self.state["claimed"]) | {key for key, done in page.all_slots.items() if done}
        lottery = (result or {}).get("lottery")
        if lottery is not None:
            if not isinstance(lottery, dict):
                raise RuntimeError("服务端 lottery 格式变化，已停止，请核对站内结果。")
            slots = lottery.get("slots") or {}
            if not isinstance(slots, dict):
                raise RuntimeError("服务端 slots 格式变化，已停止，请核对站内结果。")
            targets.update(slots)
            claimed.update(key for key, item in slots.items() if isinstance(item, dict) and confirmed(item.get("claimed")))
            total, completed = number(lottery.get("total")), number(lottery.get("completed"))
            if total is not None and total > RED_DOT_COUNT:
                raise RuntimeError("网站今日有奖广告总数超过三个，需要人工核对规则后调整，未继续领取。")
            if total == RED_DOT_COUNT and completed is not None and completed <= total:
                self.state["completed"] = max(self.state["completed"], completed)
        if len(targets) > RED_DOT_COUNT or len(claimed) > RED_DOT_COUNT:
            raise RuntimeError("识别到超过三个有奖广告位，未盲目扩大领取范围。")
        self.state["targets"], self.state["claimed"] = sorted(targets), sorted(claimed)
        self.save()


def page_day(page):
    """采用网站表单日期；日期缺失时不凭本地时间猜测。"""
    day = (page.form or {}).get("fields", {}).get("reward_day", "")
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise RuntimeError("缺少网站当天日期字段，请检查页面或登录状态。") from None
    return day


def post_form(client, page, kind, label, extra=None):
    """动态提交网页实际表单；失败时保留脱敏状态和服务端具体原因。"""
    form = page.forms.get(kind)
    if not form or form["method"] != "post" or not same_site(form["action"]):
        raise RuntimeError("{}：缺少合法的本站 POST 表单；未猜测接口。".format(label))
    fields = dict(form["fields"])
    if not fields.get("_csrf"):
        raise RuntimeError("{}：缺少 CSRF 字段。".format(label))
    if kind == "click" and not fields.get("reward_day"):
        raise RuntimeError("{}：缺少网站当天日期字段。".format(label))
    fields.update(extra or {})
    private = [str(value) for key, value in fields.items() if re.search(r"csrf|token|password|session", key, re.I)]
    private += getattr(client, "sensitive", lambda: [])()
    log("{}：开始提交本站表单（不记录凭证）。".format(label))
    try:
        result = json.loads(client.request(form["action"], fields))
    except ValueError:
        raise RuntimeError("{}：响应不是有效 JSON；未重试。".format(label)) from None
    except RuntimeError as error:
        raise RuntimeError("{}：{}".format(label, error)) from None
    summary = safe_summary(result, private)
    log("{}：{}".format(label, summary))
    if not isinstance(result, dict) or not confirmed(result.get("ok")):
        raise RuntimeError("{}未确认成功；{}；未重试。".format(label, summary))
    return result


def run(client, check_only, progress=None):
    """三个红点逐项确认后，仅执行一轮显示、隐藏、显示，并核验最终状态。"""
    page, text = client.home()
    log("脚本 v{}：已确认登录，首页访问完成。".format(VERSION))
    notice(text)
    if check_only:
        log("检查模式：未提交红点、显示或隐藏请求。")
        return
    progress = progress if progress is not None else DailyProgress()
    day = page_day(page)
    account = hashlib.sha256("".join(page.name_parts).strip().encode("utf-8")).hexdigest()
    progress.begin(day, account)
    total_points = 0

    def refresh():
        """每次操作后重新读取 CSRF、三个红点和广告状态，跨日时停止。"""
        updated, _ = client.home()
        if page_day(updated) != day:
            raise RuntimeError("执行期间网站日期发生变化，已停止；请核对结果。")
        progress.observe(updated)
        return updated

    def reward(result, label):
        """显示/隐藏和红点分别核对，只有明确发奖及积分数才计入总数。"""
        nonlocal total_points
        points = number(result.get("points"))
        if confirmed(result.get("rewarded")) and points is not None:
            total_points += points
            log("{}：明确新增 +{} 积分。".format(label, points))
        elif confirmed(result.get("already_drawn")):
            log("{}：今天已领取，不重复计算积分。".format(label))
        else:
            log("{}：无明确新增积分回执，不计入积分合计。".format(label))

    def toggle(current, kind, label):
        """只提交一次并重新读页面核验；关闭标签页不属于本站请求步骤。"""
        expected_hidden = kind == "hide"
        if current.hidden_board == expected_hidden:
            log("{}：当前已是目标显示状态，不重复提交。".format(label))
            return current
        result = post_form(client, current, kind, label)
        reward(result, label)
        updated = refresh()
        if updated.hidden_board != expected_hidden:
            raise RuntimeError("{}：请求已响应，但页面未达到目标状态；请核对，未重试。".format(label))
        log("{}：页面状态核验通过。".format(label))
        return updated

    try:
        progress.observe(page)
        log("红点进度：已确认 {}/3。".format(progress.completed))
        attempted = set()
        for _ in range(RED_DOT_COUNT):
            if progress.completed >= RED_DOT_COUNT:
                break
            # 广告隐藏不是完成凭据；必要时显示后继续处理剩余红点。
            if page.hidden_board:
                page = toggle(page, "show", "领取前显示广告")
                if progress.completed >= RED_DOT_COUNT:
                    break
            candidates = [slot for slot in page.slots if slot["placement_key"] not in attempted | set(progress.state["claimed"])]
            if not candidates:
                raise RuntimeError("只确认 {}/3 红点，未找到剩余标记；不能把隐藏或无红点当成全部完成。".format(progress.completed))
            slot = candidates[0]
            attempted.add(slot["placement_key"])
            label = "红点领取 {}/3".format(progress.completed + 1)
            result = post_form(client, page, "click", label, slot)
            progress.observe(page, result)
            # 兼容明确发奖、已领回执或该广告位的服务端 claimed 标记。
            acknowledged = (confirmed(result.get("rewarded")) or confirmed(result.get("already_drawn"))
                            or slot["placement_key"] in progress.state["claimed"])
            if not acknowledged:
                raise RuntimeError("{}：请求已响应，但没有发奖或已领取证据；未重试。".format(label))
            if slot["placement_key"] not in progress.state["claimed"]:
                progress.state["claimed"].append(slot["placement_key"])
            progress.save()
            reward(result, label)
            # 第一次响应 hidden=true 也不会提前退出；必须确认三个红点。
            page = refresh()
            log("红点进度：已确认 {}/3。".format(progress.completed))
        if progress.completed < RED_DOT_COUNT:
            raise RuntimeError("本次未确认三个红点全部完成，后续显示/隐藏奖励流程未执行。")
        log("三个红点已全部完成（包含今天已领取的项目）。")
        for stage, kind, label in (
            ("show", "show", "完成后显示广告"),
            ("hide", "hide", "完成后隐藏广告"),
            ("final-show", "show", "最终显示广告"),
        ):
            if stage in progress.state["steps"]:
                log("{}：当天已完成，跳过该步骤。".format(label))
                continue
            page = toggle(page, kind, label)
            progress.state["steps"].append(stage)
            progress.save()
        if page.hidden_board:
            # 例如用户在另一个设备上再次隐藏，只恢复显示，不再循环隐藏。
            page = toggle(page, "show", "恢复最终可见状态")
        log("流程完成：三个红点已确认，广告当前可见。")
    finally:
        log("本次统计：红点已确认 {}/3；明确新增广告积分 {}（含切换回执，不含签到）。".format(progress.completed, total_points))


def main():
    """初始化和定时任务共用入口；Cookie 从终端隐藏输入，不进入命令历史。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="linux-sb-checkin " + VERSION)
    parser.add_argument("--init", action="store_true", help="隐藏输入 Cookie，替换本机保存的登录态")
    parser.add_argument("--check-only", action="store_true", help="仅访问首页检查登录；访问本身可能触发签到")
    parser.add_argument("--data-dir", default="/var/lib/linux-sb-checkin", help="私密会话目录")
    args = parser.parse_args()
    os.umask(0o077)
    directory = Path(args.data_dir)
    if not directory.is_absolute():
        raise RuntimeError("会话目录必须使用绝对路径。")
    directory.mkdir(parents=True, exist_ok=True)
    # Linux flock 避免手动执行与定时任务同时运行。
    import fcntl
    with (directory / "run.lock").open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("已有任务正在运行，本次退出。")
        path = directory / "cookies.txt"
        jar = http.cookiejar.MozillaCookieJar(str(path))
        if args.init:
            seed_cookie(jar, getpass.getpass("请粘贴 linux.sb 首页请求的 Cookie 值（输入不显示）："))
            save_jar(jar, path)
            log("登录态已保存，下一步请运行 --check-only 验证。")
            return
        if not path.exists():
            raise RuntimeError("尚未导入登录态，请先运行 --init。")
        jar.load(ignore_discard=True, ignore_expires=False)
        try:
            progress = None if args.check_only else DailyProgress(directory / "progress.json")
            run(Client(jar), args.check_only, progress)
        finally:
            save_jar(jar, path)


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        log("失败：HTTP {}，可能是登录或安全验证问题；未自动重试。".format(error.code))
        sys.exit(1)
    except (URLError, TimeoutError, OSError):
        log("失败：网络、超时或文件读写异常；未自动重试，若发生于领取时请先核对站内结果。")
        sys.exit(1)
    except (RuntimeError, ValueError, UnicodeError) as error:
        log("失败：{}".format(error if isinstance(error, RuntimeError) else "响应格式异常，未自动重试。"))
        sys.exit(1)
