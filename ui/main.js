'use strict'
// Interfata ARAM Mayhem Helper: panoul, insignele de pe carduri, tooltip-ul si
// raportul de bug. Logica ramane in motorul Python (../app.py), pornit ca proces
// copil: el scrie starea pe stdout (JSON pe linie), noi ii trimitem comenzi pe stdin.
//
// Motorul da coordonate in pixeli fizici; ferestrele Electron lucreaza in DIP.
// Conversia se face per monitor (screenToDipRect), deci pe un setup 4K 150% +
// 1080p 100% panoul are aceeasi marime vizuala pe ambele ecrane.

const { app, BrowserWindow, ipcMain, screen, protocol, net, globalShortcut } = require('electron')
const path = require('node:path')
const fs = require('node:fs')
const { spawn } = require('node:child_process')
const { autoUpdater } = require('electron-updater')
const { pathToFileURL } = require('node:url')

const HOTKEY = 'Control+Alt+Z'
const BASE_W = 372        // latimea panoului in px CSS; zoom-ul o potriveste pe golul din HUD
const IDLE_ZOOM = 1.25    // in afara meciului panoul nu e strans intr-un gol
const ZOOM = [0.55, 1.3]
const MAX_H = 620         // px CSS: plafonul in afara HUD-ului
const MOVED_MAXH = 0.31   // fractie din inaltimea jocului cand l-ai scos din gol
const CARD_1080 = 378     // distanta dintre cardurile de augment la 1080p: scara insignelor

const ROOT = path.join(__dirname, '..')
// setari, date sincronizate, jurnal: in %APPDATA%, nu langa exe (un update il reinstaleaza)
const HOME = app.getPath('userData')
const ICON = app.isPackaged ? path.join(process.resourcesPath, 'icon.ico') : path.join(ROOT, 'icon.ico')
const FONTS_DIR = path.join(app.getPath('userData'), 'fonts')
// Fonturile HUD-ului (Beaufort, Spiegel) nu le putem livra in exe: le luam o data,
// din fisierele jocului publicate de CommunityDragon. Fara internet: fonturi de sistem.
const FONTS_URL = 'https://raw.communitydragon.org/latest/game/assets/ux/fonts/'
const FONT_FILES = ['beaufortforlol-bold.otf', 'spiegel-regular.otf', 'spiegel-semibold.otf', 'spiegel-bold.otf']

const clamp = (v, a, b) => Math.max(a, Math.min(b, v))

// --- setari ---------------------------------------------------------------------

const SETTINGS = path.join(HOME, 'settings.json')
let settings = {}
try { settings = JSON.parse(fs.readFileSync(SETTINGS, 'utf8')) } catch {}
function save(key, value) {
  settings[key] = value
  try { fs.writeFileSync(SETTINGS, JSON.stringify(settings, null, 1)) } catch {}
}

// --- motorul ------------------------------------------------------------------

let engine = null, quitting = false, crashes = 0, nextId = 1
let state = null, hello = null, iconsDir = null, engineError = null
const pending = new Map()

function startEngine() {
  const python = path.join(ROOT, '.venv', 'Scripts', 'python.exe')
  const [cmd, args] = app.isPackaged
    ? [path.join(process.resourcesPath, 'engine', 'aram-engine.exe'), []]
    : process.env.ARAM_MOCK       // test: stare redata dintr-un fisier (ui/test/mock_engine.py)
      ? [python, [path.join(__dirname, 'test', 'mock_engine.py'), process.env.ARAM_MOCK]]
      : [python, [path.join(ROOT, 'app.py')]]
  if (process.argv.includes('--no-update')) args.push('--no-update')
  const env = { ...process.env, ARAM_UI_PID: String(process.pid), ARAM_HOME: HOME,
    ARAM_VERSION: app.getVersion(), PYTHONUNBUFFERED: '1' }
  const child = spawn(cmd, args, { env, windowsHide: true, cwd: app.isPackaged ? HOME : ROOT })
  engine = child
  let buf = '', err = ''
  child.stdout.setEncoding('utf8')
  child.stdout.on('data', chunk => {
    buf += chunk
    let i
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim()
      buf = buf.slice(i + 1)
      if (line) onEngine(line)
    }
  })
  child.stderr.on('data', d => { err = (err + d).slice(-8000) })
  child.on('error', e => { engineError = `motorul nu porneste: ${e.code || e.message}`; pushState() })
  child.on('exit', code => {
    if (engine === child) engine = null
    if (quitting) return
    try { fs.writeFileSync(path.join(HOME, 'eroare.log'), `motorul s-a oprit (cod ${code})\n${err}`) } catch {}
    if (++crashes <= 3) setTimeout(startEngine, 1500 * crashes)
    else { engineError = 'motorul s-a oprit, detalii in eroare.log'; pushState() }
  })
}

function onEngine(line) {
  let msg
  try { msg = JSON.parse(line) } catch { return }
  if (msg.t === 'state') {
    state = msg
    engineError = null
    pushState()
    place()
    warmBadges(state.view)
    showBadges()
    autoRestart()
  } else if (msg.t === 'hello') {
    hello = msg
    iconsDir = msg.icons
  } else if (msg.t === 'reply' && pending.has(msg.id)) {
    pending.get(msg.id)(msg)
    pending.delete(msg.id)
  } else if (msg.t === 'error' && msg.text === 'already running') {
    engineError = 'ruleaza deja o alta copie (vezi taskbar-ul sau Task Manager)'
    pushState()
  }
}

function command(msg) {
  if (engine && engine.stdin.writable) engine.stdin.write(JSON.stringify(msg) + '\n')
}

function ask(msg, timeout = 20000) {
  const id = nextId++
  command({ ...msg, id })
  return new Promise(resolve => {
    pending.set(id, resolve)
    setTimeout(() => { if (pending.delete(id)) resolve(null) }, timeout)
  })
}

// --- ferestre ------------------------------------------------------------------

protocol.registerSchemesAsPrivileged([
  { scheme: 'aram', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } },
])

// aram://<fereastra>/<fisier> pentru interfata (gazda diferita = zoom separat per
// fereastra), aram://icons/... pentru iconitele motorului, aram://fonts/...
async function serve(req) {
  const u = new URL(req.url)
  const base = { icons: iconsDir, fonts: FONTS_DIR }[u.hostname] ?? __dirname
  const file = path.resolve(base || '', decodeURIComponent(u.pathname).replace(/^\/+/, ''))
  if (!base || !file.startsWith(path.resolve(base) + path.sep)) return new Response('', { status: 404 })
  try {
    const res = await net.fetch(pathToFileURL(file).toString())
    // fonturile se incarca in mod CORS: fara antet, pagina (alta gazda) le refuza
    if (u.hostname !== 'fonts') return res
    return new Response(res.body, { headers: { 'content-type': 'font/otf', 'access-control-allow-origin': '*' } })
  } catch {
    return new Response('', { status: 404 })
  }
}

const preload = path.join(__dirname, 'preload.js')

function overlay(url, extra = {}) {
  const win = new BrowserWindow({
    show: false, frame: false, transparent: true, resizable: false, maximizable: false,
    minimizable: false, fullscreenable: false, hasShadow: false, skipTaskbar: true, thickFrame: false,
    alwaysOnTop: true, backgroundColor: '#00000000', icon: ICON, title: 'ARAM Mayhem Helper',
    // focusable: false = un click pe panou nu ia focusul jocului (nu iesi din meci)
    focusable: false, width: 10, height: 10,
    webPreferences: { preload, backgroundThrottling: false, spellcheck: false },
    ...extra,
  })
  win.setAlwaysOnTop(true, 'screen-saver')
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  win.webContents.on('will-navigate', e => e.preventDefault())
  win.loadURL(url)
  return win
}

function send(win, channel, data) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, data)
}

function setBounds(win, b) {
  b = { x: Math.round(b.x), y: Math.round(b.y), width: Math.round(b.width), height: Math.round(b.height) }
  const cur = win.getBounds()
  if (cur.x === b.x && cur.y === b.y && cur.width === b.width && cur.height === b.height) return
  win.setBounds(b)
  // mutata pe un monitor cu alta scalare, Windows reface marimea: a doua oara iese exact
  const now = win.getBounds()
  if (now.width !== b.width || now.height !== b.height) win.setBounds(b)
}

// --- panoul si locul lui ------------------------------------------------------------

let panel = null
const dock = { manual: null, phase: null, dragging: false, mode: null }
const ui = { zoom: 0, w: 0, maxH: 0, shrink: false, h: 0, collapsed: false, hotkey: true }

function dip(r) {
  return screen.screenToDipRect(null, { x: r[0], y: r[1], width: r[2] - r[0], height: r[3] - r[1] })
}

// tine fereastra intreaga pe ecranul pe care ai pus-o, fara sa-ti uite pozitia
// (marginile monitorului, nu zona de lucru: peste un joc fullscreen bara de
// activitati nu se vede, iar golul din HUD e chiar jos)
function inside([x, y], w, h) {
  const a = screen.getDisplayNearestPoint({ x: Math.round(x + w / 2), y: Math.round(y + 8) }).bounds
  return { x: clamp(x, a.x, a.x + a.width - w), y: clamp(y, a.y, a.y + a.height - h) }
}

function freeMaxH(zoom, near) {
  const a = screen.getDisplayNearestPoint(near).workArea
  return Math.min(MAX_H * zoom, a.height - 16)
}

// Unde sta panoul: lipit in golul dintre HUD si minimap cand jocul e deschis,
// langa client in champ select, altfel unde l-ai lasat. at(h) da coltul din
// stanga-sus pentru inaltimea h (panoul lipit creste in sus, de la marginea de jos).
function target() {
  const view = state?.view, geo = state?.geo || {}
  if (view === 'in_game' && dock.phase !== 'in_game') dock.manual = settings.away || null   // meci nou
  dock.phase = view
  if (geo.game) {
    const area = dip(geo.game.dock), box = dip(geo.game.box)
    const zoom = clamp(area.width / BASE_W, ...ZOOM)
    if (dock.manual) {
      return { mode: 'moved', w: area.width, zoom, shrink: true, maxH: MOVED_MAXH * box.height,
        at: h => inside(dock.manual, area.width, h) }
    }
    return { mode: 'dock', w: area.width, zoom, shrink: true, maxH: area.height,
      at: h => ({ x: area.x, y: area.y + area.height - h }) }
  }
  const zoom = IDLE_ZOOM, w = Math.round(BASE_W * zoom)
  if (dock.manual) {
    const [x, y] = dock.manual
    return { mode: 'moved', w, zoom, maxH: freeMaxH(zoom, { x, y }), at: h => inside(dock.manual, w, h) }
  }
  if (view === 'champ_select' && geo.client) {
    const c = dip(geo.client.box)
    const a = screen.getDisplayMatching(c).workArea
    // in afara clientului cand monitorul are loc (dreapta, apoi stanga), ca sa nu
    // acopere cartile; altfel in coltul lui din dreapta-jos
    const base = h => a.x + a.width - (c.x + c.width) >= w + 8 ? { x: c.x + c.width + 8, y: c.y }
      : c.x - a.x >= w + 8 ? { x: c.x - w - 8, y: c.y }
        : { x: c.x + c.width - w - 12, y: c.y + c.height - h - 12 }
    const [ox, oy] = settings.client_offset || [0, 0]
    return { mode: 'client', w, zoom, maxH: freeMaxH(zoom, c), base, H: c.height,
      at: h => { const p = base(h); return inside([p.x + ox * c.height, p.y + oy * c.height], w, h) } }
  }
  const a = screen.getPrimaryDisplay().workArea
  const pos = settings.pos || [a.x + a.width - w - 28, a.y + 64]
  return { mode: 'free', w, zoom, maxH: freeMaxH(zoom, { x: pos[0], y: pos[1] }), at: h => inside(pos, w, h) }
}

function place() {
  if (!panel || dock.dragging) return
  const t = target()
  dock.mode = t.mode
  const zoom = Math.round(t.zoom * 1000) / 1000
  const maxH = Math.round(t.maxH), w = Math.round(t.w)
  if (zoom !== ui.zoom || w !== ui.w || maxH !== ui.maxH || !!t.shrink !== ui.shrink) {
    Object.assign(ui, { zoom, w, maxH, shrink: !!t.shrink })
    send(panel, 'layout', { zoom, w, maxH, shrink: ui.shrink })
  }
  if (!ui.h) return                       // panoul inca nu si-a masurat continutul
  setBounds(panel, { ...t.at(ui.h), width: w, height: ui.h })
  if (!panel.isVisible()) panel.showInactive()
}

// l-ai mutat cu mouse-ul: in meci ramane exact acolo pana la meciul urmator
// (sau mereu, daca l-ai scos de pe ecranul jocului); in champ select tinem
// diferenta fata de client; altfel pozitia libera.
function remember() {
  const b = panel.getBounds(), game = state?.geo?.game
  if (game || dock.manual) {
    dock.manual = [b.x, b.y]
    if (game) {
      const g = dip(game.box), cx = b.x + b.width / 2, cy = b.y + b.height / 2
      const out = !(cx >= g.x && cx < g.x + g.width && cy >= g.y && cy < g.y + g.height)
      save('away', out ? dock.manual : null)
    }
  } else if (dock.mode === 'client') {
    const t = target(), p = t.base(b.height)
    save('client_offset', [+((b.x - p.x) / t.H).toFixed(4), +((b.y - p.y) / t.H).toFixed(4)])
  } else {
    save('pos', [b.x, b.y])
  }
  place()
}

function snapBack() {
  dock.manual = null
  save('away', null)
  place()
}

function pushState() {
  send(panel, 'state', {
    view: state?.view || 'idle', data: state?.data || {}, update,
    counts: hello?.counts || {}, version: app.getVersion(), hotkey: ui.hotkey,
    error: engineError, hotkeyLabel: 'CTRL+ALT+Z',
  })
}

function createPanel() {
  panel = overlay('aram://panel/panel.html')
  panel.on('will-move', () => { dock.dragging = true; hideTip() })
  panel.on('moved', () => { dock.dragging = false; remember() })
  panel.webContents.on('did-finish-load', () => {
    ui.zoom = 0                           // trimite din nou layout-ul
    place()
    pushState()
  })
  panel.on('closed', () => app.quit())
}

// --- insignele de pe carduri ----------------------------------------------------------
// O fereastra mica per insigna, nu una mare peste joc: o fereastra peste tot
// jocul ar bloca click-urile pe carduri. Trei se creeaza cand intri in champ
// select sau in meci, ca oferta sa apara instant; in rest nu tinem memorie ocupata.

const badges = []
let badgeKey = ''

function badgeWin(i) {
  if (!badges[i]) {
    const win = overlay('aram://badge/overlay.html#badge')
    win.ready = new Promise(r => win.webContents.once('did-finish-load', r))
    badges[i] = win
  }
  return badges[i]
}

function warmBadges(view) {
  if (view === 'in_game' || view === 'champ_select') {
    for (let i = 0; i < 3; i++) badgeWin(i)
  } else if (badges.length) {
    badges.splice(0).forEach(w => w.destroy())
    badgeKey = ''
  }
}

function showBadges() {
  const geo = state?.geo || {}
  const list = []
  if (geo.bars) {
    const r = dip(geo.bars.region), col = r.width / 3, k = col / CARD_1080
    const taken = new Set((state.data.taken || []).map(t => t.name))
    const used = new Set()
    geo.bars.items.forEach((a, i) => {
      // coloana cardului pe care a fost citit numele, nu ordinea listei
      let slot = a.slot
      if (![0, 1, 2].includes(slot) || used.has(slot)) slot = [i, 0, 1, 2].find(c => !used.has(c))
      used.add(slot)
      list.push({ tier: a.tier, is_best: a.is_best, name: geo.bars.kind === 'augment' ? a.name : null,
        kind: geo.bars.kind, pick: geo.bars.kind === 'augment' ? a.name : null, taken: taken.has(a.name),
        // deasupra cardului, cu un mic gol: nimic peste iconita sau numele augmentului
        zoom: k, cx: r.x + col * (slot + 0.5), cy: r.y - 6 * k })
    })
  } else if (geo.pins) {
    for (const p of geo.pins) {
      const pt = screen.screenToDipPoint({ x: p.cx, y: p.y })
      list.push({ tier: p.tier, is_best: p.is_best, kind: 'champ', zoom: 1, cx: pt.x, cy: pt.y - 8 })
    }
  }
  const key = JSON.stringify(list)
  if (key === badgeKey) return
  badgeKey = key
  list.forEach((b, i) => {
    const win = badgeWin(i)
    win.badge = b
    win.ready.then(() => send(win, 'badge', b))
  })
  badges.slice(list.length).forEach(w => { w.badge = null; w.hide() })
}

ipcMain.on('badge-size', (e, size) => {
  const win = BrowserWindow.fromWebContents(e.sender), b = win?.badge
  if (!b) return
  const want = { x: b.cx - size.w / 2, y: b.cy - size.h, width: size.w, height: size.h }
  setBounds(win, want)
  // Windows nu lasa ferestre mai joase de ~56 px: surplusul urca deasupra insignei
  // (in aer, nu peste card), iar forma ferestrei ramane doar insigna, ca un click
  // pe langa ea sa ajunga in joc
  const extra = win.getBounds().height - want.height
  if (extra > 0) setBounds(win, { ...want, y: want.y - extra, height: want.height + extra })
  win.setShape(extra > 0 ? [{ x: 0, y: extra, width: want.width, height: want.height }] : [])
  if (!win.isVisible()) win.showInactive()
})

ipcMain.on('badge-pick', (_e, name) => command({ cmd: 'took', name }))

// --- tooltip ------------------------------------------------------------------------

let tip = null, tipSeq = 0, tipAnchor = null

function hideTip() {
  tipSeq++
  tipAnchor = null
  if (tip) tip.hide()
}

ipcMain.on('tip', (_e, t) => {
  if (!tip) {
    tip = overlay('aram://tip/overlay.html#tip')
    tip.ready = new Promise(r => tip.webContents.once('did-finish-load', r))
  }
  const seq = ++tipSeq, b = panel.getBounds(), z = ui.zoom || 1
  tipAnchor = { seq, x: b.x + t.rect.x * z, y: b.y + t.rect.y * z, w: t.rect.w * z, h: t.rect.h * z }
  tip.ready.then(() => send(tip, 'tip', { seq, title: t.title, text: t.text, zoom: z }))
})

ipcMain.on('tip-size', (_e, s) => {
  const a = tipAnchor
  if (!a || s.seq !== a.seq || dock.dragging) return
  const area = screen.getDisplayNearestPoint({ x: Math.round(a.x), y: Math.round(a.y) }).workArea
  let x = a.x + a.w + 8
  if (x + s.w > area.x + area.width) x = a.x - s.w - 8
  const y = clamp(a.y, area.y, area.y + area.height - s.h)
  setBounds(tip, { x: clamp(x, area.x, area.x + area.width - s.w), y, width: s.w, height: s.h })
  tip.showInactive()
})

ipcMain.on('tip-hide', hideTip)

// --- raportul de bug ------------------------------------------------------------------
// Fereastra proprie, pe mijlocul ecranului pe care e panoul, tinuta in ecran si
// mutabila de bara ei. Poate lua focus: are campuri de scris.

let report = null

function openReport() {
  if (report) { report.show(); report.focus(); return }
  report = overlay('aram://report/report.html', { focusable: true, skipTaskbar: false, title: 'Raporteaza un bug' })
  report.on('closed', () => { report = null })
}

ipcMain.handle('report-init', async () => {
  const diag = await ask({ cmd: 'diag' }, 5000)
  return { diag: diag?.text || '(motorul nu a raspuns)', version: app.getVersion() }
})

ipcMain.on('report-size', (_e, s) => {
  if (!report) return
  const a = screen.getDisplayMatching(panel.getBounds()).workArea
  const w = Math.min(s.w, a.width - 16), h = Math.min(s.h, a.height - 16)
  if (!report.isVisible()) {
    setBounds(report, { x: a.x + (a.width - w) / 2, y: a.y + (a.height - h) / 2, width: w, height: h })
    report.show()
    report.focus()
  } else {
    const b = report.getBounds()
    setBounds(report, { ...inside([b.x, b.y], w, h), width: w, height: h })
  }
})

ipcMain.handle('report-send', (_e, r) => ask({ cmd: 'report', desc: String(r.desc || ''),
  email: String(r.email || ''), diag: r.include ? String(r.diag || '') : '(diagnostic omis de utilizator)' }))
ipcMain.on('report-mailto', (_e, r) => command({ cmd: 'mailto', desc: String(r.desc || ''), diag: String(r.diag || '') }))
ipcMain.on('report-close', () => report?.close())

// --- comenzile panoului ---------------------------------------------------------------

ipcMain.on('height', (_e, h) => {
  ui.h = Math.max(1, Math.round(h))
  place()
})

ipcMain.on('cmd', (_e, c) => {
  if (c.cmd === 'close') app.quit()
  else if (c.cmd === 'collapse') toggleCollapse()
  else if (c.cmd === 'snap') snapBack()
  else if (c.cmd === 'report') openReport()
  else if (c.cmd === 'update') update.tag ? restart() : checkUpdate(true)
  else if (c.cmd === 'restart') restart()
  else if (c.cmd === 'drop' || c.cmd === 'took') command({ cmd: c.cmd, name: String(c.name) })
})

ipcMain.handle('fonts', () => FONT_FILES.filter(f => fs.existsSync(path.join(FONTS_DIR, f))))

function toggleCollapse() {
  ui.collapsed = !ui.collapsed
  hideTip()
  send(panel, 'collapsed', ui.collapsed)
}

// --- update-uri -------------------------------------------------------------------------
// Se descarca singure in fundal (doar diferenta) si se instaleaza cand inchizi
// aplicatia. Repornirea pe loc o face installerul, prin shell (parinte: explorer),
// nu un proces de-al nostru care dispare: de asta se plangea Vanguard.

const update = { tag: null, busy: false, why: null, manual: false }

function checkUpdate(manual) {
  if (!app.isPackaged || update.tag || update.busy) return
  Object.assign(update, { busy: manual, why: null, manual })
  pushState()
  autoUpdater.checkForUpdates().catch(() => {})
}

function finishCheck(why) {
  if (update.manual) Object.assign(update, { busy: false, why, manual: false })
  pushState()
}

autoUpdater.autoInstallOnAppQuit = true
autoUpdater.on('update-downloaded', info => {
  Object.assign(update, { tag: 'v' + info.version, busy: false })
  pushState()
})
autoUpdater.on('update-not-available', () => finishCheck('esti la zi'))
autoUpdater.on('error', e => finishCheck('eroare: ' + (e.code || e.name || 'update')))

function restart() {
  if (!update.tag) return
  quitting = true
  autoUpdater.quitAndInstall(true, true)
}

// in afara meciului si a champ select-ului repornim singuri, o data pe versiune
function autoRestart() {
  if (update.tag && state.view === 'idle' && settings.restarted_for !== update.tag) {
    save('restarted_for', update.tag)
    restart()
  }
}

async function ensureFonts() {
  fs.mkdirSync(FONTS_DIR, { recursive: true })
  let added = false
  for (const f of FONT_FILES) {
    const dest = path.join(FONTS_DIR, f)
    if (fs.existsSync(dest)) continue
    try {
      const r = await net.fetch(FONTS_URL + f)
      if (!r.ok) continue
      const data = Buffer.from(await r.arrayBuffer())
      if (data.length > 10000) { fs.writeFileSync(dest + '.part', data); fs.renameSync(dest + '.part', dest); added = true }
    } catch {}
  }
  if (added) BrowserWindow.getAllWindows().forEach(w => send(w, 'fonts-ready'))
}

// --- pornire ----------------------------------------------------------------------------

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.setAppUserModelId('Joltarise.AramMayhemHelper')
  app.whenReady().then(() => {
    protocol.handle('aram', serve)
    startEngine()
    createPanel()
    ui.hotkey = globalShortcut.register(HOTKEY, toggleCollapse)
    screen.on('display-metrics-changed', () => { ui.zoom = 0; place() })
    ensureFonts()
    if (!process.argv.includes('--no-update')) {
      checkUpdate(false)
      setInterval(() => checkUpdate(false), 30 * 60 * 1000)
    }
  })
  app.on('before-quit', () => {
    quitting = true
    command({ cmd: 'quit' })
    engine?.stdin.end()                   // stdin inchis = motorul iese singur
  })
  app.on('window-all-closed', () => app.quit())
  app.on('will-quit', () => globalShortcut.unregisterAll())
}
