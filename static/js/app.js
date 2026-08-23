/* JCF Organic — shared behaviour.
 * Deliberately small: no framework, no build step, no bundle to keep in sync.
 */
(function () {
  "use strict";

  /* ---------------------------------------------------------------------
   * Connection status
   * The shop's internet drops. Say so plainly, and say when it is back.
   * ------------------------------------------------------------------ */
  var banner = document.getElementById("connection-banner");
  var bannerText = document.getElementById("connection-text");
  var backTimer = null;

  function showBanner(message, isBack) {
    if (!banner) return;
    bannerText.textContent = message;
    banner.hidden = false;
    banner.classList.toggle("is-back", !!isBack);
    // Force a reflow so the transition runs on first show.
    void banner.offsetWidth;
    banner.classList.add("is-visible");
  }

  function hideBanner() {
    if (!banner) return;
    banner.classList.remove("is-visible");
    window.setTimeout(function () {
      banner.hidden = true;
    }, 300);
  }

  function handleOffline() {
    window.clearTimeout(backTimer);
    showBanner("No internet connection — your work is saved on this device", false);
    document.body.classList.add("is-offline");
  }

  function handleOnline() {
    document.body.classList.remove("is-offline");
    showBanner("Back online", true);
    backTimer = window.setTimeout(hideBanner, 2500);
  }

  window.addEventListener("offline", handleOffline);
  window.addEventListener("online", handleOnline);
  if (navigator.onLine === false) handleOffline();

  window.JCF = window.JCF || {};
  window.JCF.isOffline = function () {
    return navigator.onLine === false || document.body.classList.contains("is-offline");
  };
  window.JCF.showBanner = showBanner;
  window.JCF.hideBanner = hideBanner;

  /* ---------------------------------------------------------------------
   * Duplicate-submit protection
   * Any form marked data-guard-submit disables its submit button once, and
   * re-enables it if the page is restored from the back/forward cache.
   * ------------------------------------------------------------------ */
  function guardForm(form) {
    form.addEventListener("submit", function (event) {
      if (form.dataset.submitted === "true") {
        event.preventDefault();
        return;
      }
      if (!form.checkValidity || form.checkValidity()) {
        form.dataset.submitted = "true";
        Array.prototype.forEach.call(
          form.querySelectorAll('[type="submit"]'),
          function (button) {
            button.dataset.busy = "true";
            button.setAttribute("aria-busy", "true");
          }
        );
      }
    });
  }

  function releaseForms() {
    Array.prototype.forEach.call(document.querySelectorAll("form[data-guard-submit]"), function (form) {
      form.dataset.submitted = "false";
      Array.prototype.forEach.call(form.querySelectorAll('[type="submit"]'), function (button) {
        button.dataset.busy = "false";
        button.removeAttribute("aria-busy");
      });
    });
  }

  window.addEventListener("pageshow", function (event) {
    if (event.persisted) releaseForms();
  });

  /* ---------------------------------------------------------------------
   * Password visibility
   * ------------------------------------------------------------------ */
  function wirePasswordToggle(button) {
    button.addEventListener("click", function () {
      var input = document.getElementById(button.dataset.toggleTarget);
      if (!input) return;
      var revealed = input.type === "text";
      input.type = revealed ? "password" : "text";
      button.setAttribute("aria-pressed", String(!revealed));
      button.querySelector(".toggle-label").textContent = revealed ? "Show" : "Hide";
      input.focus();
    });
  }

  /* ---------------------------------------------------------------------
   * Confirmation before destructive or sensitive actions
   * data-confirm="Message" on a form or link.
   * ------------------------------------------------------------------ */
  function wireConfirm(element) {
    element.addEventListener(
      element.tagName === "FORM" ? "submit" : "click",
      function (event) {
        if (element.dataset.confirmed === "true") return;
        if (!window.confirm(element.dataset.confirm)) {
          event.preventDefault();
          event.stopPropagation();
          element.dataset.submitted = "false";
          Array.prototype.forEach.call(element.querySelectorAll('[type="submit"]') || [], function (b) {
            b.dataset.busy = "false";
          });
        }
      },
      true
    );
  }

  /* ---------------------------------------------------------------------
   * Filter forms that submit themselves when a select changes
   * ------------------------------------------------------------------ */
  function wireAutoSubmit(select) {
    select.addEventListener("change", function () {
      var form = select.form;
      if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
    });
  }

  /* ---------------------------------------------------------------------
   * Live "expected quantity after this change" preview on adjustment forms
   * ------------------------------------------------------------------ */
  function wireQuantityPreview(root) {
    var qtyInput = root.querySelector("[data-preview-quantity]");
    var output = root.querySelector("[data-preview-output]");
    if (!qtyInput || !output) return;

    function update() {
      var current = parseFloat(root.dataset.currentQuantity || "0");
      var direction = root.dataset.direction === "up" ? 1 : -1;
      var entered = parseFloat(qtyInput.value || "0");
      if (isNaN(entered) || entered <= 0) {
        output.textContent = "—";
        output.classList.remove("qty-delta", "is-down", "is-up");
        return;
      }
      var next = current + direction * entered;
      output.classList.add("qty-delta");
      output.classList.toggle("is-down", next < current);
      output.classList.toggle("is-up", next > current);
      if (next < 0) {
        output.textContent = "Not enough stock";
        output.classList.add("is-down");
      } else {
        output.textContent = String(Math.round(next * 1000) / 1000) + " " + (root.dataset.unitLabel || "");
      }
    }
    qtyInput.addEventListener("input", update);
    update();
  }

  /* ---------------------------------------------------------------------
   * Wiring
   * ------------------------------------------------------------------ */
  function wire(scope) {
    scope.querySelectorAll("form[data-guard-submit]").forEach(guardForm);
    scope.querySelectorAll("[data-toggle-target]").forEach(wirePasswordToggle);
    scope.querySelectorAll("[data-confirm]").forEach(wireConfirm);
    scope.querySelectorAll("select[data-auto-submit]").forEach(wireAutoSubmit);
    scope.querySelectorAll("[data-quantity-preview]").forEach(wireQuantityPreview);
    scope.querySelectorAll("[data-autofocus]").forEach(function (element) {
      if (!("ontouchstart" in window) || element.dataset.autofocus === "always") element.focus();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      wire(document);
    });
  } else {
    wire(document);
  }

  document.body.addEventListener("htmx:afterSwap", function (event) {
    wire(event.target);
  });

  /* ---------------------------------------------------------------------
   * Service worker — caches the shell so a dropped connection shows a
   * helpful page instead of the browser's dinosaur.
   * ------------------------------------------------------------------ */
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return;

  if (document.documentElement.dataset.sw !== "on") {
    // Development: a cache-first worker would serve yesterday's CSS and JS.
    // Tear down any worker a previous run installed so reloads are honest.
    navigator.serviceWorker.getRegistrations().then(function (registrations) {
      registrations.forEach(function (registration) {
        registration.unregister();
      });
    });
    return;
  }

  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js").catch(function () {
      /* offline support is a bonus, never a requirement */
    });
  });
})();
