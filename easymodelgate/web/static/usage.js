/**
 * EasyModelGate Usage Dashboard Page Logic
 */

(() => {
    'use strict';

    const {
        adminFetch,
        formatNumber,
        formatTimestamp,
        escapeHtml,
        showErrorToast
    } = window.EMGAdmin;

    // ==================== Constants ====================

    const PERIOD_OPTIONS = [
        { value: 'today', label: 'Today' },
        { value: 'yesterday', label: 'Yesterday' },
        { value: '24h', label: 'Last 24 Hours' },
        { value: '7d', label: 'Last 7 Days' },
        { value: 'week', label: 'This Week' },
        { value: 'month', label: 'This Month' },
        { value: 'all', label: 'All Time' },
        { value: 'custom', label: 'Custom' }
    ];

    const GROUP_BY_OPTIONS = [
        { value: 'auto', label: 'Auto' },
        { value: 'hour', label: 'Hour' },
        { value: 'day', label: 'Day' },
        { value: 'week', label: 'Week' },
        { value: 'month', label: 'Month' }
    ];

    const DEFAULT_FILTERS = {
        period: 'today',
        group_by: 'auto',
        user_id: '',
        key_id: '',
        model: '',
        from: '',
        to: ''
    };

    // ==================== State ====================

    let usersCache = [];
    let keysCache = [];
    let currentSummary = null;
    let currentTimeseries = null;

    // ==================== URL Query State ====================

    function readFiltersFromURL() {
        const params = new URLSearchParams(window.location.search);
        const filters = { ...DEFAULT_FILTERS };

        if (params.has('period')) filters.period = params.get('period');
        if (params.has('group_by')) filters.group_by = params.get('group_by');
        if (params.has('user_id')) filters.user_id = params.get('user_id');
        if (params.has('key_id')) filters.key_id = params.get('key_id');
        if (params.has('model')) filters.model = params.get('model');
        if (params.has('from')) filters.from = params.get('from');
        if (params.has('to')) filters.to = params.get('to');

        return filters;
    }

    function writeFiltersToURL(filters) {
        const params = new URLSearchParams();

        if (filters.period && filters.period !== DEFAULT_FILTERS.period) {
            params.set('period', filters.period);
        }
        if (filters.group_by && filters.group_by !== DEFAULT_FILTERS.group_by) {
            params.set('group_by', filters.group_by);
        }
        if (filters.user_id) params.set('user_id', filters.user_id);
        if (filters.key_id) params.set('key_id', filters.key_id);
        if (filters.model) params.set('model', filters.model);
        if (filters.from) params.set('from', filters.from);
        if (filters.to) params.set('to', filters.to);

        const newURL = params.toString() ? '/admin/usage?' + params.toString() : '/admin/usage';
        window.history.replaceState(null, '', newURL);
    }

    function applyFiltersToForm(filters) {
        document.getElementById('filter-period').value = filters.period;
        document.getElementById('filter-group-by').value = filters.group_by;
        document.getElementById('filter-user').value = filters.user_id || '';
        document.getElementById('filter-key').value = filters.key_id || '';
        document.getElementById('filter-model').value = filters.model || '';
        document.getElementById('filter-from').value = filters.from || '';
        document.getElementById('filter-to').value = filters.to || '';

        toggleCustomInputs(filters.period === 'custom');
    }

    function toggleCustomInputs(show) {
        const fromInput = document.getElementById('filter-from');
        const toInput = document.getElementById('filter-to');
        const fromLabel = fromInput.previousElementSibling;
        const toLabel = toInput.previousElementSibling;

        if (show) {
            fromInput.style.display = '';
            toInput.style.display = '';
            if (fromLabel) fromLabel.style.display = '';
            if (toLabel) toLabel.style.display = '';
        } else {
            fromInput.style.display = 'none';
            toInput.style.display = 'none';
            if (fromLabel) fromLabel.style.display = 'none';
            if (toLabel) toLabel.style.display = 'none';
        }
    }

    function collectFiltersFromForm() {
        return {
            period: document.getElementById('filter-period').value,
            group_by: document.getElementById('filter-group-by').value,
            user_id: document.getElementById('filter-user').value || '',
            key_id: document.getElementById('filter-key').value || '',
            model: document.getElementById('filter-model').value || '',
            from: document.getElementById('filter-from').value || '',
            to: document.getElementById('filter-to').value || ''
        };
    }

    // ==================== Filter Options Loading ====================

    async function loadFilterOptions() {
        try {
            const [usersRes, keysRes] = await Promise.allSettled([
                adminFetch('/admin/api/users'),
                adminFetch('/admin/api/keys')
            ]);

            if (usersRes.status === 'fulfilled') {
                usersCache = usersRes.value.items || [];
            } else {
                console.warn('Failed to load users:', usersRes.reason);
            }

            if (keysRes.status === 'fulfilled') {
                keysCache = keysRes.value.items || [];
            } else {
                console.warn('Failed to load keys:', keysRes.reason);
            }

            renderUserFilter(usersCache);
            renderKeyFilter(keysCache);
        } catch (err) {
            console.error('Failed to load filter options:', err);
        }
    }

    function renderUserFilter(users) {
        const select = document.getElementById('filter-user');
        select.innerHTML = '<option value="">All Users</option>' +
            users.map(u =>
                '<option value="' + u.id + '">' + escapeHtml(u.username) +
                (u.display_name ? ' (' + escapeHtml(u.display_name) + ')' : '') +
                (u.enabled ? '' : ' [Disabled]') + '</option>'
            ).join('');
    }

    function renderKeyFilter(keys) {
        const select = document.getElementById('filter-key');
        select.innerHTML = '<option value="">All API Keys</option>' +
            keys.map(k =>
                '<option value="' + k.id + '">' + escapeHtml(k.name || 'Unnamed') +
                ' — ' + escapeHtml(k.username || '-') +
                ' — ' + escapeHtml(k.key_prefix || '-') + '****' + escapeHtml((k.key_prefix || '').slice(-4)) + '</option>'
            ).join('');
    }

    // ==================== Build Query ====================

    function buildUsageQuery(filters) {
        const params = new URLSearchParams();

        if (filters.period && filters.period !== 'custom') {
            params.set('period', filters.period);
        }

        if (filters.period === 'custom') {
            if (filters.from) params.set('from', filters.from);
            if (filters.to) params.set('to', filters.to);
        }

        if (filters.group_by && filters.group_by !== 'auto') {
            params.set('group_by', filters.group_by);
        }

        if (filters.user_id) params.set('user_id', filters.user_id);
        if (filters.key_id) params.set('key_id', filters.key_id);
        if (filters.model) params.set('model', filters.model);

        return params.toString();
    }

    // ==================== Load Usage Data ====================

    let isLoading = false;

    async function loadUsage() {
        if (isLoading) return;
        isLoading = true;

        const filters = collectFiltersFromForm();
        const query = buildUsageQuery(filters);

        // Update URL
        writeFiltersToURL(filters);

        // Show loading states
        setSummaryLoading(true);
        setTimeseriesLoading(true);

        try {
            const [summaryRes, timeseriesRes] = await Promise.allSettled([
                adminFetch('/admin/api/usage/summary?' + query),
                adminFetch('/admin/api/usage/timeseries?' + query)
            ]);

            if (summaryRes.status === 'fulfilled') {
                currentSummary = summaryRes.value;
                renderSummary(currentSummary);
            } else {
                console.error('Summary load failed:', summaryRes.reason);
                renderSummaryError(summaryRes.reason);
            }

            if (timeseriesRes.status === 'fulfilled') {
                currentTimeseries = timeseriesRes.value;
                renderTimeseries(currentTimeseries);
            } else {
                console.error('Timeseries load failed:', timeseriesRes.reason);
                renderTimeseriesError(timeseriesRes.reason);
            }

        } catch (err) {
            console.error('Usage load failed:', err);
            renderSummaryError(err);
            renderTimeseriesError(err);
        } finally {
            isLoading = false;
            setSummaryLoading(false);
            setTimeseriesLoading(false);
        }
    }

    // ==================== Summary Rendering ====================

    function setSummaryLoading(loading) {
        const cards = document.querySelectorAll('.metric-card .metric-value');
        cards.forEach(card => {
            if (loading) {
                card.innerHTML = '<span class="badge badge-loading">Loading...</span>';
            }
        });
        const applyBtn = document.getElementById('btn-apply');
        if (applyBtn) applyBtn.disabled = loading;
    }

    function renderSummary(data) {
        const s = data.summary || {};
        const range = data.range || {};
        const filters = data.filters || {};

        // Metric cards
        setMetricValue('metric-requests', formatNumber(s.requests || 0));
        setMetricValue('metric-success-rate', s.success_rate !== undefined ? (s.success_rate * 100).toFixed(1) + '%' : '—');
        setMetricValue('metric-total-tokens', formatNumber(s.total_tokens || 0));
        setMetricValue('metric-prompt-tokens', formatNumber(s.prompt_tokens || 0));
        setMetricValue('metric-completion-tokens', formatNumber(s.completion_tokens || 0));
        setMetricValue('metric-avg-ttft', s.avg_ttft_ms !== undefined && s.avg_ttft_ms !== null ? s.avg_ttft_ms.toFixed(1) + ' ms' : '—');

        // Range display
        const rangeEl = document.getElementById('usage-range');
        if (rangeEl) {
            const fromMs = range.from_ms;
            const toMs = range.to_ms;
            const tz = range.timezone || 'Asia/Shanghai';
            let rangeText = 'Showing: ';
            if (fromMs) rangeText += formatTimestamp(fromMs);
            else rangeText += 'All time';
            rangeText += ' → ';
            if (toMs) rangeText += formatTimestamp(toMs);
            else rangeText += 'Now';
            rangeText += ' (Timezone: ' + tz + ')';
            rangeEl.textContent = rangeText;
        }
    }

    function setMetricValue(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    function renderSummaryError(err) {
        const cards = document.querySelectorAll('.metric-card .metric-value');
        cards.forEach(card => {
            card.innerHTML = '<span class="badge badge-error">Error</span>';
        });
        const rangeEl = document.getElementById('usage-range');
        if (rangeEl) rangeEl.textContent = 'Error loading range: ' + (err.message || 'Unknown error');
    }

    // ==================== Timeseries Rendering ====================

    function setTimeseriesLoading(loading) {
        const chartContainer = document.getElementById('requests-chart-container');
        const tableContainer = document.getElementById('timeseries-table-container');
        const message = loading ? 'Loading...' : '';

        if (chartContainer) {
            chartContainer.innerHTML = loading ? '<div class="chart-loading"><span class="badge badge-loading">Loading...</span></div>' : '';
        }
        if (tableContainer) {
            const tbody = tableContainer.querySelector('tbody');
            if (tbody && loading) {
                tbody.innerHTML = '<tr class="loading-row"><td colspan="11"><span class="badge badge-loading">Loading...</span></td></tr>';
            }
        }
    }

    function renderTimeseries(data) {
        if (!data) return;

        const items = data.items || [];
        const groupBy = data.group_by || 'auto';

        // Render chart
        renderRequestsChart(items);
        renderTokensChart(items);

        // Render table
        renderTimeseriesTable(items);
    }

    function renderRequestsChart(items) {
        const container = document.getElementById('requests-chart-container');
        if (!container) return;

        if (!items.length) {
            container.innerHTML = '<div class="chart-empty">No usage data for this period.</div>';
            return;
        }

        const requests = items.map(i => i.requests || 0);
        const maxRequests = Math.max(...requests);
        const buckets = items.map(i => i.bucket);
        const maxY = maxRequests === 0 ? 1 : maxRequests;

        const width = container.clientWidth || 600;
        const height = 200;
        const padding = { top: 20, right: 40, bottom: 40, left: 50 };
        const innerWidth = width - padding.left - padding.right;
        const innerHeight = height - padding.top - padding.bottom;

        const xScale = (i) => padding.left + (innerWidth / Math.max(1, buckets.length - 1)) * i;
        const yScale = (val) => padding.top + innerHeight - (val / maxY) * innerHeight;

        let svg = '<svg width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '" class="usage-chart" role="img" aria-label="Requests over time chart">';
        // Grid lines
        for (let i = 0; i <= 4; i++) {
            const y = padding.top + (innerHeight / 4) * i;
            svg += '<line x1="' + padding.left + '" y1="' + y + '" x2="' + (width - padding.right) + '" y2="' + y + '" stroke="var(--color-border)" stroke-width="0.5"/>';
            const val = Math.round(maxY * (1 - i / 4));
            svg += '<text x="' + (padding.left - 10) + '" y="' + (y + 4) + '" font-size="10" fill="var(--color-text-muted)" text-anchor="end">' + formatNumber(val) + '</text>';
        }
        // X axis labels
        const labelCount = Math.min(buckets.length, 8);
        const step = Math.max(1, Math.floor(buckets.length / labelCount));
        for (let i = 0; i < buckets.length; i += step) {
            const x = xScale(i);
            svg += '<text x="' + x + '" y="' + (height - padding.bottom + 20) + '" font-size="10" fill="var(--color-text-muted)" text-anchor="middle" transform="rotate(-45, ' + x + ', ' + (height - padding.bottom + 20) + ')">' + escapeHtml(buckets[i]) + '</text>';
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

        container.innerHTML = '<figure class="chart-figure">' + svg + '<figcaption>Requests Over Time</figcaption></figure>';
    }

    function renderTokensChart(items) {
        const container = document.getElementById('tokens-chart-container');
        if (!container) return;

        if (!items.length) {
            container.innerHTML = '<div class="chart-empty">No usage data for this period.</div>';
            return;
        }

        const totals = items.map(i => i.total_tokens || 0);
        const maxTotal = Math.max(...totals);
        const buckets = items.map(i => i.bucket);
        const maxY = maxTotal === 0 ? 1 : maxTotal;

        const width = container.clientWidth || 600;
        const height = 200;
        const padding = { top: 20, right: 40, bottom: 40, left: 50 };
        const innerWidth = width - padding.left - padding.right;
        const innerHeight = height - padding.top - padding.bottom;

        const xScale = (i) => padding.left + (innerWidth / Math.max(1, buckets.length - 1)) * i;
        const yScale = (val) => padding.top + innerHeight - (val / maxY) * innerHeight;

        let svg = '<svg width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '" class="usage-chart" role="img" aria-label="Token usage over time chart">';
        // Grid lines
        for (let i = 0; i <= 4; i++) {
            const y = padding.top + (innerHeight / 4) * i;
            svg += '<line x1="' + padding.left + '" y1="' + y + '" x2="' + (width - padding.right) + '" y2="' + y + '" stroke="var(--color-border)" stroke-width="0.5"/>';
            const val = Math.round(maxY * (1 - i / 4));
            svg += '<text x="' + (padding.left - 10) + '" y="' + (y + 4) + '" font-size="10" fill="var(--color-text-muted)" text-anchor="end">' + formatNumber(val) + '</text>';
        }
        // X axis labels
        const labelCount = Math.min(buckets.length, 8);
        const step = Math.max(1, Math.floor(buckets.length / labelCount));
        for (let i = 0; i < buckets.length; i += step) {
            const x = padding.left + (innerWidth / Math.max(1, buckets.length - 1)) * i;
            svg += '<text x="' + x + '" y="' + (height - padding.bottom + 20) + '" font-size="10" fill="var(--color-text-muted)" text-anchor="middle" transform="rotate(-45, ' + x + ', ' + (height - padding.bottom + 20) + ')">' + escapeHtml(buckets[i]) + '</text>';
        }
        // Line
        let path = 'M';
        for (let i = 0; i < items.length; i++) {
            const x = padding.left + (innerWidth / Math.max(1, buckets.length - 1)) * i;
            const y = padding.top + innerHeight - ((items[i].total_tokens || 0) / maxY) * innerHeight;
            path += (i === 0 ? '' : ' L') + x + ' ' + y;
        }
        svg += '<path d="' + path + '" stroke="var(--color-success)" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>';
        // Points
        for (let i = 0; i < items.length; i++) {
            const x = padding.left + (innerWidth / Math.max(1, buckets.length - 1)) * i;
            const y = padding.top + innerHeight - ((items[i].total_tokens || 0) / maxY) * innerHeight;
            svg += '<circle cx="' + x + '" cy="' + y + '" r="3" fill="var(--color-success)" stroke="var(--color-surface)" stroke-width="1.5"/>';
        }
        svg += '</svg>';

        container.innerHTML = '<figure class="chart-figure">' + svg + '<figcaption>Token Usage Over Time</figcaption></figure>';
    }

    function renderTimeseriesTable(items) {
        const container = document.getElementById('timeseries-table-container');
        if (!container) return;

        const tbody = container.querySelector('tbody');
        if (!tbody) return;

        if (!items.length) {
            tbody.innerHTML = '<tr class="empty"><td colspan="11">No usage data.</td></tr>';
            return;
        }

        tbody.innerHTML = items.map(item => `
            <tr>
                <td>${escapeHtml(item.bucket)}</td>
                <td>${item.requests ?? '—'}</td>
                <td>${item.success ?? '—'}</td>
                <td>${item.failed ?? '—'}</td>
                <td>${formatNumber(item.prompt_tokens ?? '—')}</td>
                <td>${formatNumber(item.completion_tokens ?? '—')}</td>
                <td>${formatNumber(item.total_tokens ?? '—')}</td>
                <td>${item.avg_duration_ms !== undefined && item.avg_duration_ms !== null ? item.avg_duration_ms.toFixed(1) : '—'}</td>
                <td>${item.avg_queue_wait_ms !== undefined && item.avg_queue_wait_ms !== null ? item.avg_queue_wait_ms.toFixed(1) : '—'}</td>
                <td>${item.avg_upstream_ms !== undefined && item.avg_upstream_ms !== null ? item.avg_upstream_ms.toFixed(1) : '—'}</td>
                <td>${item.avg_ttft_ms !== undefined && item.avg_ttft_ms !== null ? item.avg_ttft_ms.toFixed(1) : '—'}</td>
            </tr>
        `).join('');
    }

    function renderTimeseriesError(err) {
        const chartContainer = document.getElementById('requests-chart-container');
        const tableContainer = document.getElementById('timeseries-table-container');

        if (chartContainer) chartContainer.innerHTML = '<div class="chart-error"><span class="badge badge-error">Error loading chart</span></div>';
        const tbody = document.querySelector('#timeseries-table-container tbody');
        if (tbody) tbody.innerHTML = '<tr class="error"><td colspan="11"><span class="badge badge-error">Error loading data</span></td></tr>';
    }

    // ==================== Handlers ====================

    function onApplyClick() {
        const filters = collectFiltersFromForm();

        // Validate custom range
        if (filters.period === 'custom') {
            if (!filters.from || !filters.to) {
                showErrorToast('Custom range requires both From and To dates.');
                return;
            }
            if (filters.from >= filters.to) {
                showErrorToast('Start time must be earlier than end time.');
                return;
            }
        }

        loadUsage();
    }

    function onResetClick() {
        // Reset form to defaults
        document.getElementById('filter-period').value = DEFAULT_FILTERS.period;
        document.getElementById('filter-group-by').value = DEFAULT_FILTERS.group_by;
        document.getElementById('filter-user').value = '';
        document.getElementById('filter-key').value = '';
        document.getElementById('filter-model').value = '';
        document.getElementById('filter-from').value = '';
        document.getElementById('filter-to').value = '';

        toggleCustomInputs(false);

        // Clear URL and reload
        window.history.replaceState(null, '', '/admin/usage');
        loadUsage();
    }

    function onPeriodChange(e) {
        toggleCustomInputs(e.target.value === 'custom');
    }

    // ==================== Initialize ====================

    document.addEventListener('DOMContentLoaded', async function() {
        // Load filter options
        await loadFilterOptions();

        // Read URL and apply to form
        const urlFilters = readFiltersFromURL();
        applyFiltersToForm(urlFilters);

        // Attach event listeners
        document.getElementById('filter-period').addEventListener('change', onPeriodChange);
        document.getElementById('btn-apply').addEventListener('click', onApplyClick);
        document.getElementById('btn-reset').addEventListener('click', onResetClick);

        // Initial load
        await loadUsage();

        // Handle browser back/forward
        window.addEventListener('popstate', () => {
            const urlFilters = readFiltersFromURL();
            applyFiltersToForm(urlFilters);
            loadUsage();
        });
    });
})();