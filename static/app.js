/* Postfix Admin — UX layer: toasts, confirm modal, AJAX forms, live filters, theme */
(function () {
    'use strict';

    var csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

    /* ---------- Toasts ---------- */
    window.showToast = function (message, category) {
        category = category || 'info';
        var stack = document.getElementById('toastStack');
        if (!stack) return;
        var el = document.createElement('div');
        el.className = 'app-toast toast-' + category;
        el.setAttribute('role', 'status');
        el.innerHTML = '<span class="toast-dot"></span><span class="toast-text"></span>' +
            '<button type="button" class="toast-close" aria-label="Закрыть">&times;</button>';
        el.querySelector('.toast-text').textContent = message;
        el.querySelector('.toast-close').addEventListener('click', function () { dismiss(el); });
        stack.appendChild(el);
        requestAnimationFrame(function () { el.classList.add('show'); });
        setTimeout(function () { dismiss(el); }, 6000);
        function dismiss(node) {
            node.classList.remove('show');
            setTimeout(function () { node.remove(); }, 300);
        }
    };

    // flash-сообщения с сервера превращаем в тосты
    document.querySelectorAll('.js-flash').forEach(function (el) {
        var cat = (el.className.match(/alert-(\w+)/) || [])[1] || 'info';
        window.showToast(el.textContent.replace('×', '').trim(), cat);
        el.remove();
    });

    /* ---------- Confirm modal ---------- */
    var confirmModalEl = document.getElementById('confirmModal');
    var confirmModal = (window.bootstrap && confirmModalEl) ? new bootstrap.Modal(confirmModalEl) : null;
    var pendingForm = null;

    function askConfirm(message, form) {
        if (!confirmModal) { // graceful fallback
            if (window.confirm(message)) form.submit();
            return;
        }
        pendingForm = form;
        document.getElementById('confirmBody').textContent = message;
        confirmModal.show();
    }
    var okBtn = document.getElementById('confirmOk');
    if (okBtn) {
        okBtn.addEventListener('click', function () {
            confirmModal.hide();
            if (pendingForm) submitForm(pendingForm);
            pendingForm = null;
        });
    }

    /* ---------- AJAX forms ---------- */
    // Любая форма с data-ajax отправляется fetch'ом, ответ показывается тостом.
    // data-confirm="текст" — сначала модальное подтверждение.
    // data-ajax-remove-row — при успехе удалить строку таблицы.
    // data-ajax-reload — при успехе перезагрузить страницу через 0.8 c.
    document.addEventListener('submit', function (ev) {
        var form = ev.target;
        if (!(form instanceof HTMLFormElement) || !form.hasAttribute('data-ajax')) return;
        ev.preventDefault();
        var confirmText = form.getAttribute('data-confirm');
        if (confirmText) { askConfirm(confirmText, form); return; }
        submitForm(form);
    });

    function submitForm(form) {
        var btn = form.querySelector('[type=submit]');
        if (btn) { btn.disabled = true; btn.classList.add('btn-busy'); }
        // Демо-режим (статическое превью без сервера): имитируем успех
        if (window.PFA_DEMO) {
            setTimeout(function () {
                window.showToast('Демо-режим: действие выполнено (имитация)', 'success');
                if (form.hasAttribute('data-ajax-remove-row')) {
                    var tr = form.closest('tr');
                    if (tr) { tr.classList.add('row-removing'); setTimeout(function () { tr.remove(); }, 350); }
                }
                if (form.hasAttribute('data-ajax-reset')) form.reset();
                if (btn) { btn.disabled = false; btn.classList.remove('btn-busy'); }
            }, 500);
            return;
        }
        fetch(form.action, {
            method: (form.method || 'POST').toUpperCase(),
            body: new FormData(form),
            headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrfToken }
        }).then(function (r) {
            var ct = r.headers.get('Content-Type') || '';
            if (ct.indexOf('application/json') !== -1) return r.json();
            // сервер прислал редирект/HTML (например, сессия истекла)
            window.location.href = r.url;
            return null;
        }).then(function (data) {
            if (!data) return;
            window.showToast(data.message || 'Готово', data.category || (data.ok ? 'success' : 'danger'));
            if (data.ok) {
                if (form.hasAttribute('data-ajax-remove-row')) {
                    var tr = form.closest('tr');
                    if (tr) {
                        tr.classList.add('row-removing');
                        setTimeout(function () { tr.remove(); }, 350);
                    }
                }
                if (form.hasAttribute('data-ajax-reload')) {
                    setTimeout(function () { window.location.reload(); }, 900);
                }
                if (form.hasAttribute('data-ajax-reset')) form.reset();
            }
        }).catch(function () {
            window.showToast('Нет связи с сервером', 'danger');
        }).finally(function () {
            if (btn) { btn.disabled = false; btn.classList.remove('btn-busy'); }
        });
    }

    /* ---------- Live-фильтр таблиц ---------- */
    // <input data-filter-table="#tableId"> — мгновенный фильтр строк по тексту
    document.querySelectorAll('[data-filter-table]').forEach(function (input) {
        var table = document.querySelector(input.getAttribute('data-filter-table'));
        if (!table) return;
        var counter = input.getAttribute('data-filter-counter');
        input.addEventListener('input', function () {
            var needle = input.value.toLowerCase();
            var visible = 0, total = 0;
            table.querySelectorAll('tbody tr').forEach(function (tr) {
                if (tr.hasAttribute('data-empty-row')) return;
                total++;
                var show = tr.textContent.toLowerCase().indexOf(needle) !== -1;
                tr.style.display = show ? '' : 'none';
                if (show) visible++;
            });
            if (counter) {
                var el = document.querySelector(counter);
                if (el) el.textContent = needle ? ('Найдено: ' + visible + ' из ' + total) : ('Всего: ' + total);
            }
        });
    });

    /* ---------- Тема оформления ---------- */
    var saved = null;
    try { saved = localStorage.getItem('pfa-theme'); } catch (e) {}
    if (saved) document.documentElement.setAttribute('data-theme', saved);
    var toggle = document.getElementById('themeToggle');
    if (toggle) {
        toggle.addEventListener('click', function () {
            var cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', cur);
            try { localStorage.setItem('pfa-theme', cur); } catch (e) {}
        });
    }

    /* ---------- Автообновление только на видимой вкладке ---------- */
    // Страницы с <body data-autorefresh="15"> обновляются, только если вкладка активна
    var ar = parseInt(document.body.getAttribute('data-autorefresh') || '0', 10);
    if (ar > 0) {
        setInterval(function () {
            if (!document.hidden) window.location.reload();
        }, ar * 1000);
    }
})();
