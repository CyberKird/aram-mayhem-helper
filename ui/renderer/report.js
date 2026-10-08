'use strict'
// Raportul de bug: textul tau, emailul (optional) si, doar daca lasi bifat,
// diagnosticul pe care il vezi aici inainte sa plece. Fara capturi de ecran.

const $ = id => document.getElementById(id)
const panel = $('panel')
let diag = ''

function resize() {
  const r = panel.getBoundingClientRect()
  api.send('report-size', { w: Math.ceil(r.width), h: Math.ceil(r.height) })
}

function result(text, ok) {
  $('result').textContent = text
  $('result').className = ok ? 'ok' : 'bad'
  resize()
}

api.invoke('report-init').then(init => {
  diag = init.diag
  $('diag').textContent = diag.length > 420 ? diag.slice(0, 420) + '...' : diag
  resize()
  $('desc').focus()
})

$('form').addEventListener('submit', async e => {
  e.preventDefault()
  const send = $('send')
  if (send.disabled) return
  send.disabled = true
  send.textContent = 'SE TRIMITE...'
  const r = await api.invoke('report-send', {
    desc: $('desc').value, email: $('email').value, include: $('include').checked, diag,
  })
  send.disabled = false
  send.textContent = 'TRIMITE'
  if (!r) return result('Motorul nu a raspuns. Incearca din nou.', false)
  result(r.text, r.ok)
  if (r.ok) setTimeout(() => api.send('report-close'), 1500)
  else if (r.text && !r.text.startsWith('Descrie') && !r.text.startsWith('Prea') && !r.text.startsWith('Adresa')) {
    $('mail').hidden = false          // rezerva, doar dupa un esec de trimitere
    resize()
  }
})

$('mail').addEventListener('click', () => api.send('report-mailto', {
  desc: $('desc').value, diag: $('include').checked ? diag : '(diagnostic omis de utilizator)',
}))
$('close').addEventListener('click', () => api.send('report-close'))
document.addEventListener('keydown', e => { if (e.key === 'Escape') api.send('report-close') })
window.onFonts = resize
fontsLoaded.then(resize)
