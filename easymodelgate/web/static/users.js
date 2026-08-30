/**
 * EasyModelGate Users Page Logic
 */

const {
    adminFetch,
    escapeHtml,
    formatTimestamp,
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
    showErrorToast
} = window.EMGAdmin;

let usersCache = [];

async function loadUsers() {
    setTableLoading('users-table');
    try {
        const data = await adminFetch('/admin/api/users');
        usersCache = data.items || [];
        renderUsersTable(usersCache);
    } catch (err) {
        console.error('Failed to load users:', err);
        setTableError('users-table', err.message || 'Unable to load users.');
    }
}

function renderUsersTable(users) {
    if (!users || !users.length) {
        setTableEmpty('users-table', 'No users yet.');
        return;
    }

    const rows = users.map(user => {
        const statusBadge = user.enabled
            ? '<span class="badge badge-success">Enabled</span>'
            : '<span class="badge badge-warning">Disabled</span>';
        const actions = user.enabled
            ? '<button type="button" class="btn btn-secondary btn-sm" data-action="disable" data-user-id="' + user.id + '" data-username="' + escapeHtml(user.username) + '">Disable</button>'
            : '<button type="button" class="btn btn-primary btn-sm" data-action="enable" data-user-id="' + user.id + '" data-username="' + escapeHtml(user.username) + '">Enable</button>';

        return '<tr>' +
            '<td>' + user.id + '</td>' +
            '<td>' + escapeHtml(user.username) + '</td>' +
            '<td>' + escapeHtml(user.display_name || '-') + '</td>' +
            '<td>' + escapeHtml(user.note || '-') + '</td>' +
            '<td>' + statusBadge + '</td>' +
            '<td>' + formatTimestamp(user.created_at) + '</td>' +
            '<td class="actions-cell">' + actions + '</td>' +
        '</tr>';
    }).join('');

    const tbody = document.querySelector('#users-table tbody');
    if (tbody) tbody.innerHTML = rows;
}

// ==================== Create User Modal ====================

function openCreateUserModal() {
    const modal = createModal({
        title: 'Create User',
        content: `
            <form id="create-user-form" novalidate>
                <div class="form-group">
                    <label for="create-username">Username <span class="required">*</span></label>
                    <input type="text" id="create-username" name="username" required autocomplete="username" maxlength="64">
                    <div class="form-error" data-error-for="username"></div>
                </div>
                <div class="form-group">
                    <label for="create-display-name">Display Name</label>
                    <input type="text" id="create-display-name" name="display_name" autocomplete="name" maxlength="128">
                    <div class="form-error" data-error-for="display_name"></div>
                </div>
                <div class="form-group">
                    <label for="create-note">Note</label>
                    <textarea id="create-note" name="note" rows="3" maxlength="512"></textarea>
                    <div class="form-error" data-error-for="note"></div>
                </div>
            </form>
        `,
        actions: [
            { label: 'Cancel', action: 'cancel', class: 'btn btn-secondary' },
            { label: 'Create User', action: 'create', class: 'btn btn-primary' }
        ],
        onAction: handleCreateUserAction
    });
    // Focus username field
    setTimeout(() => {
        const input = document.getElementById('create-username');
        if (input) input.focus();
    }, 100);
}

async function handleCreateUserAction(action, modalObj) {
    if (action === 'cancel') {
        modalObj.close();
        return;
    }

    if (action !== 'create') return;

    const form = document.getElementById('create-user-form');
    clearFormErrors(form);
    const btn = modalObj.modal.querySelector('[data-action="create"]');
    setButtonLoading(btn, true);

    try {
        const data = getFormData(form);
        const result = await adminFetch('/admin/api/users', {
            method: 'POST',
            body: JSON.stringify(data)
        });

        showSuccessToast('User "' + escapeHtml(data.username) + '" created.');
        modalObj.close();
        await loadUsers();
    } catch (err) {
        handleApiError(err, 'create-user-form', 'Failed to create user.');
    } finally {
        setButtonLoading(btn, false);
    }
}

// ==================== Enable/Disable User ====================

async function handleUserAction(action, userId, username) {
    const endpoint = '/admin/api/users/' + userId + '/' + action;
    const verb = action === 'enable' ? 'enabled' : 'disabled';
    const confirmMsg = action === 'disable'
        ? 'Disable user "' + escapeHtml(username) + '"?\n\nExisting API keys owned by this user will no longer be able to access the model until the user is enabled again.'
        : 'Enable user "' + escapeHtml(username) + '"?';

    confirmModal(
        action.charAt(0).toUpperCase() + action.slice(1) + ' User',
        confirmMsg,
        async () => {
            try {
                await adminFetch(endpoint, { method: 'POST' });
                showSuccessToast('User "' + escapeHtml(username) + '" ' + verb + '.');
                await loadUsers();
            } catch (err) {
                showErrorToast(err.message || 'Failed to ' + action + ' user.');
            }
        }
    );
}

// ==================== Error Handling ====================

function handleApiError(err, formId, defaultMessage) {
    const form = document.getElementById(formId);
    if (err.code === 'user_already_exists') {
        showFormError(form, 'username', 'A user with this username already exists.');
    } else if (err.code === 'validation_error') {
        if (err.data && err.data.detail) {
            // Handle Pydantic validation errors
            err.data.detail.forEach(e => {
                if (e.loc && e.loc[1]) {
                    showFormError(form, e.loc[1], e.msg);
                }
            });
        } else {
            showFormError(form, 'username', err.message || 'Validation error.');
        }
    } else if (err.code === 'invalid_request') {
        showFormError(form, 'username', err.message || 'Invalid request.');
    } else if (err.code === 'csrf_origin_invalid') {
        alertModal('Security Error', 'Security validation failed. Reload the page and try again.');
    } else if (err.status === 401) {
        // adminFetch handles redirect
    } else {
        showErrorToast(err.message || defaultMessage);
    }
}

// ==================== Initialize ====================

document.addEventListener('DOMContentLoaded', async function() {
    await loadUsers();

    // Create User button
    const createBtn = document.getElementById('btn-create-user');
    if (createBtn) {
        createBtn.disabled = false;
        createBtn.addEventListener('click', openCreateUserModal);
    }

    // Delegate table actions
    document.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        const action = btn.dataset.action;
        const userId = parseInt(btn.dataset.userId);
        const username = btn.dataset.username;
        if (action === 'enable' || action === 'disable') {
            e.preventDefault();
            await handleUserAction(action, userId, username);
        }
    });
});