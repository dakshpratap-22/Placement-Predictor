/*
 * admin-charts.js - draws the two charts on the Admin dashboard.
 * Data comes from <script type="application/json" id="chart-data">, filled by
 * admin.py from the database. This file never creates data of its own.
 */
(function () {
  'use strict';
  var node = document.getElementById('chart-data');
  if (!node || !window.PPCharts) { return; }
  var data;
  try { data = JSON.parse(node.textContent); } catch (e) { return; }
  var GREEN = '#17a673', ORANGE = '#e08a1e', BLUE = '#2f6fed';
  function el(id) { return document.getElementById(id); }

  var d = data.daily, c1 = el('c-daily');
  if (d && c1) {
    PPCharts.line(c1, {
      labels: d.labels, xLabels: d.labels.map(function (s) { return s.slice(5); }),
      yMin: 0, yTitle: 'Predictions per day',
      series: [{ name: 'Predictions run', data: d.counts, color: BLUE }],
      legend: el('l-daily'), table: el('t-daily')
    });
  }
  var o = data.distribution, c2 = el('c-outcome');
  if (o && c2) {
    PPCharts.doughnut(c2, {
      labels: o.labels, data: o.counts, colors: [GREEN, ORANGE], centerText: 'predictions',
      emptyText: 'No predictions yet', legend: el('l-outcome'), table: el('t-outcome')
    });
  }
})();
