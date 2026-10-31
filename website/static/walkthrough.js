// Shows one walkthrough case at a time; also marks the page as scripted.
document.documentElement.classList.add('js');

const links = Array.from(document.querySelectorAll('.wt-list a[data-case]'));
const cases = Array.from(document.querySelectorAll('.wt-case'));

if (links.length && cases.length) {
  const ids = new Set(cases.map((c) => c.id));

  const show = (id, focus) => {
    const target = ids.has(id) ? id : cases[0].id;
    for (const c of cases) c.hidden = c.id !== target;
    for (const a of links) {
      if (a.dataset.case === target) a.setAttribute('aria-current', 'true');
      else a.removeAttribute('aria-current');
    }
    if (focus) {
      const heading = document.getElementById(`${target}-title`);
      if (heading) {
        heading.setAttribute('tabindex', '-1');
        heading.focus({ preventScroll: true });
      }
      // On narrow screens the picker sits above the case; bring the case into view.
      if (window.matchMedia('(max-width: 61.99rem)').matches) {
        document.getElementById(target)?.scrollIntoView({ block: 'start' });
      }
    }
  };

  for (const a of links) {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const id = a.dataset.case;
      history.replaceState(null, '', `#${id}`);
      show(id, true);
    });
  }
  window.addEventListener('hashchange', () => show(location.hash.slice(1), true));
  show(location.hash.slice(1), false);
}
