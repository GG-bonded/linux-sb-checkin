# linux-sb-checkin

面向 Ubuntu VPS 的 linux.sb 轻量签到与广告奖励流程脚本。使用 Python 标准库，不安装浏览器、桌面、Docker、青龙或第三方 Python 包。

> 本项目是非官方工具，与 linux.sb 无隶属关系。请先确认站点规则允许自动化，并且只使用你有权操作的账号。脚本不绕过验证码、访问限制或奖励次数限制。如果网站要求真实浏览广告、禁止接口自动领取，或者要求人机验证，请停止自动化并人工处理。

**当前版本：2.0。仓库默认定时：每天北京时间 09:00。** 也可以按本文改为 11:00 或其他时间。脚本执行完立即退出，不常驻 Python 进程。

**验证状态：已通过离线模拟测试；这不代表已在所有 Ubuntu 版本、VPS IP 和真实账号上验证。首次部署必须先手动验收，再开启定时器。**

## 目录

- [功能与行为边界](#功能与行为边界)
- [环境要求与资源占用](#环境要求与资源占用)
- [执行流程](#执行流程)
- [仓库文件与服务器目录](#仓库文件与服务器目录)
- [首次部署：完整步骤](#首次部署完整步骤)
- [已部署旧版：升级步骤](#已部署旧版升级步骤)
- [定时运行与修改时间](#定时运行与修改时间)
- [日常管理与更新 Cookie](#日常管理与更新-cookie)
- [日志与成功判定](#日志与成功判定)
- [故障排查](#故障排查)
- [安全与隐私](#安全与隐私)
- [原理、参数与开发测试](#原理参数与开发测试)
- [回滚与停用](#回滚与停用)
- [常见问题](#常见问题)
- [反馈与贡献](#反馈与贡献)

## 功能与行为边界

- 使用你手动登录后取得的 Cookie 访问首页，检查登录状态。
- 识别明确的自动签到提示；没有提示时记录“未取得明确签到回执”，不凭 HTTP 200 声称签到成功。
- 动态读取当天日期、CSRF、三个有奖广告位及其编号，不写死 Cookie 或广告内容。
- 逐个处理三个红点，已领取项目跳过；广告隐藏不等于三个都已完成。
- 三个完成后，按一轮“显示 → 隐藏 → 最终显示”编排，重新读取页面核对可见状态。
- 服务端明确确认发奖且提供可识别的积分数，才累计到本次广告积分；签到积分不在此合计内。
- 在私密目录保存当天进度，同日重跑跳过已完成步骤；这是减少重复操作的机制，不是网络异常下的事务或绝对 exactly-once 保证。
- 领取请求超时、收到错误或结果不明时停止，不自动重试 POST。
- 脱敏记录服务端白名单状态字段，不打印 Cookie、CSRF 或完整网页响应。

不提供：

- 自动输入账号密码、自动解决 CAPTCHA、绕过风控。
- 批量账号、无限点击、循环切换刷积分或伪造广告曝光。
- 访问广告商网站、打开并关闭真实浏览器标签页。
- 保证每个红点或每次显示/隐藏都有奖励。
- 自动短信、邮件或消息推送通知；需要自行查看日志。

## 环境要求与资源占用

推荐使用带 systemd 的 Ubuntu 22.04 / 24.04，普通用户具有 sudo 权限。以下流程也适合许多类似发行版，但其他环境需要自行验证。

| 项目 | 要求或说明 |
| --- | --- |
| Python | 建议 Python 3.10 或更新版本；不需要 pip |
| 调度 | systemd service + timer |
| 网络 | 能正常访问 GitHub（部署时）与 linux.sb HTTPS |
| 权限 | 安装需要 sudo；日常脚本使用独立 linuxsb 系统账号 |
| 出站端口 | HTTPS；不用开放任何新的入站端口 |
| 程序大小 | 脚本约 26 KB，具体以当前版本为准 |
| 其他磁盘 | Python、Git、证书、时区数据库、Git 元数据与日志另计 |
| 内存限制 | service 配置 MemoryMax=96M，是上限，不是实测常驻占用 |
| 执行时限 | service 配置 TimeoutStartSec=120；单次网络请求超时 20 秒 |
| 空闲时 | 没有常驻 Python 进程，等待由系统已有的 systemd 管理 |

不需要安装 Node.js、Java、Chromium、Playwright、requests、BeautifulSoup 或虚拟环境。Windows 可以运行离线测试，但实际任务使用 Linux 的文件锁，本文不提供 Windows 服务部署。

## 执行流程

1. 携带 Cookie 访问首页，检查是否仍为登录状态。
2. 记录签到提示，读取网站自己的当天日期。
3. 合并页面已领取标记、服务端明确回执与本机当天进度。
4. 依次处理剩余红点，最多三个不同的有奖广告位。
5. 每次请求后重新访问首页，更新 CSRF 并检查状态。
6. 三个确认完成后，执行当天尚未完成的显示、隐藏、最终显示步骤。
7. 核对最终广告可见，记录本次明确新增的广告积分并退出。

如果一开始广告就隐藏，会先尝试显示以检查剩余红点。若已是目标显示状态，不发送无意义的切换请求。每天只有一轮后置切换，不循环刷取。

## 仓库文件与服务器目录

仓库公开文件：

| 文件 | 用途 |
| --- | --- |
| checkin.py | 主脚本：页面解析、请求、Cookie、每日进度与主流程 |
| linux-sb-checkin.service | 独立账号、文件权限、资源限制及运行入口 |
| linux-sb-checkin.timer | 默认每天北京时间 09:00 的调度 |
| test_checkin.py | 离线模拟测试，不需要 Cookie、不访问网站 |
| DEPLOY-UPDATE.md | 已部署旧版用户的单独升级教程 |
| README.md | 本文：首次部署、升级、运维与故障排查 |
| .gitignore | 排除 Cookie、状态、日志、备份和私密文件 |
| .gitattributes | 固定文本为 LF 换行，方便 Linux 部署 |

按本文部署后：

| 绝对位置 | 所有者与用途 |
| --- | --- |
| /opt/linux-sb-checkin-src | root 管理的源码仓库，不存放登录态 |
| /opt/linux-sb-checkin/checkin.py | root 管理的运行脚本，linuxsb 只读 |
| /etc/systemd/system/linux-sb-checkin.service | 服务定义 |
| /etc/systemd/system/linux-sb-checkin.timer | 定时器定义 |
| /var/lib/linux-sb-checkin | linuxsb 私密目录，权限 0700 |
| /var/lib/linux-sb-checkin/cookies.txt | 登录 Cookie，权限 0600；禁止提交 |
| /var/lib/linux-sb-checkin/progress.json | 当天流程进度，不含 Cookie；仍不建议公开 |
| /var/lib/linux-sb-checkin/run.lock | 防止同一数据目录的任务并发运行 |

默认只适合一个账号。不要混用多个账号的 Cookie 或多个任务的数据目录。

## 首次部署：完整步骤

以下命令在 Ubuntu VPS 的 SSH 终端执行。请按顺序运行、确认结果，不要把所有步骤不加检查地一次性粘贴。

如果是 root 登录，可以保留 sudo，也可以按你的环境去掉。你自己的电脑仅用于获取 Cookie，定时运行不依赖电脑开机。

### 1. 检查系统

~~~bash
cat /etc/os-release
python3 --version
ps -p 1 -o comm=
timedatectl status
~~~

最后确认 PID 1 是 systemd，服务器时间正确。无需把 VPS 的全局时区改成北京时间，timer 会显式使用 Asia/Shanghai。

### 2. 安装必要系统组件

~~~bash
sudo apt update
sudo apt install -y --no-install-recommends python3 git ca-certificates tzdata
~~~

安装前 apt 可能提示预计新增占用；这部分不包含在脚本的几十 KB 内。

### 3. 克隆仓库

~~~bash
sudo git clone --branch main https://github.com/GG-bonded/linux-sb-checkin.git /opt/linux-sb-checkin-src
sudo git -C /opt/linux-sb-checkin-src log -1 --oneline
~~~

如果该目录已存在，不要覆盖或删除，请先检查，已有部署可转到升级章节。

不想在 VPS 安装 Git，也可以在电脑上下载仓库并用 SFTP 上传三个部署文件；之后将 install 命令的来源改成你实际上传的绝对位置。日常运行不依赖 Git。

### 4. 先运行离线测试

~~~bash
cd /opt/linux-sb-checkin-src
PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_checkin.py
~~~

应以 OK 结束。测试模拟三个红点、已领跳过、提前隐藏、显示/隐藏、跨日、状态持久化、错误脱敏等；不会登录、联网或领取积分。

### 5. 创建专用运行账号

先检查同名用户是否存在：

~~~bash
getent passwd linuxsb
~~~

如果没有输出，创建：

~~~bash
sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin linuxsb
~~~

若已经存在，确认它就是你之前用于本项目的账号。不要修改其他应用的同名账号。

### 6. 安装程序与服务文件

首次安装前确认以下目标没有其他用途；install 会替换同名文件。已有部署请使用升级章节先备份。

~~~bash
sudo install -d -m 0755 /opt/linux-sb-checkin
sudo install -d -o linuxsb -g linuxsb -m 0700 /var/lib/linux-sb-checkin

sudo install -o root -g root -m 0644 /opt/linux-sb-checkin-src/checkin.py /opt/linux-sb-checkin/checkin.py
sudo install -o root -g root -m 0644 /opt/linux-sb-checkin-src/linux-sb-checkin.service /etc/systemd/system/linux-sb-checkin.service
sudo install -o root -g root -m 0644 /opt/linux-sb-checkin-src/linux-sb-checkin.timer /etc/systemd/system/linux-sb-checkin.timer

sudo -u linuxsb env PYTHONUTF8=1 /usr/bin/python3 -B /opt/linux-sb-checkin/checkin.py --version
~~~

当前预期版本是 linux-sb-checkin 2.0。主程序不需要执行权限，由 Python 解释器读取即可。

### 7. 在电脑浏览器获取 Cookie

以 Chrome / Edge 为例：

1. 在你自己的浏览器打开 linux.sb，正常登录并完成人机验证。
2. 确认页面显示你的账号，而不是“访客”。
3. 按 F12 或 Ctrl+Shift+I 打开开发者工具。
4. 选择“网络 / Network”。
5. 清空过滤框，例如删除残留的 /api 条件。
6. 点击“文档 / Doc”，然后按 Ctrl+R 刷新首页。
7. 选择地址为 linux.sb 首页的 document 请求，不选广告、图片或第三方域名。
8. 打开“标头 / Headers”→“请求标头 / Request Headers”。
9. 找到 Cookie，复制冒号后面的完整值。

格式示例（是假数据，不可直接使用）：

~~~text
session=example-not-a-real-cookie; preference=example
~~~

不要复制响应中的 Set-Cookie，不要复制整条 Copy as cURL 命令，不要只复制其中一个 Cookie。

不要在控制台运行别人提供的脚本，也不要依赖 document.cookie：HttpOnly 登录 Cookie 可能无法通过它读取。

### 8. 在 VPS 隐藏输入 Cookie

~~~bash
sudo -u linuxsb env PYTHONUTF8=1 /usr/bin/python3 -B /opt/linux-sb-checkin/checkin.py --init
~~~

看到提示后粘贴 Cookie 并回车：

~~~text
请粘贴 linux.sb 首页请求的 Cookie 值（输入不显示）：
~~~

粘贴时没有任何字符显示是正常现象。不要把 Cookie 直接粘贴到 shell 提示符，也不要放进命令参数、环境变量示例、GitHub Secrets、README 或 Issue。

初始化仅导入凭证，并不会验证它是否有效。完成后清理剪贴板，避免云剪贴板同步泄露。

### 9. 只检查登录

~~~bash
sudo -u linuxsb env PYTHONUTF8=1 /usr/bin/python3 -B /opt/linux-sb-checkin/checkin.py --check-only
~~~

应看到“已确认登录，首页访问完成”。

**--check-only 不提交红点、显示或隐藏请求，但访问首页本身可能触发签到。它不是完全无副作用的 dry-run。**

本机 Cookie 可能因为 IP 绑定或风控无法在 VPS 使用。若出现登录页、安全验证或 403，请先人工解决，不能直接开启定时器。

### 10. 校验服务配置

~~~bash
sudo systemd-analyze verify /etc/systemd/system/linux-sb-checkin.service /etc/systemd/system/linux-sb-checkin.timer
systemd-analyze calendar '*-*-* 09:00:00 Asia/Shanghai'
sudo systemctl daemon-reload
~~~

错误请先处理，不要继续启用。calendar 输出用于确认时间表达式，默认 UTC 服务器显示 01:00 相当于北京时间 09:00。

### 11. 手动执行完整流程

**这一轮会真实申请奖励及切换广告，请先确认站点允许，且不要同时在浏览器操作红点。**

~~~bash
sudo systemctl start linux-sb-checkin.service
sudo journalctl -u linux-sb-checkin.service --since '5 minutes ago' --no-pager
systemctl show linux-sb-checkin.service -p Result -p ExecMainStatus
~~~

start 会等待 oneshot 结束。正常结果为 Result=success、ExecMainStatus=0。执行结束后服务 inactive (dead) 是正常的，不需要让 Python 常驻。

阅读本次 v2.0 日志，并在浏览器核对积分、三个红点与广告可见状态。今天已经领取过的项目会跳过，不保证每个阶段都有新增积分。

### 12. 验收成功后启用自动任务

~~~bash
sudo systemctl enable --now linux-sb-checkin.timer
systemctl is-enabled linux-sb-checkin.timer
systemctl list-timers --all linux-sb-checkin.timer
~~~

应看到 enabled，以及下一次运行时间。启用的是 timer，不是 service。

Persistent=true 会在错过计划时间后补执行一次；首次启用也可能发生补跑。补跑不一定在早上九点，但当天已完成的步骤会尽量跳过。

## 已部署旧版：升级步骤

如果你的 VPS 已有账号、Cookie、service 与 timer，不需要重新安装环境或重新初始化账号。

### 1. 暂停定时任务，等待正在运行的服务结束

~~~bash
sudo systemctl stop linux-sb-checkin.timer
systemctl is-active linux-sb-checkin.service
~~~

若是 inactive 或 failed 可以继续；若 active/activating，等结束后再替换。不要在领取请求中途强制杀进程。

### 2. 获取新版源码

如果按本文克隆过：

~~~bash
sudo git -C /opt/linux-sb-checkin-src status --short
sudo git -C /opt/linux-sb-checkin-src pull --ff-only origin main
~~~

若有本地改动，先检查并保留，不要 reset --hard。若未克隆过，用首次部署的 clone 命令或通过 SFTP 上传新版即可。

### 3. 离线测试后备份

~~~bash
cd /opt/linux-sb-checkin-src
PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_checkin.py

task_backup_dir=$(sudo mktemp -d /opt/linux-sb-checkin/backup.XXXXXXXX)
sudo cp --preserve=mode,ownership,timestamps /opt/linux-sb-checkin/checkin.py "$task_backup_dir/checkin.py"
printf '旧脚本备份位置：%s\n' "$task_backup_dir/checkin.py"
~~~

保存终端输出的实际备份位置，回滚时需要用到。备份仅包含旧脚本，不复制 Cookie。备份目录默认私有，避免覆盖历史备份。

### 4. 只替换运行脚本

~~~bash
sudo install -o root -g root -m 0644 /opt/linux-sb-checkin-src/checkin.py /opt/linux-sb-checkin/checkin.py
sudo -u linuxsb env PYTHONUTF8=1 /usr/bin/python3 -B /opt/linux-sb-checkin/checkin.py --version
sudo -u linuxsb env PYTHONUTF8=1 /usr/bin/python3 -B /opt/linux-sb-checkin/checkin.py --check-only
~~~

不覆盖 Cookie、progress.json、service、timer 或你的定时覆盖配置。只替换 Python 脚本不需要 daemon-reload。

### 5. 手动验收后恢复

~~~bash
sudo systemctl reset-failed linux-sb-checkin.service
sudo systemctl start linux-sb-checkin.service
sudo journalctl -u linux-sb-checkin.service --since '5 minutes ago' --no-pager
systemctl show linux-sb-checkin.service -p Result -p ExecMainStatus
~~~

确认本次成功并核对网页后再运行：

~~~bash
sudo systemctl start linux-sb-checkin.timer
systemctl list-timers --all linux-sb-checkin.timer
~~~

stop 不会改变原有的 enabled 设置。若 is-enabled 显示 disabled，而你希望开机自动启用，再执行 sudo systemctl enable linux-sb-checkin.timer。

## 定时运行与修改时间

### 默认时间与时区

默认 OnCalendar 为每天北京时间 09:00：

~~~ini
OnCalendar=*-*-* 09:00:00 Asia/Shanghai
~~~

UTC 服务器上，01:00 UTC 等于北京时间 09:00；03:00 UTC 等于北京时间 11:00。无需更改整台 VPS 时区。

### 改成每天北京时间 11:00

推荐用 systemd drop-in，不直接修改仓库文件，避免升级覆盖：

~~~bash
sudo systemctl edit linux-sb-checkin.timer
~~~

在编辑器允许输入的位置填入并保存：

~~~ini
[Timer]
# 先清空原来的日历规则，否则可能同时在 09:00 和 11:00 执行。
OnCalendar=
OnCalendar=*-*-* 11:00:00 Asia/Shanghai
~~~

校验并应用：

~~~bash
systemd-analyze calendar '*-*-* 11:00:00 Asia/Shanghai'
sudo systemctl daemon-reload
sudo systemctl restart linux-sb-checkin.timer
systemctl cat linux-sb-checkin.timer
systemctl list-timers --all linux-sb-checkin.timer
~~~

以最后一条命令显示的下一次时间为准。若安全验证或真实领取尚未通过，请不要恢复定时器。

### 不需要补跑

编辑 timer 的 drop-in，增加：

~~~ini
[Timer]
Persistent=false
~~~

然后 daemon-reload 并 restart timer。这样错过的执行不补跑，但会降低当天签到覆盖率。不要添加 Restart=always 或高频 cron 循环。

## 日常管理与更新 Cookie

### 查看状态和日志

~~~bash
systemctl status linux-sb-checkin.timer --no-pager
systemctl list-timers --all linux-sb-checkin.timer
sudo journalctl -u linux-sb-checkin.service -n 60 --no-pager
systemctl show linux-sb-checkin.service -p Result -p ExecMainStatus
~~~

默认日志时间遵循 VPS 的时区；与北京时间不一致不一定代表执行错时。

### 手动运行一次

~~~bash
sudo systemctl start linux-sb-checkin.service
~~~

这会执行真实业务，而非只做健康检查。不要反复 start 试探奖励。

### 更新失效 Cookie

1. 暂停 timer，等正在运行的任务结束。
2. 在自己浏览器正常登录，重新获取完整 Cookie。
3. 隐藏输入更新并运行只检查模式。
4. 通过后按需测试，最后恢复 timer。

~~~bash
sudo systemctl stop linux-sb-checkin.timer
systemctl is-active linux-sb-checkin.service

sudo -u linuxsb env PYTHONUTF8=1 /usr/bin/python3 -B /opt/linux-sb-checkin/checkin.py --init
sudo -u linuxsb env PYTHONUTF8=1 /usr/bin/python3 -B /opt/linux-sb-checkin/checkin.py --check-only

sudo systemctl start linux-sb-checkin.timer
~~~

最后一条仅在检查通过后执行。新 Cookie 不一定解决 VPS IP 风控，遇到人机验证应停止自动任务。

### 仅保留访问签到

编辑 service 的 drop-in：

~~~bash
sudo systemctl edit linux-sb-checkin.service
~~~

填入：

~~~ini
[Service]
ExecStart=
ExecStart=/usr/bin/python3 /opt/linux-sb-checkin/checkin.py --check-only
~~~

执行 sudo systemctl daemon-reload，之后定时触发只访问首页，不提交红点和显示/隐藏请求。仍然不能保证首页缺少明确签到提示时已成功签到。

## 日志与成功判定

下面是成功阶段示意，不代表你的账号一定有这些奖励或积分：

~~~text
脚本 v2.0：已确认登录，首页访问完成。
红点进度：已确认 1/3。
红点进度：已确认 2/3。
红点进度：已确认 3/3。
三个红点已全部完成（包含今天已领取的项目）。
完成后显示广告：页面状态核验通过。
完成后隐藏广告：页面状态核验通过。
最终显示广告：页面状态核验通过。
流程完成：三个红点已确认，广告当前可见。
~~~

解释：

- 红点进度可能直接从 2/3 或 3/3 开始，表示当天已有完成记录。
- “无明确新增积分回执”表示不统计新增积分，不等于请求失败。
- “未取得明确签到回执”表示只确认登录和访问，不声明签到已完成。
- 完整模式退出码 0 表示流程按当前证据完成，不保证有新增积分。
- 检查模式退出码 0 仅表示确认登录并访问首页，没有测试奖励流程。
- 退出码 1 可能表示红点、可见状态、网络、权限或解析问题；不代表之前成功的签到被撤销。
- journal 会保留旧记录，查看时请用时间范围和脚本版本区分本次执行。
- 当前没有外部通知服务。timer 正常等待并不表示上次任务成功，需同时查看 service 结果。

## 故障排查

| 现象 | 处理方式 |
| --- | --- |
| 未确认登录 | 核对完整 Cookie、是否过期、VPS 是否遭验证；不要绕过 CAPTCHA |
| HTTP 403 / 非 JSON 响应 | 查看脱敏原因，可能是权限、CSRF、安全验证或页面变化，暂停定时器 |
| 只确认 1/3 或 2/3 | 看具体失败阶段和返回信息，不要直接把状态文件改成 3/3 |
| 无红点但未确认完成 | 可能已领但页面没提供证据，或账号不满足条件；需要人工核对 |
| 缺少合法本站 POST 表单 | 可能功能不可用或页面变化；不要自行猜接口地址 |
| 返回 ok 但没有奖励或已领取证据 | 脚本保守停止，核对站内结果和返回字段 |
| 显示/隐藏响应成功但页面不变 | 页面核验失败，检查业务规则及是否有另一设备并发操作 |
| 超时 | 可能请求已生效但回执丢失，先看网站结果，不立刻重跑 POST |
| progress.json 损坏 | 暂停任务，私下备份检查；不随意删文件或伪造状态 |
| service inactive (dead) | oneshot 执行后正常；另外检查 Result 与 ExecMainStatus |
| timer active (waiting) | 正在等待下一次触发，不说明上次业务成功 |
| 运行时 ImportError: fcntl | 实际任务需要 Linux；Windows 仅用于离线测试 |
| Result=timeout / oom-kill | 120 秒或 96M 限制触发，先排查网络和日志，不盲目提高限制 |
| Git 提示 dubious ownership | 按文中使用 sudo git 操作 root 所有的源码目录，不全局放开 safe.directory |

只检查文件权限，不打印内容：

~~~bash
sudo stat -c '%a %U:%G %n' /var/lib/linux-sb-checkin /var/lib/linux-sb-checkin/cookies.txt
~~~

预期目录 700、Cookie 文件 600，所有者为 linuxsb。不要用 cat 输出 Cookie 来排查。

## 安全与隐私

- Cookie 相当于账号登录凭证，没有明文密码也不代表凭证安全。
- Cookie 文件使用 CookieJar 格式明文存放，不是加密存储；root、备份服务和有权限的入侵者仍可能读取。
- 初始化通过 getpass 隐藏输入，避免 Cookie 出现在命令参数和历史记录。
- 运行账号无交互 shell；程序源文件由 root 管理，运行账号不能修改程序。
- service 使用 NoNewPrivileges、ProtectSystem、ProtectHome 等限制；这些不是容器，也不是完整隔离。
- 仅向 linux.sb HTTPS 发请求，并限制重定向；不会访问广告商域名。
- 服务器更新的 Cookie 会保存。请保护整个数据目录、快照和备份。
- .gitignore 只减少意外提交，不会撤销已经公开的凭证。
- 如果 Cookie 泄露，立即在站点注销相关会话或采取站点支持的会话失效措施，再获取新 Cookie；只改仓库文件不够。
- 日志有脱敏措施，但不是对任意服务端响应的绝对保密保证。分享前仍需人工检查。
- progress.json 保存日期、账号显示名的 SHA-256 指纹、广告位及已完成步骤；不是匿名数据，也不是稳定用户 ID。
- 不要把整个私密目录、浏览器请求头、完整 HAR 或 Copy as cURL 命令放到 Issue。

## 原理、参数与开发测试

### 请求与状态

主程序通过 urllib + CookieJar 维护登录态，HTMLParser 读取页面，multipart/form-data 提交页面的实际表单。依赖网站当前的 HTML 标记和回执格式，不是稳定的官方 API。

广告点击时本站的请求，不等于浏览器打开广告页面的全部行为。若后续需要实际 JS、浏览器验证或真实浏览，当前轻量方案可能不适用。

progress.json 使用网站 reward_day 和账号显示名指纹隔离当天状态；日期变化会开启新一轮。账号改名也可能导致重新建立进度，不要在运行期间切换或修改账号。

Cookie、进度采用临时文件加原子替换保存，使用 Linux flock 防止同一数据目录并发。崩溃或网络超时仍可能造成“服务端已生效、本地未记录”的窗口，不能视为事务。

### 命令行参数

~~~bash
/usr/bin/python3 -B /opt/linux-sb-checkin/checkin.py --help
/usr/bin/python3 -B /opt/linux-sb-checkin/checkin.py --version
~~~

| 参数 | 含义 |
| --- | --- |
| --init | 隐藏输入并保存 Cookie，不验证登录 |
| --check-only | 访问首页确认登录；不提交红点和切换请求 |
| --data-dir 绝对目录 | 指定私密数据目录，默认 /var/lib/linux-sb-checkin |
| --version | 打印版本后退出，不加载 Cookie |
| --help | 查看帮助后退出 |

日常请以 linuxsb 运行，不要随意用 root 启动导致数据文件所有权变化。自定义数据目录还需同步调整 service 的写权限和运行目录，不能只修改 CLI 参数就假定沙箱允许。

### 离线开发测试

在仓库目录执行：

~~~bash
PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_checkin.py
~~~

测试不会访问真实站点。Windows PowerShell 可用：

~~~powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m unittest -v test_checkin.py
~~~

修改约定：所有源文件使用 UTF-8、LF；新业务逻辑应有注释和离线回归测试。不要把真实账号回执、Cookie 或页面快照作为测试夹具。

## 回滚与停用

### 回滚程序

1. 停止 timer，等待当前 service 结束。
2. 用升级时记录的实际备份路径恢复运行脚本。
3. Cookie、进度和 timer 保持不变。
4. 先核对旧版风险，再决定是否恢复自动运行。

在下面命令中将 BACKUP_DIRECTORY 替换为升级时打印的实际备份目录，不能原样执行占位符：

~~~bash
sudo systemctl stop linux-sb-checkin.timer
systemctl is-active linux-sb-checkin.service
sudo install -o root -g root -m 0644 /opt/linux-sb-checkin/BACKUP_DIRECTORY/checkin.py /opt/linux-sb-checkin/checkin.py
~~~

恢复旧脚本不需要 daemon-reload；如果修改了 service/timer/drop-in，才需要重新加载。

### 长期停用但保留数据

~~~bash
sudo systemctl disable --now linux-sb-checkin.timer
systemctl is-active linux-sb-checkin.service
~~~

等正在运行的任务结束即可。不要为了停用而删除账号、全局日志或私密数据。

本教程不提供一键递归删除命令。确实要卸载时，先确认服务名、安装目录、备份与会话失效策略，再分别删除明确目标；不要对根目录、家目录或整个 /opt 做递归清理。

## 常见问题

**个人电脑需要一直开机吗？**

不需要。获取 Cookie 后由持续在线的 VPS 执行。Cookie 失效时才需要人工重新登录。

**为什么默认 09:00，不是 11:00？**

当前仓库沿用已有配置 09:00。需要 11:00 的用户按定时器章节添加覆盖规则；升级脚本不会改你服务器上的时间。

**是不是执行成功就一定增加积分？**

不是。当天已领、网站规则、账户条件和奖励字段都会影响结果。操作成功、明确发奖、页面状态通过是不同的判断。

**为什么不自动重试或加浏览器？**

未知结果下自动重试可能重复提交；浏览器会增加依赖与资源。本项目优先保持轻量，遇验证人工处理。

**可以直接在 GitHub Actions 上每天运行吗？**

本文不提供这种部署。登录 Cookie 与 IP/验证码可能绑定，托管执行环境也不保证固定准点，且不能因此放宽安全边界。推荐你自己的 VPS。

**需要定期清理日志吗？**

本项目使用系统已有 journal，没有单独无限追加的日志文件；实际保留量由 VPS 的 journald 配置决定，不会为本项目自动改全局保留策略。

## 反馈与贡献

提交 Issue 时提供系统版本、Python 版本、脚本版本、失败阶段、经过人工检查的脱敏日志，以及是否已在网页核对。不要提供凭证或整份会话目录。

提交修改前运行离线测试，说明原因、兼容性和是否改变实际请求行为。不要为了让任务“看起来成功”而吞掉未知结果或伪造进度。

仓库未附带开源许可证；公开可见不等于授予任意复制、修改或再分发权限。若希望正式授权复用，请由仓库所有者选择并添加合适的许可证。

### 官方参考

- [systemd.timer 手册](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)：OnCalendar、Persistent 与定时精度。
- [systemd 服务管理手册](https://www.freedesktop.org/software/systemd/man/latest/systemctl.html)：edit、daemon-reload 与服务状态。
- [Python getpass 文档](https://docs.python.org/3/library/getpass.html)：交互式隐藏输入。

这些文档解释底层工具，不代表 linux.sb 对本项目作出兼容性或自动化授权承诺。
