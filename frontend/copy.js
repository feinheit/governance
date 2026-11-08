// Buttons copying a field's text (data-copy with the field's ID), e.g. the
// mail addresses; hidden without JavaScript, the field can be selected
// by hand

for (const button of document.querySelectorAll("[data-copy]")) {
  button.hidden = false
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]")
  if (!button) return
  const field = document.getElementById(button.dataset.copy)
  if (!field) return
  field.select()
  try {
    await navigator.clipboard.writeText(field.value)
  } catch {
    document.execCommand("copy")
  }
  const label = button.querySelector("[data-copy-label]")
  if (!label) return
  label.dataset.text ??= label.textContent
  label.textContent = button.dataset.copied || "✓"
  setTimeout(() => {
    label.textContent = label.dataset.text
  }, 1500)
})
