# JCF Organic Shop Manager — UI/UX review

**Review date:** 23 August 2026  
**Reference:** Paces Bootstrap template, **SaaS** skin, at
`/Users/kami/websites/Paces/coderthemes.com/paces/bootstrap`  
**Application reviewed:** local Django application at `http://127.0.0.1:8000`  
**Scope:** review and recommendations only. No application code was changed.

## Review method and evidence

This review combined a live walkthrough with source inspection. It did not treat passing tests as
proof of usability.

- Read `README.md`, `docs/SHOP-GUIDE.md`, URL configuration, templates, forms, `theme.css`,
  `app.js`, and `pos.js`.
- Inspected the Paces SaaS skin preview, layout controls, typography, card, table, form, navigation,
  and dashboard patterns.
- Used the seeded data: 18 products, six categories, four suppliers, hundreds of sales, low/out-of-
  stock products, batches, adjustments, and both roles.
- Signed in as owner (`ama`) and shopkeeper (`kofi`).
- Reviewed the application at 320, 375, 768, 1024, and 1440 CSS pixels.
- Visited every application area reachable from the main navigation, plus product/supplier/sale
  details, create/edit forms, receipt, confirmation, empty, validation, offline, and permission-
  denied states.
- Completed and then reversed test sale `S260823-0302`. The sale recorded GH₵24.00 cash, showed
  GH₵26.00 change from GH₵50.00, and restored the item to stock after reversal. This left a truthful
  reversed transaction in the demo audit history; stock returned to its starting quantity.
- Tested an invalid sign-in, product and POS no-result searches, an out-of-stock POS result,
  multi-item cart changes, the over-stock guard, cash/change calculation, receipt, reversal
  validation, delivery review, and adjustment review.
- Ran the full Django suite: **173 tests passed in 3.17 seconds**.

Important evidence from responsive measurement:

- No page caused document-level horizontal overflow at the tested sizes.
- The 375px owner dashboard was about 4,303px tall.
- The 320px sales history was about 8,118px tall; stock history was about 11,332px tall.
- Several secondary analytical tables use controlled horizontal scrolling. At 320px, rendered
  table widths ranged from about 463px to 666px inside a 305px content area.
- At 320px, product detail contains three horizontally scrolling tables; the batch table measured
  about 533px inside a 305px content area.
- Visible mobile control heights commonly measured 34px for chips, 36–38px for icon/small buttons,
  and 38px for card actions.
- `--ink-500` (`#75847d`) is 3.92:1 on white and `--ink-400` (`#9aa8a1`) is 2.47:1 on white.
  Both are used for small text; they fail 4.5:1 WCAG AA contrast for normal text.

## 1. Executive summary

The application is substantially better than a typical first-pass admin theme. It has a coherent
organic identity, unusually clear transaction language, strong role separation, reliable review
steps, and a genuinely efficient point-of-sale foundation. The Paces SaaS influence is visible in
the floating desktop shell, quiet cards, compact type scale, tinted statuses, and restrained
shadows, but it has been adapted rather than copied.

The shopkeeper can learn and perform the main laptop workflows without formal training. Search,
quick picks, keyboard support, cart persistence, stock limits, totals, payment choices, change due,
and reversal history are all understandable. The complete sale took no unnecessary page
transitions until confirmation and produced unambiguous success and receipt states.

The owner's phone experience is usable but not launch-polished. The first dashboard viewport is
good; the main figures are immediately visible. The deeper owner experience becomes long and
dense. Report navigation plus date controls consume most of the first viewport, several tables
require un-signposted horizontal gestures, and history screens can become 6,000–11,000px tall.

The reference-template quality is captured successfully in the shell and component finish. It is
less successful where the implementation inherits the template's small secondary text, compact
controls, and desktop-table mindset. Those patterns are acceptable in a theme demo, but not for an
owner working from a phone or a shopkeeper moving quickly at a till.

The five most important improvements are:

1. Recompose owner reports and histories for mobile so the result appears before navigation and
   advanced filters; introduce compact mobile summaries and deliberate table/card patterns.
2. Make offline messaging truthful. Only the POS cart is locally persisted; the global message
   currently promises that all work is saved on the device.
3. Raise muted-text contrast and mobile target sizes to practical WCAG 2.2 AA expectations.
4. Hide or transform the POS mobile mini-cart once the user reaches the checkout panel so it does
   not cover payment, change, note, and completion controls.
5. Standardize semantic page headings, loading announcements, mobile filters, responsive tables,
   and action placement as reusable components rather than page-specific fixes.

## 2. Scorecard

| Area | Score | Reason |
|---|---:|---|
| Visual design | 8/10 | Calm, warm, consistent, and clearly adapted to the shop. Small muted text and repeated card/chip patterns reduce distinction. |
| Information architecture | 8/10 | Daily work, inventory, insight, and owner areas are predictable. Reports are a little flat and overexposed on mobile. |
| Navigation | 8/10 | New Sale is always prominent; desktop and mobile navigation are clear. Report sub-navigation becomes a dense three-row block. |
| Shopkeeper usability | 8/10 | Main workflows are plain, guarded, and learnable. Long stock forms and history pages could be faster. |
| Owner mobile experience | 6/10 | Dashboard headline data works well; reports, histories, tables, filters, and long pages need a mobile-first pass. |
| Point-of-sale efficiency | 9/10 | Search, scan, quick picks, keyboard shortcuts, live totals, quick cash, stock guard, and persistent cart are strong. The mobile checkout overlay is the main defect. |
| Forms | 8/10 | Labels, required/optional language, help, validation, and review steps are strong. Mobile form length and action visibility need improvement. |
| Tables and data presentation | 6/10 | Desktop tables are legible and use tabular figures. Mobile conversion is inconsistent; horizontal tables lack scroll cues and sticky context. |
| Responsiveness | 7/10 | No document overflow at the tested sizes and major layouts reflow correctly. Mobile density and content order remain weak in owner views. |
| Accessibility | 6/10 | Good labels, captions, focus styles, status text, reduced motion, and landmarks. Contrast, target sizes, duplicate H1s, and idle loading semantics need work. |
| Error handling | 8/10 | Specific inline errors, preserved login name, confirmation steps, stock prevention, 403, and no-result states are good. Offline promises are misleading. |
| Design consistency | 8/10 | Tokens and shared partials produce consistent cards, badges, forms, and actions. Table/mobile behaviour is the main inconsistency. |
| Trust and professionalism | 8/10 | Totals, actor/time, receipts, immutable reversal, and profit caveats inspire trust. Offline language is a material exception. |
| Overall UI/UX | 7/10 | A strong operational product that needs a focused mobile-accessibility hardening pass before launch. |

## 3. What currently works well

### Operational clarity

- The navigation uses the shop's vocabulary: **New sale**, **Receive stock**, **Stock adjustments**,
  and **Stock history**. It does not expose Django or accounting implementation terms.
- Owner-only destinations are grouped and completely absent from the shopkeeper navigation.
- The custom 403 state says why access is denied and gives a direct route back to the dashboard.

### Point of sale

- The search field is the obvious starting point, is keyboard-focused on laptop, accepts name,
  code, or barcode, and supports `/` and Enter.
- Quick picks show price and live availability without opening product details.
- Out-of-stock products remain visible as disabled results, explaining why they cannot be added.
- An impossible quantity shows the exact available stock and disables completion.
- Cash, Mobile Money, and Bank Transfer are visually distinct full-card targets.
- Quick-cash amounts, exact payment, and live change due are appropriate for a Ghanaian walk-in
  shop.
- The basket survives refresh, uses an idempotency key, guards double submission, and returns the
  cart after a server rejection.
- Completion is unambiguous: amount, sale number, payment, change, actor, time, receipt, and next
  sale are all present.

### Inventory integrity and recovery

- Receiving and adjustment flows use a review step that explicitly says nothing has been saved.
- Confirmation shows before/after stock, quantity direction, batch choice, cost, supplier, and
  reason.
- Sale reversal does not pretend to delete history. It explains the new stock movements, requires
  a permanent reason and acknowledgement, and shows both the sale and reversal in the ledger.
- The product detail and sale detail screens connect current stock, batches, sales, costs, and
  ledger movements, supporting auditability.

### Reporting and local appropriateness

- GH₵ is consistently used in the interface and receipts.
- Dates are locally understandable (`23 Aug 2026`, `23/08/2026`) and the application is configured
  for `Africa/Accra`.
- Profit reporting repeatedly says **estimated gross profit**, explains cost of goods sold, and
  states that rent, wages, transport, electricity, taxes, and other expenses are excluded.
- Payments include Cash, Mobile Money, and Bank Transfer.
- Figures use a separate numeric typeface with tabular numerals, improving comparison in tables.

### States and accessibility foundations

- Login errors are specific and preserve the username.
- Product and POS no-result states explain what happened and provide a next action.
- Empty expiry states explain the warning window rather than showing a blank card.
- Tables generally have hidden captions, inputs have explicit labels, required fields include
  text as well as an asterisk, and statuses include words instead of relying on colour alone.
- Keyboard focus is visible and reduced-motion preferences are respected.

## 4. Reference-template assessment

### Paces Bootstrap — SaaS skin

The supplied template contains many products and layouts, but the named reference is a selectable
skin rather than a separate application. Its preview shows a compact dashboard inside a softly
rounded shell, a dark sidebar, a dense top bar, white cards, pastel status colours, charts, tables,
and small utility typography.

Strong ideas worth preserving:

- The clear application shell and stable desktop navigation.
- Quiet surfaces, thin borders, restrained shadows, and consistent radius.
- Compact but deliberate typography and aligned data figures.
- One accent colour with soft tinted status backgrounds.
- Metrics grouped with operational tables instead of a decorative marketing hero.
- Predictable page headers, filter panels, forms, and data tables.

Patterns suitable only after adaptation:

- Dense desktop tables are appropriate for secondary analysis, but mobile needs priority cards,
  sticky context, or explicit scroll affordance.
- Small labels can support hierarchy only when they still meet contrast and readability needs.
- Dashboard metric cards are useful when they answer a shop question or link to an action.

Patterns that should not be copied:

- Global search, mega menus, notifications, theme switchers, and other enterprise chrome.
- Decorative charts, radial widgets, gradients, and multi-colour accents.
- The template's blue/purple financial-product palette.
- Theme-level interaction density, 13px body text, and tiny table actions.
- Large numbers of dashboard cards without a clear operational decision attached.

How effectively the current product uses the reference:

- **Successful:** the floating shell, Poppins typography, white surfaces, soft background, quiet
  border/shadow system, tinted active navigation, status pills, card padding, and compact page
  headers clearly reflect the SaaS skin.
- **Successful adaptation:** blue was replaced with deep leaf green; Inter is used only for
  numeric alignment; enterprise navigation was removed; charts are mostly replaced by simple
  meters and ranked lists.
- **Negative divergence:** the current small muted text is even less accessible against warm
  neutrals than it appears in the template preview. Some mobile pages expose the template's
  desktop-first table density without sufficient transformation or guidance.
- **Identity gap:** repeated white cards and chips occasionally make reports feel like a themed
  admin product. The most distinctive JCF pattern should be the **stock story**—clear before/after
  quantities, expiry urgency, and actor/reason/time—rather than more card decoration.

## 5. Critical workflow review

### Login

**Goal:** enter a trustworthy, focused system quickly.

- Works: single-purpose page, clear shop identity, useful placeholder, password reveal, specific
  invalid-credential message, preserved username, and good 375px layout.
- Friction: placeholder and explanatory copy are too low-contrast; the password reveal button is
  34px high.
- Recommendation: strengthen muted/placeholder contrast and make the reveal control at least
  44px high on touch devices.

### Dashboard

**Goal:** understand today and act on urgent stock issues.

- Works: owner sees sold today, estimated profit, low stock, expiry, week/month, and stock value;
  shopkeeper sees a reduced operational set. New Sale and Receive Stock are prominent.
- Friction: the 375px page is over 4,300px tall. Running-low and recent-sales desktop tables are
  horizontally scrollable on mobile rather than being prioritized lists. Activity and best-seller
  context is far below the fold.
- Recommendation: retain the first metric viewport, then use compact five-row lists with “See all.”
  Put unusual adjustments/recent activity before generic rankings for the owner.

### New Sale

**Goal:** find products, build a basket, take payment, and start the next sale.

- Works: this is the strongest workflow. Search, scan, quick picks, Enter-to-add, quantity controls,
  removal, stock blocking, payment methods, cash/change, persistent cart, review, receipt, and next
  sale all work.
- Friction: on mobile, the fixed mini-cart remains above the tab bar after it has scrolled the user
  to the checkout panel. It covers lower checkout content and duplicates information already in
  view. The cart begins after all quick picks, so checkout is naturally far down the page.
- Recommendation: when the cart panel intersects the viewport, collapse the mini-cart to a small
  back-to-products control or hide it. On phones, show search plus two quick-pick rows, then a clear
  cart/checkout section. Keep the full quick-pick list behind “Show more.”

### Product management

**Goal:** find, add, edit, inspect, and deactivate products safely.

- Works: filters are relevant, statuses use text, mobile list becomes useful cards, and product
  detail exposes stock, value, batches, movements, and sales.
- Friction: the 320px product list becomes a 5,185px card stream. Product detail has three separate
  horizontal tables and is about 4,850px tall. Long names wrap but create uneven card density.
- Recommendation: use compact rows for the mobile list (name/status, on hand, price, overflow menu)
  and open detail for secondary actions. Convert product-detail batches and movements into compact
  ledger rows/cards at phone widths.

### Receiving stock

**Goal:** record a delivery with the right cost, supplier, batch, and expiry.

- Works: labels explain business meaning, optional fields are explicit, the supplier shortcut is
  contextual, and the review screen clearly shows total cost and 24 → 29 stock.
- Friction: the mobile form is roughly 1,568px before review; the primary action is only at the end.
  Product selection is a long native list rather than searchable.
- Recommendation: use a searchable product picker, progressively reveal supplier/batch/expiry
  details after product and quantity, and add a sticky mobile review action only after required
  fields are valid.

### Stock adjustments

**Goal:** record damage, expiry, loss, return, or a count correction with a reason.

- Works: the six reasons are plain-language cards, quantity is always entered positively, direction
  is translated on review, and reasons are mandatory.
- Friction: six full choice cards plus all fields produce an approximately 1,886px phone form.
- Recommendation: group removal reasons and addition/correction reasons, or use a two-stage choice
  that reveals the selected explanation without losing the plain-language help.

### Sales history

**Goal:** find a sale, understand payment/status, print a receipt, or safely reverse it.

- Works: summary values, date shortcuts, search, payment/status filters, responsive sale cards, CSV,
  detail, receipt, and reversal history are present.
- Friction: on 375px, stats and two filter blocks fill the first viewport before any sale appears;
  at 320px the populated page is over 8,100px tall.
- Recommendation: show the latest five sales immediately below the headline; collapse date/search
  controls behind a “Filter” button with an active-filter count.

### Inventory history

**Goal:** understand every quantity change and investigate unusual adjustments.

- Works: direction, type, actor, time, reference, reason, and stock-after values are present; mobile
  uses cards rather than the desktop ledger table.
- Friction: 25 rich cards plus expanded filters produce an 11,332px 320px page. This is too much
  scanning for an owner investigating a recent issue.
- Recommendation: default owner mobile to recent/unusual changes, reduce each card to product,
  signed quantity, type, actor/time, and stock-after, and reveal reference/reason on expansion.

### Reports

**Goal:** understand performance without accounting expertise.

- Works: strong plain-language summaries, linked report areas, appropriate payment breakdown,
  export, exact costs, and an excellent gross-profit caveat.
- Friction: nine report chips plus five date chips and date fields can consume almost the entire
  first phone viewport. Dense tables then require an undisclosed horizontal gesture. On the profit
  screen, the actual financial metrics begin below the first viewport.
- Recommendation: on phones, replace report chips with a labelled report selector or a single-row
  horizontally scrolling tab list; show the headline metrics before expanded date controls; add a
  visible “Swipe to see more columns” cue and sticky first column where a table must scroll.

### Users and settings

**Goal:** manage access and shop-wide configuration safely.

- Works: mobile users become clear cards, roles are explained, self-deactivation and last-owner
  protection are enforced, password reset explains the handoff, and settings use plain language.
- Friction: small 38px mobile actions; long settings/user forms put save far below the initial
  context; desktop user table needs internal horizontal scroll at 1024px.
- Recommendation: meet 44px mobile target size, make role the first decision on user creation, and
  use a sticky save bar for long owner-only forms after a field becomes dirty.

## 6. Screen-by-screen findings

The following table records actionable issues. Screens without an issue in this table were still
reviewed and are called out afterward.

| Screen/component | Viewport | Observation/evidence | Why it matters | Recommendation | Priority | Acceptance criterion |
|---|---|---|---|---|---|---|
| Login secondary copy and placeholder | 320/375 | `#75847d` is 3.92:1 and `#9aa8a1` is 2.47:1 on white; both appear at small sizes. | Low-vision users and people in bright shop light may miss guidance. | Raise muted and placeholder tokens to at least 4.5:1. | P1 | All normal-size text and placeholders pass 4.5:1 in automated and manual contrast checks. |
| Login password reveal | 375 | Visible button measured about 55×34px. | Height is below the requested practical touch target. | Make the entire trailing control 44px high. | P2 | Reveal target is at least 44×44px and keeps a visible focus state. |
| Desktop page headings | 1024/1440 | Many pages expose both the topbar title and content title as H1; Users showed two “Users” level-one headings. | Screen-reader hierarchy is ambiguous and repetitive. | Keep one main H1; make the topbar title non-heading text or reference the same H1. | P2 | Each document exposes exactly one visible/accessibility-tree H1. |
| Owner dashboard long content | 375 | Page measured about 4,303px; operational activity is far below rankings and tables. | Owner cannot quickly scan anomalies after headline metrics. | Limit dashboard lists to 5 items and prioritize unusual changes/recent activity. | P2 | Headline metrics plus urgent stock and latest unusual activity fit within roughly 2–2.5 phone screens. |
| Dashboard Running low / Recent sales tables | 320/375 | Tables remain horizontally scrolling; measured table content exceeded the phone content width. | Important names/statuses can be offscreen with no scroll cue. | Use compact mobile rows/cards or an explicit scroll cue with sticky first column. | P2 | All priority fields are visible without horizontal scrolling, or scrolling is clearly signposted and retains row identity. |
| POS mobile mini-cart | 375 | After “Review sale,” the 60px fixed mini-cart stayed above the 62px tab bar while the cart panel was visible. | It covers payment/discount/note/completion content and duplicates the total. | Hide or collapse it while `.cart-panel` is in view. | P1 | No checkout control is obscured at 320/375; the mini-cart reappears only when the cart panel is offscreen. |
| POS mobile product/cart order | 320/375 | All quick picks precede checkout; cart begins after a long product list. | Returning to checkout requires a large jump and creates context switching. | Show fewer quick picks on phone and keep a clear route between product search and cart. | P2 | Empty and populated cart are reachable within one viewport action from search results. |
| POS idle loading status | All | The HTMX spinner uses opacity only and static “Searching” live text remains in the accessibility tree while idle. | Assistive technology can receive misleading loading semantics. | Toggle `hidden`/`aria-hidden` and `aria-busy` only during requests. | P2 | “Searching” is absent while idle, announced once when loading, and cleared on completion/error. |
| POS confirmation | All | Final confirmation uses native `window.confirm`. | It is visually inconsistent and cannot present structured item/payment information. | Replace only if needed with a compact accessible confirmation modal showing total, payment, and change. | P3 | Confirmation has labelled title, focus trap/return, keyboard escape, and no duplicate submit risk. |
| Sale success / receipt | 320/375 | Strong state; no blocking issue found. Receipt fits at 375 and uses local date/currency. | Preserve this trust moment. | Preserve amount, sale number, payment, change, actor/time, next sale, and print actions. | P3 | Regression test retains all current details at 320px without overflow. |
| Sales history filters | 320/375 | Summary and expanded filters fill the first viewport; populated page measured about 8,118px at 320. | Recent records are slower to reach than their filters. | Put recent sales first and collapse advanced filters on phone. | P1 | First recent sale is visible in the initial 812px viewport or after one clear “Show results” action. |
| Sale detail tables | 320/375 | Item and stock-movement tables use horizontal scrolling. | Item identity can separate from amounts/status when swiping. | Convert to sale-line and movement cards; keep desktop tables. | P2 | Product, quantity, total, movement type, and signed quantity are visible together at 320px. |
| Reverse sale action area | 375 | Form is clear, but the irreversible action sits at the bottom immediately above fixed navigation. | High-risk action should not feel cramped or partially obscured. | Add bottom safe-area spacing and a stable destructive-action footer. | P2 | Entire red action and secondary cancel remain visible and separated from the tab bar at 320/375. |
| Product list density | 320 | 18 product cards produced about 5,185px of content. | Fast stock lookup turns into long scanning. | Use compact rows and move Receive/Edit into an overflow or detail action. | P2 | At least 6–8 products fit in an 800px phone viewport while status and on-hand remain readable. |
| Product detail batches/movements/sales | 320 | Three scrolling tables; batch table about 533px inside 305px content; page about 4,850px. | Core stock story is fragmented on phone. | Use ledger cards/rows for batches and movements and collapsible recent sales. | P1 | No product-detail section requires horizontal scrolling at 320/375. |
| Product edit / create | 320 | Long form measured about 2,149px; save is only at the end. | Shopkeeper may lose context or assume a field auto-saved. | Group identity/pricing/stock rules and add dirty-state save bar on phone. | P2 | Required fields and save remain clear; leaving with unsaved changes is warned. |
| Categories and suppliers lists | 320/375 | Responsive cards work; actions are 38px high. | Structure is good, targets remain small. | Preserve cards; increase action height. | P2 | All mobile card actions are at least 44px high. |
| Supplier detail deliveries | 320/375 | Delivery history remains a scrolling table. | Supplier/date/quantity/cost context can separate. | Use delivery cards with expandable batch/cost details. | P2 | Supplier, date, product, quantity, and cost remain associated without horizontal scrolling. |
| Receive stock product picker | 320/375 | Native select contains all 18 products with stock and codes. | The list will become slow as the catalogue grows. | Use an accessible searchable picker with recent products. | P2 | Product can be found by name/code with keyboard and touch in under 3 interactions. |
| Receive stock form/action | 320 | Initial form about 1,568px; review action at end. | Repetitive receiving is slower than necessary. | Progressively reveal secondary batch/supplier fields and conditionally pin Review. | P2 | Common no-batch receipt can reach review without traversing irrelevant fields. |
| Adjustment type form | 320 | Six 70px+ choice cards contribute to an approximately 1,886px form. | Correct but slow for repeated damaged/expired entries. | Use a compact two-column list on phone or group by stock out/stock in. | P2 | All six reasons remain plain-language and keyboard accessible; common types fit within one viewport. |
| Stock history | 320 | Responsive cards work, but 25 rich cards plus filters create about 11,332px. | Owner investigation becomes excessive scrolling. | Compact card content, default to recent/unusual, and collapse filters. | P1 | 10 recent rows fit within roughly 3 phone screens; reason/detail expands on demand. |
| Expiry watch empty state | All | Clear empty explanation and export action; no blocking issue. | Preserve as the model for empty reports. | Keep state-specific copy and next action. | P3 | Empty, expiring, and expired datasets each state what the user should do next. |
| Reports sub-navigation | 320/375 | Nine 34px chips wrap to about three rows. | It consumes the space where the report answer should appear and misses touch guidance. | Use a report selector or one-row scrollable tabs with 44px height. | P1 | Active report and switcher occupy no more than 52px vertical space on phone. |
| Report date controls | 320/375 | Five chips plus From/To and Apply consume another large panel. | Metrics begin below the first viewport, especially Profit. | Show current period summary with a Filter button; expand controls on demand. | P1 | Headline result appears within the first 812px while selected period remains obvious. |
| Report tables | 320/375 | Sales/category/inventory/adjustment/profit tables render 463–666px wide inside 305px content. | Users must discover a horizontal gesture and can lose row context. | Prefer summary cards for priority values; otherwise show scroll hint and sticky first column. | P2 | Every horizontally scrolling table has a visible cue, keyboard-scrollable wrapper, and sticky row label. |
| Users desktop table | 1024 | Internal table width extends beyond visible content; wrapper scrolls. | Owner must horizontally scroll for Actions on a laptop-sized window. | Hide low-priority columns or move actions to row menu at 1024. | P2 | Name, role, status, and actions fit without horizontal scrolling at 1024px. |
| Users mobile cards | 320/375 | Clear cards, but Edit/Set password are 38px high. | Owner's primary mobile admin actions are undersized. | Raise card-action targets to 44px. | P2 | Each mobile user action is at least 44px high with 8px separation. |
| Settings | 320/375 | Form is about 1,917px; save is below all identity and stock-policy fields. | Long owner-only edits lack a persistent saved/unsaved cue. | Divide into Identity and Stock rules; add dirty-state sticky Save/Cancel. | P2 | User always knows whether changes are unsaved; save is reachable without losing the edited section. |
| Audit history | 320 | Cards work but page is about 6,425px; pagination controls are 36px. | Reviewing unusual actions is slower and targets are small. | Default to unusual actions/recent 10, compact cards, and 44px pagination. | P2 | Ten events plus filters fit within about 3 phone screens; pagination targets meet 44px. |
| Profile | 320/375 | Details and password forms are stacked into one long page. | Changing a password requires passing unrelated profile controls. | Use two labelled tabs/sections or a separate password route reached from profile. | P2 | Password task opens directly with current/new password fields and one primary action. |
| Offline banner and page | All | Global copy says “your work is saved on this device” and offline page says “Anything you had typed is still on this device.” Only the POS cart is persisted. | A user can believe an unsaved delivery, adjustment, product, user, or settings form is safe when it is not. | Use truthful per-context copy or persist drafts for every form that makes the claim. | P1 | Disconnecting on every major form either restores all entered values after reconnect or explicitly says the form is not yet saved and must remain open. |
| Mobile global controls | 320/375 | Menu 36×38, chips 34px, card actions 38px, pagination 36px. | Repeated small targets increase mistakes for touch users. | Establish 44px phone target token; allow only inline links to be smaller when spacing still meets WCAG. | P1 | Automated measurement finds no primary/secondary mobile button, chip, tab, icon button, or pager below 44px height. |
| Muted typography | All | Small labels/help use colours below 4.5:1. | System-wide readability and WCAG issue. | Replace text-muted tokens; do not use opacity to create hierarchy. | P1 | Every text token used below 24px passes 4.5:1 on every supported surface. |

Screens/states reviewed with no additional blocking finding: login success, invalid login, dashboard
at all requested breakpoints, category create/edit structure, supplier create/edit structure, POS
no-results, POS out-of-stock result, cash/change, sale completion, receipt, reversal validation,
delivery confirmation, adjustment confirmation, payment report, expiry report empty state, user
password reset structure, custom 403, custom error template, and offline shell.

## 7. Cross-cutting design issues

### Mobile information order

The owner experience often renders navigation, summary cards, shortcuts, date fields, and filters
before the records or answer. Desktop composition has been stacked rather than reprioritized.

Reusable solution: create a mobile page order of **answer → urgent exception → recent records →
filters/details**. Use a compact filter trigger with an active count and a bottom sheet/offcanvas for
advanced filters.

### Responsive data pattern

There are two good responsive systems already: desktop tables and `.data-card` mobile cards. They
are used for product, sales, movement, user, supplier, category, and audit lists, but not for product
detail, sale detail, dashboard, or most report tables.

Reusable solution: define three explicit variants:

1. **Operational list:** convert to cards/rows below 768px.
2. **Analytical matrix:** controlled horizontal scroll with a visible cue, keyboard focus, sticky
   first column, and a summary above.
3. **Short comparison:** reflow to labelled definition rows rather than a table.

### Touch targets

The desktop-oriented 32/34/36/38px controls repeat across navigation chips, table actions, menu,
and pagination.

Reusable solution: add a `--target-touch: 44px` token under 768px and apply it to `.btn`, `.btn-sm`,
`.btn-icon`, `.chip`, `.pager a`, `.pager span`, mobile card actions, and mobile menu controls.

### Contrast and text hierarchy

Hierarchy currently depends too heavily on light grey-green. The failure is most visible in help,
captions, placeholders, dates, units, and metadata—the exact text users need to avoid mistakes.

Reusable solution: use weight, size, spacing, and position for hierarchy; keep all normal text at
4.5:1. Reserve very light tones for borders and decorative icons.

### Semantic headings and loading states

Desktop pages often expose two H1s. The POS loading label remains semantically present while the
spinner is only visually transparent.

Reusable solution: page component owns one H1; the shell title is a labelled `div`. Create a
shared loading pattern that toggles `hidden`, `aria-busy`, and live text with the actual request.

### Offline trust

The offline shell communicates confidence that the code does not support outside POS.

Reusable solution: use one of two messages based on capability:

- Persisted: “Your sale is kept on this device. Reconnect, then press Complete sale again.”
- Not persisted: “You are offline. Keep this page open; this form has not been saved.”

### Long mobile forms

Receive, adjust, product, user, settings, and profile pages are technically responsive but long.

Reusable solution: use clear form sections, conditional disclosure, searchable selects, a dirty
state, and a safe-area-aware sticky action bar. Do not split a short transaction across extra pages
unless the existing review step already provides the necessary separation.

## 8. Recommended design direction

This is an evolution of the current identity, not a rebrand.

### Colour

- Leaf primary: `#1F5136`
- Deep leaf: `#17402B`
- Canvas: `#F3F5F2`
- Surface: `#FFFFFF`
- Heading: `#1C2B24`
- Body: `#3D4A44`
- Accessible muted text: `#5F6F67` (about 5.31:1 on white, 4.84:1 on canvas)
- Strong line: `#D9E2DD`

Keep the current warm status families, but verify final text/background combinations. Use colour
with a word and, where useful, a simple icon or signed quantity.

### Typography

- Preserve Poppins for interface language and InterNum for currency/quantities.
- Minimum mobile body and control text: 14px.
- Utility labels: 12px only with accessible contrast and medium/semi-bold weight.
- Keep numeric columns tabular and right-aligned.
- One H1 per page; 20–24px is enough. Avoid decorative oversized headings.

### Spacing and layout

- Use a 4/8/12/16/24/32px scale.
- Preserve the 1400px operational maximum and 760–820px form maximum.
- Keep the floating SaaS shell at desktop; remove it on tablet/phone as today.
- On mobile, use 14–16px page gutters and at least 16px bottom clearance above fixed navigation.

### Shape and elevation

- Controls: 7–8px radius.
- Cards: 10–12px radius.
- Shell/modal: 14px radius.
- Continue using borders as the main separation and shadows only for floating/sticky layers.

### Buttons and forms

- One filled primary action per region.
- Quiet secondary and soft-danger/destructive actions remain appropriate.
- 44px minimum touch height; 40px is acceptable for laptop controls.
- Keep required/optional language and specific help.
- Add searchable product/supplier controls without introducing a separate frontend framework.
  HTMX plus a server-rendered listbox is sufficient.

### Tables, cards, and statuses

- Use cards only when they preserve row relationships or represent one decision.
- Do not turn every report matrix into a tall card stream. Use headline summaries plus a deliberate
  scrollable matrix for secondary analysis.
- Add scroll cues/sticky first column to analytical tables.
- Preserve signed quantities, stock-after, actor, reason, and time as the product's signature
  **stock story**.

### Icons and navigation

- Preserve the single outline icon family and current 18/20px sizing.
- Keep the desktop sidebar grouping and five-item mobile tab bar.
- Replace the mobile report-chip wall with one compact report switcher.
- Keep New Sale continuously reachable.

### Empty, error, offline, and loading states

- Preserve the current empty-state format: plain outcome, explanation, next action.
- Validation remains adjacent to the field and should receive focus at the first error.
- Offline messages must reflect actual persistence.
- Loading indicators must be both visually and semantically active only during a request.

## 9. Prioritized improvement plan

### Immediate fixes

1. **Truthful offline behaviour** — all forms and offline shell.
   - Completion: remove global saved-device claims or add real draft persistence; verify each major
     form during a simulated disconnect and reconnect.
2. **Accessible text tokens** — all screens.
   - Completion: normal-size text and placeholders pass 4.5:1 on canvas, surface, and tinted status
     backgrounds.
3. **44px mobile targets** — menu, chips, small buttons, card actions, pagination.
   - Completion: automated viewport audit at 320/375 finds no undersized actionable component.
4. **POS mobile overlay** — New Sale checkout.
   - Completion: mini-cart never covers payment, note, change, or completion controls; keyboard and
     screen-reader path remains intact.

### High-impact improvements

1. **Mobile report composition** — report index and all report detail pages.
   - Completion: headline metrics appear in the first 812px; report/period controls use no more than
     one compact row until expanded.
2. **Mobile history density** — Sales, Stock history, Audit history.
   - Completion: recent records appear before expanded filters; ten results fit within about three
     phone screens.
3. **Product detail mobile ledger** — batches, movements, recent sales.
   - Completion: no horizontal scrolling at 320/375 and signed stock context stays together.
4. **POS mobile product/cart handoff** — search, quick picks, cart.
   - Completion: user can move between search and checkout with one obvious action; cart position is
     preserved.

### Consistency improvements

1. Implement the three responsive-data variants and migrate dashboard, detail, and report tables.
2. Enforce one H1 per page and a shared semantic page-header component.
3. Create shared mobile filter disclosure with selected-filter count and clear/reset state.
4. Create one live loading pattern for HTMX and submit states.
5. Add a safe-area-aware mobile action bar for long forms and dangerous confirmations.

### Final polish

1. Reduce dashboard and report card repetition by using compact lists and definition rows.
2. Add a subtle, text-labelled horizontal-scroll cue only where analytical tables remain.
3. Tune long-name wrapping and compact product rows.
4. Consider replacing the native POS confirmation only after the higher-priority issues are fixed.
5. Re-run visual regression checks at 320, 375, 768, 1024, and 1440 with empty, long-name, error,
   and populated data.

## 10. Final verdict

**Is it ready for the shopkeeper to use daily?**  
Functionally, almost. The laptop workflows are clear and the POS is strong. Before daily use, fix
the offline promise, the mobile/keyboard announcement issues, and the most important accessibility
tokens. The shopkeeper should then receive a short observed pilot at the actual counter.

**Is it ready for the owner to monitor from a phone?**  
Not at the intended quality bar. The dashboard headline is good, but mobile reports and histories
need reordered content, larger targets, compact filters, and more deliberate data presentation.

**Does it feel like a professionally designed product?**  
Yes in structure, language, transaction safety, and visual consistency. It stops short of a fully
professional finish in mobile analytical views and accessibility details.

**Does it make effective use of the reference template?**  
Yes. The application uses the strongest SaaS-skin ideas and rejects most enterprise decoration.
The remaining template-like weakness is compact admin density, especially in secondary mobile
text, chips, and tables.

**What must be completed before launch?**

- Truthful offline behaviour/copy.
- WCAG-compliant text contrast and practical mobile targets.
- POS mobile checkout overlay correction.
- Mobile-first report and history ordering.
- Responsive product-detail and priority report data patterns.
- A final owner/shopkeeper pilot using real devices, a barcode scanner, printer, and an actual
  intermittent connection.

No frontend rewrite is warranted. These changes fit the existing Django templates, Bootstrap,
HTMX, and minimal JavaScript architecture.
