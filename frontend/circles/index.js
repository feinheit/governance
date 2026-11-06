// The circle browser: circles nested as circles (d3-hierarchy's circle
// packing), a small Preact island. Clicking a circle zooms in, clicking it
// again opens its page, the background or Escape zooms out, a role opens its
// page; ?circle=ID opens it zoomed in. Roles are colored
// as assigned, elected or unassigned; "My roles" highlights one's own. The
// page lists the same tree without JavaScript.
import { hierarchy, pack } from "d3-hierarchy"
import { render } from "preact"
import { useEffect, useMemo, useRef, useState } from "preact/hooks"

const SIZE = 1000
// Translated by the server, see governance/roles/browser.py
let labels = {}
const label = (text) => labels[text] || text
const reducedMotion = window.matchMedia?.(
  "(prefers-reduced-motion: reduce)",
).matches

function useAnimatedView(target) {
  const [view, setView] = useState(target)
  const current = useRef(target)
  useEffect(() => {
    const from = current.current
    if (reducedMotion) {
      current.current = target
      setView(target)
      return undefined
    }
    const start = performance.now()
    let frame
    const step = (now) => {
      const t = Math.min(1, (now - start) / 450)
      const ease = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2
      const next = from.map((value, i) => value + (target[i] - value) * ease)
      current.current = next
      setView(next)
      if (t < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [target])
  return view
}

// Core roles (and roles a policy makes elected) form one family; roles
// nobody holds are empty: "vacant" core roles, "unassigned" others (held by
// the Circle Lead)
function status(data) {
  if (data.kind === "circle") return "circle"
  const core = data.kind === "core" || data.elected
  if (!data.holders.length) return core ? "vacant" : "unassigned"
  return core ? "core" : "assigned"
}

function Legend() {
  return (
    <ul className="cb-legend">
      {[
        ["assigned", "Assigned"],
        ["core", "Core roles and elected roles"],
        ["unassigned", "Unassigned (held by the Circle Leads)"],
        ["lead", "Circle Lead"],
        ["mine", "Your roles"],
      ].map(([key, text]) => (
        <li key={key}>
          <svg width="18" height="18" aria-hidden="true">
            <circle
              cx="9"
              cy="9"
              r="7"
              className={`cb-swatch cb-${
                { mine: "assigned cb-mine", lead: "core" }[key] || key
              }`}
            />
            {key === "lead" ? (
              <circle cx="9" cy="9" r="4.5" className="cb-lead-ring" />
            ) : null}
          </svg>
          {label(text)}
        </li>
      ))}
    </ul>
  )
}

function CircleBrowser({ data }) {
  const root = useMemo(
    () =>
      pack()
        .size([SIZE, SIZE])
        .padding((node) => (node.depth === 0 ? 12 : 5))(
        hierarchy(data, (node) => node.children).count(),
      ),
    [data],
  )
  const myRoles = useMemo(
    () =>
      root
        .descendants()
        .filter((node) => node.data.mine && node.data.kind !== "circle"),
    [root],
  )
  // "My roles" grouped by their circle, in the organization's order
  const myCircles = useMemo(() => {
    const groups = new Map()
    for (const node of myRoles) {
      groups.set(node.parent, [...(groups.get(node.parent) || []), node])
    }
    return [...groups]
  }, [myRoles])
  // ?circle=ID opens the browser zoomed into that circle, zooming keeps
  // the URL up to date so that reloading and links keep the place
  const [focus, setFocusState] = useState(() => {
    const id = new URLSearchParams(window.location.search).get("circle")
    return (
      root.find(
        (node) => node.data.kind === "circle" && `${node.data.id}` === id,
      ) || root
    )
  })
  const setFocus = (node) => {
    setFocusState(node)
    const url = new URL(window.location.href)
    if (node === root) url.searchParams.delete("circle")
    else url.searchParams.set("circle", node.data.id)
    window.history.replaceState(null, "", url)
  }
  const [onlyMine, setOnlyMine] = useState(false)
  const [tooltip, setTooltip] = useState(null)
  // The role chosen in "My roles" pulses after zooming in; the count
  // restarts the animation when choosing it again
  const [highlight, setHighlight] = useState(null)
  useEffect(() => {
    if (!highlight) return undefined
    const timeout = setTimeout(() => setHighlight(null), 3000)
    return () => clearTimeout(timeout)
  }, [highlight])
  const target = useMemo(() => [focus.x, focus.y, focus.r * 2], [focus])
  const [vx, vy, vw] = useAnimatedView(target)
  const k = SIZE / vw
  const position = (node) => ({
    cx: (node.x - vx) * k + SIZE / 2,
    cy: (node.y - vy) * k + SIZE / 2,
    r: node.r * k,
  })
  // Circles containing one of my roles stay visible when only mine show
  const onMyPath = useMemo(
    () => new Set(myRoles.flatMap((node) => node.ancestors())),
    [myRoles],
  )

  const activate = (node) => {
    if (node.data.kind !== "circle" || node === focus) {
      // Roles open their page, the circle zoomed into too
      window.location.href = node.data.url
    } else {
      setFocus(node)
    }
  }
  const zoomOut = () => focus.parent && setFocus(focus.parent)

  const nodes = root.descendants().filter((node) => node.r * k >= 1)
  const labelled = new Set(focus.children || [focus])

  return (
    <div className="cb">
      <nav className="cb-path" aria-label={label("Path")}>
        {focus
          .ancestors()
          .reverse()
          .map((node) => (
            <button
              key={node.data.id}
              type="button"
              className="btn btn-sm btn-quiet"
              onClick={() => setFocus(node)}
              aria-current={node === focus ? "true" : undefined}
            >
              {node.data.name}
            </button>
          ))}
        <a className="btn btn-sm btn-primary" href={focus.data.url}>
          {label("Open the circle's page")}
        </a>
        <button
          type="button"
          className={`btn btn-sm ms-auto ${onlyMine ? "btn-primary" : "btn-quiet"}`}
          aria-pressed={onlyMine ? "true" : "false"}
          onClick={() => setOnlyMine(!onlyMine)}
        >
          {label("My roles")}
        </button>
      </nav>
      <div className="cb-canvas">
        <div className="cb-side cb-side-start">
          <Legend />
        </div>
        {onlyMine ? (
          <div className="cb-side cb-side-end cb-mine-list">
            {myRoles.length
              ? myCircles.map(([circle, nodes]) => [
                  <div
                    key={`circle-${circle.data.id}`}
                    className="cb-mine-circle"
                  >
                    {circle.data.name}
                  </div>,
                  ...nodes.map((node) => (
                    <button
                      key={node.data.id}
                      type="button"
                      className="btn btn-sm btn-quiet"
                      onClick={() => {
                        setFocus(node.parent)
                        setHighlight({
                          node,
                          count: (highlight?.count || 0) + 1,
                        })
                      }}
                    >
                      {node.data.name}
                    </button>
                  )),
                ])
              : label("You hold no roles.")}
          </div>
        ) : null}
        <svg
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          role="img"
          aria-label={focus.data.name}
          onClick={zoomOut}
          onKeyDown={(event) => {
            if (event.key === "Escape") zoomOut()
          }}
          onMouseLeave={() => setTooltip(null)}
        >
          {/* The highlighted role last, it grows over its neighbors */}
          {[
            ...nodes.filter((node) => node !== highlight?.node),
            ...nodes.filter((node) => node === highlight?.node),
          ].map((node) => {
            const { cx, cy, r } = position(node)
            const kind = status(node.data)
            const interactive = node.parent === focus
            const dimmed =
              onlyMine &&
              !(kind === "circle" ? onMyPath.has(node) : node.data.mine)
            return (
              // biome-ignore lint/a11y/useSemanticElements: SVG has no buttons, the list below the circles is the accessible view
              <circle
                key={`${node.data.kind}-${node.data.id}${highlight?.node === node ? `-${highlight.count}` : ""}`}
                cx={cx}
                cy={cy}
                r={r}
                className={[
                  "cb-node",
                  `cb-${kind}`,
                  `cb-depth-${Math.min(node.depth, 4)}`,
                  node.data.mine && kind !== "circle" ? "cb-mine" : "",
                  dimmed ? "cb-dimmed" : "",
                  highlight?.node === node ? "cb-highlight" : "",
                  // Clicking opens the page or zooms out, not in
                  node === focus ? "cb-current" : "",
                  node !== focus && focus.ancestors().includes(node)
                    ? "cb-outer"
                    : "",
                ].join(" ")}
                role="button"
                aria-label={node.data.name}
                tabIndex={interactive ? 0 : -1}
                onClick={(event) => {
                  event.stopPropagation()
                  activate(node)
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault()
                    activate(node)
                  }
                }}
                onMouseMove={(event) => {
                  const box =
                    event.currentTarget.ownerSVGElement.parentNode.getBoundingClientRect()
                  setTooltip({
                    node,
                    x: event.clientX - box.left,
                    y: event.clientY - box.top,
                    width: box.width,
                    height: box.height,
                  })
                }}
              />
            )
          })}
          {nodes
            .filter((node) => node.data.lead)
            .map((node) => {
              // The Circle Lead: an inner ring in the surface color
              const { cx, cy, r } = position(node)
              return (
                <circle
                  key={`lead-${node.data.id}`}
                  cx={cx}
                  cy={cy}
                  r={Math.max(1, r - Math.max(3, r * 0.1))}
                  className={`cb-lead-ring${onlyMine && !node.data.mine ? " cb-dimmed" : ""}`}
                />
              )
            })}
          {nodes
            .filter((node) => labelled.has(node))
            .map((node) => {
              const { cx, cy, r } = position(node)
              if (r < (node.data.kind === "circle" ? 50 : 24)) return null
              const circle = node.data.kind === "circle"
              // Circle labels sit near the top, where the circle is narrower
              const width = circle
                ? 2 * Math.sqrt(r * r - (r - 26) ** 2)
                : r * 2
              const maxChars = Math.max(
                3,
                Math.floor(width / (circle ? 11 : 9)),
              )
              const name =
                node.data.name.length > maxChars
                  ? `${node.data.name.slice(0, maxChars - 1)}…`
                  : node.data.name
              let holders =
                !circle && r > 70 ? node.data.holders.join(", ") : ""
              const maxHolderChars = Math.floor((r * 1.7) / 7.5)
              if (holders.length > maxHolderChars) {
                holders = `${holders.slice(0, maxHolderChars - 1)}…`
              }
              return (
                <text
                  key={`label-${node.data.kind}-${node.data.id}`}
                  x={cx}
                  y={circle ? cy - r + 26 : holders ? cy - 10 : cy}
                  className={`cb-label cb-label-${status(node.data)}`}
                  text-anchor="middle"
                  dominant-baseline="middle"
                >
                  {name}
                  {holders ? (
                    <tspan x={cx} dy={22} className="cb-label-holders">
                      {holders}
                    </tspan>
                  ) : null}
                </text>
              )
            })}
        </svg>
        {tooltip ? <Tooltip {...tooltip} /> : null}
      </div>
    </div>
  )
}

// Next to the mouse, on its other side near the right and bottom edges.
// Preact 11 doesn't add "px" to numbers.
function Tooltip({ node, x, y, width, height }) {
  const { data } = node
  const kind = status(data)
  const flipX = x > width - 300
  const flipY = y > height - 160
  const style = {
    [flipX ? "right" : "left"]: `${(flipX ? width - x : x) + 14}px`,
    [flipY ? "bottom" : "top"]: `${(flipY ? height - y : y) + 14}px`,
  }
  return (
    <div className="cb-tooltip" style={style}>
      <div className="fw-semibold">{data.name}</div>
      {kind === "circle" ? (
        <div className="text-body-secondary small">
          {/* Its own roles, a sub-circle counts as one */}
          {node.children?.length || 0} {label("roles")}
        </div>
      ) : (
        <div className="text-body-secondary small">
          {data.holders.length
            ? data.holders.join(", ")
            : label("Held by the Circle Leads")}
          {data.elected ? ` · ${label("elected")}` : ""}
        </div>
      )}
    </div>
  )
}

// Loaded by main.js only on the page with the circle browser
export function mount(element) {
  const data = document.querySelector("#circle-tree")
  if (!data) return
  labels = JSON.parse(
    document.querySelector("#circle-labels")?.textContent || "{}",
  )
  // The list stays as the accessible view, closed when the circles show
  document.querySelector("#circle-list")?.removeAttribute("open")
  render(<CircleBrowser data={JSON.parse(data.textContent)} />, element)
}
