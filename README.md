# hyMailDrop

```
== HyMailDrop by HYrecovery & HoshinoSumi from teko.IO SisTemS! ==
== Under MIT Open Source License ==
```

**Mail a book to your Kindle — without Amazon's send-to-kindle, without a cloud service, and
without a computer in the loop.** hyMailDrop is a KUAL extension that runs *on the Kindle*: it
signs in to your own Outlook mailbox, finds the attachments you mailed yourself, and drops them
straight into `/documents`.

After the one-time login, the Kindle needs nothing else. No PC, no phone, no daemon on another
machine, no third-party server.

> ### Scope
> This is **not** part of [hyKBridge](https://github.com/fengye1003/hyKBridge), and it does not
> depend on it **at runtime**. hyKBridge is a base plugin (remote shell and device operations);
> hyMailDrop is an application that happens to *borrow* it — only for the install step, and only
> if you have it. Delete hyKBridge and hyMailDrop keeps working; the dependency never goes the
> other way.

## Why it lives on the device

The obvious design is a program on your PC that checks the mailbox and pushes files to the
Kindle. That design has a permanent flaw: **a suspended Kindle has no network stack**, so
something still has to be listening on the device — a bridge, a File Browser, a USB cable. You
end up depending on a second component whose only job is to be reachable.

Putting the mail client on the Kindle removes that component entirely. It also turns out to be
possible, which was not obvious: the device's Python 3.9 has no CA bundle of its own
(`default verify paths: None`, `/etc/ssl/certs` holds 3 entries), so TLS verification fails out
of the box. hyMailDrop simply **ships a CA bundle** (`certs/cacert.pem`, the Mozilla roots) and
points `ssl` at it. Measured on a real PW3 (2026-10-01): DNS + TLS + HTTP all work —
`login.microsoftonline.com` answers 200, `graph.microsoft.com` answers 401 for an unauthenticated
request, which is correct.

**Never** does it disable verification. Skipping certificate checks in an OAuth client is how you
hand your mailbox to whoever is on the network.

## Install

Two ways. You do **not** need a USB cable for either of the interesting ones.

**1. Forge-style install over the LAN (no USB).** If you already have hyKBridge paired, this
pushes the whole extension to the device and verifies every file:

```bash
node host/install.mjs device --as hyMailDrop
# [i] 设备在线 → 直连安装
# [OK] 14 个文件全部送达并逐文件 sha256 校验一致
```

It verifies each file's sha256 against the device **after** uploading, and refuses to finish if
anything mismatches — a half-installed extension is worse than none. If the device is asleep it
queues the files through hyKBridge's pull channel instead, and the device installs itself on its
next wake.

Why this matters beyond convenience: a Kindle plugged into USB is in **mass-storage mode**, and
KUAL is not running at all while it is. The usual "copy → eject → unplug → restart → open KUAL"
dance exists only because there was no other channel. Now there is one.

**2. By hand (USB).** Copy this repository's `device/` directory to
`/mnt/us/extensions/hyMailDrop/` on the Kindle (root of the user partition), then eject and
restart. Same result, more walking.

## First run

On the Kindle: **KUAL → hyMailDrop → 1. Login Outlook**.

The Kindle cannot show a browser, so it uses the OAuth **device code** flow: the code and the URL
appear on the e-ink screen (and in `state/login.log`). Open `https://login.microsoft.com/device`
on your phone or PC, type the code, sign in, consent once. The refresh token is then stored on the
device, and you are done forever.

> The e-ink screen has **no CJK glyphs** on this device — `eips` prints
> `character "?" not available` for Chinese. Everything written to the screen is therefore ASCII
> by design; the log file is UTF-8 and stays fully Chinese.

Then: **KUAL → hyMailDrop → 2. Sync now**. Attachments whose extension is in the allow-list land
in `/documents`, and the Kindle's library picks them up like any other book.

## Menu

| Item | What it does |
|---|---|
| 1. Login Outlook | Device-code login; code on screen, approve in a browser |
| 2. Sync now | One pass: read the mailbox, fetch new attachments into `/documents` |
| Auto-sync: ON (15 min) | Re-sync every 15 min **while the device is awake** (see below) |
| Auto-sync: OFF | Stop that loop |
| Show status | Login state, free space, how many files delivered |
| Show log | Last 10 log lines on screen, full log on disk |
| Forget delivered books | Clear the ledger (next sync re-fetches history) |

Everything is also a command line, for scripting or for driving it over a bridge:

```bash
python3 bin/hyMailDrop.py login
python3 bin/hyMailDrop.py sync [--dry-run] [--force] [--quiet]
python3 bin/hyMailDrop.py status
python3 bin/hyMailDrop.py ledger [--clear]
python3 bin/hyMailDrop.py selftest      # offline checks, no network
```

## Scheduling, honestly

A suspended device cannot fetch mail. There is no way around that, so hyMailDrop does not pretend
otherwise. Three real options:

1. **Tap "Sync now"** when you pick the device up. Simple, always works.
2. **Auto-sync while awake** (the menu item): it re-checks every 15 minutes, but only while the
   device is already awake. On a device that is in your hands daily, this covers most of the use.
3. **Let a wake agent call it.** If something already wakes your Kindle on a schedule (hyKBridge's
   Pulse, an alarm script, anything), have it run `bin/sync.sh` on each wake — hyMailDrop does not
   care who woke the device, and needs no knowledge of it.

While a login or a sync is running, hyMailDrop holds the screen on (`preventScreenSaver`) so the
device cannot suspend halfway through a download — and clears it on exit, and again at every
startup, so a hard kill cannot leave your battery held awake.

## Configuration

`device/config.json` on the Kindle (created on first run, edited in place — no reinstall):

| Key | Default | Meaning |
|---|---|---|
| `folders` | `["inbox","junkemail"]` | Which folders to scan. **`junkemail` is not optional in practice** — mail from a new sender with a book attached gets filed as junk (measured: 100%) |
| `extensions` | `.mobi .azw .azw3 .azw4 .prc .pobi .epub .txt .pdf` | What counts as a book |
| `target_dir` | `/mnt/us/documents` | Where books land |
| `max_attachment_mb` | `50` | Bigger than this is skipped |
| `free_space_margin_mb` | `60` | Stop delivering when free space would drop below this |
| `max_messages_per_run` | `20` | Messages examined per folder per sync |
| `overwrite` | `true` | Same name on the device ⇒ overwrite (your original requirement) |
| `inbox_action` | `mark_read` | After a message is fully handled: `mark_read` / `archive` / `delete` / `none` |
| `inbox_warn_count` | `200` | Warn when the inbox is this full |
| `from_filter` | `[]` | If non-empty, only these senders |

`device/creds.json` holds `client_id` / `tenant` / `refresh_token`. The refresh token **is** your
mailbox credential: it is gitignored, written `0600`, and never printed (only its length is).

## Two capacities, as asked

* **Inbox:** the count is reported every sync and warns at `inbox_warn_count`. Space is actually
  reclaimed by `inbox_action` — and only for a message whose attachments **all** reached a
  definite outcome (delivered, or deliberately skipped). Anything with a download error stays put
  and is retried next time. A message is never archived or deleted while something in it is still
  unfinished.
* **Disk:** free space is checked before each file, and delivery stops at
  `free_space_margin_mb`. Nothing is written when it would not fit.

## Measured, not assumed

Everything below was observed on a real jailbroken Paperwhite 3 (2026-10-01), not inferred:

* Device-side HTTPS works: `python 3.9.8`, `OpenSSL 1.1.1l`, `login.microsoftonline.com` → 200,
  `graph.microsoft.com` → 401 (correct without a token).
* The device Python has **no CA bundle** ⇒ shipping `certs/cacert.pem` is required, not decorative
  (121 roots in the bundle that ships here).
* `eips` cannot draw CJK: it reports `paint_char> character "?" not available` and leaves blanks.
* The whole extension is 14 files / ~216 KB, installed over WiFi and verified per-file by sha256.
* Offline self-test on the device: `9 passed, 0 failed`.

Two Graph quirks the client works around (both cost real debugging time):

* `$filter=hasAttachments eq true` **silently returns 0 messages** on a folder-scoped query, while
  the same message is visible via `/me/messages` ⇒ filter client-side instead.
* Attachments larger than ~3 MB come back **without** `contentBytes` ⇒ fall back to
  `GET /me/messages/{id}/attachments/{aid}/$value` for the raw bytes.

## Known limits

* **Covers get eaten while the device is online.** A Kindle connected to WiFi refreshes its
  library metadata on its own, and it replaces sideloaded books' covers with a 961-byte
  "no image available" placeholder (measured: 5 books on the test device). hyMailDrop never
  touches metadata -- it only writes files into `/documents` -- but you will likely meet this.
  Repair it with **[bookfere/BookFere-Tools](https://github.com/bookfere/BookFere-Tools)** and
  its *Fix Cover* (a separate project, no relation to this one). Handy rule of thumb when
  hunting bad covers: **a thumbnail under 2000 bytes is broken**.
* **One mailbox, one device.** No multi-account support.
* **No `referenceAttachment`** (OneDrive share links) — only real file attachments.
* **Plain attachments only**: no HTML "daily news" generation yet. The plumbing (a rendered page
  dropped into `/documents`) is the obvious next step.
* Login needs a browser somewhere — it does not have to be the same machine, but it does have to
  be a device with a browser and the Kindle's screen in view.
* Jailbroken Kindle with KUAL and Python 3 required. Tested only on PW3.

## Layout

```
device/config.xml          KUAL extension manifest
device/menu.json           KUAL menu
device/bin/hyMailDrop.py   the client: device-code login, Graph, delivery, capacity
device/bin/*.sh            menu entry points (login / sync / status / log / auto-sync)
device/certs/cacert.pem    Mozilla CA roots (the device has none of its own)
host/install.mjs           forge-style installer: push over the LAN via hyKBridge, verify sha256
```

## Authors

Written by **HoshinoSumi (星澄)** — an AI assistant, and the personal agent of the
[fengye1003](https://github.com/fengye1003) (HYrecovery) account. The code, the on-device testing
and this document were produced by that account's agent, then reviewed by its owner.

Test device: the same owner's jailbroken Kindle Paperwhite 3.

## License

MIT — see [LICENSE](LICENSE). The bundled CA bundle in `device/certs/cacert.pem` is the Mozilla
CA certificate bundle (via <https://curl.se/ca/cacert.pem>), distributed under the Mozilla Public
License 2.0.

*中文版: [README.chs.md](README.chs.md)*
