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
    var symbol = CURRENCY_SYMBOLS[currency] || currency + " ";
    return symbol + amount.toLocaleString();
  }

  function formatEstimate(lot) {
    if (!lot.low_estimate && !lot.high_estimate) return "Estimate N/A";
    var curr = lot.currency || "GBP";
    if (lot.low_estimate && lot.high_estimate) {
      return (
        formatCurrency(lot.low_estimate, curr) +
        " \u2013 " +
        formatCurrency(lot.high_estimate, curr)
      );
    }
    if (lot.low_estimate) return formatCurrency(lot.low_estimate, curr) + "+";
    return "Up to " + formatCurrency(lot.high_estimate, curr);
  }

  function formatDate(dateStr) {
    if (!dateStr) return "TBA";
    var d = new Date(dateStr + "T00:00:00");
    var months = [
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];
    return d.getDate() + " " + months[d.getMonth()] + " " + d.getFullYear();
  }

  function getMonthKey(dateStr) {
    if (!dateStr) return "TBA";
    var d = new Date(dateStr + "T00:00:00");
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

  function buildTable(lots, grouped) {
    var html = '<table class="auction-table">';
    html +=
      "<thead><tr>" +
      "<th></th>" +
      "<th>Print Name</th>" +
      "<th>Auction House</th>" +
      "<th>Date</th>" +
      "<th>Edition</th>" +
      "<th>Estimate</th>" +
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
          '<tr class="month-header"><td colspan="6">' +
          escapeHtml(month) +
          "</td></tr>";
        groups[month].forEach(function (lot) {
          html += buildRow(lot);
        });
      });
    } else {
      lots.forEach(function (lot) {
        html += buildRow(lot);
      });
    }

    html += "</tbody></table>";
    return html;
  }

  function buildRow(lot) {
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

    return (
      "<tr>" +
      "<td>" + imgHtml + "</td>" +
      "<td>" + nameHtml + "</td>" +
      "<td>" + escapeHtml(lot.auction_house) + "</td>" +
      "<td>" + formatDate(lot.auction_date) + "</td>" +
      "<td>" + escapeHtml(lot.edition || "\u2014") + "</td>" +
      "<td>" + formatEstimate(lot) + "</td>" +
      "</tr>"
    );
  }

  function render(data) {
    var loading = document.getElementById("loading");
    var emptyState = document.getElementById("empty-state");
    var container = document.getElementById("auction-table-container");
    var updatedEl = document.getElementById("last-updated");
    var countEl = document.getElementById("lot-count");

    if (loading) loading.style.display = "none";

    if (data.last_updated) {
      var d = new Date(data.last_updated);
      updatedEl.textContent = "Last updated: " + d.toLocaleString();
    }

    var lots = (data.lots || []).filter(function (lot) {
      return lot.is_original !== false;
    });

    // Sort by auction date ascending
    lots.sort(function (a, b) {
      if (!a.auction_date) return 1;
      if (!b.auction_date) return -1;
      return a.auction_date.localeCompare(b.auction_date);
    });

    if (lots.length === 0) {
      emptyState.style.display = "block";
      return;
    }

    countEl.textContent = lots.length + " lot" + (lots.length !== 1 ? "s" : "");

    var grouped = lots.length > 10;
    container.innerHTML = buildTable(lots, grouped);
  }

  function init() {
    fetch("../data/upcoming.json")
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(render)
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
