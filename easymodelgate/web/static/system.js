/**
 * EasyModelGate System Dashboard Page Logic
 */

(() => {
    'use strict';

    const {
        adminFetch,
        formatNumber,
        formatTimestamp,
        formatUptime,
        escapeHtml,
        setStatusBadge,
        setValue,
        setButtonLoading,
        getStatusBadgeHtml
    } = window.EMGAdmin;

    // ==================== System Page Logic ====================

    let isLoadingSystem = false;

    async function loadSystem() {
        if (isLoadingSystem) return;
        isLoadingSystem = true;

        showSystemLoading(true);

        try {
            // Load system info + recent requests + recent errors in parallel
            const [systemRes, requestsRes, errorsRes] = await Promise.allSettled([
                adminFetch('/admin/api/system'),
                adminFetch('/admin/api/requests?limit=50'),
                adminFetch('/admin/api/requests?limit=20&errors_only=true')
            ]);

            // Render system health cards
            if (systemRes.status === 'fulfilled') {
                renderSystemHealth(systemRes.value);
            } else {
                console.error('System load failed:', systemRes.reason);
                renderSystemHealthError();
            }

            // Render recent requests
            if (requestsRes.status === 'fulfilled') {
                renderSystemRequests(requestsRes.value.items || []);
            } else {
                console.error('System requests load failed:', requestsRes.reason);
                renderSystemRequestsError();
            }

            // Render recent errors
            if (errorsRes.status === 'fulfilled') {
                renderSystemErrors(errorsRes.value.items || []);
            } else {
                console.error('System errors load failed:', errorsRes.reason);
                renderSystemErrorsError();
            }

            // Show unhealthy banners
            if (systemRes.status === 'fulfilled') {
                checkUnhealthyBanners(systemRes.value);
            }

        } catch (err) {
            console.error('System load failed:', err);
            renderSystemHealthError();
            renderSystemRequestsError();
            renderSystemErrorsError();
        } finally {
            isLoadingSystem = false;
            showSystemLoading(false);
        }
    }

    // ==================== Health Cards ====================

    function renderSystemHealth(data) {
        if (!data) return;

        // Version
        setValue('sys-version', data.version || '—');

        // Health status cards
        setStatusBadge('sys-gateway', data.gateway?.status || 'unknown');
        const backendStatus = data.backend?.status || 'unknown';
        setStatusBadge('sys-backend', backendStatus);
        setStatusBadge('sys-database', data.database?.status || 'unknown');

        // Show unhealthy banners
        if (backendStatus === 'unhealthy') {
            showBackendUnhealthyBanner();
        }

        // Runtime info
        setValue('sys-uptime', data.uptime_seconds !== undefined ? formatUptime(data.uptime_seconds) : '—');
        setValue('sys-started', data.started_at ? formatTimestamp(data.started_at) : '—');

        // Last updated
        updateLastUpdated();
    }

    function renderSystemHealthError() {
        document.querySelectorAll('#system-cards .card-value').forEach(el => {
            el.innerHTML = '<span class="badge badge-error">Error</span>';
        });
    }

    function checkUnhealthyBanners(data) {
        if (data.backend?.status === 'unhealthy') {
            showBackendUnhealthyBanner();
        }
        if (data.database?.status === 'unhealthy') {
            showDatabaseUnhealthyBanner();
        }
    }

    function showBackendUnhealthyBanner() {
        const existing = document.getElementById('backend-unhealthy-banner');
        if (existing) return;

        const banner = document.createElement('div');
        banner.id = 'backend-unhealthy-banner';
        banner.className = 'unhealthy-banner backend';
        banner.innerHTML = `
            <div class="unhealthy-banner-content">
                <span class="unhealthy-icon">⚠</span>
                <span class="unhealthy-message">
                    <strong>Backend is unavailable</strong> — Model requests may currently fail until the backend recovers.
                </span>
            </div>
        `;

        const mainContent = document.querySelector('.main-content');
        if (mainContent) {
            mainContent.insertBefore(banner, mainContent.firstChild);
        }
    }

    function showDatabaseUnhealthyBanner() {
        const existing = document.getElementById('database-unhealthy-banner');
        if (existing) return;

        const banner = document.createElement('div');
        banner.id = 'database-unhealthy-banner';
        banner.className = 'unhealthy-banner database';
        banner.innerHTML = `
            <div class="unhealthy-banner-content">
                <span class="unhealthy-icon">⚠</span>
                <span class="unhealthy-message">
                    <strong>Database is unavailable</strong> — Some dashboard data may not load correctly.
                </span>
            </div>
        `;

        const mainContent = document.querySelector('.main-content');
        if (mainContent) {
            mainContent.insertBefore(banner, mainContent.firstChild);
        }
    }

    function showSystemLoading(loading) {
        const cards = document.querySelectorAll('#system-cards .card-value');
        cards.forEach(card => {
            if (loading) {
                card.innerHTML = '<span class="badge badge-loading">Loading...</span>';
            }
        });

        const tableContainers = ['system-requests-table', 'system-errors-table'];
        tableContainers.forEach(id => {
            const container = document.getElementById(id);
            if (container) {
                const tbody = container.querySelector('tbody');
                if (tbody && loading) {
                    tbody.innerHTML = '<tr class="loading-row"><td colspan="8"><span class="badge badge-loading">Loading...</span></td></tr>';
                }
            }
        });
    }

    // ==================== Recent Requests ====================

    function renderSystemRequests(items) {
        const container = document.getElementById('system-requests-table');
        if (!container) return;

        const tbody = container.querySelector('tbody');
        if (!tbody) return;

        if (!items.length) {
            tbody.innerHTML = '<tr class="empty"><td colspan="8">No recent requests.</td></tr>';
            return;
        }

        tbody.innerHTML = items.map(item => {
            const statusBadge = getStatusBadgeHtml(item.status_code);
            const tokens = item.total_tokens !== null && item.total_tokens !== undefined ? formatNumber(item.total_tokens) : '—';
            const duration = item.duration_ms !== null && item.duration_ms !== undefined ? item.duration_ms + ' ms' : '—';
            const username = item.username || '—';
            const keyName = item.key_name || item.masked_key || '—';
            const errorType = item.error_type || '—';

            return '<tr>' +
                '<td>' + formatTimestamp(item.started_at) + '</td>' +
                '<td>' + escapeHtml(item.username || '—') + '</td>' +
                '<td>' + escapeHtml(item.key_name || item.masked_key || '—') + '</td>' +
                '<td>' + escapeHtml(item.model || '—') + '</td>' +
                '<td>' + getStatusBadgeHtml(item.status_code) + '</td>' +
                '<td>' + (item.total_tokens !== null && item.total_tokens !== undefined ? formatNumber(item.total_tokens) : '—') + '</td>' +
                '<td>' + (item.duration_ms !== null && item.duration_ms !== undefined ? item.duration_ms + ' ms' : '—') + '</td>' +
                '<td>' + escapeHtml(item.error_type || '—') + '</td>' +
            '</tr>';
        }).join('');
    }

    function renderSystemRequestsError() {
        const container = document.getElementById('system-requests-table');
        if (!container) return;
        const tbody = container.querySelector('tbody');
        if (tbody) tbody.innerHTML = '<tr class="error"><td colspan="8"><span class="badge badge-error">Unable to load recent requests.</span></td></tr>';
    }

    // ==================== Recent Errors ====================

    function renderSystemErrors(items) {
        const container = document.getElementById('system-errors-table');
        if (!container) return;

        const tbody = container.querySelector('tbody');
        if (!tbody) return;

        if (!items.length) {
            tbody.innerHTML = '<tr class="empty"><td colspan="5">No recent errors.</td></tr>';
            return;
        }

        tbody.innerHTML = items.map(item => {
            const statusBadge = getStatusBadgeHtml(item.status_code);
            const errorType = item.error_type || 'unknown';
            const username = item.username || '—';

            return '<tr>' +
                '<td>' + formatTimestamp(item.started_at) + '</td>' +
                '<td>' + escapeHtml(username) + '</td>' +
                '<td>' + escapeHtml(item.model || '—') + '</td>' +
                '<td>' + getStatusBadgeHtml(item.status_code) + '</td>' +
                '<td>' + escapeHtml(errorType) + '</td>' +
            '</tr>';
        }).join('');
    }

    function renderSystemErrorsError() {
        const container = document.getElementById('system-errors-table');
        if (!container) return;
        const tbody = container.querySelector('tbody');
        if (tbody) tbody.innerHTML = '<tr class="error"><td colspan="5"><span class="badge badge-error">Unable to load recent errors.</span></td></tr>';
    }

    function updateLastUpdated() {
        const el = document.getElementById('last-updated');
        if (el) {
            el.textContent = 'Last updated: ' + new Date().toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        }
    }

    // ==================== Refresh ====================

    async function refreshSystem() {
        const refreshBtn = document.getElementById('btn-refresh');
        if (refreshBtn) setButtonLoading(refreshBtn, true);
        await loadSystem();
        if (refreshBtn) setButtonLoading(refreshBtn, false);
    }

    // ==================== Initialize ====================

    document.addEventListener('DOMContentLoaded', async function() {
        // Refresh button
        const refreshBtn = document.getElementById('btn-refresh');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                setButtonLoading(refreshBtn, true);
                loadSystem().finally(() => setButtonLoading(refreshBtn, false));
            });
        }

        await loadSystem();
    });

    // ==================== Exports ====================

    window.loadSystem = loadSystem;
    window.renderSystemHealth = renderSystemHealth;
    window.renderSystemRequests = renderSystemRequests;
    window.renderSystemErrors = renderSystemErrors;
})();