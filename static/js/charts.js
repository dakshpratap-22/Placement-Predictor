/*
 * charts.js - tiny dependency-free chart helpers (line, grouped bar, doughnut)
 * drawn on <canvas>. Responsive (redraws on resize), with hover/tap tooltips,
 * HTML legends and an accessible "view data as table" fallback.
 *
 * Why not Chart.js? It works equally well - this file exists so the project has
 * no external/CDN dependency and runs fully offline in a college lab. To switch
 * to Chart.js later, only the three functions at the bottom (line/bar/doughnut)
 * need re-implementing; the page scripts call only those.
 *
 * Every value drawn comes from the data object passed in (server-generated from
 * saved database rows). Nothing is invented or smoothed here.
 */
(function (global) {
  'use strict';

  var PALETTE = ['#2f6fed', '#6d4fd6', '#17a673', '#e08a1e', '#d9534f', '#0ea5b7'];
  var TEXT = '#1c2433', MUTED = '#5a6478', GRID = '#e3e9f5';
  var FONT = '12px "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif';

  function niceScale(min, max, count) {
    if (!(max > min)) { max = min + 1; }
    var raw = (max - min) / count;
    var step = Math.pow(10, Math.floor(Math.log10(raw)));
    var err = raw / step;
    step *= err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1;
    var lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step, ticks = [];
    for (var v = lo; v <= hi + step / 2; v += step) { ticks.push(v); }
    return { min: lo, max: hi, ticks: ticks, step: step };
  }
  function fmt(v, step) {
    var d = step >= 1 ? 0 : Math.min(3, Math.ceil(-Math.log10(step) - 1e-9));
    return Number(v).toFixed(d);
  }
  function isNum(v) { return typeof v === 'number' && isFinite(v); }

  /* ---- shared canvas plumbing: DPR scaling, resize, tooltip hit-testing ---- */
  function mount(canvas, build) {
    var wrap = canvas.parentElement;
    wrap.style.position = 'relative';
    var tip = document.createElement('div');
    tip.className = 'pp-tooltip';
    tip.hidden = true;
    wrap.appendChild(tip);
    var hits = [], lastW = 0;

    function render() {
      var w = Math.max(240, wrap.clientWidth);
      var h = parseInt(canvas.getAttribute('data-height') || '300', 10);
      var dpr = window.devicePixelRatio || 1;
      lastW = wrap.clientWidth;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
      var ctx = canvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.font = FONT;
      hits = build(ctx, w, h) || [];
    }
    function find(x, y) {
      for (var i = hits.length - 1; i >= 0; i--) {
        var s = hits[i];
        if (s.type === 'circle') {
          if (Math.pow(x - s.x, 2) + Math.pow(y - s.y, 2) <= s.r * s.r) { return s; }
        } else if (s.type === 'rect') {
          if (x >= s.x && x <= s.x + s.w && y >= s.y && y <= s.y + s.h) { return s; }
        } else if (s.type === 'arc') {
          var dx = x - s.cx, dy = y - s.cy, d = Math.sqrt(dx * dx + dy * dy);
          var a = Math.atan2(dy, dx); if (a < -Math.PI / 2) { a += 2 * Math.PI; }
          if (d >= s.r0 && d <= s.r1 && a >= s.a0 && a <= s.a1) { return s; }
        }
      }
      return null;
    }
    function show(e) {
      var pt = e.touches ? e.touches[0] : e;
      var r = canvas.getBoundingClientRect();
      var x = pt.clientX - r.left, y = pt.clientY - r.top;
      var s = find(x, y);
      if (!s) { tip.hidden = true; return; }
      tip.innerHTML = '';
      s.lines.forEach(function (t, i) {
        var d = document.createElement(i === 0 ? 'strong' : 'div');
        d.textContent = t;
        tip.appendChild(d);
      });
      tip.hidden = false;
      var tx = Math.min(x + 14, wrap.clientWidth - tip.offsetWidth - 4);
      tip.style.left = Math.max(4, tx) + 'px';
      tip.style.top = Math.max(4, y - tip.offsetHeight - 10) + 'px';
    }
    canvas.addEventListener('mousemove', show);
    canvas.addEventListener('click', show);
    canvas.addEventListener('touchstart', show, { passive: true });
    canvas.addEventListener('mouseleave', function () { tip.hidden = true; });
    if (window.ResizeObserver) {
      new ResizeObserver(function () { if (wrap.clientWidth !== lastW) { render(); } }).observe(wrap);
    } else {
      window.addEventListener('resize', render);
    }
    window.addEventListener('beforeprint', render);
    render();
  }

  function emptyMessage(ctx, w, h, text) {
    ctx.fillStyle = MUTED; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(text || 'No data to display', w / 2, h / 2);
  }

  function axes(ctx, pad, w, h, scale, o) {
    var ph = h - pad.t - pad.b;
    ctx.font = FONT; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    scale.ticks.forEach(function (t) {
      var y = pad.t + ph - (t - scale.min) / (scale.max - scale.min) * ph;
      ctx.strokeStyle = GRID; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
      ctx.fillStyle = MUTED; ctx.fillText(fmt(t, scale.step) + (o.axisSuffix || ''), pad.l - 6, y);
    });
    if (o.yTitle) {
      ctx.save(); ctx.translate(12, pad.t + ph / 2); ctx.rotate(-Math.PI / 2);
      ctx.fillStyle = MUTED; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(o.yTitle, 0, 0); ctx.restore();
    }
    return function yOf(v) { return pad.t + ph - (v - scale.min) / (scale.max - scale.min) * ph; };
  }

  /* ---- HTML legend + accessible data table ---- */
  function legend(container, items) {
    if (!container) { return; }
    container.innerHTML = '';
    var ul = document.createElement('ul');
    ul.className = 'pp-legend';
    items.forEach(function (it) {
      var li = document.createElement('li');
      var sw = document.createElement('span');
      sw.className = 'pp-swatch'; sw.style.background = it.color;
      li.appendChild(sw); li.appendChild(document.createTextNode(it.name));
      ul.appendChild(li);
    });
    container.appendChild(ul);
  }

  function table(container, headers, rows) {
    if (!container) { return; }
    container.innerHTML = '';
    var det = document.createElement('details');
    det.className = 'pp-datatable';
    var sum = document.createElement('summary');
    sum.textContent = 'View chart data as a table';
    det.appendChild(sum);
    var wrap = document.createElement('div'); wrap.className = 'table-wrap';
    var t = document.createElement('table'); t.className = 'data';
    var thead = document.createElement('thead'), tr = document.createElement('tr');
    headers.forEach(function (h) { var th = document.createElement('th'); th.textContent = h; tr.appendChild(th); });
    thead.appendChild(tr); t.appendChild(thead);
    var tb = document.createElement('tbody');
    rows.forEach(function (r) {
      var row = document.createElement('tr');
      r.forEach(function (c) { var td = document.createElement('td'); td.textContent = (c === null || c === undefined) ? '–' : c; row.appendChild(td); });
      tb.appendChild(row);
    });
    t.appendChild(tb); wrap.appendChild(t); det.appendChild(wrap); container.appendChild(det);
  }

  /* ---- LINE chart -------------------------------------------------------
   * o: {labels, xLabels?, series:[{name,data,color?,pointColors?}], yMin?, yMax?,
   *     yTitle?, suffix?, extra?(i, seriesIndex) -> [lines]} */
  function line(canvas, o) {
    var series = o.series.map(function (s, i) { s.color = s.color || PALETTE[i % PALETTE.length]; return s; });
    var vals = [];
    series.forEach(function (s) { s.data.forEach(function (v) { if (isNum(v)) { vals.push(v); } }); });
    mount(canvas, function (ctx, w, h) {
      if (!vals.length) { emptyMessage(ctx, w, h); return []; }
      var pad = { l: 56, r: 18, t: 14, b: 36 };
      var lo = isNum(o.yMin) ? o.yMin : Math.min.apply(null, vals);
      var hi = isNum(o.yMax) ? o.yMax : Math.max.apply(null, vals);
      if (!isNum(o.yMin) && lo > 0 && lo === Math.min.apply(null, vals)) { lo = Math.min(0, lo); }
      var scale = niceScale(lo, hi, 5);
      var yOf = axes(ctx, pad, w, h, scale, o);
      var n = o.labels.length, pw = w - pad.l - pad.r;
      var xOf = function (i) { return n === 1 ? pad.l + pw / 2 : pad.l + pw * i / (n - 1); };
      var xl = o.xLabels || o.labels;
      var every = Math.max(1, Math.ceil(46 / (n > 1 ? pw / (n - 1) : pw)));
      ctx.fillStyle = MUTED; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      for (var i = 0; i < n; i += every) { ctx.fillText(xl[i], xOf(i), h - pad.b + 8); }
      var hits = [];
      series.forEach(function (s, si) {
        ctx.strokeStyle = s.color; ctx.lineWidth = 2.2; ctx.beginPath();
        var pen = false;
        s.data.forEach(function (v, i) {
          if (!isNum(v)) { pen = false; return; }
          if (!pen) { ctx.moveTo(xOf(i), yOf(v)); pen = true; } else { ctx.lineTo(xOf(i), yOf(v)); }
        });
        ctx.stroke();
        s.data.forEach(function (v, i) {
          if (!isNum(v)) { return; }
          var c = (s.pointColors && s.pointColors[i]) || s.color;
          ctx.fillStyle = '#fff'; ctx.strokeStyle = c; ctx.lineWidth = 2.2;
          ctx.beginPath(); ctx.arc(xOf(i), yOf(v), 4.5, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
          var lines = [o.labels[i], s.name + ': ' + fmt(v, 0.1) + (o.suffix || '')];
          if (o.extra) { lines = lines.concat(o.extra(i, si) || []); }
          hits.push({ type: 'circle', x: xOf(i), y: yOf(v), r: 11, lines: lines });
        });
      });
      return hits;
    });
    legend(o.legend, series.map(function (s) { return { name: s.name, color: s.color }; }));
    table(o.table, ['Record'].concat(series.map(function (s) { return s.name; })),
      o.labels.map(function (l, i) { return [l].concat(series.map(function (s) { return isNum(s.data[i]) ? s.data[i] : null; })); }));
  }

  /* ---- GROUPED BAR chart ------------------------------------------------
   * o: {labels, series:[{name,data,color?}], yMin?, yMax?, yTitle?, suffix?, extra?} */
  function bar(canvas, o) {
    var series = o.series.map(function (s, i) { s.color = s.color || PALETTE[i % PALETTE.length]; return s; });
    var vals = [];
    series.forEach(function (s) { s.data.forEach(function (v) { if (isNum(v)) { vals.push(v); } }); });
    mount(canvas, function (ctx, w, h) {
      if (!vals.length) { emptyMessage(ctx, w, h); return []; }
      var pad = { l: 56, r: 18, t: 22, b: 34 };
      var lo = isNum(o.yMin) ? o.yMin : Math.min(0, Math.min.apply(null, vals));
      var hi = isNum(o.yMax) ? o.yMax : Math.max.apply(null, vals);
      var scale = niceScale(lo, hi, 5);
      var yOf = axes(ctx, pad, w, h, scale, o);
      var n = o.labels.length, pw = w - pad.l - pad.r, gw = pw / n;
      var bw = Math.min(46, gw * 0.72 / series.length), group = bw * series.length;
      var zero = yOf(Math.max(scale.min, 0)), hits = [];
      ctx.textBaseline = 'top'; ctx.textAlign = 'center';
      o.labels.forEach(function (lab, i) {
        var cx = pad.l + gw * i + gw / 2;
        ctx.fillStyle = MUTED; ctx.fillText(lab, cx, h - pad.b + 8);
        series.forEach(function (s, si) {
          var v = s.data[i];
          if (!isNum(v)) { return; }
          var x = cx - group / 2 + si * bw, y = yOf(v);
          var top = Math.min(y, zero), ht = Math.max(1, Math.abs(zero - y));
          ctx.fillStyle = s.color; ctx.fillRect(x + 1, top, bw - 2, ht);
          ctx.fillStyle = TEXT; ctx.textBaseline = 'bottom';
          ctx.fillText(fmt(v, 0.1).replace(/\.0$/, ''), x + bw / 2, top - 3);
          ctx.textBaseline = 'top';
          var lines = [lab, s.name + ': ' + fmt(v, 0.1).replace(/\.0$/, '') + (o.suffix || '')];
          if (o.extra) { lines = lines.concat(o.extra(i, si) || []); }
          hits.push({ type: 'rect', x: x, y: top, w: bw, h: ht, lines: lines });
        });
      });
      return hits;
    });
    legend(o.legend, series.map(function (s) { return { name: s.name, color: s.color }; }));
    table(o.table, [''].concat(series.map(function (s) { return s.name; })),
      o.labels.map(function (l, i) { return [l].concat(series.map(function (s) { return isNum(s.data[i]) ? s.data[i] : null; })); }));
  }

  /* ---- DOUGHNUT chart ---------------------------------------------------
   * o: {labels, data, colors?, centerText?, emptyText?} */
  function doughnut(canvas, o) {
    var colors = o.colors || PALETTE;
    var total = o.data.reduce(function (a, b) { return a + (isNum(b) ? b : 0); }, 0);
    mount(canvas, function (ctx, w, h) {
      if (!total) { emptyMessage(ctx, w, h, o.emptyText); return []; }
      var cx = w / 2, cy = h / 2, r1 = Math.min(w, h) / 2 - 10, r0 = r1 * 0.58, a = -Math.PI / 2, hits = [];
      o.data.forEach(function (v, i) {
        if (!v) { return; }
        var sweep = v / total * 2 * Math.PI;
        ctx.beginPath(); ctx.arc(cx, cy, r1, a, a + sweep); ctx.arc(cx, cy, r0, a + sweep, a, true); ctx.closePath();
        ctx.fillStyle = colors[i % colors.length]; ctx.fill();
        ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
        hits.push({ type: 'arc', cx: cx, cy: cy, r0: r0, r1: r1, a0: a, a1: a + sweep,
          lines: [o.labels[i], v + ' record' + (v === 1 ? '' : 's') + ' (' + Math.round(v / total * 100) + '%)'] });
        a += sweep;
      });
      ctx.fillStyle = TEXT; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.font = '700 26px "Segoe UI", system-ui, sans-serif'; ctx.fillText(String(total), cx, cy - 8);
      ctx.font = FONT; ctx.fillStyle = MUTED; ctx.fillText(o.centerText || 'records', cx, cy + 14);
      return hits;
    });
    legend(o.legend, o.labels.map(function (l, i) { return { name: l + ' (' + o.data[i] + ')', color: colors[i % colors.length] }; }));
    table(o.table, ['Class', 'Records'], o.labels.map(function (l, i) { return [l, o.data[i]]; }));
  }

  global.PPCharts = { line: line, bar: bar, doughnut: doughnut, PALETTE: PALETTE };
})(window);
