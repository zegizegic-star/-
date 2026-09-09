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
     8a. HERO PARALLAX
     Subtle mouse-driven depth on the oversized brand-mark watermark.
     Mouse-only (pointer: fine) and skipped under reduced-motion.
     ---------------------------------------------------------------- */
  function initHeroParallax() {
    const hero = qs('.hero');
    const bg = qs('.hero-bg');
    if (!hero || !bg) return;
    if (prefersReducedMotion()) return;
    if (!window.matchMedia('(pointer: fine)').matches) return;

    const RANGE = 16; // max px shift in any direction

    hero.addEventListener('mousemove', (event) => {
      const rect = hero.getBoundingClientRect();
      const nx = (event.clientX - rect.left) / rect.width - 0.5; // -0.5..0.5
      const ny = (event.clientY - rect.top) / rect.height - 0.5;
      bg.style.setProperty('--mx', `${nx * RANGE * -1}px`);
      bg.style.setProperty('--my', `${ny * RANGE * -1}px`);
    });

    hero.addEventListener('mouseleave', () => {
      bg.style.setProperty('--mx', '0px');
      bg.style.setProperty('--my', '0px');
    });
  }

  /* -------------------------------------------------------------------
     8b. MAGNETIC BUTTONS
     The primary hero CTA leans gently toward the cursor within its own
     bounds — a small, deliberate touch, not a gimmick. Mouse-only,
     skipped under reduced-motion.
     ---------------------------------------------------------------- */
  function initMagneticButtons() {
    const buttons = qsa('[data-magnetic]');
    if (!buttons.length) return;
    if (prefersReducedMotion()) return;
    if (!window.matchMedia('(pointer: fine)').matches) return;

    const STRENGTH = 0.25;
    const MAX_SHIFT = 8;

    buttons.forEach((btn) => {
      btn.addEventListener('mousemove', (event) => {
        const rect = btn.getBoundingClientRect();
        const x = event.clientX - rect.left - rect.width / 2;
        const y = event.clientY - rect.top - rect.height / 2;
        const shiftX = Math.max(-MAX_SHIFT, Math.min(MAX_SHIFT, x * STRENGTH));
        const shiftY = Math.max(-MAX_SHIFT, Math.min(MAX_SHIFT, y * STRENGTH));
        btn.style.transform = `translate(${shiftX}px, ${shiftY}px)`;
      });
      btn.addEventListener('mouseleave', () => {
        btn.style.transform = '';
      });
    });
  }

  /* -------------------------------------------------------------------
     8c. HERO WATERMARK DRAW-IN
     The oversized brand-mark watermark strokes itself in once, shortly
     after load, instead of just appearing — a small signature moment.
     Skipped under reduced-motion and below 1024px (mark is hidden there).
     ---------------------------------------------------------------- */
  function initHeroWatermarkDraw() {
    const paths = qsa('.hero-watermark path');
    if (!paths.length) return;
    if (!window.matchMedia('(min-width: 1024px)').matches) return;

    if (prefersReducedMotion()) {
      paths.forEach((path) => { path.style.strokeDashoffset = '0'; });
      return;
    }

    paths.forEach((path, index) => {
      const length = path.getTotalLength();
      path.style.transition = 'none';
      path.style.strokeDasharray = String(length);
      path.style.strokeDashoffset = String(length);
      // Force layout so the dashoffset above is committed before the
      // transition below is re-enabled, otherwise browsers may collapse
      // both into one paint and skip the animation entirely.
      void path.getBoundingClientRect();
      path.style.transition = '';
      setTimeout(() => {
        path.style.strokeDashoffset = '0';
      }, 300 + index * 250);
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
    const footer = qs('.site-footer');
    if (!bar || !contactSection) return;

    // Hidden while the contact form itself is in view (no need for the
    // shortcut right above the real form), and hidden again for the
    // footer so the fixed bar never sits over the legal links at the
    // very bottom of the page.
    const state = { contact: false, footer: false };
    const applyState = () => {
      bar.classList.toggle('is-hidden', state.contact || state.footer);
    };

    const contactObserver = new IntersectionObserver(
      ([entry]) => {
        state.contact = entry.isIntersecting;
        applyState();
      },
      { rootMargin: '0px 0px -40% 0px' }
    );
    contactObserver.observe(contactSection);

    if (footer) {
      const footerObserver = new IntersectionObserver(([entry]) => {
        state.footer = entry.isIntersecting;
        applyState();
      });
      footerObserver.observe(footer);
    }
  }

  /* -------------------------------------------------------------------
     12b. READING PROGRESS
     Fills the thin bar at the top of long article pages as the reader
     scrolls through the article body specifically (not the whole page,
     header/footer included) — no-ops on pages without .legal-page.
     ---------------------------------------------------------------- */
  function initReadingProgress() {
    const bar = qs('#readingProgressBar');
    const article = qs('.legal-page-inner');
    if (!bar || !article) return;

    const update = () => {
      const rect = article.getBoundingClientRect();
      const articleTop = rect.top + window.scrollY;
      const total = article.offsetHeight - window.innerHeight;
      if (total <= 0) {
        bar.style.width = '100%';
        return;
      }
      const progress = (window.scrollY - articleTop) / total;
      bar.style.width = `${Math.min(100, Math.max(0, progress * 100))}%`;
    };

    update();
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', debounce(update, 200));
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
     14. QUICK DIAGNOSTIC TOOL
     Two small client-side tools — nothing is sent anywhere until the
     visitor chooses to open the contact form: a short branching quiz
     that gauges urgency, and a rough calculator for revenue lost per
     day of a blocked listing. Both funnel into the contact form via
     the existing service quick-select (data-service).
     ---------------------------------------------------------------- */
  function initDiagnosticTool() {
    const section = qs('.diagnostic');
    if (!section) return;

    const tabQuiz = qs('#diagTabQuiz', section);
    const tabCalc = qs('#diagTabCalc', section);
    const viewQuiz = qs('#diagPanelQuiz', section);
    const viewCalc = qs('#diagPanelCalc', section);

    function activateTab(tab) {
      const isQuiz = tab === tabQuiz;
      tabQuiz.classList.toggle('is-active', isQuiz);
      tabCalc.classList.toggle('is-active', !isQuiz);
      tabQuiz.setAttribute('aria-selected', String(isQuiz));
      tabCalc.setAttribute('aria-selected', String(!isQuiz));
      viewQuiz.hidden = !isQuiz;
      viewCalc.hidden = isQuiz;
    }
    if (tabQuiz && tabCalc) {
      tabQuiz.addEventListener('click', () => activateTab(tabQuiz));
      tabCalc.addEventListener('click', () => activateTab(tabCalc));
    }

    // Quiz
    const stepSituation = qs('[data-diag-step="situation"]', section);
    const stepTiming = qs('[data-diag-step="timing"]', section);
    const stepResult = qs('[data-diag-step="result"]', section);
    const resultBadge = qs('.diagnostic-result-badge', section);
    const resultText = qs('.diagnostic-result-text', section);
    const resultCta = qs('.diagnostic-result-cta', section);

    const situationLabels = {
      'blocking-defense': 'блокировкой карточки или кабинета',
      'trademark-defense': 'претензией о нарушении прав',
      litigation: 'контрафактом в чужой карточке',
      'trademark-registration': 'регистрацией товарного знака',
    };
    const nextSteps = {
      'blocking-defense': [
        'Сделайте скриншоты уведомления о блокировке и переписки с площадкой с датой и временем.',
        'Не удаляйте и не редактируйте карточку до консультации — это может усложнить обращение.',
        'Свяжитесь с нами для анализа причины блокировки и подготовки обращения к площадке.',
      ],
      'trademark-defense': [
        'Сохраните претензию и все приложенные к ней документы.',
        'Не признавайте нарушение и не удаляйте карточку до анализа обоснованности требований.',
        'Свяжитесь с нами для оценки перспектив и подготовки мотивированного ответа.',
      ],
      litigation: [
        'Зафиксируйте нарушение — скриншоты карточки нарушителя с датой и временем.',
        'Соберите доказательства ваших прав на объект (свидетельство, авторство, договоры).',
        'Свяжитесь с нами для подготовки претензии и обращения к площадке.',
      ],
      'trademark-registration': [
        'Определите точный перечень товаров и услуг (классы МКТУ) для обозначения.',
        'Проверьте обозначение на схожесть с уже зарегистрированными знаками.',
        'Свяжитесь с нами для полной проверки и подготовки заявки в Роспатент.',
      ],
    };
    let situation = null;

    function showStep(step) {
      [stepSituation, stepTiming, stepResult].forEach((s) => {
        if (s) s.hidden = s !== step;
      });
    }

    function renderResult(timing) {
      const isUrgentCase =
        situation === 'blocking-defense' ||
        situation === 'trademark-defense' ||
        situation === 'litigation';
      const isUrgent = isUrgentCase && (timing === 'urgent' || timing === 'soon');

      resultBadge.textContent = isUrgent ? 'Высокий приоритет' : 'Стандартный срок';
      resultBadge.classList.toggle('is-urgent', isUrgent);

      const about = situationLabels[situation] || 'вашей ситуацией';
      resultText.textContent = isUrgent
        ? `Ситуация с ${about} обычно требует быстрой реакции — каждый день промедления увеличивает риски и потери. Рекомендуем обратиться сегодня.`
        : `По ситуации с ${about} есть время подготовиться взвешенно. Опишите детали — оценим перспективы в течение рабочего дня.`;

      if (resultCta) resultCta.dataset.service = situation || '';
      showStep(stepResult);
    }

    if (stepSituation) {
      qsa('[data-situation]', stepSituation).forEach((btn) => {
        btn.addEventListener('click', () => {
          situation = btn.dataset.situation;
          if (situation === 'trademark-registration') {
            renderResult('calm');
          } else {
            showStep(stepTiming);
          }
        });
      });
    }
    if (stepTiming) {
      qsa('[data-timing]', stepTiming).forEach((btn) => {
        btn.addEventListener('click', () => renderResult(btn.dataset.timing));
      });
      const back = qs('.diagnostic-back', stepTiming);
      if (back) back.addEventListener('click', () => showStep(stepSituation));
    }
    if (stepResult) {
      const restart = qs('.diagnostic-restart', stepResult);
      if (restart) {
        restart.addEventListener('click', () => {
          situation = null;
          showStep(stepSituation);
        });
      }

      const printBtn = qs('.diagnostic-print-cta', stepResult);
      const plan = qs('#diagPrintPlan');
      if (printBtn && plan) {
        printBtn.addEventListener('click', () => {
          if (!situation) return;
          const dateEl = qs('#printPlanDate', plan);
          const situationEl = qs('#printPlanSituation', plan);
          const urgencyEl = qs('#printPlanUrgency', plan);
          const textEl = qs('#printPlanText', plan);
          const stepsEl = qs('#printPlanSteps', plan);
          if (dateEl) dateEl.textContent = new Date().toLocaleDateString('ru-RU');
          if (situationEl) situationEl.textContent = situationLabels[situation] || '—';
          if (urgencyEl) urgencyEl.textContent = resultBadge.textContent;
          if (textEl) textEl.textContent = resultText.textContent;
          if (stepsEl) {
            stepsEl.innerHTML = '';
            (nextSteps[situation] || []).forEach((step) => {
              const li = document.createElement('li');
              li.textContent = step;
              stepsEl.appendChild(li);
            });
          }
          window.print();
        });
      }
    }

    // Calculator
    const calcRevenue = qs('#calcRevenue', section);
    const calcDays = qs('#calcDays', section);
    const calcResult = qs('#calcResult', section);
    const calcLoss = qs('#calcLoss', section);

    function updateCalc() {
      if (!calcRevenue || !calcDays || !calcResult || !calcLoss) return;
      const revenue = parseFloat(calcRevenue.value);
      const days = parseFloat(calcDays.value);
      if (!revenue || !days || revenue <= 0 || days <= 0) {
        calcResult.hidden = true;
        return;
      }
      const loss = Math.round(revenue * days);
      calcLoss.textContent = loss.toLocaleString('ru-RU') + ' ₽';
      calcResult.hidden = false;
    }
    if (calcRevenue) calcRevenue.addEventListener('input', updateCalc);
    if (calcDays) calcDays.addEventListener('input', updateCalc);
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
    initHeroParallax();
    initMagneticButtons();
    initHeroWatermarkDraw();
    initLazyLoading();
    initContactForm();
    initServiceQuickSelect();
    initDiagnosticTool();
    initFooterYear();
    initMobileCta();
    initReadingProgress();
  });
})();
