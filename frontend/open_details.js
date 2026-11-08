// Links to <details> elsewhere on the page open them and scroll there,
// e.g. a domain's policies on the role's page: data-open-details lists
// their IDs, href points at the first one (without JavaScript the browser
// jumps there, closed)

document.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-open-details]")
  if (!link) return
  const targets = link.dataset.openDetails
    .split(" ")
    .map((id) => document.getElementById(id))
    .filter(Boolean)
  if (!targets.length) return
  event.preventDefault()
  for (const details of targets) details.open = true
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches
  targets[0].scrollIntoView({
    behavior: reduce ? "auto" : "smooth",
    block: "start",
  })
  targets[0].querySelector("summary")?.focus({ preventScroll: true })
})

// Links from elsewhere to a part of the page open what's folded there, e.g.
// a day in the history linked from the role's page (#day-…, highlighted by
// :target in main.css)
function openTarget() {
  const id = decodeURIComponent(window.location.hash.slice(1))
  const target = id && document.getElementById(id)
  if (!target) return
  if (target.matches("details")) target.open = true
  for (const details of target.querySelectorAll("details")) details.open = true
}
openTarget()
window.addEventListener("hashchange", openTarget)
