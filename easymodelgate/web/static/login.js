/**
 * EasyModelGate Login Page Logic
 */

document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('login-form');
    const errorEl = document.getElementById('login-error');
    const btn = document.getElementById('login-btn');

    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        errorEl.textContent = '';
        btn.disabled = true;
        btn.textContent = 'Signing in...';

        const password = form.password.value;
        try {
            await adminFetch('/admin/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password })
            });
            // On success, adminFetch returns parsed JSON data (no exception thrown)
            window.location.href = '/admin';
        } catch (err) {
            // adminFetch throws on non-ok responses with normalized error
            if (err.code) {
                errorEl.textContent = formatLoginError(err.code, err.status);
            } else {
                errorEl.textContent = 'Network error. Please try again.';
            }
        } finally {
            btn.disabled = false;
            btn.textContent = 'Sign In';
        }
    });

    function formatLoginError(code, status) {
        switch (code) {
            case 'admin_not_initialized':
                return 'Admin not initialized. Please run "python -m easymodelgate admin init" on the server.';
            case 'invalid_admin_credentials':
                return 'Invalid password.';
            case 'admin_login_rate_limited':
                return 'Too many login attempts. Please wait a moment.';
            case 'csrf_origin_invalid':
                return 'Invalid request origin. Please reload the page.';
            case 'admin_auth_required':
                return 'Authentication required.';
            default:
                return 'Login failed (status ' + status + '). Please try again.';
        }
    }
});