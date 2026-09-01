/**
 * EasyModelGate API Keys Page Logic
 */

(() => {
    'use strict';

    const {
        adminFetch,
        formatNumber,
        formatTimestamp,
        formatTokenUsage,
        formatRpm,
        escapeHtml,
        setTableLoading,
        setTableEmpty,
        setTableError,
        createModal,
        confirmModal,
        alertModal,
        setButtonLoading,
        getFormData,
        clearFormErrors,
        showFormError,
        showSuccessToast,
        showErrorToast,
        copyToClipboard
    } = window.EMGAdmin;

    let keysCache = [];
    let usersForDropdown = [];

    async function loadKeysPage() {
        await Promise.all([
            loadUsersForDropdown(),
            loadKeys()
        ]);
    }

    async function loadUsersForDropdown() {
        try {
            const data = await adminFetch('/admin/api/users');
            usersForDropdown = data.items || [];
        } catch (err) {
            console.error('Failed to load users for dropdown:', err);
            usersForDropdown = [];
        }
    }

    async function loadKeys() {
        setTableLoading('keys-table');
        try {
            const data = await adminFetch('/admin/api/keys');
            keysCache = data.items || [];
            renderKeysTable(keysCache);
        } catch (err) {
            console.error('Failed to load keys:', err);
            setTableError('keys-table', err.message || 'Unable to load API keys.');
        }
    }

    function renderKeysTable(keys) {
        if (!keys || !keys.length) {
            setTableEmpty('keys-table', 'No API keys yet.');
            return;
        }

        const rows = keys.map(key => {
            let statusBadge;
            const now = Date.now();
            if (!key.enabled) {
                statusBadge = '<span class="badge badge-warning">Disabled</span>';
            } else if (key.expires_at && key.expires_at < now) {
                statusBadge = '<span class="badge badge-error">Expired</span>';
            } else {
                statusBadge = '<span class="badge badge-success">Enabled</span>';
            }

            const tokenUsage = formatTokenUsage(key.token_used, key.token_limit);
            const rpm = formatRpm(key.rpm);
            const maskedKey = key.key_prefix ? escapeHtml(key.key_prefix) + '****' + escapeHtml(key.key_prefix.slice(-4)) : '-';

            return '<tr>' +
                '<td>' + key.id + '</td>' +
                '<td>' + escapeHtml(key.name || '-') + '</td>' +
                '<td>' + escapeHtml(key.username || '-') + '</td>' +
                '<td class="key-prefix-cell"><code>' + maskedKey + '</code></td>' +
                '<td>' + statusBadge + '</td>' +
                '<td>' + rpm + '</td>' +
                '<td>' + tokenUsage + '</td>' +
                '<td>' + (key.expires_at ? formatTimestamp(key.expires_at) : 'Never') + '</td>' +
                '<td>' + (key.last_used_at ? formatTimestamp(key.last_used_at) : 'Never') + '</td>' +
                '<td class="actions-cell">' +
                    '<button type="button" class="btn btn-secondary btn-sm" data-action="manage" data-key-id="' + key.id + '">Manage</button>' +
                '</td>' +
            '</tr>';
        }).join('');

        const tbody = document.querySelector('#keys-table tbody');
        if (tbody) tbody.innerHTML = rows;
    }

    // ==================== Create Key Modal ====================

    function buildUserOptions() {
        return usersForDropdown.map(u =>
            '<option value="' + u.id + '">' + escapeHtml(u.username) + (u.display_name ? ' (' + escapeHtml(u.display_name) + ')' : '') + (u.enabled ? '' : ' (Disabled)') + '</option>'
        ).join('');
    }

    function openCreateKeyModal() {
        const modal = createModal({
            title: 'Create API Key',
            content: `
                <form id="create-key-form" novalidate>
                    <div class="form-group">
                        <label for="create-key-user">User <span class="required">*</span></label>
                        <select id="create-key-user" name="user_id" required>
                            <option value="">Select user...</option>
                            ` + buildUserOptions() + `
                        </select>
                        <div class="form-error" data-error-for="user_id"></div>
                    </div>
                    <div class="form-group">
                        <label for="create-key-name">Name <span class="required">*</span></label>
                        <input type="text" id="create-key-name" name="name" required autocomplete="off" maxlength="64">
                        <div class="form-error" data-error-for="name"></div>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label for="create-key-rpm">RPM Limit</label>
                            <div class="input-with-checkbox">
                                <input type="number" id="create-key-rpm" name="rpm" min="1" step="1" placeholder="Unlimited">
                                <label class="checkbox-label">
                                    <input type="checkbox" name="rpm_unlimited" checked data-linked-input="create-key-rpm"> Unlimited
                                </label>
                            </div>
                            <div class="form-error" data-error-for="rpm"></div>
                        </div>
                        <div class="form-group">
                            <label for="create-key-token-limit">Token Quota</label>
                            <div class="input-with-checkbox">
                                <input type="number" id="create-key-token-limit" name="token_limit" min="1" step="1" placeholder="Unlimited">
                                <label class="checkbox-label">
                                    <input type="checkbox" name="token_limit_unlimited" checked data-linked-input="create-key-token-limit"> Unlimited
                                </label>
                            </div>
                            <div class="form-error" data-error-for="token_limit"></div>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="create-key-expires">Expires In Days</label>
                        <input type="number" id="create-key-expires" name="expires_in_days" min="1" step="1" placeholder="No expiry">
                        <div class="form-error" data-error-for="expires_in_days"></div>
                        <div class="form-hint">Leave empty for no expiry.</div>
                    </div>
                </form>
            `,
            actions: [
                { label: 'Cancel', action: 'cancel', class: 'btn btn-secondary' },
                { label: 'Create Key', action: 'create', class: 'btn btn-primary' }
            ],
            onAction: handleCreateKeyAction
        });

        // Handle unlimited checkboxes
        setTimeout(() => {
            const rpmUnlimited = document.querySelector('[name="rpm_unlimited"]');
            const rpmInput = document.getElementById('create-key-rpm');
            const tokenUnlimited = document.querySelector('[name="token_limit_unlimited"]');
            const tokenInput = document.getElementById('create-key-token-limit');

            function syncInput(checkbox, input) {
                if (checkbox.checked) {
                    input.disabled = true;
                    input.value = '';
                } else {
                    input.disabled = false;
                }
            }

            if (rpmUnlimited && rpmInput) {
                rpmUnlimited.addEventListener('change', () => syncInput(rpmUnlimited, rpmInput));
                syncInput(rpmUnlimited, rpmInput);
            }
            if (tokenUnlimited && tokenInput) {
                tokenUnlimited.addEventListener('change', () => syncInput(tokenUnlimited, tokenInput));
                syncInput(tokenUnlimited, tokenInput);
            }
        }, 50);
    }

    async function handleCreateKeyAction(action, modalObj) {
        if (action === 'cancel') {
            modalObj.close();
            return;
        }

        if (action !== 'create') return;

        const form = document.getElementById('create-key-form');
        clearFormErrors(form);
        const btn = modalObj.modal.querySelector('[data-action="create"]');
        setButtonLoading(btn, true);

        try {
            const data = getFormData(form);
            // Convert user_id to int
            if (data.user_id) data.user_id = parseInt(data.user_id);
            if (data.rpm) data.rpm = parseInt(data.rpm);
            if (data.token_limit) data.token_limit = parseInt(data.token_limit);
            if (data.expires_in_days) data.expires_in_days = parseInt(data.expires_in_days);

            const result = await adminFetch('/admin/api/keys', {
                method: 'POST',
                body: JSON.stringify(data)
            });

            // Show secret modal
            modalObj.close();
            showSecretModal(result.api_key, result.key.name || 'Unnamed');
            await loadKeys();
        } catch (err) {
            handleApiError(err, 'create-key-form', 'Failed to create API key.');
        } finally {
            setButtonLoading(btn, false);
        }
    }

    // ==================== Secret Modal (Key Created) ====================

    function showSecretModal(fullKey, keyName) {
        const modal = createModal({
            title: 'API Key Created',
            content: `
                <div class="secret-modal">
                    <p>Your new API key <strong>` + escapeHtml(keyName) + `</strong> has been created.</p>
                    <p class="warning">This key will only be shown once.<br>Store it securely now.</p>
                    <div class="secret-box">
                        <code class="secret-key" id="secret-key-text">` + escapeHtml(fullKey) + `</code>
                        <button type="button" class="btn btn-secondary btn-sm" id="copy-secret-btn">Copy</button>
                    </div>
                    <p class="secret-hint">After closing this dialog, the full key will never be shown again.</p>
                </div>
            `,
            actions: [
                { label: 'I have saved this key', action: 'ack', class: 'btn btn-primary' }
            ],
            onAction: (action, modalObj) => {
                if (action === 'ack') {
                    // Clear the secret from DOM before closing
                    const secretEl = document.getElementById('secret-key-text');
                    if (secretEl) secretEl.textContent = '[hidden]';
                    modalObj.close();
                }
            },
            onClose: () => {
                // Additional cleanup
                const secretEl = document.getElementById('secret-key-text');
                if (secretEl) secretEl.textContent = '[hidden]';
            },
            closeOnOverlay: false,
            closeOnEscape: false
        });

        // Copy button
        setTimeout(() => {
            const copyBtn = document.getElementById('copy-secret-btn');
            if (copyBtn) {
                copyBtn.addEventListener('click', async () => {
                    const secretEl = document.getElementById('secret-key-text');
                    const key = secretEl ? secretEl.textContent : '';
                    if (!key) return;

                    const success = await copyToClipboard(key);
                    if (success) {
                        showSuccessToast('Copied to clipboard.');
                    } else {
                        showErrorToast('Unable to copy automatically. Please copy the key manually.');
                    }
                });
            }
        }, 50);
    }

    // ==================== Key Management Modal ====================

    let currentManageKeyId = null;

    async function openManageKeyModal(keyId) {
        currentManageKeyId = keyId;
        setTableLoading('keys-table'); // reuse for feedback
        try {
            const key = await adminFetch('/admin/api/keys/' + keyId);
            currentManageKeyId = key.id;
            renderManageKeyModal(key);
        } catch (err) {
            showErrorToast(err.message || 'Failed to load key details.');
        }
    }

    function renderManageKeyModal(key) {
        let statusBadge;
        const now = Date.now();
        if (!key.enabled) {
            statusBadge = '<span class="badge badge-warning">Disabled</span>';
        } else if (key.expires_at && key.expires_at < Date.now()) {
            statusBadge = '<span class="badge badge-error">Expired</span>';
        } else {
            statusBadge = '<span class="badge badge-success">Enabled</span>';
        }

        const tokenUsage = formatTokenUsage(key.token_used, key.token_limit);
        const rpm = formatRpm(key.rpm);
        const maskedKey = key.key_prefix ? escapeHtml(key.key_prefix) + '****' + escapeHtml(key.key_prefix.slice(-4)) : '-';

        const enableDisableBtn = key.enabled
            ? '<button type="button" class="btn btn-secondary btn-sm" data-action="disable-key" data-key-id="' + key.id + '">Disable</button>'
            : '<button type="button" class="btn btn-primary btn-sm" data-action="enable-key" data-key-id="' + key.id + '">Enable</button>';

        const content = `
            <div class="key-manage-detail">
                <div class="detail-row">
                    <span class="detail-label">Name</span>
                    <span class="detail-value">` + escapeHtml(key.name || '-') + `</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">User</span>
                    <span class="detail-value">` + escapeHtml(key.username || '-') + `</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Key</span>
                    <span class="detail-value key-prefix-cell"><code>` + maskedKey + `</code></span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Status</span>
                    <span class="detail-value">` + statusBadge + `</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">RPM</span>
                    <span class="detail-value">` + rpm + `</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Token Usage</span>
                    <span class="detail-value">` + tokenUsage + `</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Expires</span>
                    <span class="detail-value">` + (key.expires_at ? formatTimestamp(key.expires_at) : 'Never') + `</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Last Used</span>
                    <span class="detail-value">` + (key.last_used_at ? formatTimestamp(key.last_used_at) : 'Never') + `</span>
                </div>
            </div>
            <hr class="modal-separator">
            <div class="key-limits-form">
                <h3>Limits</h3>
                <form id="key-limits-form" novalidate>
                    <div class="form-row">
                        <div class="form-group">
                            <label for="edit-rpm">RPM Limit</label>
                            <div class="input-with-checkbox">
                                <input type="number" id="edit-rpm" name="rpm" min="1" step="1" value="` + (key.rpm || '') + `" placeholder="Unlimited">
                                <label class="checkbox-label">
                                    <input type="checkbox" name="rpm_unlimited" ` + (key.rpm === null || key.rpm === undefined ? 'checked' : '') + ` data-linked-input="edit-rpm"> Unlimited
                                </label>
                            </div>
                            <div class="form-error" data-error-for="rpm"></div>
                        </div>
                        <div class="form-group">
                            <label for="edit-token-limit">Token Quota</label>
                            <div class="input-with-checkbox">
                                <input type="number" id="edit-token-limit" name="token_limit" min="1" step="1" value="` + (key.token_limit || '') + `" placeholder="Unlimited">
                                <label class="checkbox-label">
                                    <input type="checkbox" name="token_limit_unlimited" ` + (key.token_limit === null || key.token_limit === undefined ? 'checked' : '') + ` data-linked-input="edit-token-limit"> Unlimited
                                </label>
                            </div>
                            <div class="form-error" data-error-for="token_limit"></div>
                        </div>
                    </div>
                </form>
            </div>
        `;

        const actions = [
            { label: 'Cancel', action: 'cancel', class: 'btn btn-secondary' },
            enableDisableBtn.replace('btn btn-secondary btn-sm', 'btn btn-secondary').replace('btn btn-primary btn-sm', 'btn btn-primary').replace('data-action="disable-key"', 'data-action="disable-key" data-dismiss="false"').replace('data-action="enable-key"', 'data-action="enable-key" data-dismiss="false"'),
            { label: 'Save Limits', action: 'save-limits', class: 'btn btn-primary' }
        ];

        const modal = createModal({
            title: 'Manage Key: ' + escapeHtml(key.name || 'Unnamed'),
            content,
            actions,
            onAction: handleManageKeyAction,
            onClose: () => { currentManageKeyId = null; },
            closeOnOverlay: true,
            closeOnEscape: true
        });

        // Setup unlimited checkboxes
        setTimeout(() => {
            ['rpm', 'token_limit'].forEach(field => {
                const checkbox = document.querySelector('[name="' + field + '_unlimited"]');
                const input = document.getElementById('edit-' + field.replace('_', '-'));
                if (checkbox && input) {
                    checkbox.addEventListener('change', () => {
                        input.disabled = checkbox.checked;
                        if (checkbox.checked) input.value = '';
                    });
                    // Initial sync
                    input.disabled = checkbox.checked;
                }
            });
        }, 50);
    }

    async function handleManageKeyAction(action, modalObj) {
        if (action === 'cancel') {
            modalObj.close();
            return;
        }

        if (action === 'enable-key' || action === 'disable-key') {
            const keyId = currentManageKeyId;
            const isEnable = action === 'enable-key';
            const verb = isEnable ? 'enable' : 'disable';

            // Prevent modal from closing automatically
            if (modalObj) modalObj.modal.dataset.dismiss = 'false';

            confirmModal(
                verb.charAt(0).toUpperCase() + verb.slice(1) + ' Key',
                verb.charAt(0).toUpperCase() + verb.slice(1) + ' this API key?\n\nRequests using this key will be rejected until it is enabled again.',
                async () => {
                    try {
                        await adminFetch('/admin/api/keys/' + currentManageKeyId + '/' + verb, { method: 'POST' });
                        showSuccessToast('Key ' + verb + 'd.');
                        modalObj.close();
                        await loadKeys();
                    } catch (err) {
                        showErrorToast(err.message || 'Failed to ' + verb + ' key.');
                    }
                }
            );
            return;
        }

        if (action === 'save-limits') {
            const form = document.getElementById('key-limits-form');
            clearFormErrors(form);
            const btn = modalObj.modal.querySelector('[data-action="save-limits"]');
            setButtonLoading(btn, true);

            try {
                const data = getFormData(form);
                if (data.rpm) data.rpm = parseInt(data.rpm);
                if (data.token_limit) data.token_limit = parseInt(data.token_limit);

                await adminFetch('/admin/api/keys/' + currentManageKeyId + '/limits', {
                    method: 'PATCH',
                    body: JSON.stringify(data)
                });

                showSuccessToast('Limits updated.');
                modalObj.close();
                await loadKeys();
            } catch (err) {
                handleApiError(err, 'key-limits-form', 'Failed to update limits.');
            } finally {
                setButtonLoading(btn, false);
            }
            return;
        }
    }

    // ==================== Table Action Delegation ====================

    document.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        const action = btn.dataset.action;
        const keyId = parseInt(btn.dataset.keyId);

        if (action === 'manage') {
            e.preventDefault();
            await openManageKeyModal(keyId);
        } else if (action === 'enable-key' || action === 'disable-key') {
            e.preventDefault();
            // Handled by modal's onAction
        }
    });

    // ==================== Create Key Button ====================

    document.addEventListener('DOMContentLoaded', async function() {
        await loadKeysPage();

        const createBtn = document.getElementById('btn-create-key');
        if (createBtn) {
            createBtn.disabled = false;
            createBtn.addEventListener('click', openCreateKeyModal);
        }
    });

    // ==================== Error Handling ====================

    function handleApiError(err, formId, defaultMessage) {
        const form = document.getElementById(formId);
        if (err.code === 'user_not_found') {
            showFormError(form, 'user_id', 'Selected user not found.');
        } else if (err.code === 'key_not_found') {
            showErrorToast('Key not found.');
        } else if (err.code === 'validation_error') {
            if (err.data && err.data.detail) {
                err.data.detail.forEach(e => {
                    if (e.loc && e.loc[1]) {
                        showFormError(form, e.loc[1], e.msg);
                    }
                });
            } else {
                showFormError(form, 'name', err.message || 'Validation error.');
            }
        } else if (err.code === 'invalid_request') {
            showFormError(form, 'name', err.message || 'Invalid request.');
        } else if (err.code === 'csrf_origin_invalid') {
            alertModal('Security Error', 'Security validation failed. Reload the page and try again.');
        } else if (err.status === 401) {
            // adminFetch handles redirect
        } else {
            showErrorToast(err.message || defaultMessage);
        }
    }
})();