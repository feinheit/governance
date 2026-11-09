// Forms in a modal like Workbench's, with a <dialog> and htmx: links with
// data-modal load their form with the HX-Modal header into the dialog, the
// form posts there (generic/object_form.html), saving loads the page the
// view redirects to (HX-Redirect, governance/modals.py). Without
// JavaScript, or with a modifier key, the links open the form's page.
import htmx from "htmx.org"

const HEADERS = { "HX-Modal": "true" }

let dialog = null
let initial = null
let lastEscape = Number.NEGATIVE_INFINITY

const serialize = () => {
  const form = dialog.querySelector("form")
  return form ? new URLSearchParams(new FormData(form)).toString() : null
}

function getDialog() {
  if (dialog) return dialog
  dialog = document.createElement("dialog")
  dialog.id = "modal"
  dialog.className = "wb-modal"
  dialog.setAttribute("aria-labelledby", "modal-title")
  document.body.append(dialog)

  dialog.addEventListener("close", () => {
    dialog.replaceChildren()
    initial = null
  })
  dialog.addEventListener("click", (event) => {
    if (event.target.closest("[data-modal-close]")) dialog.close()
  })
  // Escape (the dialog's close request, not when the mentions' list takes
  // it) closes the form as long as nothing has been changed, pressing it
  // again shortly after closes changed forms anyway
  dialog.addEventListener("cancel", (event) => {
    const repeated = event.timeStamp - lastEscape < 1500
    lastEscape = event.timeStamp
    if (initial !== null && serialize() !== initial && !repeated) {
      event.preventDefault()
      dialog.classList.add("wb-modal-shake")
      setTimeout(() => dialog.classList.remove("wb-modal-shake"), 300)
    }
  })
  return dialog
}

function focusFirstField() {
  const field =
    dialog.querySelector("[autofocus]") ||
    dialog.querySelector(
      ":is(input, select, textarea):not([type=hidden]):not([disabled])",
    )
  field?.focus()
}

document.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-modal]")
  if (
    !link ||
    event.defaultPrevented ||
    event.button !== 0 ||
    event.ctrlKey ||
    event.metaKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return
  }
  event.preventDefault()
  htmx.ajax("GET", link.href, {
    target: getDialog(),
    swap: "innerHTML",
    headers: HEADERS,
  })
})

const isModal = (event) => dialog && event.detail.ctx?.target === dialog

document.addEventListener("htmx:after:swap", (event) => {
  if (!isModal(event)) return
  if (!dialog.open) {
    dialog.showModal()
    focusFirstField()
    initial = serialize()
  }
})

// Confirmed in the meeting: the meeting reloads its region (HX-Location,
// proposals/drafting.py's done()), the dialog closes
document.addEventListener("htmx:after:request", (event) => {
  if (isModal(event) && event.detail.ctx.hx?.location) dialog.close()
})

// Errors (no permission, a server error) show the form's page
document.addEventListener("htmx:after:request", (event) => {
  if (!isModal(event) || event.detail.ctx.response.status < 400) return
  event.preventDefault()
  window.location.href = event.detail.ctx.request.action
})
document.addEventListener("htmx:error", (event) => {
  if (!isModal(event)) return
  window.location.href = event.detail.ctx.request.action
})
