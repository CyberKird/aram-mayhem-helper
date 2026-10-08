'use strict'
// Comun pentru toate paginile: un constructor mic de DOM (fara innerHTML, deci
// nimic citit prin OCR nu poate deveni markup), culorile de tier si fonturile.

function h(tag, props, ...kids) {
  const [name, ...cls] = tag.split('.')
  const el = document.createElement(name || 'div')
  if (cls.length) el.className = cls.join(' ')
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue
    if (k === 'text') el.textContent = v
    else if (k.startsWith('--')) el.style.setProperty(k, v)
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v)
    else el.setAttribute(k, v === true ? '' : v)
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false || kid === '') continue
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)))
  }
  return el
}

// fundal / text al insignei de tier
const TIER = {
  'S+': ['#ff4655', '#ffffff'], S: ['#ff9a3c', '#2b1400'], A: ['#ffd166', '#3a2c00'],
  B: ['#8ac926', '#182b00'], C: ['#4a9de0', '#04203a'], D: ['#6b7280', '#ffffff'],
}
const UNKNOWN = ['#1e2328', '#a09b8c']
const tierColors = t => TIER[t] || UNKNOWN

const FACES = {
  'beaufortforlol-bold.otf': ['Beaufort', '700'],
  'spiegel-regular.otf': ['Spiegel', '400'],
  'spiegel-semibold.otf': ['Spiegel', '600'],
  'spiegel-bold.otf': ['Spiegel', '700'],
}

async function loadFonts() {
  const have = await api.invoke('fonts')
  await Promise.all(have.map(async file => {
    const [family, weight] = FACES[file] || []
    if (!family) return
    try {
      document.fonts.add(await new FontFace(family, `url(aram://fonts/${file})`, { weight }).load())
    } catch {}
  }))
}

// paginile isi remasoara continutul cand fonturile adevarate inlocuiesc rezerva
const fontsLoaded = loadFonts()
api.on('fonts-ready', () => loadFonts().then(() => window.onFonts && window.onFonts()))

