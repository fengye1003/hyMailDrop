#!/usr/bin/env node
/*
 * install.mjs -- 把一个 KUAL 扩展装到 Kindle 上，**不用插 USB**。
 *
 * == HyMailDrop by HYrecovery & HoshinoSumi from teko.IO SisTemS! ==
 * == Under MIT Open Source License ==
 *
 * 为什么需要它：KUAL 扩展平时只能靠插 USB 装 —— 而 Kindle 一插上 USB 就进 U 盘模式，
 * KUAL 整个不可用，于是"拷贝→弹出→重启→进 KUAL"这一套每次都要重来。既然设备已经在
 * 局域网上、而且已经有一个能干活的通道，那就让它自己把包装上。
 *
 * 这就是"forge 式安装"：给出一个目录，它负责**送达 + 就位 + 校验**三件事。
 *
 *   node host/install.mjs <本地扩展目录> [--as <扩展名>] [选项]
 *
 * 选项：
 *   --as <名字>        设备上的扩展目录名（默认取本地目录名）
 *   --target <路径>    设备上的目标根（默认 /mnt/us/extensions）
 *   --bridge <路径>    hyKBridge 仓库的位置（默认找 $HYKBRIDGE_HOME、../hyKBridge、./hyKBridge）
 *   --kindle <ip>      设备地址（默认用 hyKBridge 记住的那个）
 *   --via <auto|direct|queue>   默认 auto：设备醒着直连装，睡着就排队等它自己来取
 *   --dry              只列会做什么
 *
 * ★ 依赖方向（重要）：本脚本**依赖 hyKBridge**（安装期），而 **hyMailDrop 本体零依赖** ——
 *   装完之后，设备上的插件跟 hyKBridge 一点关系都没有，删掉 bridge 它照样工作。
 *   这正是"基插件 / 上位应用"分层的用法：应用可以借用基插件的能力来安装自己，
 *   但运行时不该被它绑住。
 *
 * 纪律：每一步都要**结构性验证**（发上去的 sha256 与设备上算出来的必须一致），
 *      不一致就报错停下 —— 装坏一个扩展比装不上更糟。
 */
import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const flag = (n, d) => { const i = argv.indexOf('--' + n); return i < 0 ? d : (argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : true); };
const has = (n) => argv.includes('--' + n);
const SRC = argv.find((a) => !a.startsWith('--') && argv[argv.indexOf(a) - 1] !== '--as' && argv[argv.indexOf(a) - 1] !== '--target' && argv[argv.indexOf(a) - 1] !== '--bridge' && argv[argv.indexOf(a) - 1] !== '--kindle' && argv[argv.indexOf(a) - 1] !== '--via');

if (!SRC || !fs.existsSync(SRC)) {
  console.log('用法: node install.mjs <本地扩展目录> [--as 名字] [--target /mnt/us/extensions] [--bridge 路径] [--via auto|direct|queue] [--dry]');
  process.exit(2);
}
const SRCABS = path.resolve(SRC);
const NAME = String(flag('as', path.basename(SRCABS)));
const TARGET_ROOT = String(flag('target', '/mnt/us/extensions'));
const REMOTE = `${TARGET_ROOT}/${NAME}`;
const VIA = String(flag('via', 'auto'));
const DRY = has('dry');
const KINDLE = flag('kindle', null);

// ── 找 hyKBridge ────────────────────────────────────────────────────
function findBridge() {
  const cands = [];
  if (process.env.HYKBRIDGE_HOME) cands.push(process.env.HYKBRIDGE_HOME);
  const b = flag('bridge', null);
  if (b) cands.push(String(b));
  cands.push(path.join(SRCABS, '..', '..', 'hyKBridge'), path.join(HERE, '..', '..', 'hyKBridge'), path.join(HERE, '..', 'hyKBridge'));
  for (const c of cands) {
    const cli = path.join(c, 'host', 'hyKBridge.mjs');
    if (fs.existsSync(cli)) return { home: path.resolve(c), cli: path.resolve(cli) };
  }
  return null;
}
const BRIDGE = findBridge();

// ── 打包：只带走该带的东西 ─────────────────────────────────────────
// 排除 runtime state 与内部笔记：装到设备上的应该是"产品"，不是工作台。
const SKIP_DIRS = new Set(['state', 'node_modules', '.git', '__pycache__']);
const SKIP_FILES = new Set(['CHECKPOINT.md', '.DS_Store']);
const SKIP_EXT = new Set(['.log', '.pyc', '.tmp', '.part']);
function collect(root, rel = '') {
  const out = [];
  const abs = path.join(root, rel);
  for (const e of fs.readdirSync(abs, { withFileTypes: true })) {
    const r = rel ? path.join(rel, e.name) : e.name;
    if (e.isDirectory()) {
      if (SKIP_DIRS.has(e.name)) continue;
      out.push(...collect(root, r));
    } else {
      if (SKIP_FILES.has(e.name) || SKIP_EXT.has(path.extname(e.name))) continue;
      const buf = fs.readFileSync(path.join(root, r));
      // 可执行判据：内容以 #! 开头（Windows 上 stat 不反映 exec 位）
      const exec = buf.length > 2 && buf[0] === 0x23 && buf[1] === 0x21;
      out.push({ rel: r.replace(/\\/g, '/'), buf, mode: exec ? 0o755 : 0o644,
                 sha: crypto.createHash('sha256').update(buf).digest('hex') });
    }
  }
  return out;
}
const files = collect(SRCABS);
const total = files.reduce((s, f) => s + f.buf.length, 0);

// ── 调 hyKBridge CLI ────────────────────────────────────────────────
function bridge(args, { quiet = true } = {}) {
  return new Promise((resolve) => {
    const p = spawn(process.execPath, [BRIDGE.cli, ...args], { stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, HYKBRIDGE_QUIET: '1' } });
    let out = '', err = '';
    p.stdout.on('data', (d) => { out += d; });
    p.stderr.on('data', (d) => { err += d; });
    p.on('close', (code) => {
      if (!quiet && err.trim()) process.stderr.write(err);
      const json = out.trim().startsWith('{') ? (() => { try { return JSON.parse(out.trim()); } catch { return null; } })() : null;
      resolve({ code, out, err, json });
    });
  });
}
const base = KINDLE ? ['--kindle', String(KINDLE)] : [];
const exec = (cmd) => bridge(['device', 'exec', cmd, '--json', ...base]);

function fmt(n) { return n < 1024 ? n + 'B' : (n / 1024).toFixed(1) + 'K'; }

console.log('== HyMailDrop by HYrecovery & HoshinoSumi from teko.IO SisTemS! ==');
console.log('== Under MIT Open Source License ==');
console.log(`[i] 源目录 : ${SRCABS}`);
console.log(`[i] 目标   : ${REMOTE}`);
console.log(`[i] 文件   : ${files.length} 个 / ${fmt(total)}`);
if (!BRIDGE) {
  console.log('[NG] 找不到 hyKBridge。安装期需要它（把包送到设备上）；用 --bridge <路径> 指定，');
  console.log('     或设 HYKBRIDGE_HOME。注意：这只影响**安装**，插件本体在设备上是零依赖的。');
  process.exit(3);
}
console.log(`[i] bridge : ${BRIDGE.home}`);
if (DRY) {
  for (const f of files) console.log(`    ${f.mode === 0o755 ? '755' : '644'}  ${String(f.buf.length).padStart(8)}  ${f.rel}`);
  console.log('[i] --dry：未联网');
  process.exit(0);
}

// ── 选路：设备醒着就直连，睡着就排队 ────────────────────────────────
let mode = VIA;
if (mode === 'auto') {
  const ping = await bridge(['device', 'ping', '--json', ...base]);
  mode = ping.code === 0 ? 'direct' : 'queue';
  console.log(`[i] 设备${ping.code === 0 ? '在线 → 直连安装' : '不可达（多半在睡觉）→ 排队安装（它醒来自己取）'}`);
}

async function directInstall() {
  const mk = await exec(`mkdir -p ${REMOTE}`);
  if (mk.code !== 0) { console.log('[NG] 无法在设备上建目录：' + (mk.json?.detail || mk.err || mk.out).slice(0, 160)); return false; }
  for (const f of files) {
    const remote = `${REMOTE}/${f.rel}`;
    const dir = path.posix.dirname(remote);
    if (dir !== REMOTE) await exec(`mkdir -p ${dir}`);
    const put = await bridge(['device', 'put', path.join(SRCABS, f.rel), remote, '--write', '--json', ...base]);
    if (put.code !== 0) { console.log(`[NG] 上传失败 ${f.rel}：${(put.json?.detail || put.err || put.out).slice(0, 160)}`); return false; }
  }
  // 权限 + 结构性验证（发上去的 sha256 必须与设备上算出来的一致）
  const chmods = files.filter((f) => f.mode === 0o755).map((f) => f.rel).join(' ');
  await exec(`cd ${REMOTE} && chmod 755 ${chmods} 2>/dev/null; chmod -R a+r . 2>/dev/null; echo done`);
  const list = files.map((f) => f.rel).join(' ');
  const chk = await exec(`cd ${REMOTE} && sha256sum ${list} 2>/dev/null`);
  const got = new Map();
  for (const line of String(chk.json?.data?.stdout || '').split('\n')) {
    const m = /^([0-9a-f]{64})\s+(.+)$/.exec(line.trim());
    if (m) got.set(m[2].trim(), m[1]);
  }
  let bad = 0;
  for (const f of files) {
    if (got.get(f.rel) !== f.sha) { console.log(`[NG] 校验不一致: ${f.rel}`); bad++; }
  }
  if (bad) { console.log(`[NG] ${bad} 个文件与本地不一致 —— 安装中止（别用半装好的扩展）`); return false; }
  console.log(`[OK] ${files.length} 个文件全部送达并逐文件 sha256 校验一致`);
  return true;
}

async function queueInstall() {
  // 设备睡着时的路：文件经"拉取通道"排队进 /documents（带 __ 前缀编码子路径，避免扁平化丢目录），
  // 再排一条命令让设备醒来后把它们搬到扩展目录并设权限。
  const tag = 'hmd-' + crypto.randomBytes(3).toString('hex');
  const jobs = [];
  for (const f of files) {
    const flat = `${tag}__${f.rel.replace(/\//g, '__')}`;
    const r = await bridge(['push', path.join(SRCABS, f.rel), '--as', flat, ...base]);
    if (r.code !== 0) { console.log(`[NG] 入队失败 ${f.rel}：${(r.err || r.out).slice(0, 160)}`); return false; }
    jobs.push(flat);
  }
  const execls = files.filter((f) => f.mode === 0o755).map((f) => `${tag}__${f.rel.replace(/\//g, '__')}`).join(' ');
  const script = [
    `set -e`,
    `mkdir -p ${REMOTE}`,
    `cd /mnt/us/documents`,
    `for f in ${tag}__*; do`,
    `  t=${REMOTE}/$(echo "$f" | sed "s/^${tag}__//; s/__/\\//g")`,
    `  mkdir -p "$(dirname "$t")"`,
    `  mv "$f" "$t"`,
    `done`,
    `cd ${REMOTE} && chmod 755 ${execls.replace(new RegExp(tag + '__', 'g'), '').replace(/__/g, '/')} 2>/dev/null || true`,
    `echo INSTALLED ${NAME}`,
  ].join('\n');
  const r = await bridge(['exec', script, ...base]);
  if (r.code !== 0) { console.log(`[NG] 入队安装命令失败：${(r.err || r.out).slice(0, 160)}`); return false; }
  console.log(`[OK] ${files.length} 个文件已入队，安装任务已排好`);
  console.log('[i] 设备下次醒来会自己取走并装好 —— 不用插 USB，也不用守着它');
  return true;
}

const ok = mode === 'queue' ? await queueInstall() : await directInstall();
if (!ok) process.exit(1);
console.log('');
console.log('[OK] 装好了。到 Kindle 上打开 KUAL，菜单里会出现 hyMailDrop。');
console.log('     第一次用先点「1. Login Outlook」—— 验证码会显示在 Kindle 屏幕上，');
console.log('     你用手机或电脑打开 microsoft.com/devicelogin 输一次就行。');
