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

function setValue(elementId, value) {
    const el = document.getElementById(elementId);
    if (el) el.textContent = (value === null || value === undefined) ? '' : String(value);
}

function setStatusBadge(elementId, status) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const badgeClassFor = (s) => {
        if (s === 'healthy' || s === 'ok' || s === 'online') return 'badge-success';
        if (s === 'degraded' || s === 'warning') return 'badge-warning';
        if (s === 'unhealthy' || s === 'down' || s === 'error' || s === 'offline') return 'badge-error';
        if (s === 'loading' || s === 'pending') return 'badge-loading';
        return 'badge-neutral';
    };
    const badge = el.querySelector('.badge');
    if (badge) {
        badge.className = 'badge ' + badgeClassFor(status);
        badge.textContent = String(status);
    } else {
        el.textContent = String(status);
        el.dataset.status = status;
    }
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

// ==================== Shared Chart Helper ====================

/**
 * Render a simple line chart in an SVG container.
 * @param {HTMLElement} container - The container element (must have clientWidth)
 * @param {Array} items - Array of data points with .bucket and value field
 * @param {Object} options - Chart options
 * @param {string} options.valueField - Field name for y value (e.g., 'requests', 'total_tokens')
 * @param {string} options.color - Stroke color (CSS variable or hex)
 * @param {string} options.label - Chart label for figcaption
 * @param {number} options.height - Chart height in pixels (default 180)
 * @param {number} options.maxPoints - Max X axis labels to show (default 8)
 */
function renderLineChart(container, items, options) {
    if (!container) return;

    const {
        valueField = 'requests',
        color = 'var(--color-primary)',
        label = 'Chart',
        height = 180,
        maxPoints = 8
    } = options;

    if (!items || !items.length) {
        container.innerHTML = '<div class="chart-empty">No data.</div>';
        return;
    }

    const values = items.map(i => i[valueField] || 0);
    const maxVal = Math.max(...values);
    const buckets = items.map(i => i.bucket);
    const maxY = maxVal === 0 ? 1 : maxVal;

    const width = container.clientWidth || 600;
    const chartHeight = height;
    const padding = { top: 20, right: 30, bottom: 30, left: 45 };
    const innerWidth = width - padding.left - padding.right;
    const innerHeight = chartHeight - padding.top - padding.bottom;

    const xScale = (i) => padding.left + (innerWidth / Math.max(1, buckets.length - 1)) * i;
    const yScale = (val) => padding.top + innerHeight - (val / maxY) * innerHeight;

    let svg = '<svg width="' + width + '" height="' + chartHeight + '" viewBox="0 0 ' + width + ' ' + chartHeight + '" class="usage-chart" role="img" aria-label="' + escapeHtml(label) + ' chart">';
    // Grid lines (Y axis)
    for (let i = 0; i <= 4; i++) {
        const y = padding.top + (innerHeight / 4) * i;
        svg += '<line x1="' + padding.left + '" y1="' + y + '" x2="' + (width - padding.right) + '" y2="' + y + '" stroke="var(--color-border)" stroke-width="0.5"/>';
        const val = Math.round(maxY * (1 - i / 4));
        svg += '<text x="' + (padding.left - 8) + '" y="' + (y + 4) + '" font-size="9" fill="var(--color-text-muted)" text-anchor="end">' + formatNumber(val) + '</text>';
    }
    // X axis labels
    const labelCount = Math.min(buckets.length, 8);
    const step = Math.max(1, Math.floor(buckets.length / Math.max(1, labelCount)));
    for (let i = 0; i < buckets.length; i += step) {
        const x = padding.left + (innerWidth / Math.max(1, buckets.length - 1)) * i;
        svg += '<text x="' + x + '" y="' + (chartHeight - 30 + 18) + '" font-size="9" fill="var(--color-text-muted)" text-anchor="middle" transform="rotate(-45, ' + x + ', ' + (chartHeight - 30 + 18) + ')">' + escapeHtml(buckets[i]) + '</text>';
    }
    // Line
    let path = 'M';
    for (let i = 0; i < items.length; i++) {
        const x = padding.left + (innerWidth / Math.max(1, buckets.length - 1)) * i;
        const y = padding.top + innerHeight - ((items[i][valueField] || 0) / maxY) * innerHeight;
        path += (i === 0 ? '' : ' L') + x + ' ' + y;
    }
    const strokeColor = color.startsWith('var(') ? color : color;
    svg += '<path d="' + path + '" stroke="' + strokeColor + '" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>';
    // Points
    for (let i = 0; i < items.length; i++) {
        const x = padding.left + (innerWidth / Math.max(1, buckets.length - 1)) * i;
        const y = padding.top + innerHeight - ((items[i][valueField] || 0) / maxY) * innerHeight;
        svg += '<circle cx="' + x + '" cy="' + y + '" r="3" fill="' + strokeColor + '" stroke="var(--color-surface)" stroke-width="1.5"/>';
    }
    svg += '</svg>';

    container.innerHTML = '<figure class="chart-figure">' + svg + '<figcaption>' + escapeHtml(label) + '</figcaption></figure>';
}

// ==================== Shared Request Table Helper ====================

/**
 * Render a request table from items.
 * @param {string} tableId - The table element ID (without #)
 * @param {Array} items - Array of request log items
 * @param {Object} options - Render options
 * @param {boolean} options.showErrorType - Whether to show error_type column (default true for system, false for overview)
 * @param {boolean} options.showDuration - Whether to show duration column (default true)
 */
function renderRequestTable(tableId, items, options = {}) {
    const { showErrorType = true, showDuration = true } = options;
    const container = document.getElementById(tableId);
    if (!container) return;

    const tbody = container.querySelector('tbody');
    if (!tbody) return;

    if (!items || !items.length) {
        const colspan = 7 + (showErrorType ? 1 : 0);
        tbody.innerHTML = '<tr class="empty"><td colspan="' + colspan + '">No recent requests.</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(item => {
        const statusBadge = getStatusBadgeHtml(item.status_code);
        const tokens = item.total_tokens !== null && item.total_tokens !== undefined ? formatNumber(item.total_tokens) : '—';
        const duration = item.duration_ms !== null && item.duration_ms !== undefined ? item.duration_ms + ' ms' : '—';
        const username = item.username || '—';
        const keyName = item.key_name || item.masked_key || '—';
        const errorType = item.error_type || '—';

        let row = '<tr>' +
            '<td>' + formatTimestamp(item.started_at) + '</td>' +
            '<td>' + escapeHtml(username) + '</td>' +
            '<td>' + escapeHtml(keyName) + '</td>' +
            '<td>' + escapeHtml(item.model || '—') + '</td>' +
            '<td>' + getStatusBadgeHtml(item.status_code) + '</td>';

        if (showDuration) {
            row += '<td>' + tokens + '</td>' +
                '<td>' + (item.duration_ms !== null && item.duration_ms !== undefined ? item.duration_ms + ' ms' : '—') + '</td>';
        }

        if (showErrorType) {
            row += '<td>' + escapeHtml(errorType) + '</td>';
        }

        row += '</tr>';
        return row;
    }).join('');
}

function getStatusBadgeHtml(statusCode) {
    if (!statusCode) return '<span class="badge badge-neutral">—</span>';
    if (statusCode >= 200 && statusCode < 300) return '<span class="badge badge-success">HTTP ' + statusCode + '</span>';
    if (statusCode >= 400 && statusCode < 500) return '<span class="badge badge-warning">HTTP ' + statusCode + '</span>';
    if (statusCode >= 500) return '<span class="badge badge-error">HTTP ' + statusCode + '</span>';
    return '<span class="badge badge-neutral">HTTP ' + statusCode + '</span>';
}

// ==================== EMGAdmin Shared Namespace ====================
// The single formal shared frontend helper contract.
// Page scripts MUST obtain shared helpers exclusively from window.EMGAdmin.

window.EMGAdmin = {
    // Core API
    adminFetch,

    // Formatting
    formatNumber,
    formatTimestamp,
    formatUptime,
    formatTokenUsage,
    formatRpm,

    // Security
    escapeHtml,
    safeTextContent,
    setValue,
    setStatusBadge,

    // Toast
    showToast,
    showSuccessToast,
    showErrorToast,
    showInfoToast,

    // Modal
    createModal,
    confirmModal,
    alertModal,
    closeAllModals,

    // Form
    setButtonLoading,
    getFormData,
    clearForm,
    showFormError,
    clearFormErrors,

    // Table
    setTableLoading,
    setTableEmpty,
    setTableError,
    renderTableRows,

    // Clipboard
    copyToClipboard,

    // Utility
    debounce,

    // Chart
    renderLineChart,

    // Request Table
    renderRequestTable,
    getStatusBadgeHtml
};

// Backward-compatibility flat exports, derived from the single namespace
// above so both contracts cannot drift apart.
Object.assign(window, window.EMGAdmin);
