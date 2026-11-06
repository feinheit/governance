// Meetings: htmx (imported after this file in main.js) replaces only the
// meeting's region, see meetings/meeting_detail.html. Boosting applies to
// its forms and to links marked data-in-meeting (opening a form in the
// panel, cancelling it); other links navigate as usual.
document.addEventListener("htmx:before:init", (event) => {
  const element = event.target
  if (element.matches?.("a:not([data-in-meeting]):not([hx-get])")) {
    event.preventDefault()
  }
})

// The meeting's region is merged with the server's every few seconds,
// except while somebody types, has a form in the panel or a collapsible
// section open (merging would close it). Paused for more than one check,
// a notice says so (#meeting-paused, not while typing a moment).
let busyChecks = 0
window.meetingIsIdle = () => {
  if (document.hidden) return false
  const form = document.activeElement?.closest("#meeting form")
  const busy = Boolean(
    document.querySelector(
      "#meeting details[open], #amend > *, .sortable-chosen",
    ) || form,
  )
  busyChecks = busy ? busyChecks + 1 : 0
  // Not while writing what saves itself (the secretary's outcome, notes)
  const notice = document.getElementById("meeting-paused")
  if (notice) {
    notice.hidden = busyChecks < 2 || Boolean(form?.matches("[data-autosave]"))
  }
  return !busy
}

// Dragging the agenda's items (the secretary): SortableJS, a chunk of its own
if (document.getElementById("meeting")) {
  import(/* webpackChunkName: "agenda" */ "./agenda.js")
}

// Forms with data-autosave (the outcome, the notes) save themselves a
// moment after typing and when leaving a field; the server only saves
// (X-Autosave), the others see it with their next update
const autosaveTimers = new WeakMap()

async function autosave(form) {
  clearTimeout(autosaveTimers.get(form))
  autosaveTimers.delete(form)
  const response = await fetch(form.action, {
    method: "POST",
    body: new FormData(form),
    headers: { "X-Autosave": "true" },
  })
  form.classList.toggle("wb-autosave-failed", !response.ok)
}

document.addEventListener("input", (event) => {
  const form = event.target.closest?.("form[data-autosave]")
  if (!form) return
  clearTimeout(autosaveTimers.get(form))
  autosaveTimers.set(
    form,
    setTimeout(() => autosave(form), 1000),
  )
})

document.addEventListener("focusout", (event) => {
  const form = event.target.closest?.("form[data-autosave]")
  if (form && autosaveTimers.has(form)) autosave(form)
})

// The running meeting's column (.wb-flow: results, the item being
// processed, notes) scrolls to the item when another one is processed, for
// the secretary and those following, and when its agenda row is clicked
let shownItem

function scrollToCurrent(force = false) {
  const flow = document.querySelector(".wb-flow")
  const current = flow?.querySelector("#current")
  if (!current) {
    shownItem = undefined
    return
  }
  if (!force && current.dataset.item === shownItem) return
  shownItem = current.dataset.item
  if (flow.scrollHeight > flow.clientHeight) {
    flow.scrollTo({
      top: current.offsetTop,
      behavior: force ? "smooth" : "auto",
    })
  } else if (force) {
    current.scrollIntoView({ behavior: "smooth", block: "start" })
  }
}

scrollToCurrent()
document.addEventListener("htmx:after:settle", () => scrollToCurrent())
document.addEventListener("click", (event) => {
  if (
    event.target.closest("#agenda li.wb-current") &&
    !event.target.closest("a, button, input, [data-agenda-handle]")
  ) {
    scrollToCurrent(true)
  }
})
