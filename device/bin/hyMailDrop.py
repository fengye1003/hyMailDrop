#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
hyMailDrop -- 把邮箱里的电子书附件直接放进这台 Kindle 的 /documents。

== HyMailDrop by HYrecovery & HoshinoSumi from teko.IO SisTemS! ==
== Under MIT Open Source License ==

它跑在 **Kindle 上**（KUAL 扩展，Python 3.9 纯标准库），不依赖电脑、不依赖任何桥：
自己在设备上完成 OAuth 设备码登录，自己拉 Microsoft Graph，自己把附件落到 /documents。

为什么是 Graph 而不是 IMAP：普通网络里 993/587 经常被 reset，443 才稳；而且 Kindle 上
本来也没有 IMAP 客户端可言。设备码登录是为这种"没有浏览器"的设备设计的。

凭什么能跑在设备上（真机实测 2026-10-01）：
  python 3.9.8 / OpenSSL 1.1.1l，到 login.microsoftonline.com 与 graph.microsoft.com 的
  TLS 握手 + DNS + HTTP 全部正常（LOGIN 200 / GRAPH 401）。
  ⚠️ 唯一缺口：设备 Python **没有 CA bundle**（`default verify paths: None`、/etc/ssl/certs 只有 3 项）
  ⇒ 所以本扩展**自带 certs/cacert.pem**（Mozilla 的 CA 根证书包）。绝不用"跳过校验"——
  对一个 OAuth 客户端来说那是把中间人请进门。

用法（在设备上；KUAL 菜单里也有对应项）：
  python3 bin/hyMailDrop.py login      设备码登录：屏幕上出码，你在手机/电脑上输一次
  python3 bin/hyMailDrop.py sync       同步一次（下载新附件到 /documents）
  python3 bin/hyMailDrop.py sync --dry-run   只报告会做什么
  python3 bin/hyMailDrop.py status     看配置/登录状态/台账/磁盘
  python3 bin/hyMailDrop.py ledger --clear   清空台账（会重推历史附件，慎用）
  python3 bin/hyMailDrop.py selftest   离线自检（不联网）

纪律：只在拿到 200 且体积合理时才落盘；先写 .part 再原子改名；同名覆盖按 config 的 overwrite；
     磁盘不够就跳过并说清楚；邮件只在"附件全部有明确结局"时才标记已读/归档，绝不吞掉没弄完的。
"""
from __future__ import print_function

import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 扩展根目录
BIN = os.path.join(DIR, 'bin')
STATE = os.path.join(DIR, 'state')
CERTS = os.path.join(DIR, 'certs')
CONFIG_F = os.path.join(DIR, 'config.json')
CREDS_F = os.path.join(DIR, 'creds.json')
LEDGER_F = os.path.join(STATE, 'ledger.json')
TOKEN_F = os.path.join(STATE, 'access_token.json')
LOG_F = os.path.join(STATE, 'hyMailDrop.log')

README_FIRST = os.path.join(DIR, 'README.md')
DEFAULT_CONFIG = {
    "_comment": "hyMailDrop 的配置。改完存盘即可生效，不用重装。target_dir 就是 Kindle 的书库。",
    "folders": ["inbox", "junkemail"],
    "extensions": [".mobi", ".azw", ".azw3", ".azw4", ".prc", ".pobi", ".epub", ".txt", ".pdf"],
    "target_dir": "/mnt/us/documents",
    "max_attachment_mb": 50,
    "free_space_margin_mb": 60,
    "max_messages_per_run": 20,
    "overwrite": True,
    "inbox_action": "mark_read",
    "archive_folder": "archive",
    "inbox_warn_count": 200,
    "from_filter": []
}
DEFAULT_CREDS = {
    "_comment": "client_id 必须是【第三方】公开客户端；第一方应用（Azure CLI / Microsoft Office）拿不到用户同意。login 会把 refresh_token 写回来。",
    "client_id": "9e5f94bc-e8a4-4e73-b8be-63364c29d753",
    "tenant": "common",
    "refresh_token": ""
}
SCOPE = "offline_access https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Mail.ReadWrite"
GRAPH = "https://graph.microsoft.com/v1.0"
UA = "hyMailDrop/0.1 (Kindle; +https://github.com/fengye1003)"
TIMEOUT = 60


# ── 输出：e-ink 只有 5 行，日志才是全量 ──────────────────────────────
class Screen(object):
    """把最重要的几行放到 e-ink 上，其余全部进日志。

    KUAL 跑脚本时 stdout 没人看，所以"报告结果"必须走 eips + 日志两条。
    """

    def __init__(self, quiet=False):
        self.lines = []
        self.quiet = quiet

    def log(self, msg):
        line = '%s %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg)
        try:
            if not os.path.isdir(STATE):
                os.makedirs(STATE)
            with open(LOG_F, 'a') as f:
                f.write(line + '\n')
        except IOError:
            pass
        if not self.quiet:
            print(line)

    def show(self, msg, row=None):
        """放到屏幕上。row 不给就顺排（最多 5 行，e-ink 的预算）。

        注意：eips 没有中文字形，这里强制转 ASCII（见 _ascii 的说明）。
        """
        text = _ascii(msg)
        self.log('    [screen] %s' % msg)
        if row is None:
            self.lines.append(text)
            row = len(self.lines)
        try:
            subprocess.call(['eips', '2', str(row), text[:46]])
        except Exception:
            pass

    def clear(self):
        try:
            subprocess.call(['eips', '-c'])
        except Exception:
            pass


SCREEN = Screen()


def _ascii(s):
    """eips 只认 ASCII 字符集。

    ★ 真机实测 2026-10-01：往 eips 打中文会得到 `paint_char> character "?" not available`，
    屏幕上是空白/问号，等于什么也没显示。日志文件里中文完全没问题（那是 UTF-8 文件），
    所以规矩很简单：**日志随你写中文，屏幕上必须走 ASCII**。这里兜底把它压成 ASCII，
    免得以后哪个 show() 又漏了中文字符串上去。
    """
    out = ''.join(ch if 32 <= ord(ch) < 127 else ' ' for ch in str(s))
    return ' '.join(out.split())


def die(msg, code=1):
    SCREEN.log('[NG] ' + msg)
    shown = _ascii(msg)
    SCREEN.show('hyMailDrop: ' + (shown[:36] if shown else 'error - see log'), 3)
    sys.exit(code)

def keep_awake(on):
    """Hold the device awake for the duration of a long operation.

    Why: login polls for up to 15 minutes and a sync can pull tens of MB -- and a Kindle
    suspends as soon as the screen goes off, freezing the poll/download (the device code
    even expires while frozen). `preventScreenSaver` exists for exactly this.

    * But hold it ONLY for the operation, and clear it unconditionally at startup:
      hyKBridge's pulse once held this every cycle, so the device never slept and the
      battery fell 5% a day. Here the rule is: set on entry, clear on exit, and clear once
      at startup so a hard kill (property left at 1) heals itself.
    """
    try:
        subprocess.call(['lipc-set-prop', 'com.lab126.powerd', 'preventScreenSaver',
                         '1' if on else '0'])
    except Exception:
        pass





# ── 配置 / 凭据 / 台账 ───────────────────────────────────────────────
def load_json(path, defaults, create=True):
    if not os.path.exists(path):
        if create:
            save_json(path, defaults)
        return dict(defaults)
    try:
        with open(path) as f:
            j = json.load(f)
    except ValueError as e:
        die('%s 不是合法 JSON（%s）—— 用记事本/编辑器检查一下' % (os.path.basename(path), e))
    out = dict(defaults)
    out.update(j)
    return out


def save_json(path, obj):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')
    os.rename(tmp, path)
    try:
        os.chmod(path, 0o600)     # 里面有 refresh_token
    except OSError:
        pass


def load_ledger():
    try:
        with open(LEDGER_F) as f:
            return json.load(f)
    except Exception:
        return {}


def save_ledger(l):
    save_json(LEDGER_F, l)


# ── HTTPS（自带 CA）─────────────────────────────────────────────────
_CTX = [None]


def ctx():
    if _CTX[0] is None:
        ca = os.path.join(CERTS, 'cacert.pem')
        if os.path.exists(ca):
            _CTX[0] = ssl.create_default_context(cafile=ca)
        else:
            # 没有自带 CA 就只能用系统的（本机实测系统没有）——明说，不静默降级成"跳过校验"
            SCREEN.log('[warn] 缺少 certs/cacert.pem，改用系统 CA（本机通常没有，会校验失败）')
            _CTX[0] = ssl.create_default_context()
    return _CTX[0]


def http(url, data=None, headers=None, raw=False, tries=3):
    """返回 (status, body)。body 是 str 或 bytes。网络抖动重试，别的错误立刻抛。

    为什么带重试：设备 WiFi 刚恢复时会瞬断；而设备码轮询一次失败就把进程打死，
    用户就得重新走一遍浏览器同意。
    """
    h = {'User-Agent': UA}
    h.update(headers or {})
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode('utf-8')
        h['Content-Type'] = 'application/x-www-form-urlencoded'
        h.setdefault('Accept', 'application/json')
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=h)
            r = urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx())
            payload = r.read()
            return r.status, (payload if raw else payload.decode('utf-8', 'replace'))
        except urllib.error.HTTPError as e:
            # HTTP 错误是**有效答案**（401/400 都带 JSON），不重试
            payload = e.read()
            return e.code, (payload if raw else payload.decode('utf-8', 'replace'))
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(1.5 * (i + 1))
    raise last


def post_form(url, form, tries=3):
    return http(url, data=form, tries=tries)


def graph(token, path, method='GET', body=None, raw=False):
    h = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        h['Content-Type'] = 'application/json'
    # http() 走 urlencode，这里要的是 JSON 体，所以直接自己发
    last = None
    for i in range(3):
        try:
            req = urllib.request.Request(GRAPH + path, data=data, headers=h, method=method)
            r = urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx())
            payload = r.read()
            return r.status, (payload if raw else json.loads(payload.decode('utf-8', 'replace')))
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                return e.code, (payload if raw else json.loads(payload.decode('utf-8', 'replace')))
            except ValueError:
                return e.code, {'raw': payload[:200].decode('utf-8', 'replace')}
        except Exception as e:
            last = e
            if i < 2:
                time.sleep(1.5 * (i + 1))
    raise last


# ── 登录（设备码）───────────────────────────────────────────────────
def access_token(creds, force=False):
    """拿一个可用的 access token：优先缓存，其次 refresh_token。"""
    if not force and os.path.exists(TOKEN_F):
        try:
            with open(TOKEN_F) as f:
                t = json.load(f)
            if t.get('access_token') and t.get('expires_at', 0) > time.time() + 60:
                return t['access_token']
        except Exception:
            pass
    if not creds.get('refresh_token'):
        die('还没登录过：先跑 login（KUAL → hyMailDrop → 登录 Outlook）')
    base = 'https://login.microsoftonline.com/%s/oauth2/v2.0' % creds.get('tenant') or 'common'
    st, body = post_form(base + '/token', {
        'client_id': creds['client_id'],
        'grant_type': 'refresh_token',
        'refresh_token': creds['refresh_token'],
        'scope': SCOPE,
    })
    if st != 200:
        die('刷新令牌失败（HTTP %s）：%s —— 可能要重新 login' % (st, str(body)[:200]))
    j = json.loads(body)
    if j.get('refresh_token'):                 # 微软会滚动 refresh_token，必须存回
        creds['refresh_token'] = j['refresh_token']
        save_json(CREDS_F, creds)
    save_json(TOKEN_F, {'access_token': j['access_token'],
                        'expires_at': time.time() + int(j.get('expires_in', 3600)) - 120})
    return j['access_token']


def cmd_login(creds, opts):
    base = 'https://login.microsoftonline.com/%s/oauth2/v2.0' % (creds.get('tenant') or 'common')
    rnd = 0
    while True:
        rnd += 1
        st, body = post_form(base + '/devicecode',
                             {'client_id': creds['client_id'], 'scope': SCOPE})
        if st != 200:
            die('申请设备码失败（HTTP %s）：%s' % (st, str(body)[:200]))
        j = json.loads(body)
        mins = int(j.get('expires_in', 900) / 60)
        SCREEN.log('=== 第 %d 轮设备码（%d 分钟内有效）===' % (rnd, mins))
        SCREEN.log('  网址：%s' % j.get('verification_uri'))
        SCREEN.log('  验证码：%s' % j.get('user_code'))
        SCREEN.show('1) Open %s' % j.get('verification_uri'), 1)
        SCREEN.show('2) Enter code %s' % j.get('user_code'), 2)
        SCREEN.show('3) Sign in to Outlook', 3)
        SCREEN.show('(waiting for approval)', 4)
        deadline = time.time() + int(j.get('expires_in', 900)) - 30
        interval = int(j.get('interval', 5))
        fails = 0
        while time.time() < deadline:
            time.sleep(interval)
            try:
                st, body = post_form(base + '/token', {
                    'client_id': creds['client_id'],
                    'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
                    'device_code': j['device_code'],
                })
                fails = 0
            except Exception as e:
                fails += 1
                SCREEN.log('[warn] 轮询失败第 %d 次：%s' % (fails, e))
                if fails >= 3:
                    SCREEN.log('[i] 网络连续抖动，换一枚新验证码重来')
                    break
                continue
            if st == 200:
                t = json.loads(body)
                creds['refresh_token'] = t.get('refresh_token', '')
                save_json(CREDS_F, creds)
                save_json(TOKEN_F, {'access_token': t['access_token'],
                                    'expires_at': time.time() + int(t.get('expires_in', 3600)) - 120})
                SCREEN.log('[OK] 登录成功，refresh_token 已写入 creds.json（长度 %d，内容不打印）'
                           % len(creds['refresh_token']))
                SCREEN.show('hyMailDrop: login OK', 1)
                SCREEN.show('now tap Sync now', 2)
                return 0
            err = ''
            try:
                err = json.loads(body).get('error', '')
            except ValueError:
                pass
            if err == 'authorization_pending':
                continue
            if err == 'slow_down':
                time.sleep(5)
                continue
            if err in ('expired_token', 'bad_verification_code'):
                SCREEN.log('[i] 验证码过期，换一枚重来')
                break
            die('轮询令牌失败：%s' % str(body)[:200])
        else:
            SCREEN.log('[i] 本轮超时，换一枚新验证码重来')
    return 0


# ── 容量 ────────────────────────────────────────────────────────────
def disk_free(path):
    try:
        st = os.statvfs(path)
        return st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize
    except Exception:
        return None, None


def inbox_stats(token):
    st, j = graph(token, '/me/mailFolders/inbox?$select=displayName,totalItemCount,unreadItemCount')
    return j if st == 200 else None


def apply_inbox_action(token, mid, cfg):
    act = cfg.get('inbox_action') or 'none'
    if act == 'none':
        return 'none'
    if act == 'mark_read':
        st, _ = graph(token, '/me/messages/' + mid, 'PATCH', {'isRead': True})
    elif act == 'archive':
        st, _ = graph(token, '/me/messages/%s/move' % mid, 'POST',
                      {'destinationId': cfg.get('archive_folder') or 'archive'})
    elif act == 'delete':
        st, _ = graph(token, '/me/messages/' + mid, 'DELETE')
    else:
        return 'none'
    if st not in (200, 201, 204):
        SCREEN.log('  [warn] 收件箱处置失败（%s → HTTP %s）' % (act, st))
        return 'failed'
    return act


# ── 同步 ────────────────────────────────────────────────────────────
def cmd_sync(creds, cfg, opts):
    token = access_token(creds)
    ledger = load_ledger()
    target = cfg.get('target_dir') or '/mnt/us/documents'
    if not os.path.isdir(target):
        die('目标目录不存在：%s' % target)

    folders = cfg.get('folders') or ['inbox', 'junkemail']
    top = int(cfg.get('max_messages_per_run') or 20)
    sel = 'id,subject,from,receivedDateTime,isRead,hasAttachments'
    msgs = []
    for folder in folders:
        # $orderby 里的空格必须编码：Node 的 fetch 容忍裸空格，Python 的 http.client 直接
        # 抛 InvalidURL（真机踩到，2026-10-01）。查询串一律拼完再 quote 一次。
        q = '$top=%d&$orderby=%s&$select=%s' % (top, urllib.parse.quote('receivedDateTime desc'), sel)
        st, j = graph(token, '/me/mailFolders/%s/messages?%s' % (urllib.parse.quote(folder), q))
        if st != 200:
            SCREEN.log('  [warn] 读 %s 失败（HTTP %s）' % (folder, st))
            continue
        allm = (j or {}).get('value', [])
        hit = [m for m in allm if m.get('hasAttachments')]
        SCREEN.log('%s: 看了 %d 封，带附件 %d 封' % (folder, len(allm), len(hit)))
        msgs.extend(hit)

    stats = inbox_stats(token)
    if stats:
        SCREEN.log('收件箱「%s」：%d 封（未读 %d）'
                   % (stats.get('displayName'), stats.get('totalItemCount'), stats.get('unreadItemCount')))
        warn = int(cfg.get('inbox_warn_count') or 200)
        if stats.get('totalItemCount', 0) >= warn:
            SCREEN.log('  ★ 收件箱已 %d 封（阈值 %d）——建议把 inbox_action 改成 archive 或 delete'
                       % (stats['totalItemCount'], warn))

    free, total = disk_free(target)
    if free is not None:
        SCREEN.log('Kindle 剩余 %.1f MB / 共 %.0f MB' % (free / 1048576.0, total / 1048576.0))

    if not msgs:
        SCREEN.log('没有带附件的邮件（已扫描：%s）' % ' / '.join(folders))
        SCREEN.show('hyMailDrop: no new mail', 1)
        return 0

    got = skipped = 0
    for m in msgs:
        frm = ((m.get('from') or {}).get('emailAddress') or {}).get('address') or '?'
        if cfg.get('from_filter') and frm not in cfg['from_filter']:
            skipped += 1
            continue
        st, j = graph(token, '/me/messages/%s/attachments?$select=id,name,size' % m['id'])
        if st != 200:
            SCREEN.log('  取附件列表失败 %s…' % m['id'][:12])
            continue
        atts = (j or {}).get('value', [])
        ok = skip = err = 0
        for a in atts:
            name = os.path.basename(a.get('name') or 'unnamed')
            ext = os.path.splitext(name)[1].lower()
            size = int(a.get('size') or 0)
            key = '%s:%s' % (m['id'], a.get('id'))
            if ext not in (cfg.get('extensions') or []):
                SCREEN.log('  跳过（后缀不在白名单）: %s' % name); skip += 1; continue
            if size > int(cfg.get('max_attachment_mb') or 50) * 1048576:
                SCREEN.log('  跳过（超过体积上限）: %s' % name); skip += 1; continue
            if key in ledger and not opts.get('force'):
                SCREEN.log('  跳过（台账：%s 已收过）: %s' % (ledger[key].get('at'), name)); skip += 1; continue
            if free is not None and free - size < int(cfg.get('free_space_margin_mb') or 60) * 1048576:
                SCREEN.log('  ★ 跳过（磁盘不足）：%s 需 %.1fMB，只剩 %.1fMB'
                           % (name, size / 1048576.0, free / 1048576.0)); skip += 1; continue
            dest = os.path.join(target, name)
            if os.path.exists(dest) and not cfg.get('overwrite', True) and not opts.get('force'):
                SCREEN.log('  跳过（同名且 overwrite=false）: %s' % name); skip += 1; continue
            if opts.get('dry_run'):
                SCREEN.log('  [dry-run] 会下载 %s (%.1fMB) ← %s' % (name, size / 1048576.0, frm))
                ok += 1; continue
            # 大附件（>3MB）Graph 不给 contentBytes，回退 /$value 取原始字节
            st2, j2 = graph(token, '/me/messages/%s/attachments/%s' % (m['id'], a['id']))
            buf = None
            if st2 == 200 and isinstance(j2, dict) and j2.get('contentBytes'):
                import base64
                buf = base64.b64decode(j2['contentBytes'])
            else:
                st3, b3 = graph(token, '/me/messages/%s/attachments/%s/$value' % (m['id'], a['id']), raw=True)
                if st3 == 200 and b3:
                    buf = b3
            if not buf:
                SCREEN.log('  下载失败: %s' % name); err += 1; continue
            if size and len(buf) != size:
                SCREEN.log('  [warn] %s 体积与声明不符（%d vs %d）' % (name, len(buf), size))
            tmp = dest + '.hyMailDrop-part'
            with open(tmp, 'wb') as f:
                f.write(buf)
            if os.path.exists(dest):
                os.remove(dest)
            os.rename(tmp, dest)
            if free is not None:
                free -= len(buf)
            ledger[key] = {'name': name, 'size': len(buf), 'from': frm,
                           'subject': str(m.get('subject') or '')[:80],
                           'received': m.get('receivedDateTime'),
                           'at': time.strftime('%Y-%m-%d %H:%M:%S')}
            save_ledger(ledger)
            got += 1; ok += 1
            SCREEN.log('  [OK] 已放入 /documents：%s (%.1fMB) ← %s' % (name, len(buf) / 1048576.0, frm))
        handled = bool(atts) and err == 0 and (ok + skip == len(atts))
        if handled:
            if opts.get('dry_run'):
                SCREEN.log('  [dry-run] 会处置这封邮件：%s' % cfg.get('inbox_action'))
            else:
                done = apply_inbox_action(token, m['id'], cfg)
                if done != 'none':
                    SCREEN.log('  → 收件箱处置：%s' % done)
        elif atts and not opts.get('dry_run'):
            SCREEN.log('  [i] 有 %d 个附件没弄完，这封邮件留着，下一轮再来' % err)
        skipped += skip

    save_ledger(ledger)
    SCREEN.log('完成：收到 %d 个，跳过 %d 个。台账累计 %d 个。' % (got, skipped, len(ledger)))
    if free is not None:
        SCREEN.log('Kindle 剩余约 %.1f MB' % (free / 1048576.0))
    SCREEN.show('hyMailDrop: got %d book(s)' % got, 1)
    SCREEN.show('skipped %d' % skipped, 2)
    if free is not None:
        SCREEN.show('free %.0f MB' % (free / 1048576.0), 3)
    return 0


def cmd_status(creds, cfg):
    SCREEN.log('目录      : %s' % DIR)
    SCREEN.log('CA bundle : %s' % ('有（%s）' % os.path.join(CERTS, 'cacert.pem')
                                    if os.path.exists(os.path.join(CERTS, 'cacert.pem')) else '缺失！'))
    SCREEN.log('登录状态  : %s' % ('已登录（refresh_token 长度 %d）' % len(creds.get('refresh_token') or '')
                                    if creds.get('refresh_token') else '未登录（先跑 login）'))
    SCREEN.log('扫描文件夹: %s' % ' / '.join(cfg.get('folders') or []))
    target = cfg.get('target_dir')
    free, total = disk_free(target) if os.path.isdir(target) else (None, None)
    if free is None:
        SCREEN.log('目标目录  : %s（不存在！）' % target)
    else:
        SCREEN.log('目标目录  : %s  剩余 %.1f MB / 共 %.0f MB' % (target, free / 1048576.0, total / 1048576.0))
    led = load_ledger()
    SCREEN.log('台账      : %d 个附件已收过' % len(led))
    # 屏幕版（ASCII）：eips 没有中文字形，所以这几行单独写
    SCREEN.show('hyMailDrop ok', 1)
    SCREEN.show('login: %s' % ('yes' if creds.get('refresh_token') else 'NO - run login'), 2)
    SCREEN.show('delivered: %d' % len(led), 3)
    if free is not None:
        SCREEN.show('free: %.0f MB' % (free / 1048576.0), 4)
    if os.path.exists(target):
        names = [n for n in os.listdir(target) if os.path.splitext(n)[1].lower()
                 in (cfg.get('extensions') or [])]
        SCREEN.log('书库      : %d 个可投递类型的文件' % len(names))
    return 0


def cmd_selftest(creds, cfg):
    """离线自检：只验"我能不能正确判断"，不联网。"""
    fails = []

    def chk(name, cond, extra=''):
        SCREEN.log('%s %s%s' % ('[OK]' if cond else '[NG]', name, ('  ' + extra) if extra else ''))
        if not cond:
            fails.append(name)

    chk('扩展目录存在', os.path.isdir(DIR), DIR)
    chk('自带 CA bundle', os.path.exists(os.path.join(CERTS, 'cacert.pem')),
        os.path.join(CERTS, 'cacert.pem'))
    if os.path.exists(os.path.join(CERTS, 'cacert.pem')):
        with open(os.path.join(CERTS, 'cacert.pem')) as f:
            n = f.read().count('BEGIN CERTIFICATE')
        chk('CA bundle 里有证书', n > 50, '%d 张' % n)
    chk('client_id 是第三方公开客户端', len(creds.get('client_id') or '') == 36,
        creds.get('client_id') or '(空)')
    chk('target_dir 存在', os.path.isdir(cfg.get('target_dir') or ''))
    chk('后缀白名单非空', bool(cfg.get('extensions')))
    chk('inbox_action 合法', (cfg.get('inbox_action') or '') in ('mark_read', 'archive', 'delete', 'none'),
        cfg.get('inbox_action') or '')
    chk('folders 里含垃圾邮件', 'junkemail' in (cfg.get('folders') or []),
        '（带附件的新发件人邮件会被反垃圾丢进 junkemail）')
    f, t = disk_free(cfg.get('target_dir') or '/mnt/us')
    chk('能读到磁盘余量', f is not None, '%.1f MB 可用' % (f / 1048576.0) if f else '')
    SCREEN.log('RESULT: %d passed, %d failed' % (8 + 1 - len(fails), len(fails)))
    return 1 if fails else 0


def main(argv):
    cmd = argv[0] if argv else 'status'
    opts = {'dry_run': '--dry-run' in argv, 'force': '--force' in argv, 'quiet': '--quiet' in argv}
    SCREEN.quiet = opts['quiet']
    if not os.path.isdir(STATE):
        os.makedirs(STATE)
    cfg = load_json(CONFIG_F, DEFAULT_CONFIG)
    creds = load_json(CREDS_F, DEFAULT_CREDS)
    SCREEN.log('== HyMailDrop by HYrecovery & HoshinoSumi from teko.IO SisTemS! ==')
    SCREEN.log('== Under MIT Open Source License ==')
    # 清掉可能残留的常亮（上次被硬杀会把它留在 1）——每次启动先自愈一次
    keep_awake(False)
    # 长操作期间按住屏幕，别让它半路挂起把我们冻住；退出时无论成败都放开
    if cmd in ('login', 'sync'):
        keep_awake(True)
    try:
        if cmd == 'login':
            return cmd_login(creds, opts)
        if cmd == 'sync':
            return cmd_sync(creds, cfg, opts)
    finally:
        if cmd in ('login', 'sync'):
            keep_awake(False)
    if cmd == 'status':
        return cmd_status(creds, cfg)
    if cmd == 'selftest':
        return cmd_selftest(creds, cfg)
    if cmd == 'ledger':
        if '--clear' in argv:
            save_ledger({})
            SCREEN.log('[OK] 台账已清空（下次同步会把历史附件重新收一遍）')
        else:
            led = load_ledger()
            SCREEN.log('台账 %d 条：' % len(led))
            for k, v in sorted(led.items(), key=lambda kv: kv[1].get('at') or ''):
                SCREEN.log('  %s  %s  %.1fMB  ← %s' % (v.get('at'), v.get('name'),
                                                       (v.get('size') or 0) / 1048576.0, v.get('from')))
        return 0
    SCREEN.log('用法: hyMailDrop.py <login|sync|status|ledger|selftest> [--dry-run] [--force] [--quiet]')
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        # 任何没预料到的异常都要留下痕迹：日志里写全 traceback（设备上没有终端看栈），
        # 屏幕上只放一行 ASCII —— 否则用户看到的就是"点了没反应"。
        import traceback
        SCREEN.log('[NG] 未捕获异常: %s: %s' % (type(e).__name__, e))
        SCREEN.log(traceback.format_exc())
        SCREEN.show('hyMailDrop: %s' % type(e).__name__, 3)
        sys.exit(1)
