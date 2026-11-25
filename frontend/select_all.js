// "Select all" buttons (data-select-all) check the checkboxes of their
// group or form, or
// uncheck them when all are checked; delegated, they work in modals loaded
// later too

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-select-all]")
  if (!button?.form) return
  event.preventDefault()
  // Those of its group (data-select-scope), else the form's
  const scope = button.closest("[data-select-scope]") || button.form
  const boxes = [...scope.querySelectorAll('input[type="checkbox"]')]
  const check = !boxes.every((box) => box.checked)
  for (const box of boxes) box.checked = check
})
