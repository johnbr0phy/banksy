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

  var state = {
    mode: "upcoming",
    allLots: [],
    filterQuery: "",
  };

  function formatCurrency(amount, currency) {
    if (amount == null || isNaN(amount)) return "\u2014";
    var symbol = CURRENCY_SYMBOLS[currency] || currency + " ";
    return symbol + Number(amount).toLocaleString();
  }

  function formatEstimate(lot) {
    if (lot.low_estimate == null && lot.high_estimate == null) return "Estimate N/A";
    var curr = lot.currency || "GBP";
    if (lot.low_estimate != null && lot.high_estimate != null) {
      return (
        formatCurrency(lot.low_estimate, curr) +
        " \u2013 " +
        formatCurrency(lot.high_estimate, curr)
      );
    }
    if (lot.low_estimate != null) return formatCurrency(lot.low_estimate, curr) + "+";
    return "Up to " + formatCurrency(lot.high_estimate, curr);
  }

  function formatRealised(lot) {
    if (lot.realised_price == null) return "\u2014";
    return formatCurrency(lot.realised_price, lot.currency || "GBP");
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

  function normalizeName(name) {
    return (name || "")
      .toLowerCase()
      .replace(/^banksy[\s,;:-]+/i, "")
      .replace(/\s+/g, " ")
      .trim();
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
      var raw = (lot.print_name || "").trim();
      if (!raw) return;
      // Prefer a cleaner display name for suggestions
      var label = raw.replace(/^Banksy\s*[-–—:]\s*/i, "").trim() || raw;
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

    var nameHtml;
    if (lot.url) {
      nameHtml =
        '<a href="' +
        escapeHtml(lot.url) +
        '" target="_blank" rel="noopener">' +
        escapeHtml(lot.print_name) +
        "</a>";
    } else {
      nameHtml = escapeHtml(lot.print_name);
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
        return "<option value=\"" + escapeHtml(name) + "\"></option>";
      })
      .join("");
  }

  function applyFilterAndRender() {
    var mode = state.mode;
    var emptyState = document.getElementById("empty-state");
    var container = document.getElementById("auction-table-container");
    var countEl = document.getElementById("lot-count");
    var clearBtn = document.getElementById("print-filter-clear");
    var query = state.filterQuery;

    if (clearBtn) {
      clearBtn.hidden = !query;
    }

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
      if (emptyState) emptyState.style.display = "block";
      return;
    }

    var grouped = lots.length > 8;
    if (container) container.innerHTML = buildTable(lots, grouped, mode);
  }

  function setupFilter() {
    var filterBar = document.getElementById("filter-bar");
    var input = document.getElementById("print-filter");
    var clearBtn = document.getElementById("print-filter-clear");
    if (!input) return;

    if (filterBar) filterBar.style.display = "flex";

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

  function prepareLots(data, mode) {
    var lots = (data.lots || []).filter(function (lot) {
      return lot.is_original !== false;
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
    applyFilterAndRender();
  }

  function init() {
    var mode = pageMode();
    var dataUrl =
      mode === "completed" ? "data/completed.json" : "data/upcoming.json";

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
