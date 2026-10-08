'use strict'
// Doua feluri de fereastra mica, dupa #: o insigna de tier pe un card (augment,
// Stat Anvil, carte de campion) sau tooltip-ul panoului. Fiecare deseneaza,
// se masoara si ii spune procesului principal ce marime sa aiba.

const root = document.getElementById('root')
const mode = location.hash.slice(1)
root.classList.toggle('bottom', mode === 'badge')   // insigna sta jos in fereastra (vezi badge-size)

function measure(zoom) {
  const r = root.getBoundingClientRect()
  return { w: Math.ceil(r.width * zoom), h: Math.ceil(r.height * zoom) }
}

// Insigna sta deasupra cardului, pe un singur rand, fara sa acopere nimic din
// el: fond teal inchis, fir bronz, auriu pe alegerea buna. Pe augmente scrie si
// numele, ca sa vezi imediat daca a cazut pe alt card. Click = "pe asta l-am luat".
function badge(b) {
  const color = b.kind === 'anvil' ? (b.is_best ? '#f0d68c' : '#a09b8c') : tierColors(b.tier)[0]
  const el = h('div.badge' + (b.is_best ? '.best' : '') + (b.pick ? '.pick' : '') + (b.taken ? '.taken' : ''),
    { '--c': color },
    h('span.t', { text: b.tier }),
    b.name && h('span.n', { text: b.name }),
    (b.taken || b.is_best) && h('span.k', { text: b.taken ? 'LUAT' : 'BEST' }))
  if (b.pick) el.addEventListener('click', () => api.send('badge-pick', b.pick))
  return el
}

let last = null

function show(b) {
  last = b
  api.zoom(b.zoom)
  root.replaceChildren(badge(b))
  api.send('badge-size', measure(b.zoom))
}

function showTip(t) {
  last = t
  api.zoom(t.zoom)
  root.replaceChildren(h('div.tip', {}, h('div.tt', { text: t.title }), t.text && h('div.tx', { text: t.text })))
  api.send('tip-size', { seq: t.seq, ...measure(t.zoom) })
}

if (mode === 'badge') api.on('badge', show)
else api.on('tip', showTip)
window.onFonts = () => last && (mode === 'badge' ? show(last) : showTip(last))
