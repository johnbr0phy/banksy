(function () {
  "use strict";

  var CURRENCY_SYMBOLS = {
    GBP: "\u00a3",
    USD: "$",
    EUR: "\u20ac",
    CHF: "CHF ",
    HKD: "HK$",
    CNY: "\u00a5",
  };

  var SUPPORTED_CURRENCIES = ["GBP", "USD", "EUR", "CHF", "HKD", "CNY"];

  // Fallback rates: units of currency per 1 USD (approx., used if live FX fails)
  var FALLBACK_RATES_USD = {
    USD: 1,
    GBP: 0.79,
    EUR: 0.92,
    CHF: 0.88,
    HKD: 7.8,
    CNY: 7.25,
  };

  var STORAGE_KEY = "banksy_display_currency";
  var RATES_CACHE_KEY = "banksy_fx_rates_v1";

  var state = {
    mode: "upcoming",
    allLots: [],
    filterQuery: "",
    displayCurrency: "ORIGINAL", // ORIGINAL | GBP | USD | ...
    ratesToUsd: null, // { USD:1, GBP: x, ... } amount of currency per 1 USD
    ratesDate: null,
    ratesSource: "fallback",
    filterWired: false,
    currencyWired: false,
  };

  function loadSavedCurrency() {
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved === "ORIGINAL" || SUPPORTED_CURRENCIES.indexOf(saved) !== -1) {
        return saved;
      }
    } catch (e) {
      /* ignore */
    }
    return "ORIGINAL";
  }

  function saveCurrency(code) {
    try {
      localStorage.setItem(STORAGE_KEY, code);
    } catch (e) {
      /* ignore */
    }
  }

  function loadCachedRates() {
    try {
      var raw = localStorage.getItem(RATES_CACHE_KEY);
      if (!raw) return null;
      var data = JSON.parse(raw);
      if (!data || !data.ratesToUsd || !data.fetchedAt) return null;
      // Cache for 12 hours
      if (Date.now() - data.fetchedAt > 12 * 60 * 60 * 1000) return null;
      return data;
    } catch (e) {
      return null;
    }
  }

  function saveCachedRates(ratesToUsd, dateStr) {
    try {
      localStorage.setItem(
        RATES_CACHE_KEY,
        JSON.stringify({
          ratesToUsd: ratesToUsd,
          date: dateStr || null,
          fetchedAt: Date.now(),
        })
      );
    } catch (e) {
      /* ignore */
    }
  }

  /**
   * Frankfurter returns rates as "1 base = N quote".
   * We request base=USD so rates[C] = units of C per 1 USD.
   */
  function fetchLiveRates() {
    var cached = loadCachedRates();
    if (cached) {
      state.ratesToUsd = cached.ratesToUsd;
      state.ratesDate = cached.date;
      state.ratesSource = "cache";
      return Promise.resolve(state.ratesToUsd);
    }

    var symbols = SUPPORTED_CURRENCIES.filter(function (c) {
      return c !== "USD";
    }).join(",");
    var url =
      "https://api.frankfurter.app/latest?from=USD&to=" +
      encodeURIComponent(symbols);

    return fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error("FX HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        var rates = { USD: 1 };
        SUPPORTED_CURRENCIES.forEach(function (c) {
          if (c === "USD") return;
          if (data.rates && data.rates[c] != null) {
            rates[c] = Number(data.rates[c]);
          } else {
            rates[c] = FALLBACK_RATES_USD[c];
          }
        });
        state.ratesToUsd = rates;
        state.ratesDate = data.date || null;
        state.ratesSource = "live";
        saveCachedRates(rates, state.ratesDate);
        return rates;
      })
      .catch(function () {
        state.ratesToUsd = Object.assign({}, FALLBACK_RATES_USD);
        state.ratesDate = null;
        state.ratesSource = "fallback";
        return state.ratesToUsd;
      });
  }

  function ensureRates() {
    if (state.ratesToUsd) return Promise.resolve(state.ratesToUsd);
    return fetchLiveRates();
  }

  function convertAmount(amount, fromCurrency, toCurrency) {
    if (amount == null || isNaN(amount)) return null;
    if (!toCurrency || toCurrency === "ORIGINAL" || toCurrency === fromCurrency) {
      return Number(amount);
    }
    var from = (fromCurrency || "GBP").toUpperCase();
    var to = toCurrency.toUpperCase();
    var rates = state.ratesToUsd || FALLBACK_RATES_USD;
    var fromRate = rates[from];
    var toRate = rates[to];
    if (!fromRate || !toRate) return Number(amount);
    // amount in FROM -> USD -> TO
    var usd = Number(amount) / fromRate;
    return usd * toRate;
  }

  function formatCurrency(amount, currency) {
    if (amount == null || isNaN(amount)) return "\u2014";
    var code = currency || "GBP";
    var symbol = CURRENCY_SYMBOLS[code] || code + " ";
    var rounded = Math.round(Number(amount));
    return symbol + rounded.toLocaleString();
  }

  function displayCurrencyFor(lot) {
    if (state.displayCurrency === "ORIGINAL") {
      return lot.currency || "GBP";
    }
    return state.displayCurrency;
  }

  function formatAmountForLot(amount, lot) {
    if (amount == null || isNaN(amount)) return "\u2014";
    var from = lot.currency || "GBP";
    var to = displayCurrencyFor(lot);
    var converted = convertAmount(amount, from, to);
    var label = formatCurrency(converted, to);
    // When converting, show original in a muted secondary note
    if (
      state.displayCurrency !== "ORIGINAL" &&
      from.toUpperCase() !== state.displayCurrency
    ) {
      var orig = formatCurrency(amount, from);
      return (
        label +
        ' <span class="price-original" title="Original currency">(' +
        escapeHtml(orig) +
        ")</span>"
      );
    }
    return label;
  }

  function formatEstimate(lot) {
    if (lot.low_estimate == null && lot.high_estimate == null) return "Estimate N/A";
    if (lot.low_estimate != null && lot.high_estimate != null) {
      return (
        formatAmountForLot(lot.low_estimate, lot) +
        " \u2013 " +
        formatAmountForLot(lot.high_estimate, lot)
      );
    }
    if (lot.low_estimate != null) {
      return formatAmountForLot(lot.low_estimate, lot) + "+";
    }
    return "Up to " + formatAmountForLot(lot.high_estimate, lot);
  }

  function formatRealised(lot) {
    if (lot.realised_price == null) return "\u2014";
    return formatAmountForLot(lot.realised_price, lot);
  }

  function formatDate(dateStr) {
    if (!dateStr) return "TBA";
    var d = new Date(dateStr + "T00:00:00");
    if (isNaN(d.getTime())) return dateStr;
    var months = [
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];
    return d.getDate() + " " + months[d.getMonth()] + " " + d.getFullYear();
  }

  function getMonthKey(dateStr) {
    if (!dateStr) return "TBA";
    var d = new Date(dateStr + "T00:00:00");
    if (isNaN(d.getTime())) return "TBA";
    var months = [
      "January", "February", "March", "April", "May", "June",
      "July", "August", "September", "October", "November", "December",
    ];
    return months[d.getMonth()] + " " + d.getFullYear();
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str || ""));
    return div.innerHTML;
  }

  function pageMode() {
    var mode = document.body && document.body.getAttribute("data-mode");
    if (mode === "completed") return "completed";
    if (/completed\.html/i.test(window.location.pathname)) return "completed";
    return "upcoming";
  }

  // Known titles used to recover a short name from catalogue dumps
  var KNOWN_PRINTS = [
    "girl with balloon", "girl and balloon", "love is in the bin", "flower thrower",
    "laugh now", "pulp fiction", "jack and jill", "soup can", "kate moss",
    "choose your weapon", "happy choppers", "morons", "bomb hugger", "bomb love",
    "flag", "golf sale", "grin reaper", "napalm", "nola", "rude copper",
    "sale ends", "toxic mary", "trolleys", "very little helps", "weston super mare",
    "gangsta rat", "monkey queen", "donuts", "applause", "flying copper", "love rat",
    "no ball games", "welcome to hell", "queen vic", "love is in the air",
    "banksquiat", "barely legal", "cnd soldiers", "i fought the law",
    "people who enjoy waving flags",
  ];

  var PRINT_ALIASES = {
    "girl and balloon": "Girl with Balloon",
    "girl with balloon": "Girl with Balloon",
    "jack & jill": "Jack and Jill",
    "queen victoria": "Queen Vic",
  };

  function normalizeName(name) {
    return (name || "")
      .toLowerCase()
      .replace(/^banksy[\s,;:-]+/i, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function titleCasePrint(s) {
    return (s || "")
      .split(" ")
      .map(function (w, i) {
        if (!w) return w;
        if (/^(a|an|and|of|the|on|in|with|from|to)$/i.test(w) && i > 0) {
          return w.toLowerCase();
        }
        return w.charAt(0).toUpperCase() + w.slice(1);
      })
      .join(" ");
  }

  /**
   * Strip catalogue noise so we show "Girl with Balloon" not a full lot blurb.
   */
  function cleanPrintName(raw) {
    if (!raw) return "";
    var text = String(raw).replace(/\s+/g, " ").trim();

    text = text.replace(/^banksy\b\s*/i, "");
    text = text.replace(/^\(\s*b\.?\s*\d{4}\s*\)\s*/i, "");
    text = text.replace(/^\(\s*\d{4}\s*\)\s*/i, "");
    text = text.replace(/^\([^)]*(?:born|british)[^)]*\)\s*/i, "");
    text = text.replace(/^banksy\b\s*[-:–—]?\s*/i, "");
    text = text.replace(/^[\s\-–—:,.]+|[\s\-–—:,.]+$/g, "");

    var lower = text.toLowerCase();
    var bestKey = null;
    var bestLen = 0;
    var i;

    Object.keys(PRINT_ALIASES).forEach(function (alias) {
      if (lower.indexOf(alias) !== -1 && alias.length > bestLen) {
        bestKey = alias;
        bestLen = alias.length;
      }
    });
    for (i = 0; i < KNOWN_PRINTS.length; i++) {
      var k = KNOWN_PRINTS[i];
      if (lower.indexOf(k) !== -1 && k.length > bestLen) {
        bestKey = k;
        bestLen = k.length;
      }
    }

    if (bestKey) {
      var display =
        PRINT_ALIASES[bestKey] ||
        (bestKey === "girl with balloon" || bestKey === "girl and balloon"
          ? "Girl with Balloon"
          : titleCasePrint(bestKey));

      var variantMatch = text.match(
        /\(([^)]*(?:rain|grey|gray|sepia|silver|gold|pink|blue|green|white|black|emerald|tan|pow|colour|color)[^)]*)\)/i
      );
      if (!variantMatch) {
        variantMatch = text.match(/\(([^)]*\/[^)]{1,30})\)/);
      }
      if (variantMatch) {
        var inner = variantMatch[1].trim();
        if (
          !/(born|edition|cm|in\.|executed|painted|this work)/i.test(inner) &&
          display.toLowerCase().indexOf(inner.toLowerCase()) === -1
        ) {
          return display + " (" + inner + ")";
        }
      }
      return display;
    }

    // Cut at dimensions / medium
    var cut = text.search(
      /\s+\d+(?:\.\d+)?\s*[xX×]\s*\d+|\s+screenprint|\s+lithograph|\s+signed\b|\s+on\s+arches|\s+published\s+by|\s+\(this\s+work|\s+executed\s+in|\s+painted\s+in/i
    );
    if (cut > 0) text = text.slice(0, cut).replace(/[\s,;:.\-]+$/, "");
    if (text.length > 72) text = text.slice(0, 72).replace(/\s+\S*$/, "");
    return text || String(raw).slice(0, 60);
  }

  function matchesPrintFilter(lot, query) {
    if (!query) return true;
    var q = query.toLowerCase().trim();
    if (!q) return true;
    var name = (lot.print_name || "").toLowerCase();
    var normalized = normalizeName(lot.print_name);
    return name.indexOf(q) !== -1 || normalized.indexOf(q) !== -1;
  }

  function uniquePrintNames(lots) {
    var seen = {};
    var names = [];
    lots.forEach(function (lot) {
      var label = cleanPrintName(lot.print_name || "");
      if (!label) return;
      var key = normalizeName(label);
      if (!key || seen[key]) return;
      seen[key] = true;
      names.push(label);
    });
    names.sort(function (a, b) {
      return a.localeCompare(b, undefined, { sensitivity: "base" });
    });
    return names;
  }

  function buildTable(lots, grouped, mode) {
    var isCompleted = mode === "completed";
    var colCount = 6;
    var html = '<table class="auction-table">';
    html +=
      "<thead><tr>" +
      "<th></th>" +
      "<th>Print Name</th>" +
      "<th>Auction House</th>" +
      "<th>Date</th>" +
      (isCompleted
        ? "<th>Realised</th><th>Estimate</th>"
        : "<th>Edition</th><th>Estimate</th>") +
      "</tr></thead><tbody>";

    if (grouped) {
      var groups = {};
      var order = [];
      lots.forEach(function (lot) {
        var key = getMonthKey(lot.auction_date);
        if (!groups[key]) {
          groups[key] = [];
          order.push(key);
        }
        groups[key].push(lot);
      });

      order.forEach(function (month) {
        html +=
          '<tr class="month-header"><td colspan="' +
          colCount +
          '">' +
          escapeHtml(month) +
          "</td></tr>";
        groups[month].forEach(function (lot) {
          html += buildRow(lot, mode);
        });
      });
    } else {
      lots.forEach(function (lot) {
        html += buildRow(lot, mode);
      });
    }

    html += "</tbody></table>";
    return html;
  }

  function buildRow(lot, mode) {
    var isCompleted = mode === "completed";
    var imgHtml;
    if (lot.image_url) {
      imgHtml =
        '<img class="thumb" src="' +
        escapeHtml(lot.image_url) +
        '" alt="' +
        escapeHtml(lot.print_name) +
        '" loading="lazy" onerror="this.outerHTML=\'<div class=no-thumb>No img</div>\'">';
    } else {
      imgHtml = '<div class="no-thumb">No img</div>';
    }

    var displayName = cleanPrintName(lot.print_name) || lot.print_name || "";
    var nameHtml;
    if (lot.url) {
      nameHtml =
        '<a href="' +
        escapeHtml(lot.url) +
        '" target="_blank" rel="noopener" title="' +
        escapeHtml(lot.print_name || displayName) +
        '">' +
        escapeHtml(displayName) +
        "</a>";
    } else {
      nameHtml = escapeHtml(displayName);
    }

    var midCol = isCompleted
      ? '<td class="price-realised">' + formatRealised(lot) + "</td>"
      : "<td>" + escapeHtml(lot.edition || "\u2014") + "</td>";

    return (
      "<tr>" +
      "<td>" + imgHtml + "</td>" +
      "<td>" + nameHtml + "</td>" +
      "<td>" + escapeHtml(lot.auction_house) + "</td>" +
      "<td>" + formatDate(lot.auction_date) + "</td>" +
      midCol +
      "<td>" + formatEstimate(lot) + "</td>" +
      "</tr>"
    );
  }

  function populateSuggestions(lots) {
    var list = document.getElementById("print-name-suggestions");
    if (!list) return;
    var names = uniquePrintNames(lots);
    list.innerHTML = names
      .map(function (name) {
        return '<option value="' + escapeHtml(name) + '"></option>';
      })
      .join("");
  }

  function updateFxNote() {
    var note = document.getElementById("fx-note");
    if (!note) return;
    if (state.displayCurrency === "ORIGINAL") {
      note.hidden = true;
      note.textContent = "";
      return;
    }
    note.hidden = false;
    if (state.ratesSource === "live" || state.ratesSource === "cache") {
      note.textContent = state.ratesDate
        ? "Rates as of " + state.ratesDate
        : "Live FX rates";
    } else {
      note.textContent = "Approx. FX rates";
    }
  }

  function applyFilterAndRender() {
    var mode = state.mode;
    var container = document.getElementById("auction-table-container");
    var countEl = document.getElementById("lot-count");
    var clearBtn = document.getElementById("print-filter-clear");
    var query = state.filterQuery;

    if (clearBtn) {
      clearBtn.hidden = !query;
    }

    updateFxNote();

    var lots = state.allLots.filter(function (lot) {
      return matchesPrintFilter(lot, query);
    });

    if (countEl) {
      if (query) {
        countEl.textContent =
          lots.length +
          " of " +
          state.allLots.length +
          " lot" +
          (state.allLots.length !== 1 ? "s" : "");
      } else {
        countEl.textContent =
          lots.length + " lot" + (lots.length !== 1 ? "s" : "");
      }
    }

    if (lots.length === 0) {
      if (container) {
        container.innerHTML =
          '<div class="empty-state" id="empty-state">' +
          (query
            ? "No lots match \u201c" +
              escapeHtml(query) +
              "\u201d. Try another print name."
            : mode === "completed"
              ? "No completed auction results yet. Check back after the next scrape."
              : "No upcoming auctions found. Check back soon.") +
          "</div>";
      }
      return;
    }

    var grouped = lots.length > 8;
    if (container) container.innerHTML = buildTable(lots, grouped, mode);
  }

  function setupFilter() {
    var filterBar = document.getElementById("filter-bar");
    var input = document.getElementById("print-filter");
    var clearBtn = document.getElementById("print-filter-clear");
    if (filterBar) filterBar.style.display = "flex";
    if (!input || state.filterWired) return;

    state.filterWired = true;
    input.addEventListener("input", function () {
      state.filterQuery = input.value || "";
      applyFilterAndRender();
    });

    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        input.value = "";
        state.filterQuery = "";
        applyFilterAndRender();
        input.focus();
      });
    }
  }

  function setActiveCurrencyPill(code) {
    var pills = document.querySelectorAll(".currency-pill");
    pills.forEach(function (btn) {
      var active = btn.getAttribute("data-currency") === code;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function applyDisplayCurrency(code) {
    var value = code || "ORIGINAL";
    if (value !== "ORIGINAL" && SUPPORTED_CURRENCIES.indexOf(value) === -1) {
      value = "ORIGINAL";
    }
    state.displayCurrency = value;
    saveCurrency(value);
    setActiveCurrencyPill(value);

    // Re-render the full current table (all lots, or search-filtered subset).
    // Conversion always applies to every visible row, not only search matches.
    if (value === "ORIGINAL") {
      applyFilterAndRender();
      return;
    }
    ensureRates().then(function () {
      applyFilterAndRender();
    });
  }

  function setupCurrency() {
    var toggle = document.getElementById("currency-toggle");
    var pills = document.querySelectorAll(".currency-pill");
    if (!toggle || !pills.length) return;

    toggle.hidden = false;

    if (state.currencyWired) {
      setActiveCurrencyPill(state.displayCurrency);
      return;
    }
    state.currencyWired = true;

    state.displayCurrency = loadSavedCurrency();
    setActiveCurrencyPill(state.displayCurrency);

    pills.forEach(function (btn) {
      btn.addEventListener("click", function () {
        applyDisplayCurrency(btn.getAttribute("data-currency") || "ORIGINAL");
      });
    });
  }

  function prepareLots(data, mode) {
    var lots = (data.lots || [])
      .filter(function (lot) {
        return lot.is_original !== false;
      })
      .map(function (lot) {
        // Normalize in memory so filters/suggestions use clean names
        var copy = Object.assign({}, lot);
        copy.print_name = cleanPrintName(lot.print_name) || lot.print_name;
        return copy;
      });

    if (mode === "completed") {
      lots.sort(function (a, b) {
        if (!a.auction_date) return 1;
        if (!b.auction_date) return -1;
        return b.auction_date.localeCompare(a.auction_date);
      });
    } else {
      lots.sort(function (a, b) {
        if (!a.auction_date) return 1;
        if (!b.auction_date) return -1;
        return a.auction_date.localeCompare(b.auction_date);
      });
    }

    return lots;
  }

  function render(data, mode) {
    var loading = document.getElementById("loading");
    var updatedEl = document.getElementById("last-updated");

    if (loading) loading.style.display = "none";

    if (updatedEl && data.last_updated) {
      var d = new Date(data.last_updated);
      updatedEl.textContent = "Last updated: " + d.toLocaleString();
    }

    state.mode = mode;
    state.allLots = prepareLots(data, mode);
    populateSuggestions(state.allLots);
    setupFilter();
    setupCurrency();

    var ready = Promise.resolve();
    if (state.displayCurrency !== "ORIGINAL") {
      ready = ensureRates();
    }
    ready.then(function () {
      applyFilterAndRender();
    });
  }

  function init() {
    var mode = pageMode();
    var dataUrl =
      mode === "completed" ? "data/completed.json" : "data/upcoming.json";

    // Prefetch rates in background so switching currency is instant
    fetchLiveRates().catch(function () {
      /* fallback already applied */
    });

    fetch(dataUrl)
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        render(data, mode);
      })
      .catch(function () {
        var loading = document.getElementById("loading");
        var emptyState = document.getElementById("empty-state");
        if (loading) loading.style.display = "none";
        if (emptyState) emptyState.style.display = "block";
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
