// The theme toggle from Workbench (workbench/static/workbench/main.js):
// auto -> light -> dark -> auto, stored in localStorage. The inline script
// in base.html sets the theme before the page renders.
const getStoredTheme = () => window.localStorage.getItem("theme")
const setStoredTheme = (theme) => {
  if (theme === "auto") {
    window.localStorage.removeItem("theme")
  } else {
    window.localStorage.setItem("theme", theme)
  }
}
const getSystemTheme = () =>
  window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
const getThemeMode = () => getStoredTheme() || "auto"

const ICONS = {
  light: `<path d="M8 11a3 3 0 1 1 0-6 3 3 0 0 1 0 6zm0 1a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM8 0a.5.5 0 0 1 .5.5v2a.5.5 0 0 1-1 0v-2A.5.5 0 0 1 8 0zm0 13a.5.5 0 0 1 .5.5v2a.5.5 0 0 1-1 0v-2A.5.5 0 0 1 8 13zm8-5a.5.5 0 0 1-.5.5h-2a.5.5 0 0 1 0-1h2a.5.5 0 0 1 .5.5zM3 8a.5.5 0 0 1-.5.5h-2a.5.5 0 0 1 0-1h2A.5.5 0 0 1 3 8zm10.657-5.657a.5.5 0 0 1 0 .707l-1.414 1.415a.5.5 0 1 1-.707-.708l1.414-1.414a.5.5 0 0 1 .707 0zm-9.193 9.193a.5.5 0 0 1 0 .707L3.05 13.657a.5.5 0 0 1-.707-.707l1.414-1.414a.5.5 0 0 1 .707 0zm9.193 2.121a.5.5 0 0 1-.707 0l-1.414-1.414a.5.5 0 0 1 .707-.707l1.414 1.414a.5.5 0 0 1 0 .707zM4.464 4.465a.5.5 0 0 1-.707 0L2.343 3.05a.5.5 0 1 1 .707-.707l1.414 1.414a.5.5 0 0 1 0 .708z"/>`,
  dark: `<path d="M6 .278a.768.768 0 0 1 .08.858 7.208 7.208 0 0 0-.878 3.46c0 4.021 3.278 7.277 7.318 7.277.527 0 1.04-.055 1.533-.16a.787.787 0 0 1 .81.316.733.733 0 0 1-.031.893A8.349 8.349 0 0 1 8.344 16C3.734 16 0 12.286 0 7.71 0 4.266 2.114 1.312 5.124.06A.752.752 0 0 1 6 .278zM4.858 1.311A7.269 7.269 0 0 0 1.025 7.71c0 4.02 3.279 7.276 7.319 7.276a7.316 7.316 0 0 0 5.205-2.162c-.337.042-.68.063-1.029.063-4.61 0-8.343-3.714-8.343-8.29 0-1.167.242-2.278.681-3.286z"/>`,
  auto: `<path d="M8 15A7 7 0 1 0 8 1v14zm0 1A8 8 0 1 1 8 0a8 8 0 0 1 0 16z"/>`,
}

const setTheme = (mode) => {
  const active = mode === "auto" ? getSystemTheme() : mode
  document.documentElement.setAttribute("data-bs-theme", active)
  for (const button of document.querySelectorAll("[data-theme-toggle]")) {
    const icon = button.querySelector("svg")
    if (icon) icon.innerHTML = ICONS[mode]
    // The titles come translated from the template
    button.setAttribute(
      "title",
      button.dataset[`title${mode[0].toUpperCase()}${mode.slice(1)}`],
    )
  }
}

setTheme(getThemeMode())

document.body.addEventListener("click", (event) => {
  if (event.target.closest("[data-theme-toggle]")) {
    event.preventDefault()
    const next = { auto: "light", light: "dark", dark: "auto" }[getThemeMode()]
    setStoredTheme(next)
    setTheme(next)
  }
})

// System changes only matter in auto mode
window
  .matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", () => {
    if (getThemeMode() === "auto") setTheme("auto")
  })
