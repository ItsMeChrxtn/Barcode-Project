document.addEventListener('DOMContentLoaded', () => {
    const mobileToggle = document.getElementById('mobileSidebarToggle');
    const sidebar = document.getElementById('sidebar');

    const iconMap = {
        success: 'success',
        danger: 'error',
        error: 'error',
        warning: 'warning',
        info: 'info',
    };

    window.showAppAlert = (message, category = 'info') => {
        if (!window.Swal) {
            return;
        }

        return window.Swal.fire({
            text: message,
            icon: iconMap[category] || 'info',
            confirmButtonColor: '#15803d',
        });
    };

    if (mobileToggle && sidebar) {
        mobileToggle.addEventListener('click', () => {
            sidebar.classList.toggle('-translate-x-full');
        });
    }

    // Allow scanner users to quickly jump to barcode fields with Ctrl+B.
    document.addEventListener('keydown', (event) => {
        if (event.ctrlKey && (event.key === 'b' || event.key === 'B')) {
            const barcodeInput = document.querySelector('[data-barcode-input="true"]');
            if (barcodeInput) {
                barcodeInput.focus();
                barcodeInput.select();
                event.preventDefault();
            }
        }
    });

    if (Array.isArray(window.flashMessages) && window.flashMessages.length && window.Swal) {
        window.flashMessages.reduce((promise, [category, message]) => {
            return promise.then(() => window.showAppAlert(message, category));
        }, Promise.resolve());
    }
});
