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
// section open (merging would close it)
window.meetingIsIdle = () =>
  !document.hidden &&
  !document.querySelector("#meeting details[open], #amend > *") &&
  !document.activeElement?.closest("#meeting form")
