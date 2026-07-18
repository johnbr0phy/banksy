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
    // completed.html sets data-mode="completed" on <body>
    var mode = document.body && document.body.getAttribute("data-mode");
    if (mode === "completed") return "completed";
    if (/completed\.html/i.test(window.location.pathname)) return "completed";
    return "upcoming";
  }

  function buildTable(lots, grouped, mode) {
    var isCompleted = mode === "completed";
    var colCount = isCompleted ? 6 : 6;
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
      ? "<td class=\"price-realised\">" + formatRealised(lot) + "</td>"
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

  function render(data, mode) {
    var loading = document.getElementById("loading");
    var emptyState = document.getElementById("empty-state");
    var container = document.getElementById("auction-table-container");
    var updatedEl = document.getElementById("last-updated");
    var countEl = document.getElementById("lot-count");

    if (loading) loading.style.display = "none";

    if (updatedEl && data.last_updated) {
      var d = new Date(data.last_updated);
      updatedEl.textContent = "Last updated: " + d.toLocaleString();
    }

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

    if (lots.length === 0) {
      if (emptyState) emptyState.style.display = "block";
      return;
    }

    if (countEl) {
      countEl.textContent =
        lots.length + " lot" + (lots.length !== 1 ? "s" : "");
    }

    var grouped = lots.length > 8;
    if (container) container.innerHTML = buildTable(lots, grouped, mode);
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
