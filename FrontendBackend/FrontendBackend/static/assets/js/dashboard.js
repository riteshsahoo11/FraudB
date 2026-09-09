/**
 * BFSI Transaction Intelligence - Dashboard JavaScript
 * Handles ML prediction interactions and dashboard functionality
 */

class TransactionPredictor {
    constructor() {
        this.isLoading = false;
        this.charts = {};
        this.batchResults = null;
        // History pagination state
        this.historyPage = 1;
        this.historyPageSize = 10;
        this.historyTotal = 0;
        this.selectedHistoryIds = new Set();
        this.init();
    }

    // Validate required CSV columns for batch processing
    validateCsvRequiredColumns(file) {
        const REQUIRED = ['customer_id','account_age_days','transaction_amount','channel','kyc_verified'];
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onerror = () => reject(new Error('Failed to read file'));
            reader.onload = () => {
                try {
                    const text = String(reader.result || '');
                    // Get first non-empty line (header)
                    const firstLine = (text.split(/\r?\n/).find(l => l.trim().length > 0) || '').trim();
                    if (!firstLine) return resolve({ ok: false, missing: REQUIRED });
                    // Naive CSV split (handles simple quoted headers)
                    const cols = [];
                    let cur = '', inQ = false;
                    for (let i=0;i<firstLine.length;i++) {
                        const ch = firstLine[i];
                        if (ch === '"') { inQ = !inQ; continue; }
                        if (ch === ',' && !inQ) { cols.push(cur.trim().replace(/^"|"$/g,'')); cur = ''; continue; }
                        cur += ch;
                    }
                    cols.push(cur.trim().replace(/^"|"$/g,''));
                    const lower = cols.map(c => c.toLowerCase());
                    const missing = REQUIRED.filter(r => !lower.includes(r));
                    resolve({ ok: missing.length === 0, missing });
                } catch(e) { reject(e); }
            };
            // Read only first 64KB for speed
            const blob = file.slice(0, 65536);
            reader.readAsText(blob);
        });
    }

    async handleFileSelect(e) {
        try {
            const file = e.target.files && e.target.files[0];
            const prev = document.getElementById('filePreview');
            const fn = document.getElementById('fileName');
            const fs = document.getElementById('fileSize');
            const val = document.getElementById('fileValidation');
            if (!file) {
                if (prev) prev.classList.add('d-none');
                if (val) val.classList.add('d-none');
                return;
            }
            // Show preview
            if (prev) prev.classList.remove('d-none');
            if (fn) fn.textContent = file.name;
            if (fs) fs.textContent = this.formatFileSize(file.size);

            // Validate CSV headers if CSV
            const lower = (file.name || '').toLowerCase();
            if (lower.endsWith('.csv')) {
                const res = await this.validateCsvRequiredColumns(file).catch(() => ({ ok: false, missing: [] }));
                if (val) {
                    val.classList.remove('d-none');
                    if (res.ok) {
                        val.innerHTML = '<div class="alert alert-success py-2 mb-0"><i class="bi bi-check-circle me-2"></i>All required columns detected.</div>';
                    } else {
                        const miss = (res.missing || []).map(m => `<span class="badge bg-warning text-dark me-1">${m}</span>`).join(' ');
                        val.innerHTML = `<div class="alert alert-warning py-2 mb-0"><i class="bi bi-exclamation-triangle me-2"></i>Missing required columns: ${miss}</div>`;
                    }
                }
            } else {
                if (val) {
                    val.classList.remove('d-none');
                    val.innerHTML = '<div class="alert alert-info py-2 mb-0">Header validation only applies to CSV. XLSX/JSON are accepted.</div>';
                }
            }
        } catch (err) {
            console.error('handleFileSelect error', err);
        }
    }

    async handleBatchPrediction(e) {
        e.preventDefault();
        try {
            const input = document.getElementById('batchFile');
            const btn = document.getElementById('batchPredictBtn');
            const sp = btn ? btn.querySelector('.spinner-border') : null;
            const resultWrap = document.getElementById('batchResult');
            const summaryDiv = document.getElementById('batchSummary');
            if (!input || !input.files || !input.files[0]) {
                this.showError('Please select a file to upload');
                return;
            }
            const file = input.files[0];
            if (sp) sp.classList.remove('d-none');
            if (btn) btn.disabled = true;

            const fd = new FormData();
            fd.append('file', file);
            const res = await fetch('/api/predict-batch', {
                method: 'POST',
                body: fd,
                headers: { 'X-CSRFToken': this.getCSRFToken() },
                credentials: 'same-origin'
            });
            const ct = res.headers.get('content-type') || '';
            const j = ct.includes('application/json') ? await res.json() : {};
            if (!res.ok || j.error) {
                throw new Error(j.error || `Upload failed (${res.status})`);
            }
            // Success
            this.batchResults = Array.isArray(j.results) ? j.results : [];
            if (resultWrap) resultWrap.classList.remove('d-none');
            if (summaryDiv) {
                const s = j.summary || {};
                summaryDiv.innerHTML = `
                    <div class="row text-center">
                        <div class="col"><h5>${s.total_transactions || 0}</h5><small>Total</small></div>
                        <div class="col"><h5>${s.fraud_detected || 0}</h5><small>Fraud</small></div>
                        <div class="col"><h5>${s.legitimate_transactions || 0}</h5><small>Legit</small></div>
                        <div class="col"><h5>${(s.fraud_rate || 0).toFixed ? s.fraud_rate.toFixed(2) : s.fraud_rate || 0}%</h5><small>Fraud Rate</small></div>
                    </div>`;
            }
            this.showSuccess('Batch processed successfully. See Dashboard and Analytics for updates.');
        } catch (err) {
            console.error('handleBatchPrediction error', err);
            this.showError('Batch processing failed: ' + (err.message || err));
        } finally {
            const btn = document.getElementById('batchPredictBtn');
            const sp = btn ? btn.querySelector('.spinner-border') : null;
            if (sp) sp.classList.add('d-none');
            if (btn) btn.disabled = false;
        }
    }

    async loadDrift() {
        try {
            const res = await fetch('/api/drift');
            const j = await res.json();
            if (!(res.ok && j.status === 'success')) return;
            const psi = Number(j.psi || 0);
            const psiEl = document.getElementById('psiValue');
            if (psiEl) psiEl.textContent = psi.toFixed(3);
            const series = Array.isArray(j.trend) ? j.trend : [];
            const labels = series.map(s => s.date);
            const values = series.map(s => s.avg);
            const ctx = document.getElementById('driftChart')?.getContext('2d');
            if (ctx && typeof Chart !== 'undefined') {
                this._upsertChart('drift', ctx, {
                    type: 'line',
                    data: { labels, datasets: [{ label: 'Avg Risk Score', data: values, borderColor: '#8b5cf6', backgroundColor: 'rgba(139,92,246,0.15)', tension: 0.3, fill: true }] },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
                });
            }
        } catch (e) {
            console.error('Error loading drift:', e);
        }
    }

    switchToResultsTab() {
        try {
            const resultsTab = document.querySelector('#results-tab');
            if (resultsTab && window.bootstrap && bootstrap.Tab) {
                const tab = new bootstrap.Tab(resultsTab);
                tab.show();
            } else if (resultsTab) {
                // Fallback: simulate click
                resultsTab.click();
            }
        } catch (e) {
            // Non-fatal
        }
    }

    init() {
        // Create widgets first so DOM elements exist, then bind events
        this.initializeWidgets();
        this.bindEvents();
        this.historyFilter = 'all'; // Track current filter
        this.loadPredictionHistory();
    }

    bindEvents() {
        // Single prediction form
        const singlePredForm = document.getElementById('singlePredictionForm');
        if (singlePredForm) {
            singlePredForm.addEventListener('submit', (e) => this.handleSinglePrediction(e));
        }
        // Removed demo fill button

        // Batch prediction form
        const batchPredForm = document.getElementById('batchPredictionForm');
        if (batchPredForm) {
            batchPredForm.addEventListener('submit', (e) => this.handleBatchPrediction(e));
        }

        // File upload handling
        const fileInput = document.getElementById('batchFile');
        if (fileInput) {
            fileInput.addEventListener('change', (e) => this.handleFileSelect(e));
        }

        // Refresh buttons
        document.querySelectorAll('.refresh-stats').forEach(btn => {
            btn.addEventListener('click', () => this.refreshDashboardStats());
        });

        // Explicit refresh buttons on cards
        const rStats = document.getElementById('refreshStats');
        if (rStats) rStats.addEventListener('click', () => { this.loadModelStats(); this.loadInsights(); });
        const rPerf = document.getElementById('refreshPerformance');
        if (rPerf) rPerf.addEventListener('click', () => this.loadPerformance());

        // Removed demo simulation actions

        // History pagination
        const btnPrev = document.getElementById('historyPrev');
        const btnNext = document.getElementById('historyNext');
        if (btnPrev) btnPrev.addEventListener('click', () => {
            if (this.historyPage > 1) this.loadPredictionHistory(this.historyPage - 1);
        });
        if (btnNext) btnNext.addEventListener('click', () => {
            const totalPages = Math.max(1, Math.ceil(this.historyTotal / this.historyPageSize));
            if (this.historyPage < totalPages) this.loadPredictionHistory(this.historyPage + 1);
        });
        // Bulk select controls
        const selAll = document.getElementById('selectAllHistory');
        const bulkBtn = document.getElementById('bulkDeleteBtn');
        if (selAll) selAll.addEventListener('change', () => this.toggleSelectAll(selAll.checked));
        if (bulkBtn) bulkBtn.addEventListener('click', () => this.bulkDeleteSelected());
        
        // Filter buttons
        document.querySelectorAll('.filter-pill[data-filter]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const filter = e.currentTarget.getAttribute('data-filter');
                this.historyFilter = filter;
                // Update active state
                document.querySelectorAll('.filter-pill').forEach(b => b.classList.remove('active'));
                e.currentTarget.classList.add('active');
                // Reload with filter
                this.loadPredictionHistory(1);
            });
        });

        // Recent uploads delete buttons (with page reload for full refresh)
        document.querySelectorAll('[data-upload-delete]').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = e.currentTarget.getAttribute('data-upload-delete');
                if (!id) return;
                if (!confirm('Delete this upload and all its predictions?')) return;
                try {
                    const res = await fetch(`/api/uploads/${id}/delete`, {
                        method: 'POST',
                        headers: { 'X-CSRFToken': this.getCSRFToken() },
                        credentials: 'same-origin'
                    });
                    if (!res.ok) {
                        const j = await res.json().catch(() => ({}));
                        throw new Error(j.error || 'Delete failed');
                    }
                    alert('Upload deleted successfully');
                    window.location.reload();
                } catch (err) {
                    alert('Error: ' + String(err.message || err));
                }
            });
        });

        // Removed seed button (auto-seeded in backend for new users)

        // Download/Export buttons
        const btnAnalytics = document.getElementById('downloadAnalyticsCsv');
        if (btnAnalytics) btnAnalytics.addEventListener('click', () => this.downloadUrl('/api/analytics?format=csv', `analytics_${this.today()}.csv`));
        const btnPerformance = document.getElementById('downloadPerformanceCsv');
        if (btnPerformance) btnPerformance.addEventListener('click', () => this.downloadUrl('/api/performance?format=csv', `performance_${this.today()}.csv`));
        const btnPreds = document.getElementById('downloadPredictionsCsv');
        if (btnPreds) btnPreds.addEventListener('click', () => this.downloadUrl('/api/transactions?format=csv&page=1&page_size=1000', `predictions_${this.today()}.csv`));
        const btnDrift = document.getElementById('downloadDriftCsv');
        if (btnDrift) btnDrift.addEventListener('click', () => this.downloadUrl('/api/drift?format=csv', `drift_${this.today()}.csv`));

        // Batch results download
        const btnBatchCsv = document.getElementById('downloadBatchCsv');
        if (btnBatchCsv) btnBatchCsv.addEventListener('click', () => this.downloadResults());

        // Toggle Single vs Batch sections
        const modeSingle = document.getElementById('modeSingle');
        const modeBatch = document.getElementById('modeBatch');
        const singleSec = document.getElementById('singlePredictionSection');
        const batchSec = document.getElementById('batchPredictionSection');
        const applyToggle = () => {
            const isBatch = modeBatch && modeBatch.checked;
            if (singleSec) singleSec.style.display = isBatch ? 'none' : '';
            if (batchSec) batchSec.style.display = isBatch ? '' : 'none';
        };
        if (modeSingle && modeBatch) {
            modeSingle.addEventListener('change', applyToggle);
            modeBatch.addEventListener('change', applyToggle);
            // Initialize state
            applyToggle();
        }
    }

    initializeWidgets() {
        // Initialize prediction form if it exists
        this.createPredictionWidget();
        
        // Initialize quick stats (skip if server already rendered)
        if (!window.SKIP_MODEL_LOAD) {
            this.loadModelStats();
            this.loadPerformance();
        }
        this.loadInsights();
        this.loadAlerts();
        this.loadDrift();
        
        // Auto-refresh stats every 30 seconds
        setInterval(() => this.refreshDashboardStats(), 30000);
    }

    createPredictionWidget() {
        const container = document.getElementById('predictionWidget');
        if (!container) return;

        container.innerHTML = `
            <div class="card shadow-sm mb-4">
                <div class="card-header bg-white border-bottom">
                    <div class="d-flex justify-content-start">
                        <div class="btn-group" role="group">
                            <input type="radio" class="btn-check" name="predictionMode" id="modeSingle" checked>
                            <label class="btn btn-outline-warning" for="modeSingle" style="border-color: #FF6B01; color: #FF6B01;">
                                <i class="fas fa-file-invoice me-2"></i>Single Transaction
                            </label>
                            <input type="radio" class="btn-check" name="predictionMode" id="modeBatch">
                            <label class="btn btn-outline-warning" for="modeBatch" style="border-color: #FF6B01; color: #FF6B01;">
                                <i class="fas fa-file-upload me-2"></i>Batch Upload
                            </label>
                        </div>
                    </div>
                </div>
                <div class="card-body">
                    <!-- Single Transaction Section -->
                    <div id="singlePredictionSection">
                        <div class="row g-4">
                            <!-- Left Side - Form -->
                            <div class="col-lg-6">
                                <div class="mb-4">
                                    <h5 class="fw-bold mb-1">Single Transaction Prediction</h5>
                                    <p class="text-muted small mb-0">Enter transaction details to get instant fraud risk analysis</p>
                                </div>
                                <form id="singlePredictionForm">
                                        <div class="mb-3">
                                            <label for="customerId" class="form-label fw-bold">
                                                Customer ID <span class="text-danger">*</span>
                                                <i class="fas fa-question-circle text-info ms-1" data-bs-toggle="tooltip" 
                                                   title="Unique identifier for the customer making this transaction"></i>
                                            </label>
                                            <input type="text" class="form-control" id="customerId" name="customer_id" 
                                                   placeholder="e.g., CUST12345" required>
                                            <div class="form-text">
                                                <i class="fas fa-info-circle text-muted me-1"></i>
                                                Enter the unique ID assigned to this customer in your system
                                            </div>
                                        </div>
                                        <div class="mb-3">
                                            <label for="accountAgeDays" class="form-label fw-bold">
                                                Account Age (days) <span class="text-danger">*</span>
                                                <i class="fas fa-question-circle text-info ms-1" data-bs-toggle="tooltip" 
                                                   title="How many days has this account been active?"></i>
                                            </label>
                                            <input type="number" class="form-control" id="accountAgeDays" name="account_age_days" 
                                                   placeholder="e.g., 365" min="0" step="1" required>
                                            <div class="form-text">
                                                <i class="fas fa-info-circle text-muted me-1"></i>
                                                Newer accounts (< 30 days) typically have higher fraud risk
                                            </div>
                                        </div>
                                        <div class="mb-3">
                                            <label for="transactionAmount" class="form-label fw-bold">
                                                Transaction Amount <span class="text-danger">*</span>
                                                <i class="fas fa-question-circle text-info ms-1" data-bs-toggle="tooltip" 
                                                   title="The monetary value of this transaction"></i>
                                            </label>
                                            <div class="input-group">
                                                <span class="input-group-text"><i class="fas fa-dollar-sign"></i></span>
                                                <input type="number" class="form-control" id="transactionAmount" name="transaction_amount" 
                                                       placeholder="e.g., 150.75" step="0.01" min="0" required>
                                            </div>
                                            <div class="form-text">
                                                <i class="fas fa-info-circle text-muted me-1"></i>
                                                Higher amounts (> $1000) typically indicate higher fraud risk
                                            </div>
                                        </div>
                                        <div class="mb-3">
                                            <label for="accountBalance" class="form-label fw-bold">
                                                Account Balance <span class="text-muted">(optional)</span>
                                                <i class="fas fa-question-circle text-info ms-1" data-bs-toggle="tooltip" 
                                                   title="Current balance in the account - helps detect unusual spending patterns"></i>
                                            </label>
                                            <div class="input-group">
                                                <span class="input-group-text"><i class="fas fa-dollar-sign"></i></span>
                                                <input type="number" class="form-control" id="accountBalance" name="account_balance" 
                                                       placeholder="e.g., 5000.00" step="0.01" min="0">
                                            </div>
                                            <div class="form-text">
                                                <i class="fas fa-info-circle text-muted me-1"></i>
                                                Leave blank if not available. Used to calculate amount-to-balance ratio.
                                            </div>
                                        </div>
                                        <div class="mb-3">
                                            <label for="channel" class="form-label fw-bold">
                                                Transaction Channel <span class="text-danger">*</span>
                                                <i class="fas fa-question-circle text-info ms-1" data-bs-toggle="tooltip" 
                                                   title="Where did this transaction originate?"></i>
                                            </label>
                                            <select id="channel" name="channel" class="form-select" required>
                                                <option value="">-- Select Channel --</option>
                                                <option value="ONLINE">Online Banking</option>
                                                <option value="BRANCH">Bank Branch</option>
                                                <option value="ATM">ATM</option>
                                                <option value="MOBILE">Mobile App</option>
                                                <option value="THIRD_PARTY">Third-Party Service</option>
                                                <option value="P2P">Peer-to-Peer Transfer</option>
                                            </select>
                                            <div class="form-text">
                                                <i class="fas fa-info-circle text-muted me-1"></i>
                                                Online, P2P, and Third-Party channels have historically higher fraud rates
                                            </div>
                                        </div>
                                        <div class="mb-3">
                                            <label for="kycVerified" class="form-label fw-bold">
                                                KYC Verification Status <span class="text-danger">*</span>
                                                <i class="fas fa-question-circle text-info ms-1" data-bs-toggle="tooltip" 
                                                   title="Has this customer completed Know Your Customer verification?"></i>
                                            </label>
                                            <select id="kycVerified" name="kyc_verified" class="form-select" required>
                                                <option value="">-- Select Status --</option>
                                                <option value="Yes">Verified</option>
                                                <option value="No">Not Verified</option>
                                            </select>
                                            <div class="form-text">
                                                <i class="fas fa-info-circle text-muted me-1"></i>
                                                Unverified customers have <strong>significantly higher</strong> fraud risk
                                            </div>
                                        </div>
                                        <div class="row g-3">
                                            <div class="col-md-6">
                                                <label for="dailyTxnCount" class="form-label fw-bold">
                                                    Daily Transaction Count <span class="text-muted">(optional)</span>
                                                    <i class="fas fa-question-circle text-info ms-1" data-bs-toggle="tooltip" 
                                                       title="How many transactions has this customer made today?"></i>
                                                </label>
                                                <input type="number" class="form-control" id="dailyTxnCount" name="daily_transaction_count" 
                                                       placeholder="e.g., 5" min="0" step="1">
                                                <div class="form-text small">
                                                    Number of transactions made today. High volume (>20) may indicate fraud.
                                                </div>
                                            </div>
                                            <div class="col-md-6">
                                                <label for="failed7d" class="form-label fw-bold">
                                                    Failed Transactions (Last 7 Days) <span class="text-muted">(optional)</span>
                                                    <i class="fas fa-question-circle text-info ms-1" data-bs-toggle="tooltip" 
                                                       title="How many failed transaction attempts in the past 7 days?"></i>
                                                </label>
                                                <input type="number" class="form-control" id="failed7d" name="failed_transaction_count_7d" 
                                                       placeholder="e.g., 2" min="0" step="1">
                                                <div class="form-text small">
                                                    Count of failed attempts in the past week. Multiple failures may indicate fraud testing.
                                                </div>
                                            </div>
                                        </div>
                                        <div class="row g-3 mt-1">
                                            <div class="col-md-6">
                                                <label for="ipFlag" class="form-label fw-bold">
                                                    Suspicious IP Address <span class="text-muted">(optional)</span>
                                                    <i class="fas fa-question-circle text-info ms-1" data-bs-toggle="tooltip" 
                                                       title="Is this IP address flagged as suspicious?"></i>
                                                </label>
                                                <select id="ipFlag" name="ip_address_flag" class="form-select">
                                                    <option value="">-- Select --</option>
                                                    <option value="0">No - Safe IP</option>
                                                    <option value="1">Yes - Flagged IP</option>
                                                </select>
                                                <div class="form-text small">
                                                    Whether the IP address is on a blacklist or from a high-risk location.
                                                </div>
                                            </div>
                                            <div class="col-md-6">
                                                <label for="prevFraud" class="form-label fw-bold">
                                                    Previous Fraud History <span class="text-muted">(optional)</span>
                                                    <i class="fas fa-question-circle text-info ms-1" data-bs-toggle="tooltip" 
                                                       title="Has this customer been involved in fraud before?"></i>
                                                </label>
                                                <select id="prevFraud" name="previous_fraudulent_activity" class="form-select">
                                                    <option value="">-- Select --</option>
                                                    <option value="0">No - Clean Record</option>
                                                    <option value="1">Yes - Past Fraud</option>
                                                </select>
                                                <div class="form-text small">
                                                    Whether this customer has a history of fraudulent activity.
                                                </div>
                                            </div>
                                        </div>
                                        <div class="mb-3">
                                            <label for="transactionTime" class="form-label fw-bold">
                                                Transaction Date & Time <span class="text-muted">(optional)</span>
                                                <i class="fas fa-question-circle text-info ms-1" data-bs-toggle="tooltip" 
                                                   title="When did this transaction occur?"></i>
                                            </label>
                                            <input type="datetime-local" class="form-control" id="transactionTime" name="timestamp" 
                                                   placeholder="dd-mm-yyyy --:--">
                                            <div class="form-text small">
                                                Select the exact date and time of the transaction. Leave blank to use current time.
                                            </div>
                                        </div>
                                        <div class="text-start">
                                            <button type="submit" class="btn btn-primary px-4" id="predictBtn">
                                                <span class="spinner-border spinner-border-sm d-none" role="status"></span>
                                                <i class="fas fa-brain me-2"></i>Predict Fraud Risk
                                            </button>
                                        </div>
                                    </form>
                                </div>
                                
                                <!-- Right Side - Results -->
                                <div class="col-lg-6">
                                    <div class="mb-4">
                                        <h5 class="fw-bold mb-1">Prediction Results</h5>
                                        <p class="text-muted small mb-0">Analysis results will appear here</p>
                                    </div>
                                    
                                    <!-- Empty State -->
                                    <div id="singleResultEmpty" class="text-center py-5">
                                        <div class="mb-3">
                                            <i class="fas fa-chart-line" style="font-size: 64px; color: #e5e7eb;"></i>
                                        </div>
                                        <h6 class="text-muted mb-2">No Results Yet</h6>
                                        <p class="text-muted small">Fill out the form and click "Predict Fraud Risk" to see results</p>
                                    </div>
                                    
                                    <!-- Result Display -->
                                    <div id="singleResult" class="d-none">
                                        <div class="card border-2" style="border-color: #FF6B01;">
                                            <div class="card-header bg-white" style="border-bottom: 2px solid #FF6B01;">
                                                <h6 class="mb-0" style="color: #FF6B01;"><i class="bi bi-clipboard-check me-2"></i>Analysis Complete</h6>
                                            </div>
                                            <div class="card-body bg-light" id="predictionDetails"></div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                                    <!-- Batch Upload Section -->
                                    <div id="batchPredictionSection" style="display: none;">
                                        <div class="row justify-content-center">
                                            <div class="col-lg-8 col-xl-7">
                                                <div class="mb-4">
                                                    <h5 class="fw-bold mb-1">Batch Transaction Upload</h5>
                                                    <p class="text-muted small mb-0">Upload a file containing multiple transactions for bulk fraud detection</p>
                                                </div>
                                                <form id="batchPredictionForm">
                                            <div class="mb-4">
                                                <label for="batchFile" class="form-label fw-bold">
                                                    Upload Transaction File <span class="text-danger">*</span>
                                                </label>
                                                <input type="file" class="form-control form-control-lg" id="batchFile" 
                                                       accept=".csv,.xlsx,.json" required>
                                                <div class="form-text">
                                                    <i class="fas fa-info-circle text-muted me-1"></i>
                                                    Supported formats: CSV, XLSX, JSON. Maximum 1000 transactions per file.
                                                </div>
                                            </div>
                                            <div id="filePreview" class="mb-4 d-none">
                                                <div class="alert alert-secondary border">
                                                    <div class="row">
                                                        <div class="col-md-6">
                                                            <strong>File:</strong> <span id="fileName"></span>
                                                        </div>
                                                        <div class="col-md-6">
                                                            <strong>Size:</strong> <span id="fileSize"></span>
                                                        </div>
                                                    </div>
                                                </div>
                                            </div>
                                            <div id="fileValidation" class="mb-3 d-none"></div>
                                            <div class="text-start">
                                                <button type="submit" class="btn btn-success px-4" id="batchPredictBtn">
                                                    <span class="spinner-border spinner-border-sm d-none" role="status"></span>
                                                    <i class="fas fa-upload me-2"></i>Process Batch
                                                </button>
                                            </div>
                                            
                                            <!-- Batch Result Display -->
                                            <div id="batchResult" class="mt-4 d-none">
                                                <div class="card border-2" style="border-color: #FF6B01;">
                                                    <div class="card-header bg-white" style="border-bottom: 2px solid #FF6B01;">
                                                        <h6 class="mb-0" style="color: #FF6B01;"><i class="bi bi-clipboard-check me-2"></i>Batch Analysis Complete</h6>
                                                    </div>
                                                    <div class="card-body bg-light">
                                                        <div id="batchSummary"></div>
                                                        <button class="btn btn-primary btn-sm mt-3" id="downloadBatchCsv">
                                                            <i class="bi bi-download me-2"></i>Download Results CSV
                                                        </button>
                                                    </div>
                                                </div>
                                            </div>
                                        </form>
                                    </div>
                                </div>
                            </div>
                </div>
            </div>
        `;
        
        // Add CSS for active button state and form styling
        const style = document.createElement('style');
        style.textContent = `
            .btn-check:checked + .btn-outline-warning {
                background-color: #FF6B01 !important;
                border-color: #FF6B01 !important;
                color: #fff !important;
            }
            .btn-outline-warning:hover {
                background-color: #FFF5EE !important;
                border-color: #FF6B01 !important;
                color: #FF6B01 !important;
            }
            /* Modern Filter Pills */
            .filter-pills { display: inline-flex; gap: 4px; background: #f3f4f6; padding: 4px; border-radius: 10px; }
            .filter-pill { 
                border: none; 
                background: transparent; 
                padding: 6px 16px; 
                border-radius: 8px; 
                font-size: 14px; 
                font-weight: 500; 
                color: #6b7280; 
                cursor: pointer; 
                transition: all 0.2s ease; 
            }
            .filter-pill:hover { background: rgba(255,107,1,0.1); color: #FF6B01; }
            .filter-pill.active { background: #FF6B01; color: white; box-shadow: 0 2px 4px rgba(255,107,1,0.2); }

            /* Recent predictions item */
            .pred-item { transition: background-color .2s ease, transform .1s ease; border-left: 4px solid transparent; border-radius: 10px; }
            .pred-item:hover { background-color: #fafafa; transform: translateY(-1px); }
            .pred-fraud { border-left-color: #EF4444; }
            .pred-legit { border-left-color: #10B981; }
            .pred-chip { padding: 2px 8px; border-radius: 999px; font-size: 12px; }
            .chip-fraud { background: #fee2e2; color: #b91c1c; }
            .chip-legit { background: #dcfce7; color: #047857; }
            #predictBtn, #batchPredictBtn {
                width: auto !important;
                display: inline-flex !important;
                align-items: center;
                gap: 6px;
                border-radius: 8px;
            }
            #singlePredictionForm .form-control,
            #singlePredictionForm .form-select,
            #batchPredictionForm .form-control {
                border: 2px solid #e5e7eb;
                border-radius: 8px;
                padding: 10px 14px;
                transition: all 0.3s ease;
            }
            #singlePredictionForm .form-control:focus,
            #singlePredictionForm .form-select:focus,
            #batchPredictionForm .form-control:focus {
                border-color: #FF6B01;
                box-shadow: 0 0 0 3px rgba(255,107,1,0.1);
            }
            #singlePredictionForm .input-group-text {
                background-color: #FFF5EE;
                border: 2px solid #e5e7eb;
                border-right: none;
                color: #FF6B01;
                font-weight: 600;
            }
            #singlePredictionForm .input-group .form-control {
                border-left: none;
            }
            #singlePredictionForm .form-label,
            #batchPredictionForm .form-label {
                color: #1f2937;
                font-size: 14px;
                margin-bottom: 8px;
            }
            #singlePredictionForm .form-text,
            #batchPredictionForm .form-text {
                font-size: 12px;
                color: #6b7280;
                margin-top: 6px;
            }
        `;
        document.head.appendChild(style);
    }

    toggleSelectAll(checked) {
        const container = document.getElementById('predictionHistory');
        if (!container) return;
        container.querySelectorAll('input[type="checkbox"][data-hist]')
            .forEach(cb => { cb.checked = checked; this.toggleSelect(cb.dataset.hist, checked); });
        this.updateBulkBtnState();
    }

    toggleSelect(id, on) {
        if (!id) return;
        if (on) this.selectedHistoryIds.add(id); else this.selectedHistoryIds.delete(id);
    }

    updateBulkBtnState() {
        const bulkBtn = document.getElementById('bulkDeleteBtn');
        if (bulkBtn) bulkBtn.disabled = this.selectedHistoryIds.size === 0;
    }

    async bulkDeleteSelected() {
        if (this.selectedHistoryIds.size === 0) return;
        if (!confirm(`Delete ${this.selectedHistoryIds.size} selected prediction(s)?`)) return;
        try {
            const res = await fetch('/api/transactions/bulk-delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCSRFToken() },
                body: JSON.stringify({ ids: Array.from(this.selectedHistoryIds) })
            });
            const j = await res.json().catch(()=>({}));
            if (!res.ok) throw new Error(j.error || 'Bulk delete failed');
            this.selectedHistoryIds.clear();
            const selAll = document.getElementById('selectAllHistory');
            if (selAll) selAll.checked = false;
            this.updateBulkBtnState();
            this.loadPredictionHistory(this.historyPage);
            this.loadInsights();
            this.loadPerformance();
            alert(`Deleted ${j.deleted || 0} prediction(s)`);
        } catch (e) {
            this.showError(String(e.message || e));
        }
    }

    showError(msg) {
        alert('Error: ' + msg);
        
        // Add mode toggle functionality
        document.getElementById('modeSingle').addEventListener('change', () => {
            document.getElementById('singlePredictionSection').style.display = 'block';
            document.getElementById('batchPredictionSection').style.display = 'none';
        });
        document.getElementById('modeBatch').addEventListener('change', () => {
            document.getElementById('singlePredictionSection').style.display = 'none';
            document.getElementById('batchPredictionSection').style.display = 'block';
        });
    }

    async handleSinglePrediction(e) {
        e.preventDefault();
        
        if (this.isLoading) return;
        this.isLoading = true;

        const form = e.target;
        const submitBtn = document.getElementById('predictBtn');
        const spinner = submitBtn.querySelector('.spinner-border');
        const resultDiv = document.getElementById('singleResult');
        
        // Show loading state
        submitBtn.disabled = true;
        spinner.classList.remove('d-none');
        resultDiv.classList.add('d-none');

        try {
            // Collect form data
            const formData = new FormData(form);
            const data = Object.fromEntries(formData.entries());
            
            // Convert timestamp to ISO string if provided
            if (data.timestamp) {
                data.timestamp = new Date(data.timestamp).toISOString();
            }

            const response = await fetch('/api/predict', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(data)
            });

            let result = {};
            try { result = await response.json(); } catch (_) { result = {}; }

            if (response.ok && result.status === 'success') {
                this.displaySingleResult(result.prediction, result.transaction_id);
                // Refresh insights and history
                this.loadInsights();
                this.loadAlerts();
                this.loadPerformance();
                this.loadPredictionHistory();
                this.showSuccess('Prediction saved to history. Charts updated.');
                // Switch to Results tab
                this.switchToResultsTab();
            } else {
                this.showError('Prediction failed: ' + (result.error || result.details || 'Unknown error'));
            }

        } catch (error) {
            this.showError('Network error: ' + error.message);
        } finally {
            // Reset loading state
            submitBtn.disabled = false;
            spinner.classList.add('d-none');
            this.isLoading = false;
        }
    }

    async handleBatchPrediction(e) {
        e.preventDefault();
        
        if (this.isLoading) return;
        this.isLoading = true;

        const form = e.target;
        const submitBtn = document.getElementById('batchPredictBtn');
        const spinner = submitBtn.querySelector('.spinner-border');
        const resultDiv = document.getElementById('batchResult');
        const fileInput = document.getElementById('batchFile');
        
        if (!fileInput.files[0]) {
            this.showError('Please select a file');
            this.isLoading = false;
            return;
        }

        // Validate CSV columns (client-side) for required features
        const file = fileInput.files[0];
        const ext = (file.name.split('.').pop() || '').toLowerCase();
        if (ext === 'csv') {
            try {
                const { ok, missing } = await this.validateCsvRequiredColumns(file);
                if (!ok) {
                    this.showError(`The uploaded file must contain at least these columns: customer_id, account_age_days, transaction_amount, channel, kyc_verified. Missing: ${missing.join(', ')}`);
                    // Reveal a friendly message under the file preview as well
                    const valDiv = document.getElementById('fileValidation') || null;
                    if (valDiv) {
                        valDiv.classList.remove('d-none');
                        valDiv.innerHTML = `<div class="alert alert-warning border"><i class="bi bi-exclamation-triangle me-2"></i>Missing required columns: <strong>${missing.join(', ')}</strong>. Please upload a CSV that includes: <code>customer_id, account_age_days, transaction_amount, channel, kyc_verified</code>.</div>`;
                    }
                    this.isLoading = false;
                    submitBtn.disabled = false;
                    spinner.classList.add('d-none');
                    return;
                }
            } catch(err) {
                // If parsing fails, continue but warn the user
                console.warn('CSV validation failed', err);
            }
        }

        // Show loading state
        submitBtn.disabled = true;
        spinner.classList.remove('d-none');
        resultDiv.classList.add('d-none');

        try {
            const formData = new FormData();
            formData.append('file', fileInput.files[0]);

            const response = await fetch('/api/upload', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: formData
            });

            const result = await response.json();

            if (response.ok && result.status === 'success') {
                this.displayBatchResult(result);
                this.batchResults = result.results; // Store for download
                // Refresh insights, performance and history
                this.loadInsights();
                this.loadPerformance();
                this.loadPredictionHistory();
                this.showSuccess('Batch processed. Charts and history updated.');
                // Switch to Results tab
                this.switchToResultsTab();
            } else {
                this.showError('Batch prediction failed: ' + (result.error || result.details || 'Unknown error'));
            }

        } catch (error) {
            this.showError('Network error: ' + error.message);
        } finally {
            // Reset loading state
            submitBtn.disabled = false;
            spinner.classList.add('d-none');
            this.isLoading = false;
        }
    }

    displaySingleResult(prediction, txnId) {
        const resultDiv = document.getElementById('singleResult');
        const detailsDiv = document.getElementById('predictionDetails');
        
        const riskClass = this.getRiskClass(prediction.risk_level);
        const fraudStatus = prediction.prediction === 1 ? 'FRAUDULENT' : 'LEGITIMATE';
        const fraudClass = prediction.prediction === 1 ? 'text-danger' : 'text-success';
        
        detailsDiv.innerHTML = `
            <div class="row g-3 mb-3">
                <div class="col-md-6">
                    <div class="p-4 border-2 rounded bg-white" style="border: 2px solid ${prediction.prediction === 1 ? '#EF4444' : '#10B981'} !important;">
                        <small class="text-muted d-block mb-2 text-uppercase" style="font-size: 11px; letter-spacing: 0.5px;">Status</small>
                        <h4 class="mb-0 ${fraudClass} fw-bold">${fraudStatus}</h4>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="p-4 border-2 rounded bg-white" style="border: 2px solid #FF6B01 !important;">
                        <small class="text-muted d-block mb-2 text-uppercase" style="font-size: 11px; letter-spacing: 0.5px;">Risk Level</small>
                        <h4 class="mb-0 fw-bold" style="color: #FF6B01;">${prediction.risk_level}</h4>
                    </div>
                </div>
            </div>
            <div class="row g-3 mb-4">
                <div class="col-md-4">
                    <div class="p-3 border-2 rounded bg-white" style="border: 2px solid #e5e7eb !important;">
                        <small class="text-muted d-block mb-2 text-uppercase" style="font-size: 11px;">Combined Risk</small>
                        <h5 class="mb-0 fw-bold" style="color: #FF6B01;">${(((prediction.risk_score ?? prediction.fraud_probability) * 100)).toFixed(2)}%</h5>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="p-3 border-2 rounded bg-white" style="border: 2px solid #e5e7eb !important;">
                        <small class="text-muted d-block mb-2 text-uppercase" style="font-size: 11px;">Model Probability</small>
                        <h5 class="mb-0 fw-bold" style="color: #3B82F6;">${(((prediction.model_fraud_probability ?? prediction.fraud_probability) * 100)).toFixed(2)}%</h5>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="p-3 border-2 rounded bg-white" style="border: 2px solid #e5e7eb !important;">
                        <small class="text-muted d-block mb-2 text-uppercase" style="font-size: 11px;">Decision Threshold</small>
                        <h5 class="mb-0 fw-bold" style="color: #6b7280;">${(((prediction.decision_threshold ?? 0.5) * 100)).toFixed(0)}%</h5>
                    </div>
                </div>
            </div>
            <div class="card bg-white border-2 mb-4" style="border: 2px solid #e5e7eb !important;">
                <div class="card-body">
                    <h6 class="fw-bold mb-2" style="color: #1f2937;">Reason/Rules</h6>
                    <p class="mb-2 text-muted">${prediction.reason || (Array.isArray(prediction.rules_triggered) ? prediction.rules_triggered.join(', ') : 'ML prediction')}</p>
                    ${txnId ? `<small class="text-muted"><strong>Transaction ID:</strong> <code>${txnId}</code></small>` : ''}
                </div>
            </div>
            <div class="mb-4">
                <h6 class="fw-bold mb-3" style="color: #1f2937;">Risk Score Visualization</h6>
                <div class="progress" style="height: 30px; border-radius: 8px; background-color: #f3f4f6;">
                    <div class="progress-bar" 
                         style="width: ${(((prediction.risk_score ?? prediction.fraud_probability) * 100)).toFixed(0)}%; background-color: ${prediction.prediction === 1 ? '#EF4444' : '#10B981'};">
                        <span class="fw-bold">${(((prediction.risk_score ?? prediction.fraud_probability) * 100)).toFixed(0)}%</span>
                    </div>
                </div>
                <small class="text-muted mt-2 d-block">Decision Threshold: ${(((prediction.decision_threshold ?? 0.5) * 100)).toFixed(0)}%</small>
            </div>
            <div class="d-flex gap-2 mb-4">
                ${txnId ? `<a class="btn btn-sm px-4" style="background-color: #FF6B01; border-color: #FF6B01; color: white;" href="/api/prediction/${txnId}/report" target="_blank"><i class="bi bi-download me-2"></i> Download Report</a>` : ''}
            </div>
            <div class="card bg-white border-2" style="border: 2px solid #e5e7eb !important;">
                <div class="card-body">
                    <h6 class="fw-bold mb-3" style="color: #1f2937;"><i class="bi bi-bar-chart-fill me-2" style="color: #FF6B01;"></i>Top Contributing Factors</h6>
                    <div style="height:240px"><canvas id="explainChart"></canvas></div>
                </div>
            </div>
        `;
        
        // Hide empty state and show results
        const emptyState = document.getElementById('singleResultEmpty');
        if (emptyState) emptyState.style.display = 'none';
        resultDiv.classList.remove('d-none');

        // Render explanation if available
        try {
            const exp = prediction.explanation || { top_contributors: [] };
            const top = Array.isArray(exp.top_contributors) ? exp.top_contributors.slice(0,5) : [];
            const labels = top.map(t => t.feature);
            const values = top.map(t => Number(t.contribution));
            const colors = top.map(t => (t.direction === 'fraud' ? '#dc2626' : '#16a34a'));
            const ctx = document.getElementById('explainChart')?.getContext('2d');
            if (ctx && typeof Chart !== 'undefined' && labels.length) {
                this._upsertChart('explain', ctx, {
                    type: 'bar',
                    data: { labels, datasets: [{ label: 'Contribution', data: values, backgroundColor: colors }] },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        indexAxis: 'y',
                        plugins: { legend: { display: false } },
                        scales: { x: { ticks: { callback: v => v } } }
                    }
                });
            }
        } catch (e) {
            console.warn('Explanation render failed', e);
        }
    }

    displayBatchResult(result) {
        const resultDiv = document.getElementById('batchResult');
        const summaryDiv = document.getElementById('batchSummary');
        
        const summary = result.summary;
        
        summaryDiv.innerHTML = `
            <div class="row g-3">
                <div class="col-md-3">
                    <div class="p-3 border rounded text-center bg-light">
                        <i class="bi bi-files display-6 text-primary mb-2"></i>
                        <h3 class="mb-1">${summary.total_transactions}</h3>
                        <small class="text-muted">Total Processed</small>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="p-3 border rounded text-center bg-light">
                        <i class="bi bi-exclamation-triangle display-6 text-danger mb-2"></i>
                        <h3 class="text-danger mb-1">${summary.fraud_detected}</h3>
                        <small class="text-muted">Fraud Detected</small>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="p-3 border rounded text-center bg-light">
                        <i class="bi bi-check-circle display-6 text-success mb-2"></i>
                        <h3 class="text-success mb-1">${summary.legitimate_transactions}</h3>
                        <small class="text-muted">Legitimate</small>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="p-3 border rounded text-center bg-light">
                        <i class="bi bi-graph-up display-6 text-warning mb-2"></i>
                        <h3 class="mb-1">${summary.fraud_rate.toFixed(1)}%</h3>
                        <small class="text-muted">Fraud Rate</small>
                    </div>
                </div>
            </div>
            ${summary.errors > 0 ? `<div class="alert alert-warning border mt-3">
                <i class="bi bi-exclamation-triangle me-2"></i> 
                <strong>Note:</strong> ${summary.errors} transaction${summary.errors > 1 ? 's' : ''} had processing errors.
            </div>` : ''}
        `;
        
        resultDiv.classList.remove('d-none');
    }

    handleFileSelect(e) {
        const file = e.target.files[0];
        const previewDiv = document.getElementById('filePreview');
        
        if (file) {
            document.getElementById('fileName').textContent = file.name;
            document.getElementById('fileSize').textContent = this.formatFileSize(file.size);
            previewDiv.classList.remove('d-none');
        } else {
            previewDiv.classList.add('d-none');
        }
    }

    async loadPredictionHistory(page = 1) {
        try {
            let url = `/api/transactions?page=${page}&page_size=${this.historyPageSize}&sort=recent`;
            if (this.historyFilter === 'fraud') {
                url += '&prediction=1';
            } else if (this.historyFilter === 'legit') {
                url += '&prediction=0';
            }
            const response = await fetch(url);
            const result = await response.json();
            if (response.ok && result.status === 'success') {
                this.historyPage = Number(result.page || page) || 1;
                this.historyTotal = Number(result.total || 0);
                this.displayPredictionHistory(result.items || []);
                this.updateHistoryPager();
            }
        } catch (error) {
            console.error('Error loading prediction history:', error);
        }
    }

    updateHistoryPager() {
        const info = document.getElementById('historyPageInfo');
        const btnPrev = document.getElementById('historyPrev');
        const btnNext = document.getElementById('historyNext');
        const totalPages = Math.max(1, Math.ceil(this.historyTotal / this.historyPageSize));
        if (info) info.textContent = `Page ${this.historyPage} of ${totalPages}`;
        if (btnPrev) btnPrev.disabled = this.historyPage <= 1;
        if (btnNext) btnNext.disabled = this.historyPage >= totalPages;
    }

    displayPredictionHistory(predictions) {
        const container = document.getElementById('predictionHistory');
        if (!container) return;
        
        if (predictions.length === 0) {
            container.innerHTML = '<div class="text-center text-muted py-4">No prediction history yet</div>';
            return;
        }
        
        // Ensure newest first as a fallback if API doesn't sort
        predictions.sort((a,b) => new Date(b.timestamp || b.created_at || 0) - new Date(a.timestamp || a.created_at || 0));

        let html = '<div class="list-group">';
        predictions.forEach(pred => {
            const date = new Date(pred.timestamp || pred.created_at || Date.now()).toLocaleString();
            const type = pred.prediction === 1 ? 'Fraud' : 'Legit';
            const icon = pred.prediction === 1 ? 'bi-exclamation-triangle' : 'bi-shield-check';
            const sideCls = pred.prediction === 1 ? 'pred-fraud' : 'pred-legit';
            
            html += `
                <div class="list-group-item pred-item ${sideCls} d-flex justify-content-between align-items-center">
                    <div class="d-flex align-items-start">
                        <input class="form-check-input me-3 mt-1" type="checkbox" data-hist="${pred._id}" />
                        <div>
                            <div class="d-flex align-items-center mb-1">
                                <i class="bi ${icon} me-2"></i>
                                <strong class="me-2">${type}</strong>
                                <span class="pred-chip ${type === 'Fraud' ? 'chip-fraud' : 'chip-legit'}">${pred.risk_level || 'UNKNOWN'}</span>
                            </div>
                            <small class="text-muted">${date}</small>
                        </div>
                    </div>
                    <div class="d-flex align-items-center">
                        <a href="/prediction/${pred._id}/" class="btn btn-sm btn-outline-warning me-2" style="border-color:#FF6B01;color:#FF6B01;">View</a>
                        <button class="btn btn-sm btn-outline-danger" data-del="${pred._id}">Delete</button>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        
        container.innerHTML = html;

        // Bind delete buttons
        container.querySelectorAll('button[data-del]').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = e.currentTarget.getAttribute('data-del');
                if (!id) return;
                if (!confirm('Delete this record?')) return;
                try {
                    const res = await fetch(`/api/transactions/${id}/delete`, {
                        method: 'POST',
                        headers: { 'X-CSRFToken': this.getCSRFToken() },
                        credentials: 'same-origin'
                    });
                    if (!res.ok) throw new Error('Delete failed');
                    this.loadPredictionHistory(this.historyPage);
                    this.loadInsights();
                } catch (err) {
                    this.showError('Delete failed');
                }
            });
        });

        // Bind selection checkboxes
        container.querySelectorAll('input[type="checkbox"][data-hist]').forEach(cb => {
            cb.addEventListener('change', (e) => {
                const id = e.currentTarget.getAttribute('data-hist');
                this.toggleSelect(id, e.currentTarget.checked);
                this.updateBulkBtnState();
            });
        });
        this.updateBulkBtnState();
    }

    async loadModelStats() {
        try {
            const response = await fetch('/api/performance?force=1', { credentials: 'same-origin' });
            const ct = response.headers.get('content-type') || '';
            if (!response.ok || ct.indexOf('application/json') === -1) {
                // Likely redirected to login or error HTML
                const modelInfoDiv = document.getElementById('modelInfo');
                if (modelInfoDiv) modelInfoDiv.innerHTML = '<div class="text-center text-muted py-3">Failed to load model info.</div>';
                const userStatsDiv = document.getElementById('userStats');
                if (userStatsDiv) userStatsDiv.innerHTML = '<div class="text-center text-muted py-3">Failed to load activity stats.</div>';
                return;
            }
            const result = await response.json();
            
            if (response.ok && result.status === 'success') {
                // Remove spinners and render content
                const modelInfoDiv = document.getElementById('modelInfo');
                const userStatsDiv = document.getElementById('userStats');
                if (modelInfoDiv) {
                    const spinBlock = modelInfoDiv.querySelector('.spinner-border')?.parentElement;
                    if (spinBlock && spinBlock.parentElement) {
                        spinBlock.parentElement.removeChild(spinBlock);
                    }
                }
                if (userStatsDiv) {
                    const spinBlock = userStatsDiv.querySelector('.spinner-border')?.parentElement;
                    if (spinBlock && spinBlock.parentElement) {
                        spinBlock.parentElement.removeChild(spinBlock);
                    }
                }
                this.updateModelStatsDisplay(result);
            } else {
                // Production-ready empty states
                const modelInfoDiv = document.getElementById('modelInfo');
                if (modelInfoDiv) {
                    modelInfoDiv.innerHTML = `
                        <div class="text-center text-muted py-4">
                            <i class="bi bi-cpu display-4 mb-3 d-block"></i>
                            <h6>Model Loading</h6>
                            <p class="small mb-0">Please ensure your gradient boosting model is properly loaded.</p>
                        </div>
                    `;
                }
                const userStatsDiv = document.getElementById('userStats');
                if (userStatsDiv) {
                    userStatsDiv.innerHTML = `
                        <div class="text-center text-muted py-4">
                            <i class="bi bi-graph-up display-4 mb-3 d-block"></i>
                            <h6>No Predictions Yet</h6>
                            <p class="small mb-0">Start making predictions to see your activity summary here.</p>
                        </div>
                    `;
                }
            }
        } catch (error) {
            console.error('Error loading model stats:', error);
            const modelInfoDiv = document.getElementById('modelInfo');
            if (modelInfoDiv) {
                modelInfoDiv.innerHTML = '<div class="text-center text-muted py-3">Failed to load model info.</div>';
            }
            const userStatsDiv = document.getElementById('userStats');
            if (userStatsDiv) {
                userStatsDiv.innerHTML = '<div class="text-center text-muted py-3">Failed to load activity stats.</div>';
            }
        }
    }

    async loadPerformance() {
        try {
            const res = await fetch('/api/performance?force=1', { credentials: 'include' });
            const perfContainer = document.getElementById('performanceMetrics');
            const ct = res.headers.get('content-type') || '';
            if (!res.ok || ct.indexOf('application/json') === -1) {
                if (perfContainer) {
                    perfContainer.innerHTML = '<div class="text-center text-muted py-3">Failed to load performance metrics. Please sign in and retry.</div>';
                }
                return;
            }
            const j = await res.json();
            if (res.ok && j.status === 'success') {
                // Remove the initial loading spinner in the performance card if present
                if (perfContainer) {
                    const spinBlock = perfContainer.querySelector('.spinner-border')?.parentElement;
                    if (spinBlock && spinBlock.parentElement) {
                        spinBlock.parentElement.removeChild(spinBlock);
                    }
                }
                // Append observed metrics into modelInfo/userStats blocks
                const modelInfoDiv = document.getElementById('modelInfo');
                if (modelInfoDiv) {
                    const observed = j.observed || { total_predictions: 0, predicted_fraud_rate: 0, avg_confidence: 0 };
                    const extra = document.createElement('div');
                    extra.className = 'mt-3';
                    extra.innerHTML = `
                        <div class="row text-center">
                            <div class="col">
                                <h6>${observed.predicted_fraud_rate.toFixed(1)}%</h6>
                                <small>Predicted Fraud Rate</small>
                            </div>
                            <div class="col">
                                <h6>${(observed.avg_confidence * 100).toFixed(1)}%</h6>
                                <small>Avg Confidence</small>
                            </div>
                            <div class="col">
                                <h6>${observed.total_predictions}</h6>
                                <small>Total Predictions</small>
                            </div>
                        </div>`;
                    // Avoid duplicating on repeated calls
                    const prev = modelInfoDiv.querySelector('.mt-3');
                    if (prev) prev.remove();
                    modelInfoDiv.appendChild(extra);
                }

                // Performance metrics card (optional)
                const perfDiv = document.getElementById('performanceMetrics');
                if (perfDiv) {
                    const m = (j.metrics && j.metrics.metrics) || {};
                    const acc = Number(m.accuracy || 0);
                    const prec = Number(m.precision || 0);
                    const rec = Number(m.recall || 0);
                    const f1 = Number(m.f1 || 0);
                    const spec = Number(m.specificity || 0);
                    const auc = Number(m.auc || 0);
                    const perfTable = document.getElementById('perfTable');
                    if (perfTable) {
                        perfTable.innerHTML = `
                            <table class="table table-sm">
                                <tbody>
                                    <tr><th>Accuracy</th><td>${(acc*100).toFixed(2)}%</td></tr>
                                    <tr><th>Precision</th><td>${(prec*100).toFixed(2)}%</td></tr>
                                    <tr><th>Recall</th><td>${(rec*100).toFixed(2)}%</td></tr>
                                    <tr><th>F1-Score</th><td>${(f1*100).toFixed(2)}%</td></tr>
                                    <tr><th>Specificity</th><td>${(spec*100).toFixed(2)}%</td></tr>
                                    <tr><th>AUC</th><td>${(auc*100).toFixed(2)}%</td></tr>
                                </tbody>
                            </table>`;
                    }

                    // Confusion matrix
                    const cmDiv = document.getElementById('confMatrixTable');
                    const cm = j.confusion_matrix || (j.metrics && j.metrics.confusion_matrix) || null;
                    if (cmDiv) {
                        if (cm && Array.isArray(cm) && cm.length === 2 && cm[0].length === 2) {
                            const tn = cm[0][0], fp = cm[0][1], fn = cm[1][0], tp = cm[1][1];
                            cmDiv.innerHTML = `
                                <table class="table table-bordered table-sm text-center mb-0">
                                    <thead>
                                        <tr><th></th><th colspan="2">Predicted</th></tr>
                                        <tr><th>Actual</th><th>Neg</th><th>Pos</th></tr>
                                    </thead>
                                    <tbody>
                                        <tr><th>Neg</th><td>${tn}</td><td>${fp}</td></tr>
                                        <tr><th>Pos</th><td>${fn}</td><td>${tp}</td></tr>
                                    </tbody>
                                </table>`;
                        } else {
                            cmDiv.innerHTML = '<div class="text-muted">No confusion matrix</div>';
                        }
                    }

                    // ROC curve
                    const roc = j.roc_curve || (j.metrics && j.metrics.roc_curve) || null;
                    const rocCtx = document.getElementById('rocCurveChart')?.getContext('2d');
                    if (rocCtx && roc && roc.fpr && roc.tpr) {
                        const fpr = roc.fpr.map(Number);
                        const tpr = roc.tpr.map(Number);
                        this._upsertChart('roc', rocCtx, {
                            type: 'line',
                            data: {
                                labels: fpr,
                                datasets: [
                                    { label: 'ROC', data: tpr, borderColor: '#2563eb', backgroundColor: 'rgba(37,99,235,0.1)', fill: false },
                                    { label: 'Baseline', data: fpr, borderColor: '#9ca3af', borderDash: [5,5], fill: false }
                                ]
                            },
                            options: {
                                responsive: true, maintainAspectRatio: false,
                                scales: {
                                    x: { type: 'linear', min: 0, max: 1, title: { display: true, text: 'False Positive Rate' } },
                                    y: { min: 0, max: 1, title: { display: true, text: 'True Positive Rate' } }
                                },
                                plugins: { legend: { display: false } }
                            }
                        });
                    }
                }

                // Feature importance chart (Key Fraud Indicators)
                const fi = Array.isArray(j.feature_importance) ? j.feature_importance : [];
                const fic = document.getElementById('featImpChart');
                if (fic && typeof Chart !== 'undefined' && fi.length > 0) {
                    const labels = fi.slice(0, 10).map(x => x.feature); // Top 10 features
                    const values = fi.slice(0, 10).map(x => x.importance);
                    const ctx = fic.getContext('2d');
                    this._upsertChart('featImp', ctx, {
                        type: 'bar',
                        data: { labels, datasets: [{ label: 'Importance', data: values, backgroundColor: '#2563eb' }] },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            scales: { y: { beginAtZero: true } },
                            plugins: { legend: { display: false } }
                        }
                    });
                }
            } else {
                // Graceful fallback: clear spinner and show empty state if API failed
                const perfDiv = document.getElementById('performanceMetrics');
                if (perfDiv) {
                    perfDiv.innerHTML = '<div class="text-center text-muted py-3">No performance metrics available.</div>';
                }
            }
        } catch (e) {
            console.error('Error loading performance:', e);
            const perfDiv = document.getElementById('performanceMetrics');
            if (perfDiv) {
                perfDiv.innerHTML = '<div class="text-center text-muted py-3">Failed to load performance metrics.</div>';
            }
        }
    }

    async loadInsights() {
        try {
            const res = await fetch('/api/analytics', { credentials: 'same-origin' });
            const j = await res.json();
            console.log('Analytics API response:', j); // Debug log
            if (!(res.ok && j.status === 'success')) {
                console.error('Analytics API failed:', j);
                this.showEmptyAnalyticsCharts();
                return;
            }
            const ins = j.insights || {};
            console.log('Insights data:', ins); // Debug log

            // Class distribution
            const fraud = (ins.class_distribution && ins.class_distribution.fraud) || 0;
            const legit = (ins.class_distribution && ins.class_distribution.legitimate) || 0;
            const classCtx = document.getElementById('classChart')?.getContext('2d');
            if (classCtx && typeof Chart !== 'undefined') {
                this._upsertChart('class', classCtx, {
                    type: 'bar',
                    data: {
                        labels: ['Fraud', 'Legit'],
                        datasets: [{ label: 'Count', data: [fraud, legit], backgroundColor: ['#EF4444', '#10B981'] }]
                    },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
                });
            }

            // Risk levels bar
            const order = ['VERY_LOW', 'LOW', 'MEDIUM', 'HIGH', 'VERY_HIGH'];
            const riskCounts = order.map(k => (ins.risk_levels && ins.risk_levels[k]) || 0);
            const riskCtx = document.getElementById('riskChart')?.getContext('2d');
            if (riskCtx && typeof Chart !== 'undefined') {
                this._upsertChart('risk', riskCtx, {
                    type: 'bar',
                    data: {
                        labels: order,
                        datasets: [{
                            label: 'Count',
                            data: riskCounts,
                            backgroundColor: '#FF6B01'
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: { y: { beginAtZero: true } },
                        plugins: { legend: { display: false } }
                    }
                });
            }

            // Timeline line chart (Predictions over time)
            const series = Array.isArray(ins.over_time) ? ins.over_time : [];
            const labels = series.map(s => s.date);
            const values = series.map(s => s.count);
            const tCtx = document.getElementById('timelineChart')?.getContext('2d');
            if (tCtx && typeof Chart !== 'undefined') {
                this._upsertChart('timeline', tCtx, {
                    type: 'line',
                    data: {
                        labels,
                        datasets: [{
                            label: 'Predictions',
                            data: values,
                            borderColor: '#FF6B01',
                            backgroundColor: 'rgba(255,107,1,0.15)',
                            tension: 0.3,
                            fill: true
                        }]
                    },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
                });
            }

            // Fraud % over time
            const frSeries = Array.isArray(ins.fraud_rate_over_time) ? ins.fraud_rate_over_time : [];
            const frLabels = frSeries.map(s => s.date);
            const frValues = frSeries.map(s => Number(s.fraud_pct || 0));
            const frCtx = document.getElementById('fraudRateChart')?.getContext('2d');
            if (frCtx && typeof Chart !== 'undefined') {
                this._upsertChart('fraudRate', frCtx, {
                    type: 'line',
                    data: { labels: frLabels, datasets: [{ label: 'Fraud %', data: frValues, borderColor: '#8b5cf6', backgroundColor: 'rgba(139,92,246,0.15)', tension: 0.3, fill: true }] },
                    options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, max: 100 } }, plugins: { legend: { display: false } } }
                });
            }

            // Channel-wise fraud distribution (pie)
            const ch = ins.channel_fraud || {};
            const chLabels = Object.keys(ch);
            const chValues = chLabels.map(k => Number(ch[k] || 0));
            const chCtx = document.getElementById('channelFraudChart')?.getContext('2d');
            if (chCtx && typeof Chart !== 'undefined') {
                const colors = ['#ef4444','#3b82f6','#10b981','#f59e0b','#6366f1','#14b8a6','#f97316','#22c55e'];
                this._upsertChart('channelFraud', chCtx, {
                    type: 'pie',
                    data: { labels: chLabels.length ? chLabels : ['No Data'], datasets: [{ data: chValues.length ? chValues : [1], backgroundColor: colors }] },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
                });
            }

            // Amount vs Fraud scatter
            const pts = Array.isArray(ins.amount_vs_fraud) ? ins.amount_vs_fraud : [];
            const fraudPts = pts.filter(p => Number(p.y) === 1).map(p => ({ x: Number(p.x), y: 1 }));
            const legitPts = pts.filter(p => Number(p.y) === 0).map(p => ({ x: Number(p.x), y: 0 }));
            const amCtx = document.getElementById('amountScatterChart')?.getContext('2d');
            if (amCtx && typeof Chart !== 'undefined') {
                this._upsertChart('amountScatter', amCtx, {
                    type: 'scatter',
                    data: {
                        datasets: [
                            { label: 'Fraud', data: fraudPts, borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,0.5)' },
                            { label: 'Legit', data: legitPts, borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.5)' }
                        ]
                    },
                    options: {
                        responsive: true, maintainAspectRatio: false,
                        scales: {
                            x: { type: 'linear', title: { display: true, text: 'Transaction Amount' } },
                            y: { min: -0.25, max: 1.25, ticks: { stepSize: 1, callback: v => v === 1 ? 'Fraud' : (v === 0 ? 'Legit' : '') } }
                        }
                    }
                });
            }
        } catch (e) {
            console.error('Error loading insights:', e);
            this.showEmptyAnalyticsCharts();
        }
        
        // Also load feature importance for Key Fraud Indicators
        this.loadFeatureImportance();
    }
    
    async loadFeatureImportance() {
        try {
            const res = await fetch('/api/performance?force=1', { credentials: 'same-origin' });
            const ct = res.headers.get('content-type') || '';
            if (!res.ok || ct.indexOf('application/json') === -1) return;
            const j = await res.json();
            if (res.ok && j.status === 'success') {
                const fi = Array.isArray(j.feature_importance) ? j.feature_importance : [];
                const fic = document.getElementById('featImpChart');
                if (fic && typeof Chart !== 'undefined' && fi.length > 0) {
                    const labels = fi.slice(0, 10).map(x => x.feature);
                    const values = fi.slice(0, 10).map(x => x.importance);
                    const ctx = fic.getContext('2d');
                    this._upsertChart('featImp', ctx, {
                        type: 'bar',
                        data: { 
                            labels, 
                            datasets: [{ 
                                label: 'Importance', 
                                data: values, 
                                backgroundColor: '#ff6b01',
                                borderColor: '#ff6b01',
                                borderWidth: 1
                            }] 
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            scales: { 
                                y: { beginAtZero: true },
                                x: { ticks: { maxRotation: 45 } }
                            },
                            plugins: { 
                                legend: { display: false },
                                title: {
                                    display: true,
                                    text: 'Top 10 Features Driving Fraud Detection'
                                }
                            }
                        }
                    });
                } else if (fic) {
                    // Show empty state
                    const ctx = fic.getContext('2d');
                    this._upsertChart('featImp', ctx, {
                        type: 'bar',
                        data: {
                            labels: ['No Data'],
                            datasets: [{
                                label: 'No Data',
                                data: [0],
                                backgroundColor: '#e5e7eb'
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: { display: false },
                                title: {
                                    display: true,
                                    text: 'Feature importance will appear after model training'
                                }
                            }
                        }
                    });
                }
            }
        } catch (e) {
            console.error('Error loading feature importance:', e);
        }
    }

    showEmptyAnalyticsCharts() {
        // Show empty states for all analytics charts
        const chartIds = ['classChart', 'riskChart', 'timelineChart', 'fraudRateChart', 'channelFraudChart', 'amountScatterChart'];
        chartIds.forEach(id => {
            const canvas = document.getElementById(id);
            if (canvas) {
                const ctx = canvas.getContext('2d');
                if (ctx && typeof Chart !== 'undefined') {
                    this._upsertChart(id, ctx, {
                        type: 'bar',
                        data: {
                            labels: ['No Data'],
                            datasets: [{
                                label: 'No Data Available',
                                data: [0],
                                backgroundColor: '#e5e7eb'
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: { display: false },
                                title: {
                                    display: true,
                                    text: 'No predictions yet - start making predictions to see analytics'
                                }
                            },
                            scales: { y: { beginAtZero: true, max: 1 } }
                        }
                    });
                }
            }
        });
    }

    async loadAlerts() {
        try {
            const res = await fetch('/api/alerts?active=1');
            const j = await res.json();
            if (!(res.ok && j.status === 'success')) return;
            const items = j.alerts || [];
            const counts = { CRITICAL: 0, HIGH: 0, OTHER: 0 };
            items.forEach(a => {
                const s = (a.severity || 'OTHER').toUpperCase();
                if (s === 'CRITICAL') counts.CRITICAL++; else if (s === 'HIGH') counts.HIGH++; else counts.OTHER++;
            });

            const ctx = document.getElementById('alertsChart')?.getContext('2d');
            if (ctx && typeof Chart !== 'undefined') {
                this._upsertChart('alerts', ctx, {
                    type: 'doughnut',
                    data: {
                        labels: ['Critical', 'High', 'Other'],
                        datasets: [{ data: [counts.CRITICAL, counts.HIGH, counts.OTHER], backgroundColor: ['#dc2626','#f59e0b','#6b7280'] }]
                    },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
                });
            }
        } catch (e) {
            console.error('Error loading alerts:', e);
        }
    }

    _upsertChart(name, ctx, config) {
        try {
            if (this.charts[name]) {
                this.charts[name].destroy();
            }
            this.charts[name] = new Chart(ctx, config);
        } catch (e) {
            console.error('Chart render error', name, e);
        }
    }

    updateModelStatsDisplay(data) {
        const modelInfo = data.model_info;
        const userStats = data.user_stats;
        
        // Update model info display
        const modelInfoDiv = document.getElementById('modelInfo');
        if (modelInfoDiv) {
            const featureCount = Number.isFinite(modelInfo.feature_count) ? modelInfo.feature_count : 0;
            const trainFraudRate = Number.isFinite(modelInfo.fraud_rate) ? (modelInfo.fraud_rate * 100).toFixed(1) : '0.0';
            const modelType = modelInfo.model_type || 'Unknown';
            modelInfoDiv.innerHTML = `
                <div class="row text-center">
                    <div class="col">
                        <h5>${featureCount}</h5>
                        <small>Features</small>
                    </div>
                    <div class="col">
                        <h5>${trainFraudRate}%</h5>
                        <small>Training Fraud Rate</small>
                    </div>
                    <div class="col">
                        <h5>${modelType}</h5>
                        <small>Algorithm</small>
                    </div>
                </div>
            `;
        }
        
        // Update user stats
        const userStatsDiv = document.getElementById('userStats');
        if (userStatsDiv) {
            if (!userStats || userStats.total_predictions === 0) {
                userStatsDiv.innerHTML = `
                    <div class="text-center text-muted py-4">
                        <i class="bi bi-graph-up display-4 mb-3 d-block"></i>
                        <h6>No Predictions Yet</h6>
                        <p class="small mb-0">Use the Prediction Widget below to start making fraud predictions.</p>
                        <a href="#predictionWidget" class="btn btn-sm btn-outline-primary mt-2">
                            <i class="bi bi-arrow-down"></i> Start Predicting
                        </a>
                    </div>
                `;
            } else {
                userStatsDiv.innerHTML = `
                    <div class="row text-center">
                        <div class="col">
                            <h4>${userStats.total_predictions}</h4>
                            <small>Total Predictions</small>
                        </div>
                        <div class="col">
                            <h4>${userStats.single_predictions}</h4>
                            <small>Real-time</small>
                        </div>
                        <div class="col">
                            <h4>${userStats.batch_predictions}</h4>
                            <small>Batch Upload</small>
                        </div>
                    </div>
                `;
            }
        }
    }

    async refreshDashboardStats() {
        try {
            const response = await fetch('/api/dashboard-stats/');
            if (response.ok) {
                const stats = await response.json();
                this.updateDashboardStats(stats);
            }
        } catch (error) {
            console.error('Error refreshing stats:', error);
        }
    }

    updateDashboardStats(stats) {
        // Update stats cards if they exist
        const elements = {
            'totalUploads': stats.total_files,
            'totalPredictions': stats.total_predictions,
            'fraudCount': stats.fraud_count
        };
        
        Object.keys(elements).forEach(id => {
            const element = document.getElementById(id);
            if (element) {
                element.textContent = elements[id];
            }
        });
    }

    downloadResults() {
        if (!this.batchResults) return;
        
        const csv = this.convertToCSV(this.batchResults);
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = window.URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = `fraud_predictions_${new Date().toISOString().split('T')[0]}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    }

    convertToCSV(data) {
        if (!data || data.length === 0) return '';
        
        const headers = Object.keys(data[0]);
        const csvContent = [
            headers.join(','),
            ...data.map(row => headers.map(header => {
                const value = row[header];
                return typeof value === 'string' ? `"${value}"` : value;
            }).join(','))
        ].join('\n');
        
        return csvContent;
    }

    async downloadUrl(url, filename) {
        try {
            console.log('Downloading:', url);
            const res = await fetch(url, { 
                headers: { 'X-CSRFToken': this.getCSRFToken() },
                credentials: 'same-origin'
            });
            console.log('Response status:', res.status);
            if (!res.ok) {
                const text = await res.text();
                console.error('Download failed:', text);
                this.showError(`Download failed: ${res.status} ${res.statusText}`);
                return;
            }
            const blob = await res.blob();
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(() => URL.revokeObjectURL(a.href), 1000);
            this.showSuccess('Download started');
        } catch (e) {
            console.error('Download error:', e);
            this.showError('Download error: ' + e.message);
        }
    }

    today() {
        return new Date().toISOString().split('T')[0];
    }

    getRiskClass(riskLevel) {
        const riskClasses = {
            'VERY_HIGH': 'text-danger fw-bold',
            'HIGH': 'text-danger',
            'MEDIUM': 'text-warning',
            'LOW': 'text-success',
            'VERY_LOW': 'text-success fw-light'
        };
        return riskClasses[riskLevel] || 'text-muted';
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    getCSRFToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
               document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
    }

    showError(message) {
        // Create or update error alert
        let alertDiv = document.getElementById('errorAlert');
        if (!alertDiv) {
            alertDiv = document.createElement('div');
            alertDiv.id = 'errorAlert';
            alertDiv.className = 'alert alert-danger alert-dismissible fade show position-fixed';
            alertDiv.style.cssText = 'top: 20px; right: 20px; z-index: 1050; max-width: 400px;';
            document.body.appendChild(alertDiv);
        }
        
        alertDiv.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (alertDiv && alertDiv.parentNode) {
                alertDiv.remove();
            }
        }, 5000);
    }

    showSuccess(message) {
        // Similar to showError but with success styling
        let alertDiv = document.createElement('div');
        alertDiv.className = 'alert alert-success alert-dismissible fade show position-fixed';
        alertDiv.style.cssText = 'top: 20px; right: 20px; z-index: 1050; max-width: 400px;';
        alertDiv.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        document.body.appendChild(alertDiv);
        
        setTimeout(() => {
            if (alertDiv && alertDiv.parentNode) {
                alertDiv.remove();
            }
        }, 3000);
    }
}

// Initialize the predictor when DOM is loaded
let predictor;
document.addEventListener('DOMContentLoaded', function() {
    predictor = new TransactionPredictor();
    // Export for global access (used by inline handlers)
    window.predictor = predictor;
    
    // Initialize Chart.js if available
    if (typeof Chart !== 'undefined') {
        Chart.defaults.color = '#6c757d';
        Chart.defaults.font.family = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    }
});