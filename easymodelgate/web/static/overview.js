/**
 * EasyModelGate Overview Dashboard Page Logic
 */

const {
    adminFetch,
    formatNumber,
    formatTimestamp,
    escapeHtml,
    setStatusBadge,
    setValue,
    setButtonLoading,
    getStatusBadgeHtml
} = window.EMGAdmin;

// ==================== Overview Page Logic ====================

let isLoadingOverview = false;

async function loadOverview() {
    if (isLoadingOverview) return;
    isLoadingOverview = true;

    showOverviewLoading(true);

    try {
        // Load overview main data + 24h trend + recent requests + recent errors in parallel
        const [overviewRes, trendRes, requestsRes, errorsRes] = await Promise.allSettled([
            adminFetch('/admin/api/overview'),
            adminFetch('/admin/api/usage/timeseries?period=24h&group_by=hour'),
            adminFetch('/admin/api/requests?limit=10'),
            adminFetch('/admin/api/requests?limit=5&errors_only=true')
        ]);

        // Render overview health cards
        if (overviewRes.status === 'fulfilled') {
            renderOverviewHealth(overviewRes.value);
        } else {
            console.error('Overview load failed:', overviewRes.reason);
            renderOverviewHealthError();
        }

        // Render 24h usage trend charts
        if (trendRes.status === 'fulfilled') {
            renderOverviewTrend(trendRes.value);
        } else {
            console.error('Trend load failed:', trendRes.reason);
            renderOverviewTrendError();
        }

        // Render recent requests
        if (requestsRes.status === 'fulfilled') {
            renderRecentRequests(requestsRes.value.items || []);
        } else {
            console.error('Recent requests load failed:', requestsRes.reason);
            renderRecentRequestsError();
        }

        // Render recent errors
        if (errorsRes.status === 'fulfilled') {
            renderRecentErrors(errorsRes.value.items || []);
        } else {
            console.error('Recent errors load failed:', errorsRes.reason);
            renderRecentErrorsError();
        }

    } catch (err) {
        console.error('Overview load failed:', err);
        renderOverviewHealthError();
        renderOverviewTrendError();
        renderRecentRequestsError();
        renderRecentErrorsError();
    } finally {
        isLoadingOverview = false;
        showOverviewLoading(false);
    }
}

// ==================== Health Cards ====================

function renderOverviewHealth(data) {
    if (!data) return;

    const today = data.today || {};
    const activeKeys = data.active_keys || 0;

    // Gateway status
    setStatusBadge('card-gateway', data.gateway?.status || 'unknown');

    // Backend status
    const backendStatus = data.backend?.status || 'unknown';
    setStatusBadge('card-backend', backendStatus);

    // Show backend unhealthy banner if needed
    if (backendStatus === 'unhealthy') {
        showBackendUnhealthyBanner();
    }

    // Today metrics
    setValue('card-requests', today.requests ?? '—');
    setValue('card-tokens', formatNumber(today.total_tokens ?? '—'));
    setValue('card-success-rate', today.success_rate !== undefined ? (today.success_rate * 100).toFixed(1) + '%' : '—');
    setValue('card-ttft', today.avg_ttft_ms !== undefined && today.avg_ttft_ms !== null ? today.avg_ttft_ms.toFixed(1) + ' ms' : '—');
    setValue('card-keys', activeKeys ?? '—');
}

function renderOverviewHealthError() {
    document.querySelectorAll('#overview-cards .card-value').forEach(el => {
        el.innerHTML = '<span class="badge badge-error">Error</span>';
    });
}

function showBackendUnhealthyBanner() {
    const existing = document.getElementById('backend-unhealthy-banner');
    if (existing) return;

    const banner = document.createElement('div');
    banner.id = 'backend-unhealthy-banner';
    banner.className = 'unhealthy-banner';
    banner.innerHTML = `
        <div class="unhealthy-banner-content">
            <span class="unhealthy-icon">⚠</span>
            <span class="unhealthy-message">
                <strong>Backend is unavailable</strong> — Model requests may currently fail.
            </span>
            <a href="{{ url_for('admin_system') }}" class="btn btn-secondary btn-sm">View System</a>
        </div>
    `;

    const mainContent = document.querySelector('.main-content');
    if (mainContent) {
        mainContent.insertBefore(banner, mainContent.firstChild);
    }
}

function showOverviewLoading(loading) {
    const cards = document.querySelectorAll('#overview-cards .card-value');
    cards.forEach(card => {
        if (loading) {
            card.innerHTML = '<span class="badge badge-loading">Loading...</span>';
        }
    });

    const chartContainers = ['requests-trend-container', 'tokens-trend-container'];
    chartContainers.forEach(id => {
        const container = document.getElementById(id);
        if (container) {
            if (loading) {
                container.innerHTML = '<div class="chart-loading"><span class="badge badge-loading">Loading...</span></div>';
            }
        }
    });
}

// ==================== Usage Trend (24h) ====================

function renderOverviewTrend(data) {
    if (!data) return;

    const items = data.items || [];
    renderOverviewRequestsChart(items);
    renderOverviewTokensChart(items);
}

function renderOverviewRequestsChart(items) {
    const container = document.getElementById('requests-trend-container');
    if (!container) return;

    if (!items.length) {
        container.innerHTML = '<div class="chart-empty">No usage data for the last 24 hours.</div>';
        return;
    }

    const requests = items.map(i => i.requests || 0);
    const maxRequests = Math.max(...requests);
    const buckets = items.map(i => i.bucket);
    const maxY = maxRequests === 0 ? 1 : maxRequests;

    const width = container.clientWidth || 600;
    const height = 180;
    const padding = { top: 20, right: 30, bottom: 30, left: 45 };
    const innerWidth = width - padding.left - padding.right;
    const innerHeight = height - padding.top - padding.bottom;

    const xScale = (i) => padding.left + (innerWidth / Math.max(1, buckets.length - 1)) * i;
    const yScale = (val) => padding.top + innerHeight - (val / maxY) * innerHeight;

    let svg = '<svg width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '" class="usage-chart" role="img" aria-label="Requests over last 24 hours chart">';
    // Grid lines
    for (let i = 0; i <= 4; i++) {
        const y = padding.top + (innerHeight / 4) * i;
        svg += '<line x1="' + padding.left + '" y1="' + y + '" x2="' + (width - padding.right) + '" y2="' + y + '" stroke="var(--color-border)" stroke-width="0.5"/>';
        const val = Math.round(maxY * (1 - i / 4));
        svg += '<text x="' + (padding.left - 8) + '" y="' + (y + 4) + '" font-size="9" fill="var(--color-text-muted)" text-anchor="end">' + formatNumber(val) + '</text>';
    }
    // X axis labels
    const labelCount = Math.min(buckets.length, 6);
    const step = Math.max(1, Math.floor(buckets.length / labelCount));
    for (let i = 0; i < buckets.length; i += step) {
        const x = xScale(i);
        svg += '<text x="' + x + '" y="' + (height - padding.bottom + 18) + '" font-size="9" fill="var(--color-text-muted)" text-anchor="middle" transform="rotate(-45, ' + x + ', ' + (height - padding.bottom + 18) + ')">' + escapeHtml(buckets[i]) + '</text>';
    }
    // Line
    let path = 'M';
    for (let i = 0; i < items.length; i++) {
        const x = xScale(i);
        const y = yScale(items[i].requests || 0);
        path += (i === 0 ? '' : ' L') + x + ' ' + y;
    }
    svg += '<path d="' + path + '" stroke="var(--color-primary)" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>';
    // Points
    for (let i = 0; i < items.length; i++) {
        const x = xScale(i);
        const y = yScale(items[i].requests || 0);
        svg += '<circle cx="' + x + '" cy="' + y + '" r="3" fill="var(--color-primary)" stroke="var(--color-surface)" stroke-width="1.5"/>';
    }
    svg += '</svg>';

    container.innerHTML = '<figure class="chart-figure">' + svg + '<figcaption>Requests — Last 24 Hours</figcaption></figure>';
}

function renderOverviewTokensChart(items) {
    const container = document.getElementById('tokens-trend-container');
    if (!container) return;

    if (!items.length) {
        container.innerHTML = '<div class="chart-empty">No usage data for the last 24 hours.</div>';
        return;
    }

    const totals = items.map(i => i.total_tokens || 0);
    const maxTotal = Math.max(...totals);
    const buckets = items.map(i => i.bucket);
    const maxY = maxTotal === 0 ? 1 : maxTotal;

    const width = container.clientWidth || 600;
    const height = 180;
    const padding = { top: 20, right: 30, bottom: 30, left: 45 };
    const innerWidth = width - padding.left - padding.right;
    const innerHeight = height - padding.top - padding.bottom;

    const xScale = (i) => padding.left + (innerWidth / Math.max(1, buckets.length - 1)) * i;
    const yScale = (val) => padding.top + innerHeight - (val / maxY) * innerHeight;

    let svg = '<svg width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '" class="usage-chart" role="img" aria-label="Token usage over last 24 hours chart">';
    // Grid lines
    for (let i = 0; i <= 4; i++) {
        const y = padding.top + (innerHeight / 4) * i;
        svg += '<line x1="' + padding.left + '" y1="' + y + '" x2="' + (width - padding.right) + '" y2="' + y + '" stroke="var(--color-border)" stroke-width="0.5"/>';
        const val = Math.round(maxY * (1 - i / 4));
        svg += '<text x="' + (padding.left - 8) + '" y="' + (y + 4) + '" font-size="9" fill="var(--color-text-muted)" text-anchor="end">' + formatNumber(val) + '</text>';
    }
    // X axis labels
    const labelCount = Math.min(buckets.length, 6);
    const step = Math.max(1, Math.floor(buckets.length / labelCount));
    for (let i = 0; i < buckets.length; i += step) {
        const x = xScale(i);
        svg += '<text x="' + x + '" y="' + (height - padding.bottom + 18) + '" font-size="9" fill="var(--color-text-muted)" text-anchor="middle" transform="rotate(-45, ' + x + ', ' + (height - padding.bottom + 18) + ')">' + escapeHtml(buckets[i]) + '</text>';
    }
    // Line
    let path = 'M';
    for (let i = 0; i < items.length; i++) {
        const x = xScale(i);
        const y = yScale(items[i].total_tokens || 0);
        path += (i === 0 ? '' : ' L') + x + ' ' + y;
    }
    svg += '<path d="' + path + '" stroke="var(--color-success)" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>';
    // Points
    for (let i = 0; i < items.length; i++) {
        const x = xScale(i);
        const y = yScale(items[i].total_tokens || 0);
        svg += '<circle cx="' + x + '" cy="' + y + '" r="3" fill="var(--color-success)" stroke="var(--color-surface)" stroke-width="1.5"/>';
    }
    svg += '</svg>';

    container.innerHTML = '<figure class="chart-figure">' + svg + '<figcaption>Token Usage — Last 24 Hours</figcaption></figure>';
}

function renderOverviewTrendError() {
    const containers = ['requests-trend-container', 'tokens-trend-container'];
    containers.forEach(id => {
        const container = document.getElementById(id);
        if (container) container.innerHTML = '<div class="chart-error"><span class="badge badge-error">Error loading chart</span></div>';
    });
}

// ==================== Recent Requests ====================

function renderRecentRequests(items) {
    const container = document.getElementById('recent-requests-table');
    if (!container) return;

    const tbody = container.querySelector('tbody');
    if (!tbody) return;

    if (!items.length) {
        tbody.innerHTML = '<tr class="empty"><td colspan="7">No recent requests.</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(item => {
        const statusBadge = getStatusBadgeHtml(item.status_code);
        const tokens = item.total_tokens !== null && item.total_tokens !== undefined ? formatNumber(item.total_tokens) : '—';
        const duration = item.duration_ms !== null && item.duration_ms !== undefined ? item.duration_ms + ' ms' : '—';
        const username = item.username || '—';
        const keyName = item.key_name || item.masked_key || '—';

        return '<tr>' +
            '<td>' + formatTimestamp(item.started_at) + '</td>' +
            '<td>' + escapeHtml(username) + '</td>' +
            '<td>' + escapeHtml(keyName) + '</td>' +
            '<td>' + escapeHtml(item.model || '—') + '</td>' +
            '<td>' + statusBadge + '</td>' +
            '<td>' + tokens + '</td>' +
            '<td>' + duration + '</td>' +
        '</tr>';
    }).join('');
}

function renderRecentRequestsError() {
    const container = document.getElementById('recent-requests-table');
    if (!container) return;
    const tbody = container.querySelector('tbody');
    if (tbody) tbody.innerHTML = '<tr class="error"><td colspan="7"><span class="badge badge-error">Unable to load recent requests.</span></td></tr>';
}

// ==================== Recent Errors ====================

function renderRecentErrors(items) {
    const container = document.getElementById('recent-errors-table');
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
            '<td>' + statusBadge + '</td>' +
            '<td>' + escapeHtml(errorType) + '</td>' +
        '</tr>';
    }).join('');
}

function renderRecentErrorsError() {
    const container = document.getElementById('recent-errors-table');
    if (!container) return;
    const tbody = container.querySelector('tbody');
    if (tbody) tbody.innerHTML = '<tr class="error"><td colspan="5"><span class="badge badge-error">Unable to load recent errors.</span></td></tr>';
}

// ==================== Initialize ====================

document.addEventListener('DOMContentLoaded', async function() {
    // Refresh button
    const refreshBtn = document.getElementById('btn-refresh');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            setButtonLoading(refreshBtn, true);
            loadOverview().finally(() => setButtonLoading(refreshBtn, false));
        });
    }

    await loadOverview();
});

// ==================== Exports ====================

window.loadOverview = loadOverview;
window.renderOverviewHealth = renderOverviewHealth;
window.renderOverviewTrend = renderOverviewTrend;
window.renderRecentRequests = renderRecentRequests;
window.renderRecentErrors = renderRecentErrors;