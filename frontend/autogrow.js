// Textareas grow with their text (never below their rows): on loading,
// while typing, and in what htmx loads (the meeting's updates, modals)

function autogrow(textarea) {
  textarea.style.height = "auto"
  const borders = textarea.offsetHeight - textarea.clientHeight
  textarea.style.height = `${textarea.scrollHeight + borders}px`
}

function autogrowAll() {
  for (const textarea of document.querySelectorAll("textarea")) {
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
