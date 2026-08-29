/**
 * EasyModelGate Admin JS - Shared utilities for admin pages
 */

// ==================== Shared API Helper ====================

// Unified fetch wrapper with auth handling and error normalization
async function adminFetch(url, options = {}) {
    const opts = {
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json',
            ...(options.headers || {})
        },
        ...options
    };

    const response = await fetch(url, opts);

    // 401 -> redirect to login
    if (response.status === 401) {
        const loginUrl = '/admin/login';
        if (window.location.pathname !== loginUrl) {
            window.location.href = loginUrl + '?redirect=' + encodeURIComponent(window.location.pathname + window.location.search);
        }
        throw new Error('Unauthorized');
    }

    // Try to parse JSON
    let data = null;
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
        data = await response.json().catch(() => null);
    }

    // Normalize error
    if (!response.ok) {
        const error = new Error(data?.error?.message || `HTTP ${response.status}`);
        error.status = response.status;
        error.code = data?.error?.code || 'unknown_error';
        error.data = data;
        throw error;
    }

    return data;
}

// ==================== Formatting Helpers ====================

function formatNumber(n) {
    if (typeof n !== 'number') return n;
    if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(2) + 'K';
    return n.toString();
}

function formatTimestamp(ms) {
    const date = new Date(ms);
    return date.toLocaleString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
}

function formatUptime(seconds) {
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const parts = [];
    if (d) parts.push(d + 'd');
    if (h) parts.push(h + 'h');
    if (m) parts.push(m + 'm');
    if (s || !parts.length) parts.push(s + 's');
    return parts.join(' ');
}

function formatTokenUsage(used, limit) {
    if (limit === null || limit === undefined) {
        return formatNumber(used) + ' / Unlimited';
    }
    const pct = limit > 0 ? Math.round((used / limit) * 100) : 0;
    return formatNumber(used) + ' / ' + formatNumber(limit) + ' (' + pct + '%)';
}

function formatRpm(rpm) {
    return rpm === null || rpm === undefined ? 'Unlimited' : rpm.toString();
}

// ==================== Security Helpers ====================

function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function safeTextContent(element, text) {
    if (element) element.textContent = text;
}

// ==================== Toast System ====================

let toastContainer = null;
let toastIdCounter = 0;

function initToastContainer() {
    if (toastContainer) return toastContainer;
    toastContainer = document.createElement('div');
    toastContainer.id = 'toast-container';
    toastContainer.setAttribute('aria-live', 'polite');
    toastContainer.setAttribute('aria-atomic', 'true');
    document.body.appendChild(toastContainer);
    return toastContainer;
}

function showToast(message, type = 'info', duration = 5000) {
    const container = initToastContainer();
    const id = 'toast-' + (++toastIdCounter);
    const toast = document.createElement('div');
    toast.id = id;
    toast.className = 'toast toast-' + type;
    toast.setAttribute('role', 'alert');
    toast.innerHTML = '<span class="toast-message">' + escapeHtml(message) + '</span>' +
        '<button type="button" class="toast-close" aria-label="Dismiss">&times;</button>';
    container.appendChild(toast);

    const closeBtn = toast.querySelector('.toast-close');
    closeBtn.addEventListener('click', () => removeToast(id));

    if (duration > 0) {
        setTimeout(() => removeToast(id), duration);
    }

    // Trigger reflow for animation
    requestAnimationFrame(() => toast.classList.add('show'));
    return id;
}

function removeToast(id) {
    const toast = document.getElementById(id);
    if (toast) {
        toast.classList.remove('show');
        toast.addEventListener('transitionend', () => toast.remove(), { once: true });
    }
}

function showSuccessToast(message, duration = 5000) {
    return showToast(message, 'success', duration);
}

function showErrorToast(message, duration = 8000) {
    return showToast(message, 'error', duration);
}

function showInfoToast(message, duration = 5000) {
    return showToast(message, 'info', duration);
}

// ==================== Modal System ====================

let modalStack = [];

function createModal(options) {
    const { title, content, actions, closeOnOverlay = true, closeOnEscape = true } = options;

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-labelledby', 'modal-title-' + Date.now());

    const modal = document.createElement('div');
    modal.className = 'modal';

    let html = '';
    if (title) {
        html += '<div class="modal-header">';
        html += '<h2 class="modal-title">' + escapeHtml(title) + '</h2>';
        html += '<button type="button" class="modal-close" aria-label="Close">&times;</button>';
        html += '</div>';
    }
    html += '<div class="modal-body">' + content + '</div>';
    if (actions && actions.length) {
        html += '<div class="modal-footer">';
        actions.forEach(action => {
            const cls = action.class || 'btn btn-secondary';
            html += '<button type="button" class="' + escapeHtml(cls) + '" data-action="' + escapeHtml(action.action) + '">' + escapeHtml(action.label) + '</button>';
        });
        html += '</div>';
    }
    modal.innerHTML = html;
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    const modalObj = {
        overlay,
        modal,
        close: () => {
            overlay.classList.add('closing');
            overlay.addEventListener('transitionend', () => overlay.remove(), { once: true });
            const idx = modalStack.indexOf(modalObj);
            if (idx >= 0) modalStack.splice(idx, 1);
            if (modalObj.onClose) modalObj.onClose();
        },
        onClose: options.onClose
    };

    // Close button
    const closeBtn = modal.querySelector('.modal-close');
    if (closeBtn) closeBtn.addEventListener('click', () => modalObj.close());

    // Overlay click
    if (closeOnOverlay) {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) modalObj.close();
        });
    }

    // Escape key
    if (closeOnEscape) {
        const handleEscape = (e) => {
            if (e.key === 'Escape' && modalStack[modalStack.length - 1] === modalObj) {
                modalObj.close();
            }
        };
        document.addEventListener('keydown', handleEscape);
        modalObj._handleEscape = handleEscape;
    }

    // Action buttons
    modal.querySelectorAll('[data-action]').forEach(btn => {
        btn.addEventListener('click', () => {
            const action = btn.getAttribute('data-action');
            if (modalObj.onAction) modalObj.onAction(action, modalObj);
        });
    });

    modalStack.push(modalObj);

    // Trigger animation
    requestAnimationFrame(() => overlay.classList.add('show'));

    return modalObj;
}

function confirmModal(title, message, onConfirm, onCancel) {
    return createModal({
        title,
        content: '<p>' + escapeHtml(message) + '</p>',
        actions: [
            { label: 'Cancel', action: 'cancel', class: 'btn btn-secondary' },
            { label: 'Confirm', action: 'confirm', class: 'btn btn-danger' }
        ],
        onAction: (action, modalObj) => {
            if (action === 'confirm') {
                modalObj.close();
                if (onConfirm) onConfirm();
            } else {
                modalObj.close();
                if (onCancel) onCancel();
            }
        }
    });
}

function alertModal(title, message) {
    return createModal({
        title,
        content: '<p>' + escapeHtml(message) + '</p>',
        actions: [
            { label: 'OK', action: 'ok', class: 'btn btn-primary' }
        ],
        onAction: (action, modalObj) => {
            modalObj.close();
        }
    });
}

function closeAllModals() {
    [...modalStack].forEach(m => m.close());
}

// ==================== Form Helpers ====================

function setButtonLoading(btn, loading) {
    if (!btn) return;
    if (loading) {
        btn.disabled = true;
        btn.dataset.originalText = btn.textContent;
        btn.textContent = btn.dataset.loadingText || 'Saving...';
    } else {
        btn.disabled = false;
        btn.textContent = btn.dataset.originalText || btn.textContent;
        delete btn.dataset.originalText;
    }
}

function getFormData(form) {
    const data = {};
    const formData = new FormData(form);
    for (const [key, value] of formData.entries()) {
        // Check if field should be omitted (empty optional fields)
        const input = form.querySelector('[name="' + key + '"]');
        if (input && input.dataset.omitIfEmpty === 'true' && value === '') {
            continue; // omit for KEEP semantics
        }
        // Handle checkbox for unlimited
        if (input && input.type === 'checkbox' && input.dataset.linkedInput) {
            const linked = form.querySelector('[name="' + input.dataset.linkedInput + '"]');
            if (linked) {
                data[key] = input.checked ? null : parseInt(linked.value) || null;
            }
            continue;
        }
        data[key] = value;
    }
    return data;
}

function clearForm(form) {
    form.reset();
    // Clear any error messages
    form.querySelectorAll('.form-error').forEach(el => el.textContent = '');
}

function showFormError(form, fieldName, message) {
    const errorEl = form.querySelector('[data-error-for="' + fieldName + '"]');
    if (errorEl) errorEl.textContent = message;
}

function clearFormErrors(form) {
    form.querySelectorAll('.form-error').forEach(el => el.textContent = '');
}

// ==================== Table Helpers ====================

function setTableLoading(tableId, message = 'Loading...') {
    const tbody = document.querySelector('#' + tableId + ' tbody');
    if (tbody) {
        tbody.innerHTML = '<tr class="loading-row"><td colspan="99"><span class="badge badge-loading">' + escapeHtml(message) + '</span></td></tr>';
    }
}

function setTableEmpty(tableId, message = 'No data') {
    const tbody = document.querySelector('#' + tableId + ' tbody');
    if (tbody) {
        tbody.innerHTML = '<tr class="empty"><td colspan="99">' + escapeHtml(message) + '</td></tr>';
    }
}

function setTableError(tableId, message = 'Unable to load data') {
    const tbody = document.querySelector('#' + tableId + ' tbody');
    if (tbody) {
        tbody.innerHTML = '<tr class="error"><td colspan="99"><span class="badge badge-error">' + escapeHtml(message) + '</span></td></tr>';
    }
}

function renderTableRows(tableId, items, rowRenderer) {
    const tbody = document.querySelector('#' + tableId + ' tbody');
    if (!tbody) return;

    if (!items || !items.length) {
        setTableEmpty(tableId);
        return;
    }

    tbody.innerHTML = items.map(rowRenderer).join('');
}

// ==================== Clipboard Helper ====================

async function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (e) {
            // fallback
        }
    }
    // Fallback
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
        document.execCommand('copy');
        document.body.removeChild(textarea);
        return true;
    } catch (e) {
        document.body.removeChild(textarea);
        return false;
    }
}

// ==================== Utility ====================

function debounce(fn, delay) {
    let timer = null;
    return function(...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

// ==================== Initialize Common Behaviors ====================

document.addEventListener('DOMContentLoaded', function() {
    // Initialize sidebar toggle for mobile
    const toggleBtn = document.getElementById('sidebar-toggle');
    const sidebar = document.querySelector('.sidebar');
    if (toggleBtn && sidebar) {
        toggleBtn.addEventListener('click', () => {
            sidebar.classList.toggle('open');
        });

        document.addEventListener('click', (e) => {
            if (sidebar.classList.contains('open') &&
                !sidebar.contains(e.target) &&
                !toggleBtn.contains(e.target)) {
                sidebar.classList.remove('open');
            }
        });
    }

    // Add active class to current nav item based on pathname
    const path = window.location.pathname;
    const navLinks = document.querySelectorAll('.nav-link');
    navLinks.forEach(link => {
        const href = link.getAttribute('href');
        if (href && (path === href || (href !== '/admin' && path.startsWith(href)))) {
            link.classList.add('active');
        }
    });
});

// Export for use in page scripts
window.adminFetch = adminFetch;
window.formatNumber = formatNumber;
window.formatTimestamp = formatTimestamp;
window.formatUptime = formatUptime;
window.formatTokenUsage = formatTokenUsage;
window.formatRpm = formatRpm;
window.escapeHtml = escapeHtml;
window.safeTextContent = safeTextContent;
window.showToast = showToast;
window.showSuccessToast = showSuccessToast;
window.showErrorToast = showErrorToast;
window.showInfoToast = showInfoToast;
window.createModal = createModal;
window.confirmModal = confirmModal;
window.alertModal = alertModal;
window.closeAllModals = closeAllModals;
window.setButtonLoading = setButtonLoading;
window.getFormData = getFormData;
window.clearForm = clearForm;
window.showFormError = showFormError;
window.clearFormErrors = clearFormErrors;
window.setTableLoading = setTableLoading;
window.setTableEmpty = setTableEmpty;
window.setTableError = setTableError;
window.renderTableRows = renderTableRows;
window.copyToClipboard = copyToClipboard;
window.debounce = debounce;