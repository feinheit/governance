// Everything in one bundle (rspack.config.js, {% rspack_assets "main" %} in
// base.html): Bootstrap's parts, the styles and the scripts of all pages,
// except the circle browser (Preact and d3), loaded only on its page
import "./styles/bootstrap.scss"
import "./styles/main.css"
import "./styles/icons.css"

import "./theme.js"
import "./mentions.js"
import "./show_more.js"
import "./open_details.js"
import "./autogrow.js"
import "./shortcuts.js"
// meeting.js first: it decides which links htmx boosts
import "./meeting.js"
import "htmx.org"
// Forms in a <dialog>, outside of the meeting's region its updates replace
import "./modal.js"

// The script is deferred, the page is parsed already
const circleBrowser = document.querySelector("#circle-browser")
if (circleBrowser) {
  import(/* webpackChunkName: "circles" */ "./circles/index.js").then(
    ({ mount }) => mount(circleBrowser),
  )
}
