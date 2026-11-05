// Long lists show the other entries on request (_show_more.html, from
// Workbench); without JavaScript they're all there (base.html sets .js)

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-show-more]")
  if (!button) return
  const toggle = button.closest(".wb-show-more")
  let row = toggle.nextElementSibling
  while (row?.classList.contains("wb-more")) {
    row.classList.remove("wb-more")
    row = row.nextElementSibling
  }
  toggle.remove()
})
