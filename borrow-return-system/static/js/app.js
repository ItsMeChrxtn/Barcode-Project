document.addEventListener('DOMContentLoaded', () => {
    const mobileToggle = document.getElementById('mobileSidebarToggle');
    const sidebar = document.getElementById('sidebar');

    const requestFullscreen = async () => {
        const root = document.documentElement;
        if (!root || document.fullscreenElement) {
            return true;
        }

        try {
            if (root.requestFullscreen) {
                await root.requestFullscreen();
                return true;
            }
        } catch (error) {
            return false;
        }

        return false;
    };

    const attachFullscreenFallback = () => {
        const tryOnInteraction = async () => {
            const entered = await requestFullscreen();
            if (entered) {
                document.removeEventListener('click', tryOnInteraction);
                document.removeEventListener('touchstart', tryOnInteraction);
                document.removeEventListener('keydown', tryOnInteraction);
            }
        };

        document.addEventListener('click', tryOnInteraction, { once: false });
        document.addEventListener('touchstart', tryOnInteraction, { once: false });
        document.addEventListener('keydown', tryOnInteraction, { once: false });
    };

    // Browsers may block fullscreen without user gesture, so we try immediately
    // then install one-time interaction fallback.
    requestFullscreen().then((entered) => {
        if (!entered) {
            attachFullscreenFallback();
        }
    });

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
