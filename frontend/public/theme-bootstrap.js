// Applied synchronously before first paint so a light-theme user never sees a
// dark flash. This stays in a same-origin external file so production can use
// a strict Content Security Policy without allowing arbitrary inline scripts.
;(function () {
  try {
    var stored = localStorage.getItem('agent-ops.theme')
    document.documentElement.dataset.theme = stored === 'light' ? 'light' : 'dark'
  } catch {
    document.documentElement.dataset.theme = 'dark'
  }
})()
