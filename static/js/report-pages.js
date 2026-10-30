/*
 * report-pages.js - draws the charts on the Reports, Compare and Simulator pages.
 * The data comes from a <script type="application/json" id="chart-data"> block
 * that the server fills from the user's SAVED records (or, on the simulator,
 * from the live model output). This file never creates data of its own.
 */
(function () {
  'use strict';
  var node = document.getElementById('chart-data');
  if (!node || !window.PPCharts) { return; }
  var data;
  try { data = JSON.parse(node.textContent); } catch (e) { return; }

  var GREEN = '#17a673', ORANGE = '#e08a1e', BLUE = '#2f6fed', PURPLE = '#6d4fd6';
  function el(id) { return document.getElementById(id); }
  function shortIds(labels) { return labels.map(function (l) { return l.split(' ')[0]; }); }
  function opts(name, o) { o.legend = el('l-' + name); o.table = el('t-' + name); return o; }
  function draw(fn, name, o) { var c = el('c-' + name); if (c) { PPCharts[fn](c, opts(name, o)); } }

  // 1. Prediction history trend
  if (data.trend && data.trend.labels.length) {
    var t = data.trend;
    draw('line', 'trend', {
      labels: t.labels, xLabels: shortIds(t.labels), yMin: 0, yMax: 100, suffix: '%', yTitle: 'Probability of "Placed" (%)', axisSuffix: '',
      series: [{ name: 'Estimated probability of Placed', data: t.probability, color: BLUE,
                 pointColors: t.classes.map(function (c) { return c === 'Placed' ? GREEN : ORANGE; }) }],
      extra: function (i) { return ['Model prediction: ' + t.classes[i], 'Model version: ' + t.versions[i]]; }
    });
  }

  // 2. Outcome distribution
  if (data.distribution) {
    draw('doughnut', 'dist', { labels: data.distribution.labels, data: data.distribution.counts,
      colors: [GREEN, ORANGE], centerText: 'predictions', emptyText: 'No records in this range' });
  }

  // 3 + 4. Two records side by side (probability + academic profile)
  var pair = data.pair;
  if (pair) {
    draw('bar', 'pair-prob', {
      labels: [pair.a_label, pair.b_label], yMin: 0, yMax: 100, suffix: '%', yTitle: 'Probability (%)',
      series: [{ name: 'Estimated probability of Placed', data: pair.probability, color: PURPLE }],
      extra: function (i) { return pair.classes ? ['Model prediction: ' + pair.classes[i]] : []; }
    });
    (pair.groups || []).forEach(function (g, i) {
      draw('bar', 'pair-g' + i, { labels: g.labels,
        series: [{ name: pair.a_label, data: g.a, color: BLUE }, { name: pair.b_label, data: g.b, color: PURPLE }] });
    });
  }

  // Academic values over time (all selected records, chronological)
  (data.timeline || []).forEach(function (g, i) {
    draw('line', 'timeline-g' + i, { labels: g.labels, xLabels: shortIds(g.labels), series: g.series });
  });

  // 5. What-if comparison (saved simulation on Reports; live result on the Simulator)
  if (data.whatif) {
    var w = data.whatif;
    draw('bar', 'whatif', { labels: w.labels, yMin: 0, yMax: 100, suffix: '%', yTitle: 'Probability (%)',
      series: [{ name: 'Estimated probability of Placed', data: w.probability, color: BLUE }],
      extra: function (i) { return w.classes ? ['Model prediction: ' + w.classes[i]] : []; } });
  }

  // 6. Role readiness: checklist coverage (NOT placement probability)
  if (data.readiness) {
    var r = data.readiness;
    draw('doughnut', 'readiness', { labels: ['Matched skills', 'Missing skills'], data: r.counts,
      colors: [GREEN, ORANGE], centerText: 'checklist skills', emptyText: 'No checklist for this role' });
  }
})();
