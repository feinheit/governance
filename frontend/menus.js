// Menus of what isn't needed often (details.wb-menu): closed when clicking
// elsewhere and with Escape, like Bootstrap's dropdowns

document.addEventListener("click", (event) => {
  for (const menu of document.querySelectorAll("details.wb-menu[open]")) {
    if (!menu.contains(event.target)) menu.open = false
  }
})

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return
  const menu = event.target.closest?.("details.wb-menu[open]")
  if (menu) {
    menu.open = false
    menu.querySelector("summary").focus()
  }
})
