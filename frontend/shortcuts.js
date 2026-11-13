// Keyboard shortcuts like Workbench's: Alt with a letter, Ctrl on Macs (Alt
// types special characters there). Elements with data-shortcut="h" are
// links to follow or fields to focus, see docs/orientation.md.
const isMac = /Mac/.test(navigator.platform)
const modifier = isMac ? "Ctrl" : "Alt"

document.addEventListener("keydown", (event) => {
  const pressed = isMac ? event.ctrlKey : event.altKey
  const other = isMac ? event.altKey : event.ctrlKey
  if (!pressed || other || event.metaKey || event.shiftKey) return
  const key = event.key.toLowerCase()
  const element = document.querySelector(`[data-shortcut="${key}"]`)
  if (!element) return
  event.preventDefault()
  if (element.matches("input, textarea")) {
    element.focus()
    element.select()
  } else {
    window.location.href = element.href
  }
})

// Tell screen readers and the tooltip which keys to press
for (const element of document.querySelectorAll("[data-shortcut]")) {
  const keys = `${modifier}-${element.dataset.shortcut.toUpperCase()}`
  element.setAttribute("aria-keyshortcuts", keys.replace("-", "+"))
  element.title = element.title ? `${element.title} (${keys})` : keys
}

// The help names the keys for Alt (docs/orientation.md), Macs press Ctrl
if (isMac) {
  for (const kbd of document.querySelectorAll(".wb-help kbd")) {
    kbd.textContent = kbd.textContent.replace(/\bAlt-/g, "Ctrl-")
  }
}
