'use strict'
// Panoul: deseneaza starea primita de la motor si isi masoara inaltimea. Locul
// si latimea le decide procesul principal (layout); aici alegem doar zoom-ul
// la care incape continutul in golul dintre HUD si minimap.

const ZOOM_MIN = 0.55
const $ = id => document.getElementById(id)
const panel = $('panel'), body = $('body')

let S = null           // ultima stare
let layout = null      // { zoom, w, maxH, shrink } de la procesul principal
let collapsed = false
let augOn = false      // augmentele bune ale campionului, cand OCR-ul nu vede oferta
let shown = ''         // amprenta a ce e desenat acum
let shownView = ''
let verNote = null     // raspunsul scurt dupa o cautare de update ("ESTI LA ZI")
let wasBusy = false

// --- tooltip: fereastra separata, ca sa poata iesi din panou ------------------

function tip(el, title, text) {
  el.addEventListener('mouseenter', () => {
    const r = el.getBoundingClientRect()
    api.send('tip', { title, text: text || null, rect: { x: r.left, y: r.top, w: r.width, h: r.height } })
  })
  el.addEventListener('mouseleave', () => api.send('tip-hide'))
  return el
}

// --- caramizile ------------------------------------------------------------------

const sec = text => h('div.sec', { text })
const note = (text, cls = '') => h('div.note' + (cls ? '.' + cls : ''), { text })

function icon(path, alt, cls = '') {
  if (!path) return h('div.ic.ph' + cls, { text: (alt || '?').slice(0, 3).toUpperCase() })
  return h('img.ic' + cls, { src: `aram://icons/${path}`, alt: alt || '', draggable: 'false' })
}

function tierBadge(t) {
  const [c, fg] = tierColors(t)
  return h('div.tier', { '--c': c, '--fg': fg, text: t })
}

function arrow(v, unit = '') {
  if (!v) return ['=', 'flat']
  return v > 0 ? [`▲${Math.abs(v)}${unit}`, 'up'] : [`▼${Math.abs(v)}${unit}`, 'down']
}

// win rate / pick rate si cum s-au schimbat fata de patch-ul anterior
function stats(e) {
  if (e.wr == null && e.tier_change == null) return null
  const parts = []
  if (e.balance && e.balance.length) parts.push(h('span.mods', { text: 'MAYHEM  ' + e.balance.join('  ') }))
  if (e.wr != null) {
    parts.push(h('span', { text: `WR ${e.wr.toFixed(1)}%` }))
    if (e.wr_delta != null) { const [t, c] = arrow(e.wr_delta, '%'); parts.push(h('span.' + c, { text: t })) }
    parts.push(h('span.flat', { text: `PR ${e.pr.toFixed(1)}%` }))
  }
  if (e.tier_change != null) { const [t, c] = arrow(e.tier_change); parts.push(h('span.' + c, { text: `TIER ${t}` })) }
  return h('div.stats', {}, parts)
}

// un campion sau un augment: iconita + insigna de tier + ce stim despre el
function tierRow(e, kind) {
  const [c] = tierColors(e.tier)
  const label = e.is_best ? 'BEST' + (e.origin ? `  ·  ${e.origin}` : '') : e.origin
  return h('div.row' + (e.is_best ? '.best' : ''), { '--c': c },
    icon(e.icon, e.name),
    tierBadge(e.tier),
    h('div.txt', {},
      h('div.nm', { text: e.name }),
      kind === 'champ' && stats(e),
      // unele augmente ("Upgrade Zhonya's") n-au sens decat daca cumperi itemul
      e.needs && h('div.why', { text: `CERE ${e.needs}` }),
      // fara tier aratam ce face; nu inventam un rank
      kind === 'aug' && !TIER[e.tier] && h('div.desc', { text: (e.desc || 'neclasat de u.gg').slice(0, 110) })),
    label && h('span.tag', { text: label }))
}

function strip(items, label) {
  return h('div.strip', {}, label && h('span.k', { text: label }), items.map(e => {
    const cls = (e.owned ? '.owned' : '') + (e.next ? '.next' : '') + (e.reason ? '.hot' : '')
    return tip(icon(e.icon, e.item, cls), e.item, tipText(e))
  }))
}

const tipText = e => [e.reason && e.reason[0].toUpperCase() + e.reason.slice(1), e.desc].filter(Boolean).join('\n\n')

// itemul de cumparat ACUM, mare si incadrat; restul ordinii ca sloturi mici
function nextItems(items) {
  const [head, ...rest] = items
  return [
    h('div.hero', {},
      tip(icon(head.icon, head.item), head.item, tipText(head)),
      h('div.txt', {},
        h('div.k', { text: 'CUMPARA ACUM' }),
        h('div.nm', { text: head.item }),
        head.reason && h('div.why', { text: head.reason }))),
    rest.length && strip(rest, 'APOI'),
  ]
}

// vinde X -> ia Y
function sellRow(s) {
  return h('div.row.sell', {},
    tip(icon(s.sell_icon, s.sell, '.out'), s.sell),
    h('span.arrow', { text: '→' }),
    tip(icon(s.buy_icon, s.buy), s.buy),
    h('div.txt', {},
      h('div.k', { text: `VINDE ${s.sell}` }),
      h('div.nm', { text: `IA ${s.buy}` }),
      s.reason && h('div.why', { text: s.reason })))
}

function anvilRow(s) {
  return h('div.row' + (s.is_best ? '.best' : ''), { '--c': 'var(--teal)' },
    h('div.txt', {},
      h('div.nm', { text: `${s.name} (${s.tier})` }),
      s.is_best && s.why && h('div.why', { text: s.why })),
    s.is_best && h('span.tag', { text: 'BEST' }))
}

function stateRow(label, value, ok) {
  return h('div.state', {}, h('span', { text: label }), h('b' + (ok ? '.ok' : ''), { text: value }))
}

const waiting = () => h('div.wait', {}, Array.from({ length: 16 }, (_, i) => h('i', { '--i': i })))

// --- cele trei vederi ----------------------------------------------------------------

function idle(d) {
  const c = S.counts || {}
  return [
    sec('STARE'),
    stateRow('CLIENT LEAGUE', d.client_up ? 'PORNIT' : 'OPRIT', d.client_up),
    stateRow('MECI', 'NU', false),
    sec('ASTEPT'),
    waiting(),
    note('Se umple singura cand intri in champ select de Mayhem sau cand incepe meciul.'),
    sec('DATE LOCALE'),
    note(`${c.builds ?? '?'} build-uri  ·  ${c.champions ?? '?'} campioni  ·  ${c.augments ?? '?'} augmente`),
    d.error && note(d.error, 'err'),
    sec('SCURTATURA'),
    note(`${S.hotkeyLabel} strange fereastra la bara de titlu. Daca nu merge (unele anti-cheat-uri `
      + 'blocheaza taste globale cat jocul e activ), click pe "_" din colt face acelasi lucru.'),
  ]
}

// Toti campionii pe care ii poti avea, ordonati dupa tier. Sus, fixate: cel mai
// bun si spell-urile lui; decizia se vede fara scroll.
function champSelect(d) {
  const [best, ...rest] = d.pool || []
  if (!best) return [note('se incarca...')]
  return [
    sec('CEL MAI BUN'),
    tierRow(best, 'champ'),
    d.summoners.length > 0 && [
      sec(`SUMMONER SPELLS  ·  ${best.name}`),
      h('div.strip', {}, d.summoners.map(s => h('div.row', {}, icon(s.icon, s.name), h('div.nm', { text: s.name })))),
    ],
    rest.length > 0 && [sec('RESTUL  ·  DUPA TIER'), rest.map(e => tierRow(e, 'champ'))],
  ]
}

function topAugments(d) {
  const out = [sec('TOP AUGMENTE' + (d.champ ? `  ·  ${d.champ}` : ''))]
  if (d.ocr) out.push(note('OCR: ' + d.ocr))
  for (const [rarity, label] of [['prismatic', 'PRISM'], ['gold', 'AUR'], ['silver', 'ARGINT']]) {
    const list = (d.top || {})[rarity]
    if (list && list.length) {
      out.push(h('div.top', {}, h('span.k', { text: label }),
        h('span.v', { text: list.map(a => `${a.name} (${a.tier})`).join('  ·  ') })))
    }
  }
  return out
}

// Doar ce te ajuta sa castigi meciul: ce cumperi, ce vinzi, ce shard iei.
function inGame(d) {
  const out = []
  if (d.status) out.push(note(d.status))
  if (d.offer.length) out.push(sec('OFERTA'), d.offer.map(a => tierRow(a, 'aug')))
  else if (augOn) out.push(topAugments(d))
  if (d.anvil.length) out.push(sec('STAT ANVIL'), d.anvil.map(anvilRow))
  const b = d.build
  if (b) {
    if (b.starting.length) out.push(sec('START'), strip(b.starting))
    // vanzarea e cel mai urgent lucru de pe ecran: sta prima
    if (b.sell) out.push(b.sell && sellRow(b.sell))
    if (b.next.length) out.push(nextItems(b.next))
    else if (b.complete.length) out.push(sec('BUILD COMPLET'), strip(b.complete))
    if (b.unavailable.length) {
      out.push(note('Indisponibil: ' + b.unavailable.join(', ') + (b.range ? ` (esti ${b.range})` : '')))
    }
  }
  if (d.loading) out.push(note('se incarca...'))
  return out
}

const VIEWS = { idle, champ_select: champSelect, in_game: inGame }

// --- bara de titlu ------------------------------------------------------------------

function bugIcon() {
  const ns = 'http://www.w3.org/2000/svg'
  const svg = document.createElementNS(ns, 'svg')
  svg.setAttribute('viewBox', '0 0 64 64')
  const add = (tag, attrs) => {
    const el = document.createElementNS(ns, tag)
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v)
    svg.append(el)
  }
  add('ellipse', { cx: 32, cy: 41, rx: 13, ry: 19 })
  add('circle', { cx: 32, cy: 16, r: 7, class: 'solid' })
  add('path', { d: 'M32 26v32M19 32 7 26M45 32l12-6M19 42H7m38 0h12M19 52 7 58m38-6 12 6M28 12l-7-10m15 10 7-10' })
  return svg
}

function chrome() {
  const v = S.view, d = S.data || {}
  $('title').textContent = v === 'in_game' && d.champ ? d.champ.toUpperCase() : 'ARAM MAYHEM'
  $('sub').textContent = v === 'champ_select' ? 'CHAMP SELECT  ·  REROLL'
    : v === 'in_game' ? `IN JOC  ·  ${(d.champ || '?').toUpperCase()}` + (d.enemies ? `  ·  VS ${d.enemies}` : '')
      : 'IDLE  ·  ASTEPT'

  // augmentele luate, langa nume; click pe una o scoate (ai ales gresit)
  $('augs').replaceChildren(...(v === 'in_game' ? d.taken || [] : []).map(a => {
    const el = tip(icon(a.icon, a.name), a.name, 'Click: scoate din lista (ai ales gresit)')
    el.addEventListener('click', () => api.send('cmd', { cmd: 'drop', name: a.name }))
    return el
  }))

  const u = S.update || {}
  $('upd').hidden = !u.tag
  $('upd').textContent = u.tag ? `UPDATE ${u.tag}` : ''
  if (wasBusy && !u.busy && u.why) {
    verNote = u.why.split(':')[0].toUpperCase()
    setTimeout(() => { verNote = null; chrome() }, 4000)
  }
  wasBusy = !!u.busy
  $('ver').textContent = u.busy ? '...' : verNote || `v${S.version}`
  $('aug').hidden = v !== 'in_game'
  $('aug').classList.toggle('on', augOn)

  const status = []
  if (S.error) status.push(S.error)
  if (!S.hotkey) status.push(`${S.hotkeyLabel} ocupat -- foloseste "_" din titlu`)
  if (v !== 'in_game' && d.status) status.push(d.status)
  $('foot').textContent = status.join('  ·  ').toUpperCase()
}

// --- desenare si potrivire --------------------------------------------------------

function render(force) {
  if (!S) return
  const key = JSON.stringify([S.view, S.data, S.update, S.error, S.hotkey, augOn, verNote])
  if (!force && key === shown) return
  shown = key
  const view = S.view
  panel.className = (view === 'in_game' ? 'hud lean' : 'client') + (collapsed ? ' collapsed' : '')
  api.send('tip-hide')        // elementul de sub cursor tocmai dispare
  chrome()
  body.replaceChildren(...[VIEWS[view](S.data || {})].flat(Infinity).filter(Boolean))
  if (view !== shownView) {
    shownView = view
    body.classList.remove('enter')
    void body.offsetWidth
    body.classList.add('enter')
    body.scrollTop = 0
  }
  fit()
}

// Latimea vine de la procesul principal (golul din HUD). Daca nu incape pe
// inaltime, micsoram tot panoul pana la ZOOM_MIN; sub el ramane scroll.
// Totul se calculeaza in px CSS: zoom-ul doar ii mapeaza pe ecran.
function fit() {
  if (!layout) return
  let z = layout.zoom
  body.style.maxHeight = ''
  for (let i = 0; i < 6; i++) {
    panel.style.width = `${layout.w / z}px`
    const total = panel.offsetHeight * z
    if (collapsed || !layout.shrink || total <= layout.maxH || z <= ZOOM_MIN + 0.002) break
    z = Math.max(ZOOM_MIN, z * layout.maxH / total * 0.98)
  }
  if (panel.offsetHeight * z > layout.maxH + 0.5 && !collapsed) {
    const chromeH = panel.offsetHeight - body.offsetHeight
    body.style.maxHeight = `${Math.max(40, layout.maxH / z - chromeH)}px`
  }
  api.zoom(z)
  api.send('height', Math.ceil(panel.offsetHeight * z))
}

// rotita de mouse doar peste corp, si doar cand chiar are ce derula
body.addEventListener('wheel', e => {
  if (body.scrollHeight > body.clientHeight) body.scrollTop += Math.sign(e.deltaY) * 48
}, { passive: true })

api.on('state', s => { S = s; render() })
api.on('layout', l => { layout = l; fit() })
api.on('collapsed', c => {
  collapsed = c
  panel.classList.toggle('collapsed', c)
  fit()
})
window.onFonts = () => fit()
fontsLoaded.then(() => fit())

$('bug').append(bugIcon())
const click = (id, fn) => $(id).addEventListener('click', fn)
click('close', () => api.send('cmd', { cmd: 'close' }))
click('min', () => api.send('cmd', { cmd: 'collapse' }))
click('snap', () => api.send('cmd', { cmd: 'snap' }))
click('bug', () => api.send('cmd', { cmd: 'report' }))
click('ver', () => api.send('cmd', { cmd: 'update' }))
click('upd', () => api.send('cmd', { cmd: 'restart' }))
click('aug', () => { augOn = !augOn; render(true) })
tip($('bug'), 'Raporteaza un bug', 'Trimite ce vede aplicatia acum, ca sa pot repara.')
tip($('snap'), 'Aseaza in gol', 'Pune panoul inapoi intre HUD si minimap. Il poti trage si pe alt ecran: ramane acolo.')
tip($('ver'), 'Versiunea', 'Click: cauta si instaleaza acum o versiune noua.')
tip($('upd'), 'Versiune noua instalata', 'Click: reporneste pe ea acum. In afara meciului se reporneste singura.')
tip($('aug'), 'Top augmente', 'Cele mai bune augmente pentru campionul tau, cand insignele nu apar pe carduri.')
