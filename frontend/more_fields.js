// Fields of which there may be several, e.g. the new accountabilities of a
// role in a proposal: a button below the last one (data-more, its label)
// adds another empty one. Without JavaScript the form has one empty field
// each time it's opened.
import { attachAll } from "./mentions.js"

function addButtons(root) {
  for (const field of root.querySelectorAll("[data-more]")) {
    const group = field.closest(".mb-3")
    if (group.nextElementSibling?.matches("[data-more-add]")) continue
    const button = document.createElement("button")
    button.type = "button"
    button.className = "btn btn-sm btn-quiet mb-3"
    button.dataset.moreAdd = ""
    button.textContent = field.dataset.more
    group.after(button)
  }
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-more-add]")
  if (!button) return
  const group = button.previousElementSibling
  const field = group.querySelector("[data-more]")
  const clone = group.cloneNode(true)
  // The next index, a fresh field without the notes and errors of the last
  const next = field.name.replace(/\d+$/, (index) => Number(index) + 1)
  const copy = clone.querySelector("[data-more]")
  copy.name = next
  copy.id = `id_${next}`
  copy.value = ""
  copy.style.height = ""
  delete copy.dataset.mentionsAttached
  clone.querySelector("label")?.setAttribute("for", copy.id)
  for (const element of clone.querySelectorAll(
    ".form-text, .invalid-feedback",
  )) {
    element.remove()
  }
  copy.classList.remove("is-invalid")
  delete field.dataset.more
  button.before(clone)
  attachAll(clone)
  copy.focus()
})

addButtons(document)
document.addEventListener("htmx:after:settle", () => addButtons(document))
