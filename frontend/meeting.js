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
  const busy = Boolean(
    document.querySelector(
      "#meeting details[open], #amend > *, .sortable-chosen",
    ) || document.activeElement?.closest("#meeting form"),
  )
  busyChecks = busy ? busyChecks + 1 : 0
  const notice = document.getElementById("meeting-paused")
  if (notice) notice.hidden = busyChecks < 2
  return !busy
}

// Dragging the agenda's items (the secretary): SortableJS, a chunk of its own
if (document.getElementById("meeting")) {
  import(/* webpackChunkName: "agenda" */ "./agenda.js")
}
