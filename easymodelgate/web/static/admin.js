/**
 * EasyModelGate Admin JS - Shared utilities for admin pages
 */

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

// Format numbers for display
function formatNumber(n) {
    if (typeof n !== 'number') return n;
    if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(2) + 'K';
    return n.toString();
}

// Format timestamp (ms since epoch) to locale string
function formatTimestamp(ms) {
    const date = new Date(ms);
    return date.toLocaleString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
}

// Format uptime seconds to human readable
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

// Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Show badge element for status
function setStatusBadge(elementId, status) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const cls = status === 'healthy' ? 'badge-success' : 'badge-error';
    el.innerHTML = '<span class="badge ' + cls + '">' + escapeHtml(status) + '</span>';
}

// Set text content of element
function setElementValue(elementId, value) {
    const el = document.getElementById(elementId);
    if (el) el.textContent = value;
}

// Loading state for table
function setTableLoading(tableId, message = 'Loading...') {
    const tbody = document.querySelector('#' + tableId + ' tbody');
    if (tbody) {
        tbody.innerHTML = '<tr class="loading-row"><td colspan="99"><span class="badge badge-loading">' + escapeHtml(message) + '</span></td></tr>';
    }
}

// Empty state for table
function setTableEmpty(tableId, message = 'No data') {
    const tbody = document.querySelector('#' + tableId + ' tbody');
    if (tbody) {
        tbody.innerHTML = '<tr class="empty"><td colspan="99">' + escapeHtml(message) + '</td></tr>';
    }
}

// Render table rows from data array
function renderTableRows(tableId, items, rowRenderer) {
    const tbody = document.querySelector('#' + tableId + ' tbody');
    if (!tbody) return;

    if (!items || !items.length) {
        setTableEmpty(tableId);
        return;
    }

    tbody.innerHTML = items.map(rowRenderer).join('');
}

// Debounce utility
function debounce(fn, delay) {
    let timer = null;
    return function(...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

// Mobile sidebar toggle (if needed in future)
function initSidebarToggle() {
    const toggleBtn = document.getElementById('sidebar-toggle');
    const sidebar = document.querySelector('.sidebar');
    if (!toggleBtn || !sidebar) return;

    toggleBtn.addEventListener('click', () => {
        sidebar.classList.toggle('open');
    });

    // Close on outside click
    document.addEventListener('click', (e) => {
        if (sidebar.classList.contains('open') &&
            !sidebar.contains(e.target) &&
            !toggleBtn.contains(e.target)) {
            sidebar.classList.remove('open');
        }
    });
}

// Initialize common behaviors on DOM ready
document.addEventListener('DOMContentLoaded', function() {
    // Initialize sidebar toggle for mobile
    initSidebarToggle();

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
window.escapeHtml = escapeHtml;
window.setStatusBadge = setStatusBadge;
window.setElementValue = setElementValue;
window.setTableLoading = setTableLoading;
window.setTableEmpty = setTableEmpty;
window.renderTableRows = renderTableRows;