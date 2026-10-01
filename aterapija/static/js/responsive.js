/* Progressive enhancement for shared navigation and wide data components. */
(() => {
    const menu = document.getElementById('mainNav');
    const toggle = document.querySelector('[aria-controls="mainNav"]');
    if (menu && toggle) {
        menu.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && menu.classList.contains('show') && window.bootstrap) {
                window.bootstrap.Collapse.getOrCreateInstance(menu).hide();
                toggle.focus();
            }
        });
    }

    document.querySelectorAll('.table-responsive, .at-week-schedule__table-wrap').forEach((region) => {
        const hint = document.createElement('p');
        hint.className = 'at-scroll-hint';
        hint.textContent = '↔ ' + document.body.dataset.scrollHint;
        hint.hidden = true;
        region.before(hint);
        const update = () => {
            const overflow = region.scrollWidth > region.clientWidth + 1;
            hint.hidden = !overflow;
            if (overflow) {
                region.setAttribute('tabindex', '0');
                region.setAttribute('role', 'region');
                region.setAttribute('aria-label', document.body.dataset.scrollHint);
            } else {
                region.removeAttribute('tabindex');
                region.removeAttribute('role');
                region.removeAttribute('aria-label');
            }
        };
        update();
        if ('ResizeObserver' in window) {
            const observer = new ResizeObserver(update);
            observer.observe(region);
            if (region.firstElementChild) observer.observe(region.firstElementChild);
        } else {
            window.addEventListener('resize', update);
        }
        document.fonts?.ready.then(update);
    });
})();
