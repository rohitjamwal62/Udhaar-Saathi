/* UdhaarSaathi site.js - progressive enhancement only; every page works without it. */
(function () {
  'use strict';
  var doc = document;
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* SMIL ignores CSS media queries, so pause it ourselves for reduced motion. */
  if (reduce) {
    doc.querySelectorAll('svg').forEach(function (s) { if (s.pauseAnimations) { s.pauseAnimations(); } });
  }

  /* Header shadow */
  var header = doc.querySelector('.site-header');
  function onScroll() { if (header) { header.classList.toggle('scrolled', window.scrollY > 4); } }
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });

  /* Mobile drawer */
  var toggle = doc.getElementById('nav-toggle');
  var nav = doc.getElementById('site-nav');
  if (toggle && nav) {
    var setOpen = function (open) {
      nav.classList.toggle('open', open);
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    };
    toggle.addEventListener('click', function () { setOpen(toggle.getAttribute('aria-expanded') !== 'true'); });
    nav.addEventListener('click', function (e) { if (e.target.closest('a')) { setOpen(false); } });
    doc.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') { setOpen(false); toggle.focus(); }
    });
    window.addEventListener('resize', function () { if (window.innerWidth >= 900) { setOpen(false); } });
  }

  /* Scroll reveal + draw-on-reveal + count-up */
  var targets = doc.querySelectorAll('.reveal, .a-draw.pre');
  function countUp(el) {
    var end = parseInt(el.getAttribute('data-count'), 10);
    if (isNaN(end) || reduce) { el.textContent = el.getAttribute('data-count'); return; }
    var start = null;
    (function step(t) {
      if (start === null) { start = t; }
      var p = Math.min((t - start) / 900, 1);
      el.textContent = Math.round(end * (1 - Math.pow(1 - p, 3)));
      if (p < 1) { requestAnimationFrame(step); }
    })(performance.now());
  }
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) {
          en.target.classList.add('in');
          en.target.querySelectorAll('[data-count]').forEach(countUp);
          io.unobserve(en.target);
        }
      });
    }, { threshold: 0.15, rootMargin: '0px 0px -5% 0px' });
    targets.forEach(function (t) { io.observe(t); });
  } else {
    targets.forEach(function (t) { t.classList.add('in'); });
  }

  /* Password show/hide */
  doc.querySelectorAll('.pw .toggle').forEach(function (btn) {
    btn.hidden = false;
    btn.addEventListener('click', function () {
      var input = btn.parentNode.querySelector('input');
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.textContent = show ? 'Hide' : 'Show';
      btn.setAttribute('aria-pressed', show ? 'true' : 'false');
    });
  });

  /* OTP resend countdown */
  var rs = doc.getElementById('resend-btn');
  if (rs) {
    var left = parseInt(rs.getAttribute('data-wait'), 10) || 0;
    var msg = doc.getElementById('resend-msg');
    var tick = function () {
      if (left > 0) {
        rs.disabled = true;
        if (msg) { msg.textContent = 'You can request a new code in ' + left + 's.'; }
        left -= 1;
        setTimeout(tick, 1000);
      } else {
        rs.disabled = false;
        if (msg) { msg.textContent = 'Did not get the email? Check spam, then request a new code.'; }
      }
    };
    tick();
  }

  /* Drag and drop filename */
  doc.querySelectorAll('.drop').forEach(function (zone) {
    var input = zone.querySelector('input[type=file]');
    var out = zone.querySelector('.fname');
    if (!input) { return; }
    input.addEventListener('change', function () {
      if (out) {
        var f = input.files && input.files[0];
        out.textContent = f ? f.name + ' (' + (f.size / 1048576).toFixed(2) + ' MB)' : '';
      }
    });
    ['dragenter', 'dragover'].forEach(function (ev) { zone.addEventListener(ev, function () { zone.classList.add('over'); }); });
    ['dragleave', 'drop'].forEach(function (ev) { zone.addEventListener(ev, function () { zone.classList.remove('over'); }); });
  });

  /* Toasts: close button + auto-dismiss (errors stay until closed) */
  doc.querySelectorAll('.toast').forEach(function (t) {
    var dismiss = function () { t.classList.add('out'); setTimeout(function () { t.remove(); }, 320); };
    var b = t.querySelector('button');
    if (b) { b.hidden = false; b.addEventListener('click', dismiss); }
    if (!t.classList.contains('toast-error')) { setTimeout(dismiss, 7000); }
  });
})();
