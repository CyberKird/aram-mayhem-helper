'use strict'
// Puntea dintre pagini si procesul principal: doar canalele de mai jos.
const { contextBridge, ipcRenderer, webFrame } = require('electron')

const LISTEN = ['state', 'layout', 'collapsed', 'badge', 'tip', 'fonts-ready']
const SEND = ['height', 'cmd', 'tip', 'tip-hide', 'tip-size', 'badge-size', 'badge-pick',
  'report-size', 'report-mailto', 'report-close']
const INVOKE = ['fonts', 'report-init', 'report-send']

contextBridge.exposeInMainWorld('api', {
  on: (ch, fn) => { if (LISTEN.includes(ch)) ipcRenderer.on(ch, (_e, data) => fn(data)) },
  send: (ch, data) => { if (SEND.includes(ch)) ipcRenderer.send(ch, data) },
  invoke: (ch, data) => INVOKE.includes(ch) ? ipcRenderer.invoke(ch, data) : Promise.reject(new Error(ch)),
  zoom: z => webFrame.setZoomFactor(z),
})
