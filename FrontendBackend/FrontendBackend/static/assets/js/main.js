// Main JavaScript for BFSI Transaction Monitoring System
document.addEventListener('DOMContentLoaded', function() {
    // Initialize Bootstrap tooltips and popovers
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    var popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    var popoverList = popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });

    // Auto-hide alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    alerts.forEach(function(alert) {
        setTimeout(function() {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });

    // File upload handler
    const fileUploadAreas = document.querySelectorAll('.file-upload-area');
    fileUploadAreas.forEach(function(area) {
        const fileInput = area.querySelector('input[type="file"]');
        
        area.addEventListener('click', function() {
            if (fileInput) fileInput.click();
        });

        area.addEventListener('dragover', function(e) {
            e.preventDefault();
            area.classList.add('border-primary');
        });

        area.addEventListener('dragleave', function(e) {
            e.preventDefault();
            area.classList.remove('border-primary');
        });

        area.addEventListener('drop', function(e) {
            e.preventDefault();
            area.classList.remove('border-primary');
            
            if (fileInput && e.dataTransfer.files.length) {
                fileInput.files = e.dataTransfer.files;
                updateFileDisplay(area, e.dataTransfer.files[0]);
            }
        });

        if (fileInput) {
            fileInput.addEventListener('change', function(e) {
                if (e.target.files.length) {
                    updateFileDisplay(area, e.target.files[0]);
                }
            });
        }
    });

    function updateFileDisplay(area, file) {
        const displayElement = area.querySelector('.file-name-display');
        if (displayElement) {
            displayElement.textContent = `Selected: ${file.name} (${formatFileSize(file.size)})`;
        }
    }

    function formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    }

    // Form validation
    const forms = document.querySelectorAll('.needs-validation');
    forms.forEach(function(form) {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            form.classList.add('was-validated');
        });
    });

    // Password strength indicator
    const passwordInputs = document.querySelectorAll('input[type="password"].password-strength');
    passwordInputs.forEach(function(input) {
        const strengthIndicator = document.createElement('div');
        strengthIndicator.className = 'password-strength-indicator mt-2';
        input.parentElement.appendChild(strengthIndicator);

        input.addEventListener('input', function() {
            const strength = calculatePasswordStrength(input.value);
            updatePasswordStrengthIndicator(strengthIndicator, strength);
        });
    });

    function calculatePasswordStrength(password) {
        let strength = 0;
        if (password.length >= 8) strength++;
        if (password.length >= 12) strength++;
        if (/[a-z]/.test(password) && /[A-Z]/.test(password)) strength++;
        if (/\d/.test(password)) strength++;
        if (/[^a-zA-Z\d]/.test(password)) strength++;
        return strength;
    }

    function updatePasswordStrengthIndicator(indicator, strength) {
        const strengthTexts = ['Very Weak', 'Weak', 'Fair', 'Good', 'Strong'];
        const strengthClasses = ['text-danger', 'text-warning', 'text-info', 'text-primary', 'text-success'];
        
        indicator.textContent = `Password Strength: ${strengthTexts[strength]}`;
        indicator.className = `password-strength-indicator mt-2 ${strengthClasses[strength]}`;
    }

    // Dynamic table search
    const searchInputs = document.querySelectorAll('.table-search');
    searchInputs.forEach(function(input) {
        const tableId = input.getAttribute('data-table');
        const table = document.getElementById(tableId);
        
        if (table) {
            input.addEventListener('input', function() {
                const searchTerm = input.value.toLowerCase();
                const rows = table.querySelectorAll('tbody tr');
                
                rows.forEach(function(row) {
                    const text = row.textContent.toLowerCase();
                    row.style.display = text.includes(searchTerm) ? '' : 'none';
                });
            });
        }
    });

    // Copy to clipboard functionality
    const copyButtons = document.querySelectorAll('.copy-to-clipboard');
    copyButtons.forEach(function(button) {
        button.addEventListener('click', function() {
            const targetId = button.getAttribute('data-target');
            const targetElement = document.getElementById(targetId);
            
            if (targetElement) {
                const text = targetElement.textContent || targetElement.value;
                navigator.clipboard.writeText(text).then(function() {
                    showToast('Copied to clipboard!', 'success');
                });
            }
        });
    });

    // Toast notification helper
    window.showToast = function(message, type = 'info') {
        const toastContainer = document.getElementById('toast-container');
        if (!toastContainer) {
            const container = document.createElement('div');
            container.id = 'toast-container';
            container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            document.body.appendChild(container);
        }

        const toastHtml = `
            <div class="toast align-items-center text-white bg-${type} border-0" role="alert">
                <div class="d-flex">
                    <div class="toast-body">${message}</div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
                </div>
            </div>
        `;

        const toastElement = document.createElement('div');
        toastElement.innerHTML = toastHtml;
        const toast = toastElement.firstElementChild;
        document.getElementById('toast-container').appendChild(toast);

        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();

        toast.addEventListener('hidden.bs.toast', function() {
            toast.remove();
        });
    };

    // Smooth scroll for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            const targetId = this.getAttribute('href');
            if (targetId !== '#') {
                e.preventDefault();
                const targetElement = document.querySelector(targetId);
                if (targetElement) {
                    targetElement.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }
            }
        });
    });


    // Ajax form submission helper
    window.submitFormAjax = function(formElement, successCallback, errorCallback) {
        const formData = new FormData(formElement);
        
        fetch(formElement.action, {
            method: formElement.method || 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': getCookie('csrftoken')
            }
        })
        .then(response => response.json())
        .then(data => {
            if (successCallback) successCallback(data);
        })
        .catch(error => {
            if (errorCallback) errorCallback(error);
            console.error('Form submission error:', error);
        });
    };

    // Get CSRF token from cookies
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    // Number formatting for financial data
    window.formatCurrency = function(amount, currency = 'USD') {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: currency
        }).format(amount);
    };

    window.formatNumber = function(number) {
        return new Intl.NumberFormat('en-US').format(number);
    };

    // Date formatting
    window.formatDate = function(date, format = 'short') {
        const options = format === 'short' 
            ? { year: 'numeric', month: 'short', day: 'numeric' }
            : { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' };
        
        return new Date(date).toLocaleDateString('en-US', options);
    };
});
