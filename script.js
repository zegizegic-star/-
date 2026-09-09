/* ==========================================================================
   Website script.js
   Vanilla JS, no dependencies. Organized as small independent modules,
   each with its own init(), wired up once on DOMContentLoaded.
   Every module no-ops safely if its markup isn't present on the page.
   ========================================================================== */

(function () {
  'use strict';

  /* -------------------------------------------------------------------
     0. SHARED HELPERS
     ---------------------------------------------------------------- */
  const prefersReducedMotion = () =>
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /** Debounce: waits for a pause in calls before firing. Used on resize. */
  function debounce(fn, wait = 150) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), wait);
    };
  }

  const qs = (selector, scope = document) => scope.querySelector(selector);
  const qsa = (selector, scope = document) => Array.from(scope.querySelectorAll(selector));

  /* -------------------------------------------------------------------
     1. STICKY HEADER
     Adds a border/shadow once the page scrolls past the hero padding.
     Uses requestAnimationFrame to avoid layout thrash on scroll.
     ---------------------------------------------------------------- */
  function initStickyHeader() {
    const header = qs('.site-header');
    if (!header) return;

    let ticking = false;
    const SCROLL_THRESHOLD = 8;

    const update = () => {
      header.classList.toggle('is-scrolled', window.scrollY > SCROLL_THRESHOLD);
      ticking = false;
    };

    window.addEventListener(
      'scroll',
      () => {
        if (!ticking) {
          window.requestAnimationFrame(update);
          ticking = true;
        }
      },
      { passive: true }
    );

    update(); // set correct state on load (e.g. after a page refresh mid-scroll)
  }

  /* -------------------------------------------------------------------
     2. MOBILE NAVIGATION
     Full-screen panel with focus trap, Escape-to-close, scroll lock,
     and focus restored to the toggle button on close.
     ---------------------------------------------------------------- */
  function initMobileNav() {
    const toggle = qs('#navToggle');
    const panel = qs('#mobileNav');
    if (!toggle || !panel) return;

    const FOCUSABLE = 'a[href], button:not([disabled])';
    let lastFocusedElement = null;

    const trapFocus = (event) => {
      if (event.key === 'Escape') {
        closePanel();
        return;
      }
      if (event.key !== 'Tab') return;

      const focusables = qsa(FOCUSABLE, panel);
      if (!focusables.length) return;

      const first = focusables[0];
      const last = focusables[focusables.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    function openPanel() {
      lastFocusedElement = document.activeElement;
      panel.classList.add('is-open');
      toggle.classList.add('is-active');
      toggle.setAttribute('aria-expanded', 'true');
      toggle.setAttribute('aria-label', 'Закрыть меню');
      document.body.style.overflow = 'hidden';

      const firstLink = qs(FOCUSABLE, panel);
      if (firstLink) firstLink.focus();

      document.addEventListener('keydown', trapFocus);
    }

    function closePanel() {
      panel.classList.remove('is-open');
      toggle.classList.remove('is-active');
      toggle.setAttribute('aria-expanded', 'false');
      toggle.setAttribute('aria-label', 'Открыть меню');
      document.body.style.overflow = '';
      document.removeEventListener('keydown', trapFocus);
      if (lastFocusedElement) lastFocusedElement.focus();
    }

    toggle.addEventListener('click', () => {
      panel.classList.contains('is-open') ? closePanel() : openPanel();
    });

    // Close on link click so navigation doesn't leave the panel open underneath.
    qsa('a', panel).forEach((link) => link.addEventListener('click', closePanel));

    // If the viewport grows into desktop while the panel is open, reset state
    // so it can't get stuck open behind the now-visible desktop nav.
    window.addEventListener(
      'resize',
      debounce(() => {
        if (window.innerWidth >= 1024 && panel.classList.contains('is-open')) {
          closePanel();
        }
      }, 150)
    );
  }

  /* -------------------------------------------------------------------
     3. SMOOTH SCROLL (header-aware)
     Native CSS smooth-scroll doesn't know about the sticky header height,
     so anchors land under it. This compensates and also moves keyboard
     focus to the target section for screen-reader / keyboard users.
     ---------------------------------------------------------------- */
  function initSmoothScroll() {
    const header = qs('.site-header');
    const links = qsa('a[href^="#"]');
    if (!links.length) return;

    links.forEach((link) => {
      link.addEventListener('click', (event) => {
        const hash = link.getAttribute('href');
        if (!hash || hash.length < 2) return; // ignore bare "#"

        const target = qs(hash);
        if (!target) return;

        event.preventDefault();

        // The header itself is the "#top" anchor and is sticky, so its
        // getBoundingClientRect().top reads 0 once stuck — applying the
        // usual header-offset compensation would land short of the real
        // top of the page. Scroll straight to 0 for that case.
        let top;
        if (target === header) {
          top = 0;
        } else {
          const headerOffset = header ? header.offsetHeight : 0;
          top = target.getBoundingClientRect().top + window.pageYOffset - headerOffset - 12;
        }

        window.scrollTo({
          top,
          behavior: prefersReducedMotion() ? 'auto' : 'smooth',
        });

        // Move focus once scrolling settles, so keyboard/screen-reader users
        // land where sighted users land. Section doesn't need a permanent
        // tabindex, so we add/remove it around the focus call.
        target.setAttribute('tabindex', '-1');
        target.addEventListener('blur', () => target.removeAttribute('tabindex'), {
          once: true,
        });
        window.setTimeout(
          () => target.focus({ preventScroll: true }),
          prefersReducedMotion() ? 0 : 550
        );

        history.pushState(null, '', hash);
      });
    });
  }

  /* -------------------------------------------------------------------
     4. ACTIVE NAVIGATION STATE
     Highlights the nav link matching the section currently in view.
     ---------------------------------------------------------------- */
  function initActiveNav() {
    const links = qsa('.main-nav a[href^="#"]');
    if (!links.length) return;

    const sectionToLink = new Map();
    links.forEach((link) => {
      const section = qs(link.getAttribute('href'));
      if (section) sectionToLink.set(section, link);
    });
    if (!sectionToLink.size) return;

    const clearActive = () =>
      links.forEach((link) => {
        link.classList.remove('is-active');
        link.removeAttribute('aria-current');
      });

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const link = sectionToLink.get(entry.target);
          if (!link) return;
          clearActive();
          link.classList.add('is-active');
          link.setAttribute('aria-current', 'true');
        });
      },
      { rootMargin: '-45% 0px -50% 0px', threshold: 0 }
    );

    sectionToLink.forEach((_link, section) => observer.observe(section));
  }

  /* -------------------------------------------------------------------
     5. SCROLL-REVEAL ANIMATIONS
     Elements marked [data-reveal] fade/rise into place once visible.
     A small stagger is applied to siblings so groups (cards, stats)
     animate in sequence rather than all at once.
     ---------------------------------------------------------------- */
  function initScrollReveal() {
    const items = qsa('[data-reveal]');
    if (!items.length) return;

    if (prefersReducedMotion()) {
      items.forEach((el) => el.classList.add('is-visible'));
      return;
    }

    const MAX_STAGGER_MS = 320;
    const STAGGER_STEP_MS = 70;

    const observer = new IntersectionObserver(
      (entries, obs) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const el = entry.target;

          const siblings = qsa(':scope > [data-reveal]', el.parentElement);
          const index = siblings.indexOf(el);
          const delay = Math.min(index * STAGGER_STEP_MS, MAX_STAGGER_MS);
          el.style.transitionDelay = `${delay}ms`;

          el.classList.add('is-visible');
          obs.unobserve(el);
        });
      },
      { threshold: 0.15, rootMargin: '0px 0px -40px 0px' }
    );

    items.forEach((el) => observer.observe(el));
  }

  /* -------------------------------------------------------------------
     6. ANIMATED STATISTIC COUNTERS
     Counts up from 0 to data-count once the stat scrolls into view.
     Runs once per element; ease-out cubic for a natural deceleration.
     ---------------------------------------------------------------- */
  function initCounters() {
    const counters = qsa('.stat-number[data-count]');
    if (!counters.length) return;

    const DURATION_MS = 1400;
    const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

    const animateCounter = (el) => {
      const target = parseInt(el.dataset.count, 10) || 0;

      if (prefersReducedMotion()) {
        el.textContent = target;
        return;
      }

      const start = performance.now();

      const tick = (now) => {
        const progress = Math.min((now - start) / DURATION_MS, 1);
        const value = Math.round(target * easeOutCubic(progress));
        el.textContent = value;
        if (progress < 1) window.requestAnimationFrame(tick);
        else el.textContent = target; // guarantee exact final value
      };

      window.requestAnimationFrame(tick);
    };

    const observer = new IntersectionObserver(
      (entries, obs) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          animateCounter(entry.target);
          obs.unobserve(entry.target);
        });
      },
      { threshold: 0.6 }
    );

    counters.forEach((el) => observer.observe(el));
  }

  /* -------------------------------------------------------------------
     7. FAQ ACCORDION
     Single-open accordion. Height animation is handled entirely in CSS
     via grid-template-rows; this module only manages state + a11y.
     ---------------------------------------------------------------- */
  function initFAQ() {
    const items = qsa('.faq-item');
    if (!items.length) return;

    items.forEach((item) => {
      const button = qs('.faq-question', item);
      if (!button) return;

      button.addEventListener('click', () => {
        const isOpen = item.classList.contains('is-open');

        items.forEach((other) => {
          other.classList.remove('is-open');
          const otherButton = qs('.faq-question', other);
          if (otherButton) otherButton.setAttribute('aria-expanded', 'false');
        });

        if (!isOpen) {
          item.classList.add('is-open');
          button.setAttribute('aria-expanded', 'true');
        }
      });
    });
  }

  /* -------------------------------------------------------------------
     8. RIPPLE BUTTON EFFECT
     Lightweight, dependency-free ripple using the Web Animations API
     so no keyframes or extra classes are needed in the stylesheet.
     Skipped entirely under reduced-motion.
     ---------------------------------------------------------------- */
  function initRippleEffect() {
    if (prefersReducedMotion()) return;

    const buttons = qsa('.btn');
    if (!buttons.length) return;

    buttons.forEach((btn) => {
      btn.addEventListener('click', (event) => {
        const rect = btn.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height) * 1.6;
        const originX = event.clientX ?? rect.left + rect.width / 2;
        const originY = event.clientY ?? rect.top + rect.height / 2;
        const x = originX - rect.left - size / 2;
        const y = originY - rect.top - size / 2;

        const ripple = document.createElement('span');
        ripple.style.cssText = [
          'position: absolute',
          `left: ${x}px`,
          `top: ${y}px`,
          `width: ${size}px`,
          `height: ${size}px`,
          'border-radius: 50%',
          'background: currentColor',
          'opacity: 0.25',
          'pointer-events: none',
        ].join(';');
        btn.appendChild(ripple);

        const animation = ripple.animate(
          [
            { transform: 'scale(0)', opacity: 0.35 },
            { transform: 'scale(1)', opacity: 0 },
          ],
          { duration: 600, easing: 'cubic-bezier(0.16, 1, 0.3, 1)' }
        );

        animation.onfinish = () => ripple.remove();
      });
    });
  }

  /* -------------------------------------------------------------------
     9. LAZY LOADING
     Defers offscreen media until it's about to enter the viewport.
     Native `loading="lazy"` is preferred where supported; this module
     covers data-src/data-bg patterns for anything that needs JS control
     (e.g. future case-study photography, background images).
     ---------------------------------------------------------------- */
  function initLazyLoading() {
    const targets = qsa('img[data-src], [data-bg]');
    if (!targets.length) return;

    const load = (el) => {
      if (el.dataset.src) {
        el.src = el.dataset.src;
        el.removeAttribute('data-src');
      }
      if (el.dataset.bg) {
        el.style.backgroundImage = `url(${el.dataset.bg})`;
        el.removeAttribute('data-bg');
      }
    };

    if (!('IntersectionObserver' in window)) {
      targets.forEach(load); // fallback: load everything immediately
      return;
    }

    const observer = new IntersectionObserver(
      (entries, obs) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          load(entry.target);
          obs.unobserve(entry.target);
        });
      },
      { rootMargin: '200px 0px' }
    );

    targets.forEach((el) => observer.observe(el));
  }

  /* -------------------------------------------------------------------
     10. CONTACT FORM
     Client-side validation with inline, screen-reader-announced errors
     (the markup wires each input to a #error-* span via aria-describedby).
     Submission posts to FormSubmit.co (see FORM_ENDPOINT below), which
     relays the data to the firm's inbox by email — no custom backend.
     ---------------------------------------------------------------- */
  function initContactForm() {
    const form = qs('#contactForm');
    if (!form) return;

    const FORM_ENDPOINT = 'https://formsubmit.co/ajax/sergeyvlg777@yandex.ru';

    const successBox = qs('#formSuccess');
    const errorBox = qs('#formError');
    const submitBtn = qs('.btn-submit', form);
    const submitLabel = qs('.btn-text', submitBtn);

    const fields = {
      name: {
        el: form.elements.name,
        error: qs('#error-name'),
        validate: (v) => (v.trim().length >= 2 ? '' : 'Введите имя — не менее 2 символов.'),
      },
      email: {
        el: form.elements.email,
        error: qs('#error-email'),
        validate: (v) =>
          /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim()) ? '' : 'Введите корректный email.',
      },
      service: {
        el: form.elements.service,
        error: qs('#error-service'),
        validate: (v) => (v ? '' : 'Выберите услугу из списка.'),
      },
      description: {
        el: form.elements.description,
        error: qs('#error-description'),
        validate: (v) =>
          v.trim().length >= 10 ? '' : 'Опишите задачу подробнее — от 10 символов.',
      },
      consent: {
        el: form.elements.consent,
        error: qs('#error-consent'),
        getValue: (el) => el.checked,
        validate: (checked) => (checked ? '' : 'Необходимо дать согласие на обработку персональных данных.'),
      },
    };

    // Validate on blur so errors appear as the person moves through the
    // form, not all at once on submit. Checkboxes also validate on change
    // so the error clears the moment they're checked, not only on blur.
    Object.values(fields).forEach(({ el, error, validate, getValue }) => {
      if (!el || !error) return;
      const readValue = () => (getValue ? getValue(el) : el.value);
      el.addEventListener('blur', () => {
        error.textContent = validate(readValue());
      });
      if (el.type === 'checkbox') {
        el.addEventListener('change', () => {
          error.textContent = validate(readValue());
        });
      }
    });

    form.addEventListener('submit', (event) => {
      event.preventDefault();

      let firstInvalidField = null;

      Object.values(fields).forEach(({ el, error, validate, getValue }) => {
        if (!el || !error) return;
        const message = validate(getValue ? getValue(el) : el.value);
        error.textContent = message;
        if (message && !firstInvalidField) firstInvalidField = el;
      });

      if (firstInvalidField) {
        firstInvalidField.focus();
        return;
      }

      const originalLabel = submitLabel ? submitLabel.textContent : '';
      submitBtn.disabled = true;
      if (submitLabel) submitLabel.textContent = 'Отправка…';
      if (successBox) successBox.hidden = true;
      if (errorBox) errorBox.hidden = true;

      fetch(FORM_ENDPOINT, {
        method: 'POST',
        headers: { Accept: 'application/json' },
        body: new FormData(form),
      })
        .then((res) => {
          if (!res.ok) throw new Error('Request failed');
          form.reset();
          if (successBox) {
            successBox.hidden = false;
            successBox.setAttribute('tabindex', '-1');
            successBox.focus();
          }
        })
        .catch(() => {
          if (errorBox) {
            errorBox.hidden = false;
            errorBox.setAttribute('tabindex', '-1');
            errorBox.focus();
          }
        })
        .finally(() => {
          submitBtn.disabled = false;
          if (submitLabel) submitLabel.textContent = originalLabel;
        });
    });
  }

  /* -------------------------------------------------------------------
     11. FOOTER YEAR
     Keeps the copyright year correct without a manual edit each January.
     ---------------------------------------------------------------- */
  function initFooterYear() {
    const el = qs('#year');
    if (el) el.textContent = new Date().getFullYear();
  }

  /* -------------------------------------------------------------------
     12. MOBILE STICKY CTA
     Hides itself once the real contact form scrolls into view, so it
     never sits on top of the form it's meant to lead people to.
     ---------------------------------------------------------------- */
  function initMobileCta() {
    const bar = qs('.mobile-cta');
    const contactSection = qs('#contact');
    if (!bar || !contactSection) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          bar.classList.toggle('is-hidden', entry.isIntersecting);
        });
      },
      { rootMargin: '0px 0px -40% 0px' }
    );

    observer.observe(contactSection);
  }

  /* -------------------------------------------------------------------
     SERVICE QUICK-SELECT
     Links tagged data-service (case cards, pricing CTAs) jump to the
     contact form and pre-select the matching option, so a visitor
     doesn't have to re-describe what they already told us by clicking.
     ---------------------------------------------------------------- */
  function initServiceQuickSelect() {
    const triggers = qsa('[data-service]');
    const select = qs('#service');
    if (!triggers.length || !select) return;

    triggers.forEach((trigger) => {
      trigger.addEventListener('click', () => {
        const value = trigger.dataset.service;
        if (!value || !qs(`option[value="${value}"]`, select)) return;

        select.value = value;
        select.classList.remove('field-highlight');
        // Force reflow so re-adding the class restarts the animation
        // even if the same service is picked twice in a row.
        void select.offsetWidth;
        select.classList.add('field-highlight');
        select.addEventListener(
          'animationend',
          () => select.classList.remove('field-highlight'),
          { once: true }
        );
      });
    });
  }

  /* -------------------------------------------------------------------
     INIT
     ---------------------------------------------------------------- */
  document.addEventListener('DOMContentLoaded', () => {
    initStickyHeader();
    initMobileNav();
    initSmoothScroll();
    initActiveNav();
    initScrollReveal();
    initCounters();
    initFAQ();
    initRippleEffect();
    initLazyLoading();
    initContactForm();
    initServiceQuickSelect();
    initFooterYear();
    initMobileCta();
  });
})();
