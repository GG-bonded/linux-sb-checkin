# linux-sb-checkin

**Ubuntu VPS 轻量签到工具｜v2.0｜每天北京时间 09:00 自动运行**

访问首页签到 → 逐个处理三个红点 → 显示广告 → 隐藏广告 → 最终显示广告。

只用 Python 标准库，不安装浏览器或第三方包，执行完就退出。需要 Ubuntu 22.04 / 24.04、systemd 和 sudo 权限。

> 非官方工具，仅在站点允许自动化时使用。不绕过验证码，不访问广告商页面，不保证每次操作都有积分。已通过离线测试，真实领取请先手动验收。Cookie 是登录凭证，禁止提交或分享。

## 1. 安装

以下命令在 VPS 的 SSH 终端执行，适用于全新部署。已有同名目录或服务时，先检查并备份，不要直接覆盖。

~~~bash
sudo apt update
sudo apt install -y --no-install-recommends python3 git ca-certificates tzdata

sudo git clone --branch main https://github.com/GG-bonded/linux-sb-checkin.git /opt/linux-sb-checkin-src
sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin linuxsb

sudo install -d -m 0755 /opt/linux-sb-checkin
sudo install -d -o linuxsb -g linuxsb -m 0700 /var/lib/linux-sb-checkin
sudo install -o root -g root -m 0644 /opt/linux-sb-checkin-src/checkin.py /opt/linux-sb-checkin/checkin.py
sudo install -o root -g root -m 0644 /opt/linux-sb-checkin-src/linux-sb-checkin.service /etc/systemd/system/linux-sb-checkin.service
sudo install -o root -g root -m 0644 /opt/linux-sb-checkin-src/linux-sb-checkin.timer /etc/systemd/system/linux-sb-checkin.timer

sudo systemd-analyze verify /etc/systemd/system/linux-sb-checkin.service /etc/systemd/system/linux-sb-checkin.timer
sudo systemctl daemon-reload
~~~

命令报错时先处理，不要继续下一步。如果 linuxsb 用户已存在，确认它属于本项目后跳过创建用户。

## 2. 导入 Cookie

在电脑浏览器登录 linux.sb，按以下顺序复制 Cookie：

**F12 → 网络 → 清空筛选条件 → 刷新首页 → 选择首页文档请求 → 标头 → 请求标头 → Cookie。**

复制完整值，不要复制响应中的 Set-Cookie。然后在 VPS 执行：

~~~bash
sudo -u linuxsb env PYTHONUTF8=1 /usr/bin/python3 -B /opt/linux-sb-checkin/checkin.py --init
~~~

按提示粘贴并回车，输入不显示是正常的。不要把 Cookie 直接粘贴到 shell 命令行。

检查登录：

~~~bash
sudo -u linuxsb env PYTHONUTF8=1 /usr/bin/python3 -B /opt/linux-sb-checkin/checkin.py --check-only
~~~

看到“已确认登录”再继续。此模式不领红点、不切换广告，但访问首页本身可能触发签到。

## 3. 测试一次

~~~bash
sudo systemctl start linux-sb-checkin.service
sudo journalctl -u linux-sb-checkin.service --since '5 minutes ago' --no-pager
systemctl show linux-sb-checkin.service -p Result -p ExecMainStatus
~~~

成功时应看到：

~~~text
三个红点已全部完成（包含今天已领取的项目）。
流程完成：三个红点已确认，广告当前可见。
Result=success
ExecMainStatus=0
~~~

回到网站核对积分和广告显示状态。已有领取记录会跳过，显示/隐藏是否发奖以网站回执为准。缺少明确签到提示时，脚本不会宣称签到成功。

## 4. 开启每天自动运行

测试通过后执行：

~~~bash
sudo systemctl enable --now linux-sb-checkin.timer
systemctl list-timers --all linux-sb-checkin.timer
~~~

默认每天北京时间 **09:00**，你的电脑不需要开机。VPS 显示 01:00 UTC 就是北京时间 09:00；错过时间后可能补跑一次。

**想改成 11:00？** 执行 sudo systemctl edit linux-sb-checkin.timer，填入：

~~~ini
[Timer]
# 清空原规则，避免九点、十一点各执行一次。
OnCalendar=
OnCalendar=*-*-* 11:00:00 Asia/Shanghai
~~~

保存后执行：

~~~bash
sudo systemctl daemon-reload
sudo systemctl restart linux-sb-checkin.timer
systemctl list-timers --all linux-sb-checkin.timer
~~~

## 常用命令

~~~bash
# 查看最近日志
sudo journalctl -u linux-sb-checkin.service -n 50 --no-pager

# 暂停自动运行，不删除数据
sudo systemctl stop linux-sb-checkin.timer

# 恢复自动运行
sudo systemctl start linux-sb-checkin.timer
~~~

Cookie 失效时：先暂停 timer，等正在运行的 service 结束，再重复第 2 步；检查通过后恢复 timer。

## 遇到问题

| 现象 | 怎么处理 |
| --- | --- |
| 未确认登录、403、人机验证 | 暂停任务，人工检查 Cookie 和 VPS 访问，不绕过验证 |
| 只确认 1/3 或 2/3 红点 | 查看具体错误并核对网页，不要改进度冒充完成 |
| 请求超时 | 可能已经到账，先核对网站，不立即反复执行 |
| service 显示 inactive (dead) | 单次任务结束后正常，另外检查 Result 和退出码 |
| timer 正常但没积分 | 查看 service 日志；任务成功不代表一定有新增积分 |

会话和每日进度保存在私密目录 /var/lib/linux-sb-checkin，不要上传 GitHub，不要随意删除进度文件。脚本不常驻；service 内存上限 96 MiB、执行超时 120 秒，系统组件和日志另占空间。

## 离线测试

不需要 Cookie，不联网，不领取真实积分：

~~~bash
cd /opt/linux-sb-checkin-src
PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_checkin.py
~~~
