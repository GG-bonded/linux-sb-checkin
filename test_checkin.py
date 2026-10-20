# -*- coding: utf-8 -*-
"""离线回归测试：模拟三个红点与显示/隐藏状态，不连接网站、不领取真实积分。"""

import http.cookiejar
import io
import json
import tempfile
import unittest
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import checkin


def fixture(claimed=(), hidden=False, token="fresh-token", day="2026-10-20", logged=True, kinds=("click", "show", "hide"), keys=("a", "b", "c")):
    """模拟实际页面的三种表单，已领取和未领取广告都保留标记。"""
    user = '<div class="user-name">测试账号</div>' if logged else '<div class="visitor-avatar"></div><div class="user-name">访客</div>'
    links = []
    for key in keys:
        done = ' data-sidebar-promotions-lottery-done="1"' if key in claimed else ""
        links.append('<a data-sidebar-promotions-lottery-slot="1" data-promotion-id="{}" data-sidebar-promotions-order-id="{}"{}>红点</a>'.format(key, ord(key), done))
    forms = []
    for kind in kinds:
        forms.append('''<form method="post" action="/promotions_{}" data-sidebar-promotions-{}-form hidden>
          <input name="_csrf" value="{}"><input name="reward_day" value="{}">
          <input name="disabled_field" value="ignore" disabled>
          <input type="checkbox" name="unchecked" value="ignore">
        </form>'''.format(kind, kind, token, day))
    return '''<div class="card user-card">{}</div>
      <section data-sidebar-promotions-board="user_sidebar">
      <div data-sidebar-promotions-wrap{}>{}</div>{}</section>'''.format(user, " hidden" if hidden else "", "".join(links), "".join(forms))


def parse(text):
    """辅助解析，无网络请求。"""
    page = checkin.HomePage()
    page.feed(text)
    return page


class FakeSite:
    """有状态模拟器：每次刷新更换 CSRF，第三个红点完成时自动隐藏。"""

    def __init__(self, claimed=(), hidden=False, flags=True, keys=("a", "b", "c")):
        self.claimed = set(claimed)
        self.hidden = hidden
        self.flags = flags
        self.keys = keys
        self.day = "2026-10-20"
        self.calls = []
        self.home_count = 0
        self.token = ""
        self.errors = {}
        self.kinds = ("click", "show", "hide")
        self.early_hidden = False
        self.ignore_toggle = False
        self.switch_day = False

    def sensitive(self):
        return ["private-session-value"]

    def home(self):
        self.home_count += 1
        self.token = "token-{}".format(self.home_count)
        day = "2026-10-21" if self.switch_day and self.home_count > 1 else self.day
        return parse(fixture(self.claimed, self.hidden, self.token, day, kinds=self.kinds, keys=self.keys)), ""

    def request(self, url, fields):
        kind = url.rsplit("_", 1)[-1]
        self.calls.append((kind, dict(fields)))
        if fields.get("_csrf") != self.token:
            raise AssertionError("没有使用最新 CSRF")
        if kind in self.errors:
            error = self.errors[kind]
            if isinstance(error, Exception):
                raise error
            return error
        result = {"ok": self.flags}
        if kind == "click":
            key = fields["placement_key"]
            if fields["reward_day"] != self.day:
                raise AssertionError("网站日期不匹配")
            already = key in self.claimed
            self.claimed.add(key)
            self.hidden = len(self.claimed) == 3 or (self.early_hidden and len(self.claimed) == 1)
            result.update({"already_drawn": self.flags if already else False,
                           "rewarded": self.flags if not already else False, "points": "7" if not already else 0,
                           "hidden": self.hidden})
        elif kind in ("show", "hide"):
            if not self.ignore_toggle:
                self.hidden = kind == "hide"
            result.update({"hidden": self.hidden, "triggered": self.flags, "rewarded": self.flags, "points": 2})
        else:
            raise AssertionError("使用了未在页面出现的接口")
        result["lottery"] = {"total": 3, "completed": len(self.claimed),
                             "slots": {key: {"claimed": key in self.claimed} for key in self.keys}}
        return json.dumps(result)


class Tests(unittest.TestCase):
    """覆盖三个红点、步骤幂等、返回类型、脱敏与 HTTP 错误信息。"""

    def setUp(self):
        self.log_patch = patch.object(checkin, "log")
        self.output = self.log_patch.start()
        self.addCleanup(self.log_patch.stop)

    def operations(self, site):
        return [kind for kind, _ in site.calls]

    def test_three_forms_and_slots(self):
        page = parse(fixture(claimed=("b",)))
        self.assertTrue(page.logged_in)
        self.assertTrue(page.has_wrap)
        self.assertEqual(set(page.forms), {"click", "show", "hide"})
        self.assertEqual([slot["placement_key"] for slot in page.slots], ["a", "c"])
        self.assertEqual(page.all_slots, {"a": False, "b": True, "c": False})
        self.assertEqual(page.form["fields"], {"_csrf": "fresh-token", "reward_day": "2026-10-20"})

    def test_hidden_wrap(self):
        self.assertTrue(parse(fixture(hidden=True)).hidden_board)

    def test_visitor(self):
        self.assertFalse(parse(fixture(logged=False)).logged_in)

    def test_challenge(self):
        self.assertFalse(parse("<title>Just a moment...</title>").logged_in)

    def test_unrelated_auth_not_visitor(self):
        self.assertTrue(parse(fixture() + '<div class="side-auth">其他模块</div>').logged_in)

    def test_all_three_and_full_toggle_sequence(self):
        site = FakeSite()
        checkin.run(site, False)
        self.assertEqual(self.operations(site), ["click", "click", "click", "show", "hide", "show"])
        self.assertEqual([fields["placement_key"] for kind, fields in site.calls if kind == "click"], ["a", "b", "c"])
        self.assertFalse(site.hidden)
        self.assertTrue(any("广告积分 27" in call.args[0] for call in self.output.call_args_list))

    def test_preclaimed_one_does_not_stop_remaining_two(self):
        site = FakeSite(claimed=("a",))
        checkin.run(site, False)
        self.assertEqual(self.operations(site).count("click"), 2)
        self.assertEqual(site.claimed, {"a", "b", "c"})

    def test_all_preclaimed_hidden_still_toggles(self):
        site = FakeSite(claimed=("a", "b", "c"), hidden=True)
        checkin.run(site, False)
        self.assertEqual(self.operations(site), ["show", "hide", "show"])
        self.assertFalse(site.hidden)

    def test_early_hidden_is_not_all_complete(self):
        site = FakeSite()
        site.early_hidden = True
        checkin.run(site, False)
        self.assertEqual(self.operations(site), ["click", "show", "click", "click", "show", "hide", "show"])

    def test_hidden_initially_unclaimed(self):
        site = FakeSite(hidden=True)
        checkin.run(site, False)
        self.assertEqual(self.operations(site)[0], "show")
        self.assertEqual(self.operations(site).count("click"), 3)

    def test_integer_boolean_response(self):
        site = FakeSite(flags=1)
        checkin.run(site, False)
        self.assertEqual(self.operations(site).count("click"), 3)

    def test_string_boolean_response(self):
        site = FakeSite(flags="true")
        checkin.run(site, False)
        self.assertFalse(site.hidden)

    def test_false_string_is_not_success(self):
        site = FakeSite()
        site.errors["click"] = '{"ok":"false","message":"参数错误"}'
        with self.assertRaisesRegex(RuntimeError, "参数错误"):
            checkin.run(site, False)
        self.assertEqual(self.operations(site), ["click"])

    def test_specific_error_retained_and_sanitized(self):
        site = FakeSite()
        site.errors["click"] = json.dumps({"ok": False, "message": "CSRF错误 token-1 private-session-value", "cookie": "private-session-value"})
        with self.assertRaises(RuntimeError) as caught:
            checkin.run(site, False)
        output = str(caught.exception) + " ".join(call.args[0] for call in self.output.call_args_list)
        self.assertIn("CSRF错误", output)
        self.assertNotIn("private-session-value", output)
        self.assertNotIn("token-1", output)

    def test_ok_without_reward_proof_stops(self):
        site = FakeSite()
        site.errors["click"] = '{"ok":true,"message":"请求已收到"}'
        with self.assertRaisesRegex(RuntimeError, "没有发奖或已领取证据"):
            checkin.run(site, False)
        self.assertEqual(self.operations(site), ["click"])

    def test_network_timeout_no_retry(self):
        site = FakeSite()
        site.errors["click"] = TimeoutError()
        with self.assertRaises(TimeoutError):
            checkin.run(site, False)
        self.assertEqual(self.operations(site), ["click"])

    def test_only_two_slots_not_success(self):
        site = FakeSite(keys=("a", "b"))
        with self.assertRaisesRegex(RuntimeError, "只确认 2/3"):
            checkin.run(site, False)
        self.assertEqual(self.operations(site), ["click", "click"])

    def test_missing_show_form(self):
        site = FakeSite(claimed=("a", "b", "c"), hidden=True)
        site.kinds = ("click", "hide")
        with self.assertRaisesRegex(RuntimeError, "缺少合法"):
            checkin.run(site, False)
        self.assertEqual(site.calls, [])

    def test_toggle_post_without_visibility_change_is_failure(self):
        site = FakeSite(claimed=("a", "b", "c"), hidden=True)
        site.ignore_toggle = True
        with self.assertRaisesRegex(RuntimeError, "未达到目标状态"):
            checkin.run(site, False)
        self.assertEqual(self.operations(site), ["show"])

    def test_same_day_rerun_no_posts(self):
        site, progress = FakeSite(), checkin.DailyProgress()
        checkin.run(site, False, progress)
        site.calls.clear()
        checkin.run(site, False, progress)
        self.assertEqual(site.calls, [])

    def test_restore_visibility_without_repeating_hide(self):
        site, progress = FakeSite(), checkin.DailyProgress()
        checkin.run(site, False, progress)
        site.calls.clear()
        site.hidden = True
        checkin.run(site, False, progress)
        self.assertEqual(self.operations(site), ["show"])

    def test_partial_toggle_resume(self):
        site, progress = FakeSite(), checkin.DailyProgress()
        site.errors["hide"] = '{"ok":false,"message":"暂时不可用"}'
        with self.assertRaisesRegex(RuntimeError, "暂时不可用"):
            checkin.run(site, False, progress)
        self.assertEqual(progress.state["steps"], ["show"])
        site.calls.clear()
        site.errors.clear()
        checkin.run(site, False, progress)
        self.assertEqual(self.operations(site), ["hide", "show"])

    def test_next_day_resets_state(self):
        site, progress = FakeSite(), checkin.DailyProgress()
        checkin.run(site, False, progress)
        site.calls.clear()
        site.day = "2026-10-21"
        site.claimed.clear()
        checkin.run(site, False, progress)
        self.assertEqual(self.operations(site).count("click"), 3)

    def test_cross_midnight_stops(self):
        site = FakeSite()
        site.switch_day = True
        with self.assertRaisesRegex(RuntimeError, "日期发生变化"):
            checkin.run(site, False)
        self.assertEqual(self.operations(site), ["click"])

    def test_check_mode_does_not_post(self):
        site = FakeSite()
        checkin.run(site, True)
        self.assertEqual(site.calls, [])

    def test_no_dots_not_success(self):
        site = FakeSite(keys=())
        with self.assertRaisesRegex(RuntimeError, "只确认 0/3"):
            checkin.run(site, False)

    def test_more_than_three_slots_stops(self):
        site = FakeSite(keys=("a", "b", "c", "d"))
        with self.assertRaisesRegex(RuntimeError, "超过三个"):
            checkin.run(site, False)
        self.assertEqual(site.calls, [])

    def test_progress_utf8_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            progress = checkin.DailyProgress(path)
            progress.begin("2026-10-20", "账号哈希示例")
            progress.state["steps"].append("show")
            progress.save()
            self.assertEqual(checkin.DailyProgress(path).state["steps"], ["show"])
            self.assertIn("账号哈希示例", path.read_text(encoding="utf-8"))

    def test_corrupt_progress_not_silently_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            path.write_text("invalid", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "损坏"):
                checkin.DailyProgress(path)

    def test_domains(self):
        self.assertTrue(checkin.same_site(checkin.SITE))
        for url in ("http://linux.sb/", "https://linux.sb.example/", "https://example.com/", "https://linux.sb@evil.com/"):
            self.assertFalse(checkin.same_site(url))

    def test_cookie(self):
        jar = http.cookiejar.CookieJar()
        checkin.seed_cookie(jar, "Cookie: session=abc==; other=123")
        self.assertEqual({item.name: item.value for item in jar}, {"session": "abc==", "other": "123"})
        self.assertTrue(all(item.secure and item.domain == "linux.sb" for item in jar))
        with self.assertRaises(RuntimeError):
            checkin.seed_cookie(jar, "session=abc\nmalicious=1")

    def test_notice_and_no_receipt(self):
        checkin.notice('window.__pageFlash = "您是第10位，已帮您完成自动签到";')
        self.assertIn("明确", self.output.call_args[0][0])
        checkin.notice("<html></html>")
        self.assertIn("未取得明确", self.output.call_args[0][0])

    def test_multipart_format(self):
        content_type, body = checkin.multipart({"_csrf": "测试令牌", "placement_key": "a"})
        message = BytesParser().parsebytes(("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode("ascii") + body)
        parts = {part.get_param("name", header="Content-Disposition"): part.get_payload(decode=True).decode("utf-8") for part in message.get_payload()}
        self.assertEqual(parts, {"_csrf": "测试令牌", "placement_key": "a"})

    def test_http_error_keeps_json_reason(self):
        client = checkin.Client(http.cookiejar.CookieJar())
        client.opener = Mock()
        client.opener.open.side_effect = HTTPError(checkin.SITE, 403, "Forbidden", {}, io.BytesIO(b'{"ok":false,"message":"CSRF expired"}'))
        with self.assertRaisesRegex(RuntimeError, "HTTP 403.*CSRF expired"):
            client.request(checkin.SITE + "promotions_click", {"_csrf": "private-token"})
        self.assertEqual(client.opener.open.call_count, 1)

    def test_unknown_response_format(self):
        site = FakeSite()
        site.errors["click"] = "<html>login</html>"
        with self.assertRaisesRegex(RuntimeError, "有效 JSON"):
            checkin.run(site, False)

    def test_false_flags_and_invalid_points(self):
        for value in (False, 0, "0", "false", "yes", {}, []):
            self.assertFalse(checkin.confirmed(value))
        for value in (True, 1, "1", "true"):
            self.assertTrue(checkin.confirmed(value))
        for value in (True, -1, "-5", "12.5", None):
            self.assertIsNone(checkin.number(value))


if __name__ == "__main__":
    unittest.main()
