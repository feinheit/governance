// Lists reordered by dragging their items' handles (SortableJS, a chunk of
// its own): the agenda (meetings/_agenda.html, the secretary) and a role's
// accountabilities (roles/role_detail.html, everyone). The list's
// data-sortable names the hidden form posting the new order (ids), which
// htmx sends in the meeting; with data-sortable-quiet it's sent in the
// background, the page stays as it is. SortableJS is set up when a handle
// is first pressed: the meeting's updates replace the list. Without
// JavaScript the arrows move the items.
import Sortable from "sortablejs"

function submit(form) {
  if (form.hasAttribute("data-sortable-quiet")) {
    fetch(form.action, { method: "POST", body: new FormData(form) })
  } else {
    form.requestSubmit()
  }
}

document.addEventListener(
  "pointerdown",
  (event) => {
    const list = event.target
      .closest("[data-sortable-handle]")
      ?.closest("[data-sortable]")
    if (!list || list.sortable) return
    list.sortable = Sortable.create(list, {
      handle: "[data-sortable-handle]",
      draggable: "[data-sortable-item]",
      onEnd(event) {
        if (event.oldIndex === event.newIndex) return
        const form = document.querySelector(list.dataset.sortable)
        for (const input of form.querySelectorAll("input[name=ids]")) {
          input.remove()
        }
        for (const item of list.querySelectorAll("[data-sortable-item]")) {
          const input = document.createElement("input")
          input.type = "hidden"
          input.name = "ids"
          input.value = item.dataset.sortableItem
          form.append(input)
        }
        submit(form)
      },
    })
  },
  true,
)
