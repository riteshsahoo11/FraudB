/**
 * Initialize Bootstrap tooltips globally
 * Add this script to base.html to enable all tooltips
 */
document.addEventListener('DOMContentLoaded', function() {
    // Initialize all tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    console.log('[Tooltips] Initialized', tooltipList.length, 'tooltips');
    
    // Auto-refresh dashboard data every 30 seconds
    if (window.location.pathname.includes('/dashboard') || window.location.pathname.includes('/analytics')) {
        setInterval(function() {
            console.log('[Auto-Refresh] Updating data...');
            
            // Refresh various data sections if functions exist
            if (typeof loadInsights === 'function') {
                loadInsights().catch(err => console.warn('Could not refresh insights:', err));
            }
            if (typeof loadPerformance === 'function') {
                loadPerformance().catch(err => console.warn('Could not refresh performance:', err));
            }
            if (typeof loadAlerts === 'function') {
                loadAlerts().catch(err => console.warn('Could not refresh alerts:', err));
            }
            if (typeof loadPredictionHistory === 'function') {
                loadPredictionHistory().catch(err => console.warn('Could not refresh history:', err));
            }
            
            // Show subtle notification
            showAutoRefreshToast();
        }, 30000); // 30 seconds
    }
});

/**
 * Show a subtle auto-refresh notification
 */
function showAutoRefreshToast() {
    // Create toast container if it doesn't exist
    let toastContainer = document.getElementById('autoRefreshToastContainer');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'autoRefreshToastContainer';
        toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        toastContainer.style.zIndex = '9999';
        document.body.appendChild(toastContainer);
    }
    
    // Create toast
    const toastHtml = `
        <div class="toast align-items-center text-white bg-success border-0" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="d-flex">
                <div class="toast-body">
                    <i class="fas fa-sync-alt me-2"></i>Data refreshed
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        </div>
    `;
    
    const toastEl = document.createElement('div');
    toastEl.innerHTML = toastHtml;
    const toast = toastEl.firstElementChild;
    toastContainer.appendChild(toast);
    
    const bsToast = new bootstrap.Toast(toast, {
        delay: 2000,
        autohide: true
    });
    bsToast.show();
    
    // Remove toast element after it's hidden
    toast.addEventListener('hidden.bs.toast', () => {
        toast.remove();
    });
}
