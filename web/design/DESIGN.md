# ARPA Data Hub: design brief

Reuse the look, layout and behaviour of the ARPA Data Hub dashboard in another project.

## How to use these files

| File | Role |
|---|---|
| `DESIGN.md` | The intent: principles, tokens, rules, behaviour. Read first. |
| `ui.css` | The whole look in one stylesheet (tokens, base, components, overview, responsive). **Source of truth for every value.** Include it as is. |
| `kit.html` | Catalogue: every component once, with fake data. Copy the markup of a block, keep its classes. |
| `app-shell.html` | A working mini app (router, sticky bar, tables that fit the screen, patient window, live updates). Copy the patterns. |
| `fonts/` | Hanken Grotesk (200 to 600) and Geist Mono (400, 500). Optional but needed for the exact look. |

When asked to build a screen: start from the closest block in `kit.html`, reuse the classes of `ui.css`, add no colour, radius, font or shadow that is not listed here. If something is missing, compose it from existing pieces before adding CSS, and put the new CSS in a separate file, never in `ui.css`.

## 1. Character

Editorial, laboratory-instrument look. **Black hairlines on white**, big LIGHT titles, small mono UPPERCASE labels, generous whitespace, almost no shadow. Colour is information, never decoration.

- Chrome (frames, text, borders) is black and white. A single 1 px black line (`--ink`) draws every box.
- Colour appears only for **states** (mint ok, butter warning, rose failed, sky info), **where you are** (lime), and the **simulation bar** (pink). Nothing else is coloured.
- Big things are light (weight 200 to 300). Labels, numbers, ids and buttons are mono.
- Calm and dense: data is shown, not explained. Clicking reveals detail; the first view stays clean.

## 2. Tokens (`:root` in `ui.css`)

```
--bg #fff  --tint #f3f5f2  --ink #0a0a0a  --text #161616  --muted #575b58  --line #d7dbd6
--mint #b9ecd0 (ok)  --butter #f6e58d (warn)  --rose #f7b9c7 (failed)  --sky #bcd6ff (info)
--lime #d6f55f (you are here: current nav, selected row, hover)  --pink #ff3fd0 (simulation only)
--r 12px (boxes)  --rs 8px (fields, buttons)  99px (pills)  --gut clamp(16px,2.4vw,32px)  --maxw 1360px
--sans Hanken Grotesk  --mono Geist Mono
```

Matrix cell colours, Overview only (`overview.css`): `k-v` green `#7fd6a3`, `k-y` yellow `#f3d35c`, `k-m` grey `#d3d6d1`; another party's data is pale: `k-pg` `#d8f1e2`, `k-pm` `#eff1ee`. Each has an edge colour `--e`.

**Type**

| Use | Style |
|---|---|
| Page title `.t1` | 300, `clamp(38px,4.8vw,60px)`, line-height .96, letter-spacing -.045em. **Same size on every page.** |
| Hero id (window) | 200, 44 px |
| `.big`, `.big-name` | 300, 22 px |
| Box title `.plate-h h2` | 400, 21 px |
| Body | 400, 15 px / 1.55 |
| `.sub` | 13 px, muted |
| Labels `.lab`, `.dk`, `.rec-l`, table heads | mono 500, 10.5 to 11 px, UPPERCASE, letter-spacing .08 to .1em, muted |
| Buttons, nav, chips | mono 500, 11 to 12 px, UPPERCASE (chips are not uppercase) |
| Ids, dates, file names | `.mono` |

## 3. Layout

```
.chrome (sticky, frosted)  >  header.cells.top :  .brand | nav#nav (.na, current = .on lime) | .who (id + sign out)
.frame (max 1360, side gutter --gut)  >  .cells.sim (pink bar, optional)  +  main
main  >  .head (title + optional right block)  >  one or more .plate / .ov-card
```

- **`.cells`** is the signature: a row of cells separated by 1 px black gaps, framed by a 1 px black border, 12 px radius. The top bar and the simulation bar use it.
- **`.plate`** is the basic box: black 1 px border, 12 px radius, `.plate-h` (title row, black rule under), then one or more `.plate-b` (20 px padding; `.flush` = no padding, `.tint` = grey). Stacked `.plate-b` get a black rule between them. Inside the patient window the rules are dashed `#c9cdc7`.
- **Page head** `.head`: light title on the left, an optional block on the right (the colour legend, a figure). One title per page, nothing above it.
- **A page that fits the screen**: the list lives in a `.fill` box whose `max-height` is "what is left under it" (`fitFill`, see `app-shell.html`). The **box scrolls, not the page**. Header row and first column are sticky.
- Widths: content is capped at 1360 px and centred. Below 1000 px figures go two per row; below 640 px one column, the nav becomes a sideways-scrolling row, tables scroll under a frozen first column, every field is 16 px (iOS zoom). All of it is in `responsive.css` (already in `ui.css`).

## 4. Components (see `kit.html`)

| Need | Markup / class |
|---|---|
| Status | `<span class="st ok|warn|bad|sky|ink">Text</span>`; none = neutral. One wording per state everywhere (Validated, Received, QC failed, Rejected, Missing). |
| Button | `.btn` (+ `.solid` black, `.sm`, `.danger`); `.go` = label + black arrow square (primary action); `.opt` pill toggle (`.on` = black); `.link` underlined text; `.plate-x` round close button |
| Field | `.field > label.lab + input` (44 px, 1 px black border, 8 px radius). Several in a `.row`. |
| Dropdown | `.dd > button.dd-btn + ul.dd-list > li.dd-opt` (mono uppercase rows, a small dot marks the selection). `.dd.sm` for filters. Never use a native `<select>` for user-facing choices. |
| Search by sentence | `.lg-ask` (input + button), understood filters shown as removable `.lg-chip` (lime pill with a round `×`) |
| Key / value | `.dr > .dk + .dv` |
| Note | `.note`, `.note.warn`, `.note.bad` |
| Flag list | `ul.flaglist > li` = chip (`bad` for error, `warn` for warning) + message |
| Table | `.tbl` (rows `.click`, selected `.sel` lime); in a `.fill` box for a frozen header; `.pager` under it |
| Progress | `.bar`, `.simtrack`, `.ov-track` (all: 10 px or 8 px pill, black outline) |
| Cell | `.cell` (+ `v p q x m e n`), 26 px; matrix cells `.ov-c` + `k-*` |
| Window | `.pw-overlay > .pw-back + .pw` (900 px, 16 px radius). Locks page scroll. Escape and backdrop close it. |
| Record | `.plate.record.pw-sheet`: title and status, `.rec-grid`, `.rec-flags`, `.rec-feat`, `.rec-ver` |
| Loader | `.loading > .spin > svg` four squares changing colour (the logo) |
| Calendar | `.cal` (home-made, click to pick; the native date input is not used) |
| Simulation bar | `.cells.sim` with `.sim-lab .sim-play .sim-step .sim-speed .sim-track .sim-count .sim-word .sim-rst`; `.play` is the black pill button with a lime round icon |

The Overview matrix: one CSS grid per row with the same `grid-template-columns` as the header (`104px` id column, then one column per modality: fixed cells of 22 px with 4 px gaps when few, a `minmax(300px,1fr)` strip of thin cells when many). Header cell = name + percentage on one line, a lime progress bar on a black-outlined track under it. No filter chips. Legend of three entries only (VALIDATED, FAILED OR INCOMPLETE, MISSING, uppercase, top right of the title row).

## 5. Behaviour rules (the UX)

1. **Nothing jumps.** When data arrives while the person reads, the page updates **in place**: scroll position, open window, open record, open entry, filters and page offset all stay. Never rebuild a page for a data tick. Pattern in `app-shell.html` (`ctx.refresh`): a page registers a `refresh()`; the app calls it instead of re-rendering; only a full reset rebuilds.
2. **Do not shift rows under the reader.** In a list with the newest on top, if the reader is not at the top of the first page (or has an item open), do not insert rows: show a `N new entries, show` button in the pager. At the top with nothing open, update live.
3. **Old content stays until the new is ready** (no loading flash on the same page). A new page starts at the top; the same page keeps its scroll.
4. **Detail on click, not up front.** The patient window shows only coloured cells and counts, no flag text. A yellow or rose cell opens the record, which lists the flags (errors first, chip + message). Counts of flags are not shown on list pages.
5. **One route per place**, state in the URL hash (`#/ledger?seq=618`, `#/overview?patient=ARPA_004`) so a reload or a link restores it. Opening and closing use `history.replaceState`.
6. **Escape closes** the topmost thing (window, entry). Focus goes to the close button when a window opens.
7. **Dangerous action = two steps** (first click asks "are you sure", second does it, falls back after 6 s).
8. **Loading** is the four-square logo, centred in the space the page will take. No text such as "Reading the data".
9. **Wording**: short, English, no marketing, no em dashes. Same word for the same state on every page.
10. **Simulated data is always visibly pink.** Real data never shows the pink bar.

## 6. Accessibility

Every control is a real `button`, `a`, `input`. Visible focus is a 2 px black outline with 2 px offset. Touch fields are 16 px. Colour is never the only carrier: cells have titles, rows have `aria-label`, dialogs have `role="dialog" aria-modal`, lists of options have `role="listbox"`. `prefers-reduced-motion` stops animations (already in `base.css`).

## 7. Implementation notes

- Vanilla ES modules, no framework. A 10-line `h(tag, attrs, ...children)` builds DOM (`app-shell.html`). Pages are `async render(root, ctx, route)`. `mount(el, ...kids)` replaces children.
- `fitFill(el)` must tolerate being called **before the page is mounted** (wait until `el.isConnected`). A version that gave up on the first frame made a table lose its height and stop scrolling.
- Windows and menus are appended to `<body>` and removed when their page goes away (a `MutationObserver` on the page root).
- Dropdown panels and the calendar are `position: fixed` and placed from the button's rectangle so no card clips them.
- Fonts are served locally (no CDN) so the look is identical offline.

## 8. Do not

- Add colours (a new accent, gradients, dark mode), shadows other than the menu/panel shadow (`0 18px 40px -16px rgba(10,10,10,.35)`), or radii other than 12 / 8 / 99 (16 for the window).
- Use native `select` or `input[type=date]` for visible choices.
- Show filter chips on the Overview, or explanatory sentences under titles.
- Put different title sizes on different pages.
- Re-render a page on a timer, or let a live update close what the user opened.
- Spell labels in lowercase mono or title-case mono: mono labels are UPPERCASE.

## 9. Prompt to give another project

> Build the UI with the design in `DESIGN.md`. Include `ui.css` unchanged (and `fonts/`). Use the markup and classes of `kit.html` for components and the structure and live-update pattern of `app-shell.html`. Do not add colours, radii or fonts. Pages must update in place when data changes (scroll, open windows and records stay).
