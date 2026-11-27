// Textareas grow with their text (never below their rows): when they
// appear (loading, what htmx loads, a modal opening, a hidden part of a
// form shown), when their width changes, on focus and while typing

function autogrow(textarea) {
  textarea.style.height = "auto"
  const borders = textarea.offsetHeight - textarea.clientHeight
  textarea.style.height = `${textarea.scrollHeight + borders}px`
}

// The width tells: zero while hidden, another one wraps the lines
// differently; the height is ours. Growing a frame later, growing inside
// the callback would be a loop the browser reports as an error.
const widths = new WeakMap()
const observer = new ResizeObserver((entries) => {
  for (const { target } of entries) {
    const width = target.offsetWidth
    if (!width || widths.get(target) === width) continue
    widths.set(target, width)
    requestAnimationFrame(() => autogrow(target))
  }
})

// (also the visible ones again: htmx may have changed their text)
function autogrowAll() {
  for (const textarea of document.querySelectorAll("textarea")) {
    observer.observe(textarea)
    if (textarea.offsetParent !== null) autogrow(textarea)
  }
}

document.addEventListener("input", (event) => {
  if (event.target.matches?.("textarea")) autogrow(event.target)
})
document.addEventListener("focusin", (event) => {
  if (event.target.matches?.("textarea")) autogrow(event.target)
})
document.addEventListener("htmx:after:settle", autogrowAll)
autogrowAll()
