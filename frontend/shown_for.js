// Parts of forms shown for some choices only: data-shown-for="kind=comment
// meeting" shows the element while the radio button "kind" with one of the
// values is checked, or while its fields have text (it isn't dropped
// unseen, the server refuses it where it doesn't belong). Without
// JavaScript everything stays visible.

function update(form) {
  for (const element of form.querySelectorAll("[data-shown-for]")) {
    const [name, values] = element.dataset.shownFor.split("=")
    const checked = form.querySelector(`[name="${name}"]:checked`)
    const filled = [...element.querySelectorAll("textarea, input")].some(
      (field) => field.value.trim(),
    )
    element.hidden = !(
      filled ||
      (checked && values.split(" ").includes(checked.value))
    )
  }
}

function updateAll() {
  for (const form of document.querySelectorAll("form")) {
    if (form.querySelector("[data-shown-for]")) update(form)
  }
}

// Only on choosing: a textarea emptied and left (its change event) hiding
// itself would move what's clicked next away under the pointer
document.addEventListener("change", (event) => {
  if (event.target.type === "radio" && event.target.form) {
    update(event.target.form)
  }
})
document.addEventListener("htmx:after:settle", updateAll)
updateAll()
