/* app.js - small UI behaviours. The site still works with JavaScript disabled. */
(function () {
  'use strict';

  // Password show/hide toggle: <button data-toggle-password="#fieldId">
  document.querySelectorAll('[data-toggle-password]').forEach(function (btn) {
    var input = document.querySelector(btn.getAttribute('data-toggle-password'));
    if (!input) { return; }
    btn.hidden = false;
    btn.addEventListener('click', function () {
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.textContent = show ? 'Hide' : 'Show';
      btn.setAttribute('aria-pressed', show ? 'true' : 'false');
      btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    });
  });

  // Mobile sidebar toggle
  var toggle = document.getElementById('sidebar-toggle');
  var shell = document.querySelector('.app-shell');
  if (toggle && shell) {
    toggle.addEventListener('click', function () {
      var open = shell.classList.toggle('sidebar-open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  // Dismiss flash messages
  document.querySelectorAll('.flash .flash-close').forEach(function (b) {
    b.addEventListener('click', function () { b.closest('.flash').remove(); });
  });

  // History: allow ticking at most two records to compare
  var boxes = document.querySelectorAll('input[name="ids"]');
  var cmpBtn = document.getElementById('compare-btn');
  var hint = document.getElementById('compare-hint');
  function updateCompare() {
    var checked = Array.prototype.filter.call(boxes, function (b) { return b.checked; });
    boxes.forEach(function (b) { b.disabled = !b.checked && checked.length >= 2; });
    if (cmpBtn) { cmpBtn.disabled = checked.length !== 2; }
    if (hint) { hint.textContent = checked.length + ' of 2 selected'; }
  }
  if (boxes.length) {
    boxes.forEach(function (b) { b.addEventListener('change', updateCompare); });
    updateCompare();
  }

  // Print / save as PDF
  document.querySelectorAll('[data-print]').forEach(function (b) {
    b.addEventListener('click', function () { window.print(); });
  });
})();
