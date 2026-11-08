// Forms filtering lists (form[data-autosubmit], generic/_filters.html),
// like Workbench's: changing a field loads the list with the form's
// non-empty values, from its first page; the button is only needed
// without JavaScript

for (const button of document.querySelectorAll(
  "form[data-autosubmit] [data-filter-submit]",
)) {
  button.hidden = true
}

document.addEventListener("change", (event) => {
  const form = event.target.closest?.("form[data-autosubmit]")
  if (form?.method !== "get") return
  const params = new URLSearchParams()
  for (const [name, value] of new FormData(form)) {
    if (value) params.append(name, value)
  }
  params.sort()
  const query = params.toString()
  window.location.href = query ? `?${query}` : "?"
})
