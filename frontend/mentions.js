// Autocompleting @mentions of roles in textareas with data-mentions.
// Typing "@" and a part of a role's name lists the matching roles; picking
// one inserts "@[Name](role:ID)", which the markdown filter renders as a
// link with the role's current name. Without JavaScript the textareas
// stay plain textareas.

const MAX_RESULTS = 8
let roles = null

// Fetched once, the keystrokes before it arrives share the request
function loadRoles() {
  roles ??= fetch("/api/roles/", { credentials: "same-origin" })
    .then((response) => (response.ok ? response.json() : []))
    .then((list) => {
      for (const role of list) role.search = fold(role.name)
      return list
    })
  return roles
}

const fold = (text) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()

// The "@query" before the caret, if any: "@" at the start or after a
// space, no line break, not already a mention
function queryAt(textarea) {
  const before = textarea.value.slice(0, textarea.selectionStart)
  const match = /(?:^|\s)@([^@\n[\]()]{0,40})$/.exec(before)
  return match
    ? { query: match[1], start: before.length - match[1].length - 1 }
    : null
}

function matches(list, query) {
  const folded = fold(query.trim())
  const ranked = []
  for (const role of list) {
    const index = role.search.indexOf(folded)
    if (index >= 0) ranked.push([index === 0 ? 0 : 1, role])
  }
  ranked.sort((a, b) => a[0] - b[0] || a[1].name.localeCompare(b[1].name))
  return ranked.slice(0, MAX_RESULTS).map(([, role]) => role)
}

// Where a character of the textarea is (relative to its border box, not
// scrolled): a hidden copy with the same text styles, wrapped the same way
const MIRRORED = [
  "boxSizing",
  "width",
  "borderTopWidth",
  "borderRightWidth",
  "borderBottomWidth",
  "borderLeftWidth",
  "borderStyle",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "fontFamily",
  "fontSize",
  "fontStyle",
  "fontWeight",
  "lineHeight",
  "letterSpacing",
  "wordSpacing",
  "textIndent",
  "textTransform",
  "tabSize",
]

function caretPosition(textarea, index) {
  const style = getComputedStyle(textarea)
  const mirror = document.createElement("div")
  for (const property of MIRRORED) mirror.style[property] = style[property]
  Object.assign(mirror.style, {
    position: "absolute",
    top: "0",
    left: "-9999px",
    visibility: "hidden",
    overflow: "hidden",
    whiteSpace: "pre-wrap",
    overflowWrap: "break-word",
  })
  // Without the textarea's scrollbar
  const scrollbar = textarea.offsetWidth - textarea.clientWidth
  mirror.style.width = `${textarea.offsetWidth - scrollbar}px`
  mirror.style.boxSizing = "border-box"
  mirror.textContent = textarea.value.slice(0, index)
  const marker = document.createElement("span")
  marker.textContent = textarea.value[index] || "@"
  mirror.append(marker)
  document.body.append(mirror)
  const position = {
    top: marker.offsetTop + Number.parseFloat(style.borderTopWidth),
    left: marker.offsetLeft + Number.parseFloat(style.borderLeftWidth),
    height: marker.offsetHeight,
  }
  mirror.remove()
  return position
}

function attach(textarea) {
  const list = document.createElement("ul")
  list.className = "wb-mentions list-group"
  list.id = `${textarea.id || "mentions"}-mentions`
  list.setAttribute("role", "listbox")
  list.hidden = true
  textarea.after(list)
  textarea.parentElement.classList.add("position-relative")
  textarea.setAttribute("aria-autocomplete", "list")
  textarea.setAttribute("aria-controls", list.id)

  let results = []
  let active = 0
  let current = null

  const close = () => {
    list.hidden = true
    results = []
    textarea.removeAttribute("aria-activedescendant")
  }

  const render = () => {
    list.replaceChildren(
      ...results.map((role, index) => {
        const item = document.createElement("li")
        item.id = `${list.id}-${index}`
        item.className = `list-group-item list-group-item-action${index === active ? " active" : ""}`
        item.setAttribute("role", "option")
        item.setAttribute("aria-selected", index === active ? "true" : "false")
        const name = document.createElement("span")
        name.textContent = role.name
        const circle = document.createElement("small")
        circle.className = "wb-mentions-circle"
        circle.textContent = role.circle
        item.append(name, " ", circle)
        // mousedown keeps the focus in the textarea
        item.addEventListener("mousedown", (event) => {
          event.preventDefault()
          pick(role)
        })
        return item
      }),
    )
    list.hidden = !results.length
    if (results.length) {
      textarea.setAttribute("aria-activedescendant", `${list.id}-${active}`)
      place()
    }
  }

  // Below the line with the "@", starting at it, inside the textarea's
  // parent (which is relative)
  const place = () => {
    const caret = caretPosition(textarea, current.start)
    const top = Math.min(
      textarea.offsetTop + caret.top + caret.height - textarea.scrollTop,
      textarea.offsetTop + textarea.offsetHeight,
    )
    const left = textarea.offsetLeft + caret.left - textarea.scrollLeft
    const maxLeft = textarea.parentElement.clientWidth - list.offsetWidth
    list.style.top = `${top}px`
    list.style.left = `${Math.max(0, Math.min(left, maxLeft))}px`
  }

  const pick = (role) => {
    const mention = `@[${role.name}](role:${role.id}) `
    const end = textarea.selectionStart
    textarea.setRangeText(mention, current.start, end, "end")
    textarea.dispatchEvent(new Event("input", { bubbles: true }))
    close()
  }

  textarea.addEventListener("input", async () => {
    current = queryAt(textarea)
    if (!current) {
      close()
      return
    }
    const typed = current
    const available = await loadRoles()
    // Typed on in the meantime, or the "@" is gone
    if (current !== typed) return
    results = matches(available, typed.query)
    active = 0
    render()
  })

  textarea.addEventListener("keydown", (event) => {
    if (list.hidden) return
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault()
      const step = event.key === "ArrowDown" ? 1 : -1
      active = (active + step + results.length) % results.length
      render()
    } else if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault()
      pick(results[active])
    } else if (event.key === "Escape") {
      event.preventDefault()
      close()
    }
  })

  textarea.addEventListener("blur", close)
}

// Also textareas htmx inserts later, e.g. the forms amending a proposal in
// a meeting
export const attachAll = (root) => {
  for (const textarea of root.querySelectorAll("textarea[data-mentions]")) {
    if (textarea.dataset.mentionsAttached) continue
    textarea.dataset.mentionsAttached = "true"
    attach(textarea)
  }
}
attachAll(document)
document.addEventListener("htmx:after:process", (event) =>
  attachAll(event.target),
)
