function setupBarcodeScanner(config) {
    const input = document.querySelector(config.inputSelector);
    if (!input) {
        return;
    }

    const autoSubmit = !!config.autoSubmit;
    const fetchUrlBuilder = config.fetchUrlBuilder;
    const onData = config.onData;
    const onMissing = config.onMissing;
    const onError = config.onError;

    const processScan = async () => {
        const rawCode = input.value.trim();
        if (!rawCode) {
            return;
        }

        if (typeof fetchUrlBuilder !== 'function') {
            return;
        }

        try {
            const response = await fetch(fetchUrlBuilder(rawCode));
            const data = await response.json();

            if (!data.found) {
                if (typeof onMissing === 'function') {
                    onMissing(rawCode);
                }
                return;
            }

            if (typeof onData === 'function') {
                onData(data);
            }

            if (autoSubmit && config.formSelector) {
                const form = document.querySelector(config.formSelector);
                if (form) {
                    form.requestSubmit();
                }
            }
        } catch (error) {
            if (typeof onError === 'function') {
                onError(error);
            }
        }
    };

    // Most USB scanners send an Enter key at the end of a scan.
    input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            processScan();
        }
    });

    input.addEventListener('blur', () => {
        // Keep scanner field focused for kiosk-like workflows.
        setTimeout(() => {
            input.focus();
        }, 120);
    });

    input.focus();

    return {
        processScan,
    };
}
