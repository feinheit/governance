// Fields filtering a list as you type (input[data-filter-rows] with the
// list's selector): rows ([data-filter-text]) containing all the words
// entered stay, ignoring case and accents; checked rows always do, groups
// ([data-filter-group]) without rows disappear. Without JavaScript the
// field is hidden and the whole list shown.

const normalize = (text) =>
  text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()

for (const field of document.querySelectorAll("input[data-filter-rows]")) {
  const list = document.querySelector(field.dataset.filterRows)
  if (!list) continue
  field.hidden = false
  // Not submitting the form with Enter, which would skip the choice
  field.addEventListener("keydown", (event) => {
    if (event.key === "Enter") event.preventDefault()
  })
  field.addEventListener("input", () => {
    const words = normalize(field.value).split(/\s+/).filter(Boolean)
    for (const row of list.querySelectorAll("[data-filter-text]")) {
      const text = normalize(row.dataset.filterText)
      const checked = row.querySelector("input:checked")
      row.hidden = !checked && !words.every((word) => text.includes(word))
    }
    for (const group of list.querySelectorAll("[data-filter-group]")) {
      group.hidden = !group.querySelector("[data-filter-text]:not([hidden])")
    }
  })
}
