// The secretary drags the agenda's items by their handles
// (meetings/_agenda.html): dropping one posts the new order with the hidden
// form, which htmx sends like the meeting's other forms. SortableJS is set up
// when a handle is first pressed: the meeting's updates replace the list.
import Sortable from "sortablejs"

document.addEventListener(
  "pointerdown",
  (event) => {
    const list = event.target
      .closest("[data-agenda-handle]")
      ?.closest("[data-agenda-sortable]")
    if (!list || list.sortable) return
    list.sortable = Sortable.create(list, {
      handle: "[data-agenda-handle]",
      draggable: "[data-agenda-item]",
      onEnd(event) {
        if (event.oldIndex === event.newIndex) return
        const form = document.querySelector("[data-agenda-order]")
        for (const input of form.querySelectorAll("input[name=ids]")) {
          input.remove()
        }
        for (const item of list.querySelectorAll("[data-agenda-item]")) {
          const input = document.createElement("input")
          input.type = "hidden"
          input.name = "ids"
          input.value = item.dataset.agendaItem
          form.append(input)
        }
        form.requestSubmit()
      },
    })
  },
  true,
)
