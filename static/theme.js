// Theme switcher script
(function(){
    const bodyEl = document.body;
    const toggle = document.getElementById('theme-switch');
    const switchLabel = document.querySelector('.theme-switch');
    const announcer = document.getElementById('theme-announcer');

    function applyTheme(t) {
        if (!t || t === 'system') {
            bodyEl.classList.remove('dark');
            bodyEl.classList.remove('light');
            const preferDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
            bodyEl.classList.add(preferDark ? 'dark' : 'light');
        } else {
            bodyEl.classList.toggle('dark', t === 'dark');
            bodyEl.classList.toggle('light', t === 'light');
        }
    }

    // initial theme load
    let t = (bodyEl.className && bodyEl.className.trim()) || localStorage.getItem('theme') || 'system';
    applyTheme(t);

    // set visual state of the switch (checkbox) based on theme
    if (toggle) {
        const currentTheme = (localStorage.getItem('theme') || (bodyEl.classList.contains('dark') ? 'dark' : (bodyEl.classList.contains('light') ? 'light' : 'system')));
        toggle.checked = currentTheme === 'dark';
        // initialize aria-checked
        if (switchLabel) switchLabel.setAttribute('aria-checked', toggle.checked ? 'true' : 'false');
        toggle.addEventListener('change', function(){
            const next = toggle.checked ? 'dark' : 'light';
            localStorage.setItem('theme', next);
            applyTheme(next);
            if (switchLabel) switchLabel.setAttribute('aria-checked', toggle.checked ? 'true' : 'false');
            // announce
            if (announcer) announcer.textContent = 'Theme set to ' + next + ' mode.';
            fetch('/set_theme', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'theme=' + encodeURIComponent(next)
            }).catch(()=>{});
        });
    }
})();
