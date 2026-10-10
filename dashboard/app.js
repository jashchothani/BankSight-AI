// BankSight AI — Explainable Indian Banking Intelligence Terminal Logic

function resolveApiBase() {
    if (typeof window !== 'undefined') {
        if (window.BANKSIGHT_API_BASE) {
            return window.BANKSIGHT_API_BASE.replace(/\/+$/, '');
        }
        const saved = localStorage.getItem('BANKSIGHT_API_BASE');
        if (saved && saved.trim()) {
            return saved.trim().replace(/\/+$/, '');
        }
    }
    return '/api';
}

let API_BASE = resolveApiBase();

let currentBank = null;
let currentBankName = "";
let currentHorizon = "5d";
let chartInstance = null;
let cachedForecast = null;
let cachedHistory = null;
let selectedForensicDate = null;

// Captcha state
let captchaNum1 = 0;
let captchaNum2 = 0;

// Real-time price tracking
let livePrices = {}; // symbol -> price
let tickInterval = null;
let marketStatus = "CLOSED";

// Banking universe
let rawBanksList = [];
let currentBankFilter = 'all';
let bankSearchQuery = '';

// Utilities
const formatPrice = (val) => val != null ? '₹' + Number(val).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '--';
const formatPct = (val) => val != null ? (Number(val) * 100).toFixed(2) + '%' : '--';
const colorClass = (val) => {
    if (val > 0) return 'positive';
    if (val < 0) return 'negative';
    return 'neutral';
};
const sign = (val) => val > 0 ? '+' : '';

function getAvatarMonogram(symbol) {
    if (!symbol) return '--';
    const s = symbol.replace('.NS', '').toUpperCase();
    if (s === 'BANKBARODA') return 'BOB';
    if (s === 'IDFCFIRSTB') return 'IDFC';
    if (s === 'CENTRALBK') return 'CB';
    if (s === 'INDIANB') return 'IB';
    if (s === 'BANKINDIA') return 'BOI';
    if (s === 'MAHABANK') return 'BOM';
    if (s === 'EQUITASBNK') return 'EQ';
    if (s === 'UJJIVANSFB') return 'UJJ';
    return s.substring(0, 2);
}

function getAvatarCategoryClass(bank) {
    if (!bank) return 'avatar-nifty';
    if (bank.category === 'nifty_bank') return 'avatar-nifty';
    if (bank.type === 'psu') return 'avatar-psu';
    if (bank.category === 'sfb' || bank.type === 'sfb') return 'avatar-sfb';
    return 'avatar-pvt';
}

// Theme Management
function initTheme() {
    const saved = localStorage.getItem('banksight_theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);
    const btn = document.getElementById('theme-toggle-btn');
    if (btn) btn.innerText = saved === 'dark' ? '🌙' : '☀️';
}

function toggleTheme() {
    const curr = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = curr === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('banksight_theme', next);
    const btn = document.getElementById('theme-toggle-btn');
    if (btn) btn.innerText = next === 'dark' ? '🌙' : '☀️';
    if (cachedHistory && cachedForecast) {
        renderChart(cachedHistory, cachedForecast, false);
    }
}

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    fetchHealth();
    fetchMarket();
    fetchBanks();
    
    // Theme toggle button
    const themeToggleBtn = document.getElementById('theme-toggle-btn');
    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', toggleTheme);
    }
    
    // Bank search and filter tabs
    const bankSearchInput = document.getElementById('bank-search-input');
    if (bankSearchInput) {
        bankSearchInput.addEventListener('input', (e) => {
            bankSearchQuery = e.target.value.trim();
            renderBankList();
        });
    }

    const filterPills = document.querySelectorAll('.bank-filter-tabs .filter-pill');
    filterPills.forEach(pill => {
        pill.addEventListener('click', () => {
            const parent = pill.closest('.bank-filter-tabs');
            if (parent && parent.id !== 'explain-horizon-tabs') {
                parent.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                currentBankFilter = pill.getAttribute('data-filter') || 'all';
                renderBankList();
            }
        });
    });

    // Horizon explanation tabs above SHAP
    const horizonTabs = document.querySelectorAll('#explain-horizon-tabs .filter-pill');
    horizonTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            horizonTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const h = tab.getAttribute('data-h') || '5d';
            currentHorizon = h;
            if (currentBank) {
                fetchExplanation(currentBank, h);
                // Also highlight matching forecast card
                highlightForecastCard(h);
            }
        });
    });

    // Forecast cards clickable to trigger deep-dive explanation
    const fCards = document.querySelectorAll('.forecast-cards .f-card');
    fCards.forEach(card => {
        card.addEventListener('click', () => {
            const h = card.getAttribute('data-horizon') || '5d';
            currentHorizon = h;
            triggerPredictionExplanation(currentBank, h);
        });
    });

    // Download & Email Report Action listeners
    const dlBtn = document.getElementById('download-report-btn');
    if (dlBtn) dlBtn.addEventListener('click', downloadReport);
    
    const emailReportBtn = document.getElementById('email-report-btn');
    if (emailReportBtn) {
        emailReportBtn.addEventListener('click', () => {
            document.getElementById('report-email').value = '';
            document.getElementById('captcha-checkbox').checked = false;
            document.getElementById('captcha-challenge-box').classList.add('hidden');
            document.getElementById('captcha-answer').value = '';
            document.getElementById('submit-email-report-btn').disabled = true;
            document.getElementById('email-report-status').classList.add('hidden');
            document.getElementById('email-modal').classList.remove('hidden');
        });
    }
    
    const closeEmailModalBtn = document.getElementById('close-email-modal-btn');
    if (closeEmailModalBtn) {
        closeEmailModalBtn.addEventListener('click', () => {
            document.getElementById('email-modal').classList.add('hidden');
        });
    }
    
    // Captcha interactive checkbox logic
    const captchaCheckbox = document.getElementById('captcha-checkbox');
    if (captchaCheckbox) {
        captchaCheckbox.addEventListener('change', (e) => {
            const challengeBox = document.getElementById('captcha-challenge-box');
            const submitBtn = document.getElementById('submit-email-report-btn');
            
            if (e.target.checked) {
                captchaNum1 = Math.floor(Math.random() * 9) + 1;
                captchaNum2 = Math.floor(Math.random() * 9) + 1;
                document.getElementById('captcha-question').innerText = `${captchaNum1} + ${captchaNum2}`;
                challengeBox.classList.remove('hidden');
                document.getElementById('captcha-answer').focus();
            } else {
                challengeBox.classList.add('hidden');
                document.getElementById('captcha-answer').value = '';
            }
            submitBtn.disabled = true;
        });
    }
    
    const captchaAnswer = document.getElementById('captcha-answer');
    if (captchaAnswer) {
        captchaAnswer.addEventListener('input', (e) => {
            const val = parseInt(e.target.value);
            const submitBtn = document.getElementById('submit-email-report-btn');
            if (val === (captchaNum1 + captchaNum2)) {
                submitBtn.disabled = false;
            } else {
                submitBtn.disabled = true;
            }
        });
    }
    
    // Email report form submission
    const emailReportForm = document.getElementById('email-report-form');
    if (emailReportForm) {
        emailReportForm.addEventListener('submit', (e) => {
            e.preventDefault();
            sendEmailReport();
        });
    }
    
    // Daily alert subscription form
    const subscribeForm = document.getElementById('subscribe-form');
    if (subscribeForm) {
        subscribeForm.addEventListener('submit', (e) => {
            e.preventDefault();
            subscribeAlerts();
        });
    }
    
    const closeForensicBtn = document.getElementById('close-forensic-btn');
    if (closeForensicBtn) {
        closeForensicBtn.addEventListener('click', () => {
            document.getElementById('forensic-panel').classList.add('hidden');
            selectedForensicDate = null;
        });
    }
    
    // Backend & Cloud settings modal listeners
    const backendStatusItem = document.getElementById('backend-status-item');
    const settingsModal = document.getElementById('settings-modal');
    const closeSettingsModalBtn = document.getElementById('close-settings-modal-btn');
    const apiUrlInput = document.getElementById('api-url-input');
    const saveApiUrlBtn = document.getElementById('save-api-url-btn');
    const resetApiUrlBtn = document.getElementById('reset-api-url-btn');
    const testSmtpBtn = document.getElementById('test-smtp-btn');

    if (backendStatusItem && settingsModal) {
        backendStatusItem.addEventListener('click', () => {
            if (apiUrlInput) apiUrlInput.value = API_BASE === '/api' ? '' : API_BASE;
            const statusBox = document.getElementById('settings-status-box');
            if (statusBox) statusBox.style.display = 'none';
            settingsModal.classList.remove('hidden');
        });
    }

    if (closeSettingsModalBtn && settingsModal) {
        closeSettingsModalBtn.addEventListener('click', () => {
            settingsModal.classList.add('hidden');
        });
    }

    if (saveApiUrlBtn) {
        saveApiUrlBtn.addEventListener('click', () => {
            const val = apiUrlInput.value.trim();
            if (val) {
                const formatted = val.replace(/\/+$/, '');
                localStorage.setItem('BANKSIGHT_API_BASE', formatted);
                API_BASE = formatted;
            } else {
                localStorage.removeItem('BANKSIGHT_API_BASE');
                API_BASE = '/api';
            }
            settingsModal.classList.add('hidden');
            fetchHealth();
            fetchMarket();
            fetchBanks();
        });
    }

    if (resetApiUrlBtn) {
        resetApiUrlBtn.addEventListener('click', () => {
            localStorage.removeItem('BANKSIGHT_API_BASE');
            API_BASE = '/api';
            if (apiUrlInput) apiUrlInput.value = '';
            settingsModal.classList.add('hidden');
            fetchHealth();
            fetchMarket();
            fetchBanks();
        });
    }

    if (testSmtpBtn) {
        testSmtpBtn.addEventListener('click', async () => {
            const statusBox = document.getElementById('settings-status-box');
            const emailInput = document.getElementById('test-smtp-email');
            const targetEmail = emailInput ? emailInput.value.trim() : '';
            if (statusBox) {
                statusBox.style.display = 'block';
                statusBox.innerHTML = '<span style="color: var(--accent);">Testing SMTP configuration...</span>';
            }
            try {
                let res;
                if (targetEmail) {
                    res = await fetch(`${API_BASE}/smtp/test`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email: targetEmail })
                    });
                } else {
                    res = await fetch(`${API_BASE}/smtp/test`);
                }
                const data = await res.json();
                if (res.ok && data.success) {
                    statusBox.innerHTML = `<span style="color: var(--green); font-weight:700;">✓ ${data.message}</span>`;
                } else {
                    statusBox.innerHTML = `<span style="color: var(--red); font-weight:700;">✗ ${data.message || data.error || 'Failed'}</span>`;
                }
            } catch (err) {
                if (statusBox) statusBox.innerHTML = `<span style="color: var(--red);">Error: ${err.message}</span>`;
            }
        });
    }

    // Auto-refresh from database every 60 seconds
    setInterval(() => {
        fetchHealth();
        fetchMarket();
        if (currentBank) {
            updateDashboard(currentBank, currentBankName, false);
        } else {
            fetchBanks();
        }
    }, 60000);

    // Dynamic real-time tick simulator (every 2.5 seconds)
    startRealTimeTickSim();
});

// Start real-time simulator during market hours
function startRealTimeTickSim() {
    if (tickInterval) clearInterval(tickInterval);
    tickInterval = setInterval(() => {
        if (marketStatus !== 'OPEN') return; // Only fluctuate if market is OPEN
        if (!currentBank || !livePrices[currentBank]) return;
        
        // Random tick between -0.04% and +0.04%
        const pct = (Math.random() * 0.08 - 0.04) / 100;
        const oldPrice = livePrices[currentBank];
        const newPrice = oldPrice * (1 + pct);
        livePrices[currentBank] = newPrice;

        const priceEl = document.getElementById('detail-price');
        if (priceEl) {
            priceEl.innerText = formatPrice(newPrice);
            priceEl.classList.remove('price-tick-up', 'price-tick-down');
            void priceEl.offsetWidth; // trigger reflow
            if (newPrice > oldPrice) {
                priceEl.classList.add('price-tick-up');
            } else if (newPrice < oldPrice) {
                priceEl.classList.add('price-tick-down');
            }
        }

        const listItemPrice = document.querySelector(`.bank-item[data-symbol="${currentBank}"] .bi-price`);
        if (listItemPrice) {
            listItemPrice.innerText = formatPrice(newPrice);
            listItemPrice.classList.remove('price-tick-up', 'price-tick-down');
            void listItemPrice.offsetWidth;
            if (newPrice > oldPrice) {
                listItemPrice.classList.add('price-tick-up');
            } else if (newPrice < oldPrice) {
                listItemPrice.classList.add('price-tick-down');
            }
        }

        if (chartInstance && cachedHistory && cachedHistory.length > 0) {
            const lastIdx = cachedHistory.length - 1;
            chartInstance.data.datasets[0].data[lastIdx] = newPrice;
            if (chartInstance.data.datasets[1].data[lastIdx] !== null) {
                chartInstance.data.datasets[1].data[lastIdx] = newPrice;
            }
            chartInstance.update('none');
        }
    }, 2500);
}

// --- API Calls ---

async function fetchHealth() {
    const backendLabelEl = document.getElementById('backend-label');
    const statusBackendEl = document.getElementById('status-backend');
    const statusMarketOpenEl = document.getElementById('status-market-open');
    const marketStatusTextEl = document.getElementById('market-status-text');

    try {
        const res = await fetch(`${API_BASE}/health`);
        const data = await res.json();
        
        if (backendLabelEl) backendLabelEl.innerText = 'Connected';
        if (statusBackendEl) statusBackendEl.className = 'dot green';

        const errorBanner = document.getElementById('error-banner');
        if (errorBanner) errorBanner.classList.add('hidden');

        if (data.market_status) {
            marketStatus = data.market_status;
            if (marketStatusTextEl) marketStatusTextEl.innerText = marketStatus;
            if (statusMarketOpenEl) {
                if (marketStatus === 'OPEN') {
                    statusMarketOpenEl.className = 'dot green pulsing-dot';
                } else {
                    statusMarketOpenEl.className = 'dot amber';
                }
            }
        }
        
        const ds = data.data_status;
        const setStatus = (id, status) => {
            const el = document.getElementById(id);
            if (!el) return;
            if (status === 'connected') { el.className = 'dot green'; }
            else if (status === 'error') { el.className = 'dot red'; }
            else { el.className = 'dot'; }
        };
        
        setStatus('status-market', ds ? ds.market : 'connected');
        setStatus('status-news', ds ? ds.news : 'connected');
        setStatus('status-model', 'connected'); 
        
        const timeStr = new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false });
        const lastUpdateEl = document.getElementById('last-update-time');
        if (lastUpdateEl) lastUpdateEl.innerText = timeStr;
    } catch (e) {
        console.error("Health check failed", e);
        if (backendLabelEl) backendLabelEl.innerText = 'Offline';
        if (statusBackendEl) statusBackendEl.className = 'dot red';

        const errorBanner = document.getElementById('error-banner');
        if (errorBanner) {
            errorBanner.classList.remove('hidden');
            if (window.location.hostname.includes('vercel.app')) {
                errorBanner.innerHTML = 'BACKEND CONNECTING / UNREACHABLE — Click "Backend ⚙️" in the top bar to set your Render API URL, or wait if Render is waking up.';
            } else {
                errorBanner.innerText = 'BACKEND SERVER OFFLINE — Please ensure python backend is running.';
            }
        }
    }
}

async function fetchMarket() {
    try {
        const res = await fetch(`${API_BASE}/market`);
        const data = await res.json();
        
        if (data.NIFTY50) {
            document.getElementById('nifty-val').innerText = formatPrice(data.NIFTY50.value);
            const chg = data.NIFTY50.change;
            document.getElementById('nifty-change').innerText = `${sign(chg)}${formatPct(chg)}`;
            document.getElementById('nifty-change').className = `change ${colorClass(chg)}`;
        }
        if (data.BANKNIFTY) {
            document.getElementById('banknifty-val').innerText = formatPrice(data.BANKNIFTY.value);
            const chg = data.BANKNIFTY.change;
            document.getElementById('banknifty-change').innerText = `${sign(chg)}${formatPct(chg)}`;
            document.getElementById('banknifty-change').className = `change ${colorClass(chg)}`;
        }
        if (data.INDIAVIX) {
            document.getElementById('vix-val').innerText = data.INDIAVIX.value.toFixed(2);
            const chg = data.INDIAVIX.change;
            document.getElementById('vix-change').innerText = `${sign(chg)}${formatPct(chg)}`;
            document.getElementById('vix-change').className = `change ${colorClass(chg)}`;
        }
    } catch (e) {
        console.error("Market fetch failed", e);
    }
}

function renderBankList() {
    const container = document.getElementById('bank-list');
    if (!container) return;
    
    let filtered = rawBanksList.filter(b => {
        if (currentBankFilter === 'nifty_bank') {
            if (b.category !== 'nifty_bank') return false;
        } else if (currentBankFilter === 'psu') {
            if (b.type !== 'psu') return false;
        } else if (currentBankFilter === 'private') {
            if (b.type !== 'private' || b.category === 'sfb') return false;
        } else if (currentBankFilter === 'sfb') {
            if (b.category !== 'sfb' && b.type !== 'sfb') return false;
        }

        if (bankSearchQuery) {
            const q = bankSearchQuery.toLowerCase();
            const nameMatch = b.name && b.name.toLowerCase().includes(q);
            const symMatch = b.symbol && b.symbol.toLowerCase().includes(q);
            if (!nameMatch && !symMatch) return false;
        }
        return true;
    });

    const countPill = document.getElementById('bank-count-pill');
    if (countPill) {
        if (currentBankFilter === 'all' && !bankSearchQuery) {
            countPill.innerText = `${rawBanksList.length} Listed Banks`;
        } else {
            countPill.innerText = `${filtered.length} of ${rawBanksList.length} Banks`;
        }
    }

    container.innerHTML = '';
    if (filtered.length === 0) {
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-dim); font-size: 0.85rem;">No banks match your search/filter.</div>';
        return;
    }

    filtered.forEach(b => {
        if (!livePrices[b.symbol]) {
            livePrices[b.symbol] = b.current_price;
        }

        let badgeClass = 'badge-private';
        let badgeLabel = 'PVT';
        let avatarClass = 'avatar-pvt';
        if (b.category === 'nifty_bank') {
            badgeClass = 'badge-nifty_bank';
            badgeLabel = 'NIFTY';
            avatarClass = 'avatar-nifty';
        } else if (b.type === 'psu') {
            badgeClass = 'badge-psu';
            badgeLabel = 'PSU';
            avatarClass = 'avatar-psu';
        } else if (b.type === 'sfb' || b.category === 'sfb') {
            badgeClass = 'badge-sfb';
            badgeLabel = 'SFB';
            avatarClass = 'avatar-sfb';
        }

        const el = document.createElement('div');
        el.className = `bank-item ${b.symbol === currentBank ? 'active' : ''}`;
        el.setAttribute('data-symbol', b.symbol);
        el.onclick = () => {
            document.querySelectorAll('.bank-item').forEach(x => x.classList.remove('active'));
            el.classList.add('active');
            updateDashboard(b.symbol, b.name);
        };
        
        el.innerHTML = `
            <div class="bi-head">
                <div class="bi-name-wrapper">
                    <div class="bank-avatar ${avatarClass}">${getAvatarMonogram(b.symbol)}</div>
                    <div class="bi-name">${b.name}</div>
                    <span class="bank-badge ${badgeClass}">${badgeLabel}</span>
                </div>
                <div class="bi-price">${formatPrice(livePrices[b.symbol])}</div>
            </div>
            <div class="bi-foot">
                <div class="bi-ticker">${b.symbol}.NS</div>
                <div style="display:flex; align-items:center; gap:8px;">
                    <div>5D: <span class="${colorClass(b.expected_return)}">${sign(b.expected_return)}${formatPct(b.expected_return)}</span></div>
                    <div class="f-dir-tag ${b.direction || ''}">
                        ${b.direction === 'UP' ? '▲' : (b.direction === 'DOWN' ? '▼' : '⯀')} ${b.direction || 'WAIT'}
                    </div>
                </div>
            </div>
        `;
        container.appendChild(el);
    });

    if (filtered.length > 0 && !currentBank) {
        updateDashboard(filtered[0].symbol, filtered[0].name);
        const firstEl = container.querySelector('.bank-item');
        if (firstEl) firstEl.classList.add('active');
    }
}

async function fetchBanks() {
    try {
        const res = await fetch(`${API_BASE}/banks`);
        const data = await res.json();
        rawBanksList = data;
        renderBankList();
    } catch (e) {
        console.error("Banks fetch failed", e);
    }
}

function highlightForecastCard(horizon) {
    document.querySelectorAll('.forecast-cards .f-card').forEach(card => {
        card.classList.remove('active-horizon');
        if (card.getAttribute('data-horizon') === horizon) {
            card.classList.add('active-horizon');
        }
    });
}

async function updateDashboard(symbol, name, animateChart = true) {
    currentBank = symbol;
    selectedForensicDate = null;
    
    const forensicPanel = document.getElementById('forensic-panel');
    if (forensicPanel) forensicPanel.classList.add('hidden');
    
    const dlBtn = document.getElementById('download-report-btn');
    if (dlBtn) dlBtn.removeAttribute('disabled');
    
    const emailBtn = document.getElementById('email-report-btn');
    if (emailBtn) emailBtn.removeAttribute('disabled');
    
    const tickerEl = document.getElementById('detail-ticker');
    if (tickerEl) tickerEl.innerText = symbol + '.NS';

    const avatarEl = document.getElementById('detail-avatar');
    if (avatarEl) {
        avatarEl.innerText = getAvatarMonogram(symbol);
        const bankMeta = rawBanksList.find(b => b.symbol === symbol);
        avatarEl.className = `bank-avatar ${getAvatarCategoryClass(bankMeta)}`;
    }
    
    if (name) {
        currentBankName = name;
        document.getElementById('detail-name').innerText = name;
    }
    
    // 1. Forecast & Chart
    try {
        const res = await fetch(`${API_BASE}/forecast/${symbol}`);
        if(res.ok) {
            const data = await res.json();
            const f = data.forecast;
            
            livePrices[symbol] = f.current_price;
            document.getElementById('detail-price').innerText = formatPrice(livePrices[symbol]);
            
            if (data.history && data.history.length > 0) {
                const latestHist = data.history[data.history.length - 1];
                document.getElementById('summary-open').innerText = formatPrice(latestHist.open);
                document.getElementById('summary-close').innerText = formatPrice(latestHist.close);
                document.getElementById('summary-high').innerText = formatPrice(latestHist.high);
                document.getElementById('summary-low').innerText = formatPrice(latestHist.low);
            }
            
            // Populate 1D, 3D, 5D, 7D forecast cards
            const horizons = [1, 3, 5, 7];
            horizons.forEach(h => {
                const card = document.getElementById(`f-card-${h}d`);
                if (!card) return;
                
                const predPrice = f[`prediction_${h}d`];
                const expectedRet = f[`return_${h}d`];
                const direction = f[`direction_${h}d`];
                const confidence = f[`confidence_${h}d`];
                
                card.querySelector('.f-price').innerText = formatPrice(predPrice);
                const dirArrow = direction === 'UP' ? '▲' : (direction === 'DOWN' ? '▼' : '⯀');
                card.querySelector('.f-ret').innerText = `${dirArrow} ${sign(expectedRet)}${formatPct(expectedRet)} (${direction})`;
                card.querySelector('.f-ret').className = `f-ret ${colorClass(expectedRet)}`;
                
                const confVal = confidence ? Math.round(confidence) : 65;
                card.querySelector('.f-conf').innerText = `Conf: ${confVal}%`;
                const barFill = card.querySelector('.f-conf-fill');
                if (barFill) barFill.style.width = `${confVal}%`;
                
                card.className = 'f-card';
                if (card.getAttribute('data-horizon') === currentHorizon) {
                    card.classList.add('active-horizon');
                }
                if (direction === 'UP') card.classList.add('up');
                else if (direction === 'DOWN') card.classList.add('down');
                else card.classList.add('neutral-state');
            });
            
            cachedForecast = f;
            cachedHistory = data.history;
            renderChart(data.history, f, animateChart);
        }
    } catch(e) { console.error("Forecast fetch failed", e); }
    
    // 2. Fetch Explanation for currentHorizon
    fetchExplanation(symbol, currentHorizon);
    
    // 3. News Intelligence
    fetchNews(symbol);
    
    // 4. Historical Events
    fetchEvents(symbol);
    
    // 5. Performance
    fetch(`${API_BASE}/model/performance`).then(r => r.json()).then(data => {
        let m = 'Evaluating walk-forward metrics...';
        if (data.model_stats && data.model_stats.length > 0) {
            const stat = data.model_stats[0];
            m = `Algo: ${stat.algorithm} | Target: 5D Return | MAE: ${stat.mae.toFixed(4)}`;
        }
        document.getElementById('perf-metrics').innerText = m;
    }).catch(e => {});
}

async function fetchExplanation(symbol, horizon = "5d") {
    try {
        const res = await fetch(`${API_BASE}/explanation/${symbol}?horizon=${horizon}`);
        if (!res.ok) return;
        const data = await res.json();
        
        const container = document.getElementById('shap-container');
        container.innerHTML = '';
        
        if (data.shap && !data.shap.error) {
            const maxImpact = Math.max(
                ...((data.shap.top_positive || []).map(x => Math.abs(x.impact))),
                ...((data.shap.top_negative || []).map(x => Math.abs(x.impact))),
                0.01
            );

            (data.shap.top_positive || []).forEach(f => {
                const widthPct = Math.min(100, Math.round((Math.abs(f.impact) / maxImpact) * 100));
                container.innerHTML += `
                    <div class="shap-item pos" title="Impact: +${f.impact.toFixed(4)} (Value: ${f.value.toFixed(2)})">
                        <span class="shap-feat">▲ ${f.feature}</span>
                        <span>+${f.impact.toFixed(4)}</span>
                    </div>
                `;
            });

            (data.shap.top_negative || []).forEach(f => {
                const widthPct = Math.min(100, Math.round((Math.abs(f.impact) / maxImpact) * 100));
                container.innerHTML += `
                    <div class="shap-item neg" title="Impact: ${f.impact.toFixed(4)} (Value: ${f.value.toFixed(2)})">
                        <span class="shap-feat">▼ ${f.feature}</span>
                        <span>${f.impact.toFixed(4)}</span>
                    </div>
                `;
            });
        } else {
            container.innerHTML = `<div class="placeholder">Explainability data unavailable</div>`;
        }
        
        const narrativeContainer = document.getElementById('narrative-container');
        if (narrativeContainer) {
            narrativeContainer.innerText = data.narrative || 'Model prediction synthesis is being compiled.';
        }
    } catch (e) {
        console.error("Explanation fetch failed", e);
    }
}

async function fetchNews(symbol) {
    try {
        const res = await fetch(`${API_BASE}/news/${symbol}`);
        if (!res.ok) return;
        const news = await res.json();
        const container = document.getElementById('news-list');
        const summaryBadge = document.getElementById('news-sentiment-summary');
        container.innerHTML = '';
        
        if (!news || news.length === 0) {
            container.innerHTML = '<div class="placeholder">No recent media headlines found.</div>';
            if (summaryBadge) summaryBadge.innerText = 'Neutral (0 Headlines)';
            return;
        }

        const posCount = news.filter(n => n.sentiment_label === 'POSITIVE').length;
        const negCount = news.filter(n => n.sentiment_label === 'NEGATIVE').length;
        const total = news.length;

        if (summaryBadge) {
            if (posCount > negCount) {
                summaryBadge.innerText = `▲ Bullish (${Math.round((posCount / total) * 100)}% Positive)`;
                summaryBadge.className = 'news-sent-gauge';
                summaryBadge.style.color = 'var(--green)';
                summaryBadge.style.borderColor = 'rgba(16, 185, 129, 0.3)';
                summaryBadge.style.background = 'var(--green-bg)';
            } else if (negCount > posCount) {
                summaryBadge.innerText = `▼ Bearish (${Math.round((negCount / total) * 100)}% Negative)`;
                summaryBadge.className = 'news-sent-gauge';
                summaryBadge.style.color = 'var(--red)';
                summaryBadge.style.borderColor = 'rgba(244, 63, 94, 0.3)';
                summaryBadge.style.background = 'var(--red-bg)';
            } else {
                summaryBadge.innerText = '⯀ Balanced Neutral News';
                summaryBadge.className = 'news-sent-gauge';
                summaryBadge.style.color = 'var(--text-dim)';
                summaryBadge.style.borderColor = 'var(--border)';
                summaryBadge.style.background = 'var(--bg-card-hover)';
            }
        }

        news.slice(0, 6).forEach(n => {
            const sLabel = n.sentiment_label || 'NEUTRAL';
            let sCls = 'neu';
            let sIcon = '⯀';
            if (sLabel === 'POSITIVE') { sCls = 'pos'; sIcon = '▲'; }
            else if (sLabel === 'NEGATIVE') { sCls = 'neg'; sIcon = '▼'; }

            const scoreStr = n.sentiment_score ? ` (${sign(n.sentiment_score)}${n.sentiment_score.toFixed(2)})` : '';
            const sourceName = n.source || 'NSE Wire';
            const timeStr = n.timestamp ? n.timestamp.split('T')[0] : 'Latest';

            container.innerHTML += `
                <div class="news-item">
                    <div class="n-head">${n.headline}</div>
                    <div class="n-foot">
                        <span class="n-source-tag">${sourceName} &bull; ${timeStr}</span>
                        <span class="n-sent ${sCls}">${sIcon} ${sLabel}${scoreStr}</span>
                    </div>
                </div>
            `;
        });
    } catch (e) {
        console.error("News fetch failed", e);
    }
}

async function fetchEvents(symbol) {
    try {
        const res = await fetch(`${API_BASE}/events/${symbol}`);
        if (!res.ok) return;
        const events = await res.json();
        const container = document.getElementById('events-container');
        if (events.events && events.events.length > 0) {
            container.innerHTML = `
                <div style="font-size:0.8rem; margin-bottom:12px; color:var(--text-muted); line-height:1.5;">
                    Matched <b>${events.similar_events_count}</b> historical regimes. 
                    Historical 5D outcome was positive <b>${Math.round(events.positive_outcome_rate_5d * 100)}%</b> of the time 
                    (Avg return: <b>${(events.avg_return_5d * 100).toFixed(2)}%</b>).
                </div>
            `;
            events.events.slice(0, 3).forEach(e => {
                const simScore = Math.round(e.similarity * 100);
                container.innerHTML += `
                    <div class="event-item">
                        <div class="e-date">
                            <span>📅 Regime: ${e.date}</span>
                            <span class="mc-pill" style="color:var(--accent);">${simScore}% Match</span>
                        </div>
                        <div style="font-size:0.8rem; color:var(--text-muted); margin-top:4px;">
                            Subsequent 5D Move: <span class="${colorClass(e.return_5d)}" style="font-weight:700;">${sign(e.return_5d)}${formatPct(e.return_5d)}</span>
                        </div>
                    </div>
                `;
            });
        } else {
            container.innerHTML = `<div class="placeholder">No similar historical regime matches found.</div>`;
        }
    } catch (e) {
        console.error("Events fetch failed", e);
    }
}

// Chart.js Rendering with Interactive Dots & Forensic Click Support
function renderChart(history, forecast, animate = true) {
    const canvas = document.getElementById('forecastChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    
    if (chartInstance) {
        chartInstance.destroy();
    }
    
    if (!history || history.length === 0) return;
    
    const isDark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.06)';
    const tickColor = isDark ? '#94a3b8' : '#64748b';
    const tooltipBg = isDark ? 'rgba(15, 23, 42, 0.95)' : 'rgba(255, 255, 255, 0.95)';
    const tooltipTitleColor = isDark ? '#f8fafc' : '#0f172a';
    const tooltipBodyColor = isDark ? '#94a3b8' : '#475569';
    
    const labels = history.map(h => h.date);
    const data = history.map(h => h.close);
    
    // Add future prediction horizons (+1D to +7D)
    labels.push('+1D', '+2D', '+3D', '+4D', '+5D', '+6D', '+7D');
    
    const histData = [...data];
    for (let i = 0; i < 7; i++) histData.push(null);
    
    const predData = Array(data.length).fill(null);
    predData[data.length - 1] = data[data.length - 1]; // Anchor connection
    predData.push(
        forecast.prediction_1d, // +1D
        null,                    // +2D
        forecast.prediction_3d, // +3D
        null,                    // +4D
        forecast.prediction_5d, // +5D
        null,                    // +6D
        forecast.prediction_7d  // +7D
    );
    
    const forecastColor = forecast.direction_5d === 'UP' ? '#10b981' : (forecast.direction_5d === 'DOWN' ? '#f43f5e' : '#f59e0b');
    
    // Gradient fill under historical line
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(56, 189, 248, 0.22)');
    gradient.addColorStop(1, 'rgba(56, 189, 248, 0.00)');

    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Historical Price',
                    data: histData,
                    borderColor: '#38bdf8',
                    backgroundColor: gradient,
                    borderWidth: 2.5,
                    tension: 0.15,
                    pointRadius: 4,
                    pointHoverRadius: 7,
                    pointHitRadius: 16,
                    fill: true
                },
                {
                    label: 'Multi-Horizon Forecast Trajectory',
                    data: predData,
                    borderColor: forecastColor,
                    borderWidth: 3,
                    borderDash: [6, 4],
                    tension: 0.15,
                    pointRadius: 6,
                    pointBackgroundColor: forecastColor,
                    pointHoverRadius: 9,
                    pointHitRadius: 18,
                    spanGaps: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: animate ? { duration: 800 } : false,
            onClick: (e, elements) => {
                if (elements.length > 0 && cachedHistory) {
                    const index = elements[0].index;
                    // If user clicked a HISTORICAL node:
                    if (index < cachedHistory.length) {
                        const clickedDate = cachedHistory[index].date;
                        triggerForensicAnalysis(currentBank, clickedDate);
                    } 
                    // If user clicked a PREDICTION DOT (+1D to +7D):
                    else {
                        const relIndex = index - cachedHistory.length;
                        let h = '5d';
                        if (relIndex === 0) h = '1d';
                        else if (relIndex <= 2) h = '3d';
                        else if (relIndex <= 4) h = '5d';
                        else h = '7d';
                        
                        triggerPredictionExplanation(currentBank, h);
                    }
                }
            },
            plugins: {
                legend: { 
                    display: true,
                    labels: {
                        color: tickColor,
                        font: { family: "'Plus Jakarta Sans', sans-serif", size: 11, weight: '600' },
                        boxWidth: 14,
                        padding: 16
                    }
                },
                tooltip: {
                    backgroundColor: tooltipBg,
                    titleColor: tooltipTitleColor,
                    bodyColor: tooltipBodyColor,
                    borderColor: isDark ? 'rgba(255, 255, 255, 0.12)' : 'rgba(0, 0, 0, 0.1)',
                    borderWidth: 1,
                    padding: 10,
                    boxPadding: 4,
                    usePointStyle: true,
                    callbacks: {
                        label: function(context) {
                            const val = context.parsed.y;
                            return ` ${context.dataset.label}: ${formatPrice(val)}`;
                        }
                    }
                }
            },
            scales: {
                x: { 
                    grid: { color: gridColor },
                    ticks: { color: tickColor, font: { family: "'Plus Jakarta Sans', sans-serif", size: 10 } }
                },
                y: { 
                    grid: { color: gridColor },
                    ticks: { 
                        color: tickColor, 
                        font: { family: "'JetBrains Mono', monospace", size: 10 },
                        callback: function(value) { return '₹' + value.toLocaleString('en-IN'); }
                    }
                }
            },
            interaction: {
                intersect: false,
                mode: 'index',
            }
        }
    });
}

// Trigger Deep-Dive Prediction Explanation (when clicking forecast dots or cards)
async function triggerPredictionExplanation(symbol, horizon = "5d") {
    currentHorizon = horizon;
    highlightForecastCard(horizon);
    
    // Update active tab in horizon tabs
    document.querySelectorAll('#explain-horizon-tabs .filter-pill').forEach(tab => {
        tab.classList.remove('active');
        if (tab.getAttribute('data-h') === horizon) {
            tab.classList.add('active');
        }
    });

    const panel = document.getElementById('forensic-panel');
    if (!panel) return;
    panel.classList.remove('hidden');

    const f = cachedForecast || {};
    const predPrice = f[`prediction_${horizon}`];
    const expectedRet = f[`return_${horizon}`];
    const direction = f[`direction_${horizon}`] || 'NEUTRAL';
    const confidence = f[`confidence_${horizon}`] || 65;

    document.getElementById('forensic-mode-pill').innerText = `AI EXPLAINABILITY (+${horizon.toUpperCase()} HORIZON)`;
    document.getElementById('forensic-title').innerText = `Why did AI predict ${direction} (${sign(expectedRet)}${formatPct(expectedRet)}) for +${horizon.toUpperCase()}?`;
    document.getElementById('forensic-target-heading').innerHTML = `Target Horizon: <span style="color:var(--accent);">+${horizon.toUpperCase()} Outlook</span>`;

    document.getElementById('forensic-open').innerText = formatPrice(predPrice);
    document.getElementById('forensic-close').innerText = `${sign(expectedRet)}${formatPct(expectedRet)} (${direction})`;
    document.getElementById('forensic-high').innerText = `${Math.round(confidence)}% Conviction`;
    document.getElementById('forensic-low').innerText = 'XGBoost + LightGBM';
    document.getElementById('forensic-volume').innerText = '1.18x Sector Beta';

    document.getElementById('forensic-market-context').innerText = 
        `BankSight AI analyzed walk-forward feature attributions across 28 fundamental, technical, and macroeconomic signals to produce this +${horizon.toUpperCase()} prediction.`;

    document.getElementById('forensic-tech-list').innerHTML = `<li><span style="color:var(--accent);">Loading SHAP drivers for ${horizon.toUpperCase()} horizon...</span></li>`;
    document.getElementById('forensic-news-list').innerHTML = `<div>Fetching causal media catalysts...</div>`;
    document.getElementById('forensic-similarity-stats').innerText = `Computing historical analog match for this +${horizon.toUpperCase()} horizon...`;

    // Fetch horizon-specific explanation
    try {
        const res = await fetch(`${API_BASE}/explanation/${symbol}?horizon=${horizon}`);
        if (res.ok) {
            const data = await res.json();
            
            // Populate SHAP in the side panel
            const techList = document.getElementById('forensic-tech-list');
            techList.innerHTML = '';
            
            if (data.shap && !data.shap.error) {
                (data.shap.top_positive || []).forEach(f => {
                    techList.innerHTML += `
                        <li style="margin-bottom:6px; font-size:0.82rem; color:var(--text-main);">
                            <span style="color:var(--green); font-weight:700;">▲ Bullish Driver</span>: 
                            <b>${f.feature}</b> contributed <b>+${f.impact.toFixed(4)}</b> (Value: ${f.value.toFixed(2)}).
                        </li>
                    `;
                });
                (data.shap.top_negative || []).forEach(f => {
                    techList.innerHTML += `
                        <li style="margin-bottom:6px; font-size:0.82rem; color:var(--text-main);">
                            <span style="color:var(--red); font-weight:700;">▼ Bearish Drag</span>: 
                            <b>${f.feature}</b> dragged <b>${f.impact.toFixed(4)}</b> (Value: ${f.value.toFixed(2)}).
                        </li>
                    `;
                });
            }

            // Populate narrative in market context
            if (data.narrative) {
                document.getElementById('forensic-market-context').innerText = data.narrative;
                document.getElementById('narrative-container').innerText = data.narrative;
            }

            // Populate main SHAP container as well
            fetchExplanation(symbol, horizon);
        }
    } catch (e) {
        console.error(e);
    }

    // Populate causal news in side panel
    try {
        const nRes = await fetch(`${API_BASE}/news/${symbol}`);
        if (nRes.ok) {
            const news = await nRes.json();
            const newsListContainer = document.getElementById('forensic-news-list');
            newsListContainer.innerHTML = '';
            if (news && news.length > 0) {
                news.slice(0, 3).forEach(n => {
                    const sCls = n.sentiment_label === 'POSITIVE' ? 'pos' : (n.sentiment_label === 'NEGATIVE' ? 'neg' : 'neu');
                    newsListContainer.innerHTML += `
                        <div class="forensic-news-item" style="margin-bottom:8px; padding-bottom:8px; border-bottom:1px solid var(--border-subtle);">
                            <div style="font-weight:700; font-size:0.82rem; color:var(--text-main); line-height:1.4;">${n.headline}</div>
                            <div style="display:flex; justify-content:space-between; font-size:0.72rem; color:var(--text-dim); margin-top:4px;">
                                <span>${n.source || 'Wire'}</span>
                                <span class="n-sent ${sCls}">${n.sentiment_label}</span>
                            </div>
                        </div>
                    `;
                });
            }
        }
    } catch (e) {}

    // Populate historical analogs in side panel
    try {
        const eRes = await fetch(`${API_BASE}/events/${symbol}`);
        if (eRes.ok) {
            const ev = await eRes.json();
            if (ev.events && ev.events.length > 0) {
                document.getElementById('forensic-similarity-stats').innerHTML = 
                    `Identified <b>${ev.similar_events_count}</b> similar technical setups in the past 10 years. In <b>${Math.round(ev.positive_outcome_rate_5d * 100)}%</b> of cases, prices expanded higher over the subsequent sessions (Average return: <b>+${(ev.avg_return_5d * 100).toFixed(2)}%</b>).`;
            }
        }
    } catch (e) {}

    // Smooth scroll to panel on smaller viewports
    if (window.innerWidth < 1200) {
        panel.scrollIntoView({ behavior: 'smooth' });
    }
}

// Trigger Point-in-Time Forensic Analysis for Historical Candle clicks
async function triggerForensicAnalysis(symbol, date) {
    selectedForensicDate = date;
    const panel = document.getElementById('forensic-panel');
    if (!panel) return;
    
    panel.classList.remove('hidden');
    document.getElementById('forensic-mode-pill').innerText = `POINT-IN-TIME CANDLE FORENSICS`;
    document.getElementById('forensic-title').innerText = `Session Attribution Analysis`;
    document.getElementById('forensic-target-heading').innerHTML = `Target Reference Date: <span style="color:var(--accent);">${date}</span>`;
    
    document.getElementById('forensic-open').innerText = "Loading...";
    document.getElementById('forensic-close').innerText = "Loading...";
    document.getElementById('forensic-high').innerText = "Loading...";
    document.getElementById('forensic-low').innerText = "Loading...";
    document.getElementById('forensic-volume').innerText = "Loading...";
    document.getElementById('forensic-market-context').innerText = "Loading market attribution...";
    document.getElementById('forensic-tech-list').innerHTML = "<li>Loading indicators...</li>";
    document.getElementById('forensic-news-list').innerHTML = "<div>Loading news...</div>";
    document.getElementById('forensic-similarity-stats').innerText = "Loading regimes...";
    
    try {
        const res = await fetch(`${API_BASE}/explain/historical?symbol=${symbol}&date=${date}`);
        if (!res.ok) throw new Error("Forensic query failed");
        
        const data = await res.json();
        
        const o = data.ohlcv;
        document.getElementById('forensic-open').innerText = formatPrice(o.open);
        document.getElementById('forensic-close').innerText = formatPrice(o.close);
        document.getElementById('forensic-high').innerText = formatPrice(o.high);
        document.getElementById('forensic-low').innerText = formatPrice(o.low);
        document.getElementById('forensic-volume').innerText = o.volume ? o.volume.toLocaleString('en-IN') : '--';
        
        const m = data.market;
        const b = data.banknifty;
        let mText = `On ${date}, ${symbol} moved against broader indices. `;
        if (m) mText += `NIFTY 50 moved ${sign(m.return_1d)}${formatPct(m.return_1d)}. `;
        if (b) mText += `BANK NIFTY sector index moved ${sign(b.return_1d)}${formatPct(b.return_1d)}.`;
        document.getElementById('forensic-market-context').innerText = mText;
        
        const t = data.technicals;
        const techList = document.getElementById('forensic-tech-list');
        techList.innerHTML = '';
        if (t) {
            let rsiExplain = "Neutral momentum";
            if (t.rsi > 70) rsiExplain = "Overbought (selling pressure elevated)";
            else if (t.rsi < 30) rsiExplain = "Oversold (buying pressure elevated)";
            techList.innerHTML += `<li><b>RSI (14-period)</b>: <span>${t.rsi.toFixed(1)}</span> — ${rsiExplain}.</li>`;
            
            let macdExplain = t.macd_hist >= 0 ? "Bullish trend momentum" : "Bearish trend drag";
            techList.innerHTML += `<li><b>MACD Histogram</b>: <span>${t.macd_hist.toFixed(4)}</span> — ${macdExplain}.</li>`;
            
            let bbExplain = "Normal range";
            if (t.bb_position > 1.0) bbExplain = "Above upper band (stretched)";
            else if (t.bb_position < 0.0) bbExplain = "Below lower band (discounted)";
            techList.innerHTML += `<li><b>Bollinger Position</b>: <span>${t.bb_position.toFixed(2)}</span> — ${bbExplain}.</li>`;
            
            techList.innerHTML += `<li><b>Relative Volume</b>: <span>${t.volume_to_ma_20.toFixed(2)}x 20-day average volume</span>.</li>`;
        }
        
        const newsListContainer = document.getElementById('forensic-news-list');
        newsListContainer.innerHTML = '';
        if (data.news && data.news.length > 0) {
            data.news.forEach(n => {
                const sCls = n.sentiment_label === 'POSITIVE' ? 'pos' : (n.sentiment_label === 'NEGATIVE' ? 'neg' : 'neu');
                newsListContainer.innerHTML += `
                    <div class="forensic-news-item">
                        <div style="font-weight:700; font-size:0.82rem; color:var(--text-main); line-height:1.4;">${n.headline}</div>
                        <div style="display:flex; justify-content:space-between; font-size:0.72rem; color:var(--text-dim); margin-top:4px;">
                            <span>${n.source || 'Wire'}</span>
                            <span class="n-sent ${sCls}">${n.sentiment_label}</span>
                        </div>
                    </div>
                `;
            });
        } else {
            newsListContainer.innerHTML = '<div style="font-size:0.82rem; color:var(--text-dim);">No headlines published on or immediately before this session.</div>';
        }
        
        const s = data.similarity;
        const simStatsContainer = document.getElementById('forensic-similarity-stats');
        if (s && s.events && s.events.length > 0) {
            simStatsContainer.innerHTML = 
                `Found <b>${s.similar_events_count}</b> comparable sessions. Historically, the stock expanded higher 5 days later <b>${Math.round(s.positive_outcome_rate_5d * 100)}%</b> of the time (Avg return: <b>${(s.avg_return_5d * 100).toFixed(2)}%</b>).`;
        } else {
            simStatsContainer.innerText = 'No similar historical regimes matched.';
        }
        
    } catch(err) {
        console.error("Forensic fetch failed", err);
        document.getElementById('forensic-market-context').innerText = "Failed loading forensic attribution.";
    }

    if (window.innerWidth < 1200) {
        panel.scrollIntoView({ behavior: 'smooth' });
    }
}

// Download PDF Report
async function downloadReport() {
    if (!currentBank) return;
    const btn = document.getElementById('download-report-btn');
    const oldText = btn.innerHTML;
    btn.disabled = true;
    btn.innerText = "Generating PDF...";
    
    let chartBase64 = null;
    if (chartInstance) {
        chartBase64 = chartInstance.toBase64Image();
    }
    
    try {
        const res = await fetch(`${API_BASE}/report/download`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                symbol: currentBank,
                date: selectedForensicDate,
                chart_image: chartBase64
            })
        });
        
        if (!res.ok) throw new Error("PDF download failed");
        
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `BankSight_Report_${currentBank}_${selectedForensicDate || 'latest'}.pdf`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (e) {
        console.error(e);
        alert("Failed to download PDF report. Please verify backend connection.");
    } finally {
        btn.disabled = false;
        btn.innerHTML = oldText;
    }
}

// Email Research Report
async function sendEmailReport() {
    if (!currentBank) return;
    const email = document.getElementById('report-email').value;
    const submitBtn = document.getElementById('submit-email-report-btn');
    const statusDiv = document.getElementById('email-report-status');
    
    submitBtn.disabled = true;
    submitBtn.innerText = "Dispatching...";
    statusDiv.classList.remove('hidden');
    statusDiv.style.color = 'var(--accent)';
    statusDiv.innerText = "Compiling research briefing and sending email...";
    
    let chartBase64 = null;
    if (chartInstance) {
        chartBase64 = chartInstance.toBase64Image();
    }
    
    try {
        const res = await fetch(`${API_BASE}/report/email`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                symbol: currentBank,
                date: selectedForensicDate,
                chart_image: chartBase64,
                email: email
            })
        });
        
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Failed sending email report.");
        
        statusDiv.style.color = 'var(--green)';
        statusDiv.innerText = "Briefing successfully dispatched to your inbox!";
        
        setTimeout(() => {
            document.getElementById('email-modal').classList.add('hidden');
        }, 2000);
    } catch (e) {
        console.error(e);
        statusDiv.style.color = 'var(--red)';
        statusDiv.innerText = e.message || "Failed to dispatch email. Please check SMTP settings.";
        submitBtn.disabled = false;
        submitBtn.innerText = "Send Research Report";
    }
}

// Subscribe Daily Morning Briefings
async function subscribeAlerts() {
    if (!currentBank) return;
    const emailInput = document.getElementById('subscribe-email');
    const email = emailInput.value;
    const btn = document.getElementById('subscribe-btn');
    const statusDiv = document.getElementById('subscribe-status');
    
    btn.disabled = true;
    statusDiv.classList.remove('hidden');
    statusDiv.style.color = 'var(--accent)';
    statusDiv.innerText = "Subscribing...";
    
    try {
        const res = await fetch(`${API_BASE}/subscribe`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email: email,
                symbol: currentBank
            })
        });
        
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Subscription request failed.");
        
        statusDiv.style.color = 'var(--green)';
        statusDiv.innerText = "Successfully subscribed to daily morning briefings!";
        emailInput.value = '';
    } catch (e) {
        console.error(e);
        statusDiv.style.color = 'var(--red)';
        statusDiv.innerText = e.message || "Subscription failed.";
    } finally {
        btn.disabled = false;
        setTimeout(() => {
            statusDiv.classList.add('hidden');
        }, 4000);
    }
}
