# 已有 Ubuntu VPS：v2.0 更新与测试教程

修改原因：旧版没有显示/隐藏流程，隐藏状态会提前结束领取，并且丢失服务端错误原因。
新版逐项核对三个红点，再执行一轮显示、隐藏、显示；最终保持广告可见。
依然只使用 Python 标准库，不新增浏览器、pip 包、Docker、桌面或常驻进程。

边界：离线模拟测试通过不等于你的账号真实领取通过。本次未连接 VPS，也未重跑真实领取。
显示/隐藏是否发奖以本站实际回执为准；若站点要求浏览广告或禁止自动化，不应使用请求方式领取。

## 1. 暂停定时器，确认没有任务正在运行

在 VPS 的 SSH 终端执行：

```bash
sudo systemctl stop linux-sb-checkin.timer
systemctl is-active linux-sb-checkin.service
```

若输出 inactive 或 failed，可以继续；若是 active/activating，等待本次任务完成后再更新。
不要在领取请求进行中强制停止服务，否则可能已经到账但本地没有回执。
stop timer 不会删除任务，也不改变原先的 enabled 设置。

## 2. 上传新版脚本

```bash
mkdir -p /tmp/linux-sb-checkin-upload
chmod 700 /tmp/linux-sb-checkin-upload
```

使用你已有的 SFTP 工具，将本地新版 checkin.py 上传到上述目录。
本次只上传 checkin.py，不覆盖定时器和服务文件，也不复制或上传 Cookie。
可选上传 test_checkin.py，供 VPS 离线运行测试。

## 3. 备份并替换（不覆盖已有备份）

先备份旧脚本，备份文件已存在时不覆盖：

```bash
sudo cp --no-clobber --preserve=mode,ownership,timestamps /opt/linux-sb-checkin/checkin.py /opt/linux-sb-checkin/checkin.py.v1.bak
```

安装刚上传的新版：

```bash
sudo install -o root -g root -m 0644 /tmp/linux-sb-checkin-upload/checkin.py /opt/linux-sb-checkin/checkin.py
sudo -u linuxsb env PYTHONUTF8=1 /usr/bin/python3 -B /opt/linux-sb-checkin/checkin.py --version
```

必须看到 linux-sb-checkin 2.0。如果仍显示旧版或不认识 --version，先检查上传位置，不继续运行。
不需要重新安装依赖，不需要重新输入有效的 Cookie，不需要 daemon-reload。
可选：如果同时上传了测试文件，在上传目录运行离线测试，不连接网站：

```bash
cd /tmp/linux-sb-checkin-upload
PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_checkin.py
```

## 4. 先检查登录（不会领取红点或切换广告）

```bash
sudo -u linuxsb env PYTHONUTF8=1 /usr/bin/python3 -B /opt/linux-sb-checkin/checkin.py --check-only
```

访问首页本身可能触发签到。若未确认登录，先更新 Cookie，不进行下一步。
更新命令（输入不显示，Cookie 不进入命令参数或历史）：

```bash
sudo -u linuxsb env PYTHONUTF8=1 /usr/bin/python3 -B /opt/linux-sb-checkin/checkin.py --init
```

更新后再运行只检查模式。不要把 Cookie、cookies.txt 或开发者工具请求头截图发到聊天。

## 5. 用现有服务手动测试一次

```bash
sudo systemctl reset-failed linux-sb-checkin.service
sudo systemctl start linux-sb-checkin.service
sudo journalctl -u linux-sb-checkin.service --since '5 minutes ago' --no-pager
systemctl show linux-sb-checkin.service -p Result -p ExecMainStatus
```

start 会等本次 oneshot 任务结束。这一轮会真实申请奖励，不要同时在浏览器手动点红点。
请核对本次 v2.0 日志，不要把以前失败的旧日志混为本次结果。

预期关键结果（不是保证每步都有新增积分）：

1. 脚本 v2.0，已确认登录。
2. 红点进度依次到 1/3、2/3、3/3；如果今天已领过，会跳过并直接显示已有进度。
3. 完成后显示广告、完成后隐藏广告、最终显示广告：页面状态核验通过。
4. 流程完成：三个红点已确认，广告当前可见。
5. Result=success、ExecMainStatus=0。

最后刷新网页核对：红点是否全部已领、广告是否可见、积分是否对应增加。
如果只确认部分红点、缺少合法表单、没有奖励回执或显示状态不匹配，脚本会失败，不假装全部完成。
本次新增积分只合计服务端明确返回 rewarded 和 points 的结果，不包含签到和以前领取的积分。

## 6. 成功后恢复原定时任务

```bash
sudo systemctl start linux-sb-checkin.timer
systemctl is-enabled linux-sb-checkin.timer
systemctl list-timers --all linux-sb-checkin.timer
```

原先是 enabled 的不需要重新 enable；若输出 disabled 而你希望开机自动启用，执行：

```bash
sudo systemctl enable linux-sb-checkin.timer
```

本次不修改定时时间，沿用你 VPS 的配置；当前本地定时器为北京时间 09:00。
若 VPS 用 UTC 显示，01:00 UTC 等于北京时间 09:00。Persistent=true 可能造成补执行，
但当天进度会让已完成的步骤跳过，不循环切换广告。

## 如果测试失败

- 保持 timer 暂停，先读新日志里的具体 message/code 和失败阶段。
- 领取请求超时：可能已经到账。先到网页核对，不立刻反复执行。
- 显示/隐藏返回成功但页面不变：脚本会明确报状态核验失败，需要核对网站规则。
- 仅有 message 提示积分、但没有明确奖励字段：会记录脱敏消息，但不擅自计入积分合计。
- 本地进度保存在服务私密数据目录的 progress.json，不要随意删除，否则同日切换步骤可能再次执行。
- 本日完成后重复运行，已完成的红点和显示/隐藏步骤跳过；次日按网站日期自动开始新一轮。
- 如仍失败，可分享本次脱敏的阶段日志，不分享 Cookie 或整个页面响应。

## 必要时回滚

确认没有任务运行后，仅恢复脚本，保留 Cookie 和定时器：

```bash
sudo systemctl stop linux-sb-checkin.timer
sudo install -o root -g root -m 0644 /opt/linux-sb-checkin/checkin.py.v1.bak /opt/linux-sb-checkin/checkin.py
```

回滚后不要立即恢复自动领取，先确认旧版故障风险是否可以接受。
备份会保留；本教程没有删除服务器文件或清理全局日志。
