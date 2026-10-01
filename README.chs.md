# hyMailDrop

```
== HyMailDrop by HYrecovery & HoshinoSumi from teko.IO SisTemS! ==
== Under MIT Open Source License ==
```

**把一本书寄给自己的 Kindle —— 不用 Amazon 的 send-to-kindle、不用云服务、也不需要电脑在旁边。**
hyMailDrop 是一个 **跑在 Kindle 上**的 KUAL 扩展：它自己登录你的 Outlook 邮箱、自己找出你发给
自己的附件、自己把它们放进 `/documents`。

登录一次之后，这台 Kindle 不再需要任何别的东西：不要电脑、不要手机、不要另一台机器上跑常驻程序、
不要第三方服务器。

> ### 定位
> 这**不是** [hyKBridge](https://github.com/fengye1003/hyKBridge) 的一部分，**运行时也不依赖它**。
> hyKBridge 是基插件（远程 shell 与设备操作）；hyMailDrop 是一个**借用**它的应用 —— 只在**安装那一步**、
> 而且只在你恰好有它的时候。删掉 hyKBridge，hyMailDrop 照常工作；依赖永远不会反过来。

## 为什么把它放在设备上

最自然的做法是在电脑上跑一个程序，去查邮箱、再推到 Kindle。但那条路有个绕不过的缺陷：
**挂起的 Kindle 没有网络栈** —— 所以设备侧总得有东西在听着（一个桥、一个 File Browser、或者一根 USB 线）。
你最后总会依赖上第二个组件，而那个组件存在的唯一理由就是"能被连上"。

把邮件客户端放到 Kindle 上，这个组件就彻底不存在了。而这件事**居然可行** —— 这一点并不显然：
设备上的 Python 3.9 **自己不带 CA bundle**（`default verify paths: None`，`/etc/ssl/certs` 只有 3 项），
所以开箱即用的 TLS 校验必然失败。hyMailDrop 的做法是**自带一份 CA**（`certs/cacert.pem`，Mozilla 根证书），
用它去建 `ssl` 上下文。真机实测（2026-10-01）：DNS + TLS + HTTP 全通 ——
`login.microsoftonline.com` 返 200，`graph.microsoft.com` 对未带令牌的请求返 401（这是正确的）。

**任何时候都不关校验**。在一个 OAuth 客户端里跳过证书校验，等于把邮箱交给同网段的任何人。

## 安装

两条路，**都不需要 USB 线**（有意思的那两条都不需要）。

**1. 走局域网"forge 式"安装（不插 USB）**：如果你已经配好 hyKBridge，这一条会把整个扩展推上设备并校验：

```bash
node host/install.mjs device --as hyMailDrop
# [i] 设备在线 → 直连安装
# [OK] 14 个文件全部送达并逐文件 sha256 校验一致
```

它是**先传、再在设备上重新算一遍 sha256**，对不上就当场停下 —— 装了一半的扩展比装不上更糟。
设备在睡觉时它会改走 hyKBridge 的拉取通道排队，设备下次醒来自己装。

为什么这件事不只是"方便"：**Kindle 插上 USB 就进 U 盘模式，那时 KUAL 整个没在跑**。
"拷贝 → 弹出 → 拔线 → 重启 → 进 KUAL"这一套之所以存在，只是因为以前没有别的通道。现在有了。

**2. 手动（USB）**：把仓库里的 `device/` 拷成设备上的 `/mnt/us/extensions/hyMailDrop/`，弹出、重启。结果一样，就是多走几步。

## 第一次使用

在 Kindle 上：**KUAL → hyMailDrop → 1. Login Outlook**。

Kindle 上没有浏览器，所以走 OAuth 的**设备码**流程：验证码和网址显示在墨水屏上（同时写进
`state/login.log`）。你用手机或电脑打开 `https://login.microsoft.com/device`，输入验证码、登录、同意一次。
refresh_token 就存在设备上了，之后永远不用再来一遍。

> 这台设备的墨水屏**没有中文字形** —— `eips` 打中文会报 `character "?" not available` 并留白。
> 所以**所有上屏文字一律是 ASCII**；日志文件是 UTF-8，中文完全正常。

然后：**KUAL → hyMailDrop → 2. Sync now**。后缀在白名单里的附件就落进 `/documents`，
Kindle 书库会像对待任何一本书那样把它收进去。

## 菜单

| 项 | 作用 |
|---|---|
| 1. Login Outlook | 设备码登录：码在屏幕上，你在浏览器里同意 |
| 2. Sync now | 跑一轮：读邮箱、把新附件取进 `/documents` |
| Auto-sync: ON (15 min) | **设备醒着时**每 15 分钟同步一次（见下） |
| Auto-sync: OFF | 停掉那个循环 |
| Show status | 登录状态、剩余空间、已收了多少个 |
| Show log | 最近 10 行打到屏幕上，完整日志在磁盘 |
| Forget delivered books | 清台账（下次同步会把历史附件重收一遍） |

全部也都有命令行，便于脚本化或经桥远程驱动：

```bash
python3 bin/hyMailDrop.py login
python3 bin/hyMailDrop.py sync [--dry-run] [--force] [--quiet]
python3 bin/hyMailDrop.py status
python3 bin/hyMailDrop.py ledger [--clear]
python3 bin/hyMailDrop.py selftest      # 离线自检，不联网
```

## 定时这件事，说实话

**挂起的设备没法收邮件。** 这一点绕不过去，所以 hyMailDrop 不装样子。三条真正可用的路：

1. **拿起设备时点一下「Sync now」** —— 简单，永远有效。
2. **醒着时自动同步**（菜单里那项）：每 15 分钟查一次，但**只在设备本来就醒着的时候**。对每天都会拿起来的设备，这一条覆盖了大部分场景。
3. **让唤醒方顺手调它**：如果已经有东西在按计划唤醒你的 Kindle（hyKBridge 的 Pulse、闹钟脚本、任何东西），
   让它在每次唤醒时跑一遍 `bin/sync.sh` 即可 —— **hyMailDrop 不关心是谁唤醒的设备，也不需要知道**。

登录或同步进行期间，hyMailDrop 会按住屏幕常亮（`preventScreenSaver`），免得下到一半被挂起冻住；
**退出时清除、每次启动再清一次** —— 所以被硬杀也不会把你的电池一直按着不睡。

## 配置

设备上的 `device/config.json`（首次运行自动生成，直接改文件即可生效，不用重装）：

| 键 | 默认 | 含义 |
|---|---|---|
| `folders` | `["inbox","junkemail"]` | 扫哪些文件夹。**`junkemail` 实际上不是可选项** —— 新发件人带附件的邮件会被丢进垃圾邮件（实测 100%） |
| `extensions` | `.mobi .azw .azw3 .azw4 .prc .pobi .epub .txt .pdf` | 什么算"书" |
| `target_dir` | `/mnt/us/documents` | 书落到哪 |
| `max_attachment_mb` | `50` | 超过就跳过 |
| `free_space_margin_mb` | `60` | 剩余空间低于它就停止投递 |
| `max_messages_per_run` | `20` | 每轮每个文件夹看几封 |
| `overwrite` | `true` | 设备上同名文件 ⇒ 覆盖（你最初的需求） |
| `inbox_action` | `mark_read` | 一封邮件被完整处理之后怎么处置：`mark_read` / `archive` / `delete` / `none` |
| `inbox_warn_count` | `200` | 收件箱到这个数就提醒 |
| `from_filter` | `[]` | 非空时只收这些发件人 |

`device/creds.json` 存 `client_id` / `tenant` / `refresh_token`。那个 refresh_token **就是**你的邮箱凭据：
已进 `.gitignore`、落盘权限 `0600`、任何输出里只打长度不打内容。

## 两处容量，按你说的处理

* **收件箱**：每轮都报数，到 `inbox_warn_count` 就提醒；真正腾地方靠 `inbox_action` ——
  而且**只对"附件全部有明确结局"的邮件**动手（已投递，或被策略明确跳过）。任何一个附件下载失败，
  这封邮件就原样留着，下轮再来。**绝不把没弄完的邮件归档或删掉。**
* **磁盘**：每个文件落盘前先看剩余空间，低于 `free_space_margin_mb` 就停止投递。装不下就不写。

## 实测，不是推断

以下全部来自真机（越狱 Paperwhite 3，2026-10-01）：

* 设备侧 HTTPS 可用：`python 3.9.8`、`OpenSSL 1.1.1l`，`login.microsoftonline.com` → 200，`graph.microsoft.com` → 401（未带令牌时正确）。
* 设备 Python **没有 CA bundle** ⇒ 自带 `certs/cacert.pem` 是**必需品**而非装饰（这里打进去的是 121 张根证书）。
* `eips` 画不了中文：报 `paint_char> character "?" not available` 并留白。
* 整个扩展 14 个文件 / 约 216 KB，**经 WiFi 安装并逐文件 sha256 校验通过**。
* 设备端离线自检：`9 passed, 0 failed`。

两个 Graph 的坑，客户端都得绕（都花过真实排障时间）：

* 在文件夹范围内用 `$filter=hasAttachments eq true` 会**静默返回 0 封**，而同一封邮件在 `/me/messages` 上查得到 ⇒ 一律改成客户端筛。
* 大于约 3 MB 的附件**不带** `contentBytes` ⇒ 回退 `GET /me/messages/{id}/attachments/{aid}/$value` 取原始字节。

## 已知限制

* **一个邮箱、一台设备**，不支持多账号。
* **不支持 `referenceAttachment`**（OneDrive 分享链接），只处理真正的文件附件。
* **只投附件**，还没有"每日新闻"那种生成一页 HTML 的能力 —— 但管道已经通了（把渲染好的页面丢进 `/documents` 即可），这是最顺的下一步。
* 登录需要一个浏览器（不必是同一台机器，但得能看见 Kindle 屏幕上的码）。
* 需要越狱 Kindle + KUAL + Python 3。只在 PW3 上验证过。

## 目录结构

```
device/config.xml          KUAL 扩展清单
device/menu.json           KUAL 菜单
device/bin/hyMailDrop.py   客户端本体：设备码登录 / Graph / 投递 / 容量
device/bin/*.sh            菜单入口（login / sync / status / log / auto-sync）
device/certs/cacert.pem    Mozilla 根证书（设备自己没有）
host/install.mjs           forge 式安装器：经 hyKBridge 从局域网推送并逐文件 sha256 校验
```

## 作者

由 **星澄（HoshinoSumi）** 撰写 —— 我是一个 AI 助手，也是本仓库所属账号
[fengye1003](https://github.com/fengye1003)（HYrecovery）的**专属 Agent**。
代码、真机实测与这份文档都由该账号的 Agent 产出，并由账号持有人审阅。

测试机是同一位持有者的越狱 Kindle Paperwhite 3。

## 许可证

MIT —— 见 [LICENSE](LICENSE)。`device/certs/cacert.pem` 里打包的是 Mozilla CA 根证书包
（取自 <https://curl.se/ca/cacert.pem>），按 Mozilla Public License 2.0 分发。

*English: [README.md](README.md)*
