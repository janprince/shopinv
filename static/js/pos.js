/* Point of sale — the till.
 *
 * Design notes:
 *  - The cart lives in localStorage, so a stray refresh or a flat battery does
 *    not lose a customer's basket.
 *  - The whole thing submits as an ordinary form POST. If the server rejects it
 *    (stock ran out, connection died) the page comes back with the cart intact.
 *  - Every submission carries an idempotency key, so pressing the button twice —
 *    or retrying after the connection drops — can never record two sales.
 */
(function () {
  "use strict";

  var form = document.getElementById("sale-form");
  if (!form) return;

  var STORAGE_KEY = "jcf.cart.v1";
  var CURRENCY = document.getElementById("sum-total").textContent.replace(/[\d.,]/g, "").trim();

  var el = {
    search: document.getElementById("pos-search"),
    searchSpinner: document.getElementById("search-spinner"),
    results: document.getElementById("pos-results"),
    lines: document.getElementById("cart-lines"),
    empty: document.getElementById("cart-empty"),
    totals: document.getElementById("cart-totals"),
    payment: document.getElementById("payment-block"),
    count: document.getElementById("cart-count"),
    clear: document.getElementById("clear-cart"),
    sumItems: document.getElementById("sum-items"),
    sumSubtotal: document.getElementById("sum-subtotal"),
    sumDiscount: document.getElementById("sum-discount"),
    discountLine: document.getElementById("discount-line"),
    sumTotal: document.getElementById("sum-total"),
    btnTotal: document.getElementById("btn-total"),
    complete: document.getElementById("complete-btn"),
    cartField: form.querySelector('input[name="cart"]'),
    keyField: form.querySelector('input[name="idempotency_key"]'),
    cash: document.getElementById("id_amount_received"),
    cashFields: document.getElementById("cash-fields"),
    quickCash: document.getElementById("quick-cash"),
    changeBlock: document.getElementById("change-block"),
    changeAmount: document.getElementById("change-amount"),
    cashShort: document.getElementById("cash-short"),
    reference: document.getElementById("reference-field"),
    discount: document.getElementById("id_discount"),
    discountError: document.getElementById("discount-error"),
    offlineNote: document.getElementById("offline-note"),
    minicart: document.getElementById("pos-minicart"),
    mcCount: document.getElementById("mc-count"),
    mcTotal: document.getElementById("mc-total"),
    cartPanel: document.querySelector(".cart-panel"),
    confirmDialog: document.getElementById("sale-confirm-modal"),
    confirmButton: document.getElementById("confirm-complete-sale"),
    confirmItems: document.getElementById("confirm-items"),
    confirmTotal: document.getElementById("confirm-total"),
    confirmPayment: document.getElementById("confirm-payment"),
    confirmChange: document.getElementById("confirm-change"),
    confirmChangeLabel: document.getElementById("confirm-change-label")
  };

  /** cart: [{id, name, price, stock, unit, fractions, step, qty}] */
  var cart = [];
  var cartPanelInView = false;

  /* ------------------------------------------------------------------ */
  /* Money helpers — cents as integers, never floats for the arithmetic  */
  /* ------------------------------------------------------------------ */
  function cents(value) {
    return Math.round(parseFloat(value || 0) * 100);
  }
  function fromCents(value) {
    return (value / 100).toFixed(2);
  }
  function fmt(value) {
    return CURRENCY + Number(value / 100).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }
  function trimQty(value) {
    return String(Math.round(value * 1000) / 1000);
  }

  /* ------------------------------------------------------------------ */
  /* Persistence                                                         */
  /* ------------------------------------------------------------------ */
  function save() {
    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ cart: cart, key: el.keyField.value })
      );
    } catch (err) {
      /* private mode or full storage — the sale still works, just not resumable */
    }
  }

  function restore() {
    var serverCart = document.getElementById("initial-cart");
    if (serverCart) {
      try {
        var parsed = JSON.parse(serverCart.textContent || "[]");
        if (Array.isArray(parsed) && parsed.length) {
          // The server handed the cart back after a rejected submission. It only
          // carries ids and quantities, so re-hydrate the display fields.
          hydrateFromServer(parsed);
          return;
        }
      } catch (err) { /* fall through to localStorage */ }
    }
    try {
      var stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null");
      if (stored && Array.isArray(stored.cart)) {
        cart = stored.cart;
        if (stored.key) el.keyField.value = stored.key;
      }
    } catch (err) { /* ignore */ }
  }

  function hydrateFromServer(lines) {
    var ids = lines.map(function (line) { return line.product_id; });
    fetch(
      "/sales/new/stock-check/?" + ids.map(function (id) { return "id=" + id; }).join("&"),
      { headers: { "X-Requested-With": "fetch" } }
    )
      .then(function (response) { return response.json(); })
      .then(function (data) {
        cart = lines
          .filter(function (line) { return data.products[String(line.product_id)]; })
          .map(function (line) {
            var info = data.products[String(line.product_id)];
            var existing = findStored(line.product_id);
            return {
              id: line.product_id,
              name: existing ? existing.name : "Product " + line.product_id,
              price: info.price,
              stock: info.stock,
              unit: existing ? existing.unit : "",
              fractions: existing ? existing.fractions : true,
              step: existing ? existing.step : "0.001",
              qty: parseFloat(line.quantity)
            };
          });
        render();
      })
      .catch(function () { render(); });
  }

  function findStored(id) {
    try {
      var stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null");
      if (!stored || !Array.isArray(stored.cart)) return null;
      return stored.cart.filter(function (line) { return line.id === id; })[0] || null;
    } catch (err) {
      return null;
    }
  }

  function resetCart() {
    cart = [];
    el.keyField.value = newKey();
    try { window.localStorage.removeItem(STORAGE_KEY); } catch (err) { /* ignore */ }
    render();
  }

  function newKey() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  /* ------------------------------------------------------------------ */
  /* Cart operations                                                     */
  /* ------------------------------------------------------------------ */
  function addProduct(dataset, quantity) {
    var id = parseInt(dataset.id, 10);
    var step = parseFloat(dataset.step || "1");
    var amount = quantity || (dataset.fractions === "1" ? 1 : 1);
    var line = cart.filter(function (item) { return item.id === id; })[0];

    if (line) {
      line.qty = Math.round((line.qty + amount) * 1000) / 1000;
    } else {
      cart.push({
        id: id,
        name: dataset.name,
        price: dataset.price,
        stock: dataset.stock,
        unit: dataset.unit,
        fractions: dataset.fractions === "1",
        step: step,
        qty: amount
      });
    }
    render();
    announce(dataset.name + " added");
    flashLine(id);
  }

  function setQuantity(id, value) {
    var line = cart.filter(function (item) { return item.id === id; })[0];
    if (!line) return;
    var next = Math.round(parseFloat(value || 0) * 1000) / 1000;
    if (!isFinite(next) || next <= 0) {
      removeLine(id);
      return;
    }
    line.qty = next;
    render();
  }

  function nudge(id, direction) {
    var line = cart.filter(function (item) { return item.id === id; })[0];
    if (!line) return;
    var step = line.fractions ? 0.5 : 1;
    setQuantity(id, line.qty + direction * step);
  }

  function removeLine(id) {
    var line = cart.filter(function (item) { return item.id === id; })[0];
    cart = cart.filter(function (item) { return item.id !== id; });
    render();
    if (line) announce(line.name + " removed");
  }

  function flashLine(id) {
    var row = el.lines.querySelector('[data-line="' + id + '"]');
    if (!row) return;
    row.style.background = "var(--leaf-050)";
    window.setTimeout(function () { row.style.background = ""; }, 400);
  }

  var liveRegion;
  function announce(message) {
    if (!liveRegion) {
      liveRegion = document.createElement("div");
      liveRegion.className = "visually-hidden";
      liveRegion.setAttribute("role", "status");
      liveRegion.setAttribute("aria-live", "polite");
      document.body.appendChild(liveRegion);
    }
    liveRegion.textContent = message;
  }

  /* ------------------------------------------------------------------ */
  /* Rendering                                                           */
  /* ------------------------------------------------------------------ */
  function render() {
    el.lines.innerHTML = "";
    var subtotal = 0;
    var units = 0;
    var blocked = false;

    cart.forEach(function (line) {
      var lineTotal = cents(line.price) * line.qty;
      subtotal += lineTotal;
      units += line.qty;

      var over = parseFloat(line.stock) < line.qty;
      if (over) blocked = true;

      var row = document.createElement("div");
      row.className = "cart-line" + (over ? " is-over" : "");
      row.dataset.line = String(line.id);
      row.innerHTML =
        '<div class="min-w-0">' +
          '<div class="cl-name">' + escapeHtml(line.name) + "</div>" +
          '<div class="cl-price">' + fmt(cents(line.price)) + " each · " +
            escapeHtml(trimQty(parseFloat(line.stock))) + " " + escapeHtml(line.unit || "") + " in stock</div>" +
        "</div>" +
        '<div class="cl-total">' + fmt(Math.round(lineTotal)) + "</div>" +
        '<div class="cl-controls">' +
          '<div class="qty-stepper">' +
            '<button type="button" data-nudge="-1" data-id="' + line.id + '" aria-label="Reduce quantity of ' + escapeAttr(line.name) + '">−</button>' +
            '<input type="text" inputmode="decimal" value="' + escapeAttr(trimQty(line.qty)) + '" ' +
              'data-qty="' + line.id + '" aria-label="Quantity of ' + escapeAttr(line.name) + '">' +
            '<button type="button" data-nudge="1" data-id="' + line.id + '" aria-label="Increase quantity of ' + escapeAttr(line.name) + '">+</button>' +
          "</div>" +
          '<button type="button" class="btn btn-sm btn-quiet ms-auto" data-remove="' + line.id + '">Remove</button>' +
        "</div>" +
        (over
          ? '<p class="field-error mb-0" style="grid-column: 1 / -1;">Only ' +
            escapeHtml(trimQty(parseFloat(line.stock))) + " " + escapeHtml(line.unit || "") +
            " available. Reduce the quantity to continue.</p>"
          : "");
      el.lines.appendChild(row);
    });

    var discount = Math.max(0, cents(el.discount.value));
    var overDiscount = discount > subtotal;
    el.discountError.hidden = !overDiscount;
    if (overDiscount) blocked = true;

    var total = Math.max(0, Math.round(subtotal) - discount);

    var hasItems = cart.length > 0;
    el.empty.hidden = hasItems;
    el.totals.hidden = !hasItems;
    el.payment.hidden = !hasItems;
    el.clear.hidden = !hasItems;
    el.count.textContent = hasItems
      ? "(" + cart.length + " product" + (cart.length === 1 ? "" : "s") + ")"
      : "(empty)";

    el.sumItems.textContent = trimQty(units);
    el.sumSubtotal.textContent = fmt(Math.round(subtotal));
    el.discountLine.hidden = discount <= 0;
    el.sumDiscount.textContent = "−" + fmt(discount);
    el.sumTotal.textContent = fmt(total);
    el.btnTotal.textContent = fmt(total);

    el.cartField.value = JSON.stringify(
      cart.map(function (line) { return { product_id: line.id, quantity: line.qty }; })
    );

    updatePayment(total);
    updateMiniCart(hasItems, units, total);
    el.complete.disabled = !hasItems || blocked || cashIsShort(total);
    save();
  }

  /** The phone-only running total pinned above the tab bar. */
  function updateMiniCart(hasItems, units, total) {
    if (!el.minicart) return;
    var shouldShow = hasItems && !cartPanelInView;
    document.body.classList.toggle("has-cart", shouldShow);
    el.minicart.hidden = !shouldShow;
    el.minicart.setAttribute("aria-hidden", String(!shouldShow));
    if (!shouldShow) {
      el.minicart.classList.remove("is-visible");
      return;
    }
    var count = Math.round(units * 1000) / 1000;
    el.mcCount.textContent = count + (count === 1 ? " item" : " items");
    el.mcTotal.textContent = fmt(total);
    // Force a reflow so the slide-up transition runs the first time.
    void el.minicart.offsetWidth;
    el.minicart.classList.add("is-visible");
  }

  function cashIsShort(total) {
    var method = form.querySelector('input[name="payment_method"]:checked');
    if (!method || method.value !== "cash") return false;
    if (!el.cash.value) return false;
    return cents(el.cash.value) < total;
  }

  function updatePayment(total) {
    var method = form.querySelector('input[name="payment_method"]:checked');
    var isCash = !method || method.value === "cash";
    el.cashFields.hidden = !isCash;
    el.reference.hidden = isCash;

    if (!isCash) {
      el.changeBlock.hidden = true;
      el.cashShort.hidden = true;
      return;
    }

    renderQuickCash(total);
    var given = el.cash.value ? cents(el.cash.value) : null;
    if (given === null) {
      el.changeBlock.hidden = true;
      el.cashShort.hidden = true;
      return;
    }
    if (given < total) {
      el.changeBlock.hidden = true;
      el.cashShort.hidden = false;
    } else {
      el.cashShort.hidden = true;
      el.changeBlock.hidden = false;
      el.changeAmount.textContent = fmt(given - total);
    }
  }

  /** Suggest the notes a customer is likely to hand over. */
  function renderQuickCash(total) {
    if (total <= 0) {
      el.quickCash.innerHTML = "";
      return;
    }
    var exact = total;
    var notes = [500, 1000, 2000, 5000, 10000, 20000];
    var suggestions = [exact];
    notes.forEach(function (note) {
      var rounded = Math.ceil(total / note) * note;
      if (suggestions.indexOf(rounded) === -1 && suggestions.length < 4) suggestions.push(rounded);
    });
    var signature = suggestions.join(",");
    if (el.quickCash.dataset.signature === signature) return;
    el.quickCash.dataset.signature = signature;
    el.quickCash.innerHTML = suggestions
      .map(function (value, index) {
        return '<button type="button" class="chip" data-cash="' + fromCents(value) + '">' +
          (index === 0 ? "Exact " : "") + fmt(value) + "</button>";
      })
      .join("");
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function escapeAttr(value) {
    return escapeHtml(value);
  }

  /* ------------------------------------------------------------------ */
  /* Events                                                              */
  /* ------------------------------------------------------------------ */
  document.addEventListener("click", function (event) {
    var addBtn = event.target.closest("[data-add-product]");
    if (addBtn && !addBtn.disabled) {
      addProduct(addBtn.dataset);
      return;
    }
    var nudgeBtn = event.target.closest("[data-nudge]");
    if (nudgeBtn) {
      nudge(parseInt(nudgeBtn.dataset.id, 10), parseInt(nudgeBtn.dataset.nudge, 10));
      return;
    }
    var removeBtn = event.target.closest("[data-remove]");
    if (removeBtn) {
      removeLine(parseInt(removeBtn.dataset.remove, 10));
      return;
    }
    var cashBtn = event.target.closest("[data-cash]");
    if (cashBtn) {
      el.cash.value = cashBtn.dataset.cash;
      render();
      return;
    }
    if (event.target.closest("#pos-minicart")) {
      document.querySelector(".cart-panel").scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
        block: "end"
      });
      return;
    }
    if (event.target.closest("#clear-cart")) {
      if (window.confirm("Remove every item from this sale?")) resetCart();
    }
  });

  el.lines.addEventListener("change", function (event) {
    var input = event.target.closest("[data-qty]");
    if (input) setQuantity(parseInt(input.dataset.qty, 10), input.value);
  });

  el.cash.addEventListener("input", function () { render(); });
  el.discount.addEventListener("input", function () { render(); });
  form.addEventListener("change", function (event) {
    if (event.target.name === "payment_method") render();
  });

  /* Keyboard: "/" focuses search, Enter adds the first result. */
  document.addEventListener("keydown", function (event) {
    if (event.key === "/" && document.activeElement !== el.search &&
        !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
      event.preventDefault();
      el.search.focus();
      el.search.select();
      return;
    }
    if (event.key === "Escape" && document.activeElement === el.search) {
      el.search.value = "";
      el.search.blur();
    }
  });

  el.search.addEventListener("keydown", function (event) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    var first = el.results.querySelector("[data-add-product]:not([disabled])");
    if (first) {
      addProduct(first.dataset);
      el.search.value = "";
      el.search.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });

  /* A barcode scanner types fast and ends with Enter — the handler above covers
   * it, and an exact barcode match is auto-added here. */
  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.target.id !== "pos-results") return;
    var auto = el.results.querySelector("[data-autoadd]:not([disabled])");
    if (auto && el.search.value.length >= 6) {
      addProduct(auto.dataset);
      el.search.value = "";
      el.search.focus();
    }
  });

  function setSearchBusy(isBusy) {
    el.results.setAttribute("aria-busy", String(isBusy));
    if (!el.searchSpinner) return;
    el.searchSpinner.hidden = !isBusy;
    el.searchSpinner.setAttribute("aria-hidden", String(!isBusy));
  }

  document.body.addEventListener("htmx:beforeRequest", function (event) {
    if (event.detail && event.detail.elt === el.search) setSearchBusy(true);
  });
  document.body.addEventListener("htmx:afterRequest", function (event) {
    if (event.detail && event.detail.elt === el.search) setSearchBusy(false);
  });
  document.body.addEventListener("htmx:responseError", function (event) {
    if (event.detail && event.detail.elt === el.search) setSearchBusy(false);
  });

  /* Submission.
   *
   * confirm() is synchronous, so the decision is made inside the submit event
   * and the browser's own submission continues untouched when the shopkeeper
   * agrees. (Calling form.requestSubmit() from inside a submit handler is a
   * no-op — the form is already firing submission events — which would leave
   * the sale silently unsent.)
   *
   * pos.js owns the submit guard here rather than the shared data-guard-submit
   * helper, so a cancelled confirmation does not leave the button stuck. */
  function markBusy() {
    el.complete.dataset.busy = "true";
    el.complete.setAttribute("aria-busy", "true");
    el.complete.disabled = true;
  }

  function releaseBusy() {
    el.complete.dataset.busy = "false";
    el.complete.removeAttribute("aria-busy");
    render();
  }

  var confirmation = el.confirmDialog && window.bootstrap
    ? new window.bootstrap.Modal(el.confirmDialog)
    : null;

  function showSaleConfirmation() {
    var method = form.querySelector('input[name="payment_method"]:checked');
    var methodLabel = method && method.nextElementSibling
      ? method.nextElementSibling.textContent.trim()
      : "Not selected";
    el.confirmItems.textContent = el.sumItems.textContent;
    el.confirmTotal.textContent = el.sumTotal.textContent;
    el.confirmPayment.textContent = methodLabel;
    var showChange = method && method.value === "cash" && el.cash.value && !el.changeBlock.hidden;
    el.confirmChange.hidden = !showChange;
    el.confirmChangeLabel.hidden = !showChange;
    if (showChange) el.confirmChange.textContent = el.changeAmount.textContent;
    confirmation.show();
  }

  if (el.confirmButton) {
    el.confirmButton.addEventListener("click", function () {
      form.dataset.confirmed = "true";
      confirmation.hide();
      form.requestSubmit();
    });
  }

  form.addEventListener("submit", function (event) {
    if (!cart.length || form.dataset.sending === "true") {
      event.preventDefault();
      return;
    }

    if (form.dataset.confirmed !== "true") {
      event.preventDefault();
      if (confirmation) showSaleConfirmation();
      else if (window.confirm("Complete this sale for " + el.sumTotal.textContent + "?")) {
        form.dataset.confirmed = "true";
        form.requestSubmit();
      }
      return;
    }

    form.dataset.sending = "true";
    markBusy();
    if (window.JCF && window.JCF.isOffline()) {
      window.JCF.showBanner("No connection — the sale has not been saved yet", false);
    }
    // The cart is also carried in the form body, so the server hands it straight
    // back if it rejects the sale. Safe to drop the local copy now.
    try { window.localStorage.removeItem(STORAGE_KEY); } catch (err) { /* ignore */ }
    // Default action continues: the browser posts the form.
  });

  // Returning via the back/forward cache must not leave a dead button.
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    form.dataset.sending = "false";
    releaseBusy();
  });

  window.addEventListener("online", function () { render(); });
  window.addEventListener("offline", function () {
    if (el.offlineNote) el.offlineNote.hidden = false;
  });
  window.addEventListener("online", function () {
    if (el.offlineNote) el.offlineNote.hidden = true;
  });

  if (el.cartPanel && "IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      cartPanelInView = entries[0].isIntersecting;
      render();
    }, { threshold: 0.01 }).observe(el.cartPanel);
  }

  /* ------------------------------------------------------------------ */
  if (!el.keyField.value) el.keyField.value = newKey();
  restore();
  render();
  setSearchBusy(false);
  if (navigator.onLine === false) {
    if (el.offlineNote) el.offlineNote.hidden = false;
    if (window.JCF) window.JCF.showBanner("No connection — your sale is kept on this device, but it has not been recorded yet.", false);
  }
})();
