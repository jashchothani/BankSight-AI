// BankSight AI Dashboard Logic

const API_BASE = '/api';
let currentBank = null;
let currentBankName = "";
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

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    fetchHealth();
    fetchMarket();
    fetchBanks();
    
    // Attach action listeners
    const dlBtn = document.getElementById('download-report-btn');
    if (dlBtn) dlBtn.addEventListener('click', downloadReport);
    
    const emailReportBtn = document.getElementById('email-report-btn');
    if (emailReportBtn) {
        emailReportBtn.addEventListener('click', () => {
            // Reset captcha and form
            document.getElementById('report-email').value = '';
            document.getElementById('captcha-checkbox').checked = false;
            document.getElementById('captcha-challenge-box').classList.add('hidden');
            document.getElementById('captcha-answer').value = '';
            document.getElementById('submit-email-report-btn').disabled = true;
            document.getElementById('email-report-status').classList.add('hidden');
            
            // Show modal
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
                // Generate simple math captcha question (X + Y)
                captchaNum1 = Math.floor(Math.random() * 9) + 1;
                captchaNum2 = Math.floor(Math.random() * 9) + 1;
                document.getElementById('captcha-question').innerText = `${captchaNum1} + ${captchaNum2}`;
                
                challengeBox.classList.remove('hidden');
                document.getElementById('captcha-answer').focus();
            } else {
                challengeBox.classList.add('hidden');
                document.getElementById('captcha-answer').value = '';
            }
            submitBtn.disabled = true; // Stay disabled until answer validated
        });
    }
    
    // Captcha dynamic answer input validation
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
    
    // Daily alert alerts subscription form
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
    
    // Auto-refresh from database every 60 seconds (for updates like news/ML retraining)
    setInterval(() => {
        fetchHealth(); // refresh market status too
        fetchMarket();
        if (currentBank) {
            updateDashboard(currentBank, currentBankName, false);
        } else {
            fetchBanks();
        }
    }, 60000);

    // Dynamic tick-by-tick real-time simulator (every 2.5 seconds)
    startRealTimeTickSim();
});

// Utilities
const formatPrice = (val) => val != null ? '₹' + val.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '--';
const formatPct = (val) => val != null ? (val * 100).toFixed(2) + '%' : '--';
const colorClass = (val) => {
    if (val > 0) return 'positive';
    if (val < 0) return 'negative';
    return 'neutral';
};
const sign = (val) => val > 0 ? '+' : '';

// Start the real-time simulator
function startRealTimeTickSim() {
    if (tickInterval) clearInterval(tickInterval);
    tickInterval = setInterval(() => {
        if (marketStatus !== 'OPEN') return; // Do not fluctuate prices if market is closed!
        if (!currentBank || !livePrices[currentBank]) return;
        
        // Random fluctuation between -0.04% and +0.04%
        const pct = (Math.random() * 0.08 - 0.04) / 100;
        const oldPrice = livePrices[currentBank];
        const newPrice = oldPrice * (1 + pct);
        livePrices[currentBank] = newPrice;

        // Apply price flashing on header
        const priceEl = document.getElementById('detail-price');
        if (priceEl) {
            priceEl.innerText = formatPrice(newPrice);
            // Trigger animation
            priceEl.classList.remove('price-tick-up', 'price-tick-down');
            void priceEl.offsetWidth; // trigger reflow
            if (newPrice > oldPrice) {
                priceEl.classList.add('price-tick-up');
            } else if (newPrice < oldPrice) {
                priceEl.classList.add('price-tick-down');
            }
        }

        // Update corresponding bank item in the list
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

        // Live update the chart's last historical point to match the ticker
        if (chartInstance && cachedHistory && cachedHistory.length > 0) {
            // Update the last element close price
            const lastIdx = cachedHistory.length - 1;
            chartInstance.data.datasets[0].data[lastIdx] = newPrice;
            
            // Connect prediction starting point to the new price
            if (chartInstance.data.datasets[1].data[lastIdx] !== null) {
                chartInstance.data.datasets[1].data[lastIdx] = newPrice;
            }
            chartInstance.update('none'); // Update without full reload animation
        }
    }, 2500);
}

// --- API Calls ---

async function fetchHealth() {
    try {
        const res = await fetch(`${API_BASE}/health`);
        const data = await res.json();
        
        const errorBanner = document.getElementById('error-banner');
        if (errorBanner) {
            if (data.data_status && data.data_status.market === 'error') {
                errorBanner.classList.remove('hidden');
            } else {
                errorBanner.classList.add('hidden');
            }
        }
        
        marketStatus = data.market_status || "CLOSED";
        const marketStatusTextEl = document.getElementById('market-status-text');
        if (marketStatusTextEl) {
            marketStatusTextEl.innerText = marketStatus;
        }
        
        const statusMarketOpenEl = document.getElementById('status-market-open');
        if (statusMarketOpenEl) {
            if (marketStatus === 'OPEN') {
                statusMarketOpenEl.className = 'dot green';
            } else {
                statusMarketOpenEl.className = 'dot red';
            }
        }
        
        const ds = data.data_status;
        const setStatus = (id, status) => {
            const el = document.getElementById(id);
            if (!el) return;
            if(status === 'connected') { el.className = 'dot green'; }
            else if(status === 'error') { el.className = 'dot red'; }
            else { el.className = 'dot'; }
        };
        
        setStatus('status-market', ds.market);
        setStatus('status-news', ds.news);
        setStatus('status-model', 'connected'); 
        
        const timeStr = new Date().toLocaleTimeString();
        document.getElementById('last-update-time').innerText = timeStr;
    } catch (e) {
        console.error("Health check failed", e);
        const errorBanner = document.getElementById('error-banner');
        if (errorBanner) errorBanner.classList.remove('hidden');
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

async function fetchBanks() {
    try {
        const res = await fetch(`${API_BASE}/banks`);
        const data = await res.json();
        
        const container = document.getElementById('bank-list');
        container.innerHTML = '';
        
        data.forEach(b => {
            // Save to live prices
            if (!livePrices[b.symbol]) {
                livePrices[b.symbol] = b.current_price;
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
                    <div class="bi-name">${b.name}</div>
                    <div class="bi-price">${formatPrice(livePrices[b.symbol])}</div>
                </div>
                <div class="bi-foot">
                    <div>5D: <span class="${colorClass(b.expected_return)}">${sign(b.expected_return)}${formatPct(b.expected_return)}</span></div>
                    <div class="f-dir-tag ${b.direction || ''}">${b.direction || 'WAIT'}</div>
                </div>
            `;
            container.appendChild(el);
        });
        
        // Auto-select first bank if none selected
        if (!currentBank && data.length > 0) {
            document.querySelector('.bank-item').click();
        }
    } catch (e) {
        console.error("Banks fetch failed", e);
    }
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
            
            // Set current price in real-time tracker if empty or selection changed
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
                card.querySelector('.f-ret').innerText = `${sign(expectedRet)}${formatPct(expectedRet)} (${direction})`;
                card.querySelector('.f-ret').className = `f-ret ${colorClass(expectedRet)}`;
                card.querySelector('.f-conf').innerText = confidence ? `Conf: ${confidence.toFixed(0)}%` : '--';
                
                // Color card based on direction
                card.className = 'f-card';
                if (direction === 'UP') card.classList.add('up');
                else if (direction === 'DOWN') card.classList.add('down');
                else card.classList.add('neutral-state');
            });
            
            cachedForecast = f;
            cachedHistory = data.history;
            renderChart(data.history, f, animateChart);
        }
    } catch(e) { console.error(e); }
    
    // 2. Explanation
    try {
        const res = await fetch(`${API_BASE}/explanation/${symbol}`);
        if(res.ok) {
            const data = await res.json();
            const container = document.getElementById('shap-container');
            container.innerHTML = '';
            
            if(data.shap && !data.shap.error) {
                data.shap.top_positive.forEach(f => {
                    container.innerHTML += `<div class="shap-item pos"><span class="shap-feat">${f.feature}</span> <span>+${f.impact.toFixed(4)}</span></div>`;
                });
                data.shap.top_negative.forEach(f => {
                    container.innerHTML += `<div class="shap-item neg"><span class="shap-feat">${f.feature}</span> <span>${f.impact.toFixed(4)}</span></div>`;
                });
            } else {
                container.innerHTML = `<div class="placeholder">Explainability data unavailable</div>`;
            }
            
            document.getElementById('narrative-container').innerText = data.narrative || '';
        }
    } catch(e) { console.error(e); }
    
    // 3. News
    try {
        const res = await fetch(`${API_BASE}/news/${symbol}`);
        if(res.ok) {
            const news = await res.json();
            const container = document.getElementById('news-list');
            container.innerHTML = '';
            news.slice(0, 5).forEach(n => {
                const sCls = n.sentiment_label === 'POSITIVE' ? 'pos' : (n.sentiment_label === 'NEGATIVE' ? 'neg' : '');
                container.innerHTML += `
                    <div class="news-item">
                        <div class="n-head">${n.headline}</div>
                        <div class="n-foot">
                            <span>${n.source}</span>
                            <span class="n-sent ${sCls}">${n.sentiment_label}</span>
                        </div>
                    </div>
                `;
            });
        }
    } catch(e) { console.error(e); }
    
    // 4. Events
    try {
        const res = await fetch(`${API_BASE}/events/${symbol}`);
        if(res.ok) {
            const events = await res.json();
            const container = document.getElementById('events-container');
            if (events.events && events.events.length > 0) {
                container.innerHTML = `<div style="font-size:0.85rem;margin-bottom:10px;color:var(--text-muted);">Found ${events.similar_events_count} similar historical scenarios. Historically, 5D return was positive ${Math.round(events.positive_outcome_rate_5d*100)}% of the time (Avg: ${(events.avg_return_5d*100).toFixed(2)}%).</div>`;
                events.events.slice(0,3).forEach(e => {
                    container.innerHTML += `
                        <div class="event-item">
                            <div class="e-date">${e.date} (Sim: ${(e.similarity*100).toFixed(0)}%)</div>
                            <div>Followed by 5D Return: <span class="${colorClass(e.return_5d)}">${sign(e.return_5d)}${formatPct(e.return_5d)}</span></div>
                        </div>
                    `;
                });
            } else {
                container.innerHTML = `<div class="placeholder">No similar historical events found.</div>`;
            }
        }
    } catch(e) { console.error(e); }
    
    // 5. Performance
    fetch(`${API_BASE}/model/performance`).then(r => r.json()).then(data => {
        let m = 'Evaluating...';
        if(data.model_stats && data.model_stats.length > 0) {
            const stat = data.model_stats[0]; // Just show first for UI
            m = `Algorithm: ${stat.algorithm} | MAE: ${stat.mae.toFixed(4)}`;
        }
        document.getElementById('perf-metrics').innerText = m;
    }).catch(e=>{});
}

function renderChart(history, forecast, animate = true) {
    const ctx = document.getElementById('forecastChart').getContext('2d');
    
    if (chartInstance) {
        chartInstance.destroy();
    }
    
    if (!history || history.length === 0) return;
    
    const labels = history.map(h => h.date);
    const data = history.map(h => h.close);
    
    // Add future labels (+1D to +7D)
    labels.push('+1D', '+2D', '+3D', '+4D', '+5D', '+6D', '+7D');
    
    // Historical dataset: padded with nulls so it stops at current price
    const histData = [...data];
    for (let i = 0; i < 7; i++) histData.push(null);
    
    // Forecast dataset: starts with nulls for all historical points except the last one
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
    
    // Color determined by 5D prediction direction
    const color = forecast.direction_5d === 'UP' ? '#10b981' : (forecast.direction_5d === 'DOWN' ? '#ef4444' : '#f59e0b');
    
    Chart.defaults.color = '#64748b';
    Chart.defaults.font.family = 'Inter';
    
    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Historical Price',
                    data: histData,
                    borderColor: '#3b82f6',
                    borderWidth: 2,
                    tension: 0.1,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointHitRadius: 12,
                    fill: false
                },
                {
                    label: 'Forecast Path',
                    data: predData,
                    borderColor: color,
                    borderWidth: 3,
                    borderDash: [5, 5],
                    tension: 0.1,
                    pointRadius: 6,
                    pointBackgroundColor: color,
                    pointHoverRadius: 8,
                    spanGaps: true // Crucial: draws straight line across nulls
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
                    if (index < cachedHistory.length) {
                        const clickedDate = cachedHistory[index].date;
                        triggerForensicAnalysis(currentBank, clickedDate);
                    }
                }
            },
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: { 
                    grid: { color: '#f1f5f9' },
                    ticks: { color: '#64748b' }
                },
                y: { 
                    grid: { color: '#f1f5f9' },
                    ticks: { color: '#64748b' }
                }
            },
            interaction: {
                intersect: false,
                mode: 'index',
            }
        }
    });
}

async function triggerForensicAnalysis(symbol, date) {
    selectedForensicDate = date;
    const panel = document.getElementById('forensic-panel');
    if (!panel) return;
    
    panel.classList.remove('hidden');
    document.getElementById('forensic-date').innerText = date;
    
    // Set elements to loading state
    document.getElementById('forensic-open').innerText = "Loading...";
    document.getElementById('forensic-close').innerText = "Loading...";
    document.getElementById('forensic-high').innerText = "Loading...";
    document.getElementById('forensic-low').innerText = "Loading...";
    document.getElementById('forensic-volume').innerText = "Loading...";
    document.getElementById('forensic-market-context').innerText = "Loading...";
    document.getElementById('forensic-tech-list').innerHTML = "<li>Loading...</li>";
    document.getElementById('forensic-news-list').innerHTML = "<div>Loading...</div>";
    document.getElementById('forensic-similarity-stats').innerText = "Loading...";
    
    try {
        const res = await fetch(`${API_BASE}/explain/historical?symbol=${symbol}&date=${date}`);
        if (!res.ok) throw new Error("Forensic query failed");
        
        const data = await res.json();
        
        // Populate OHLCV
        const o = data.ohlcv;
        document.getElementById('forensic-open').innerText = formatPrice(o.open);
        document.getElementById('forensic-close').innerText = formatPrice(o.close);
        document.getElementById('forensic-high').innerText = formatPrice(o.high);
        document.getElementById('forensic-low').innerText = formatPrice(o.low);
        document.getElementById('forensic-volume').innerText = o.volume ? o.volume.toLocaleString('en-IN') : '--';
        
        // Populate market context
        const m = data.market;
        const stockPct = formatPct(m.stock_return_1d);
        const niftyPct = formatPct(m.nifty_return_1d);
        const bankniftyPct = formatPct(m.banknifty_return_1d);
        
        let attributionText = `Stock moved ${sign(m.stock_return_1d)}${stockPct} on this day. `;
        attributionText += `Nifty 50 changed ${sign(m.nifty_return_1d)}${niftyPct}, and Bank Nifty changed ${sign(m.banknifty_return_1d)}${bankniftyPct}.<br/><br/>`;
        
        // Explain logic
        const threshold = 0.015;
        if (Math.abs(m.nifty_return_1d) >= threshold && Math.sign(m.stock_return_1d) === Math.sign(m.nifty_return_1d)) {
            attributionText += `<b>Primary attribution: Broader Market Influence.</b> The stock aligned closely with general index movements.`;
        } else if (Math.abs(m.banknifty_return_1d) >= threshold && Math.sign(m.stock_return_1d) === Math.sign(m.banknifty_return_1d)) {
            attributionText += `<b>Primary attribution: Sector-Driven Influence.</b> Movement was aligned with the banking sector index.`;
        } else if (Math.abs(m.stock_return_1d - m.banknifty_return_1d) >= 0.02) {
            attributionText += `<b>Primary attribution: Stock-Specific Event.</b> Significant divergence from the banking sector indicates company-specific announcements or reports.`;
        } else {
            attributionText += `<b>Primary attribution: Normal trading fluctuation/mixed indicators.</b>`;
        }
        document.getElementById('forensic-market-context').innerHTML = attributionText;
        
        // Populate Technicals
        const t = data.technical;
        const techList = document.getElementById('forensic-tech-list');
        techList.innerHTML = '';
        if (t && t.rsi) {
            let rsiExplain = "Neutral buying momentum";
            if (t.rsi > 70) rsiExplain = "Stock is Overbought (heavy buying, price might drop/reverse soon)";
            else if (t.rsi < 30) rsiExplain = "Stock is Oversold (heavy selling, ripe for a rebound/recovery soon)";
            techList.innerHTML += `<li><b>RSI (Buying Momentum)</b>: <span>${t.rsi.toFixed(2)}</span> — ${rsiExplain}.</li>`;
            
            let macdExplain = "Neutral short-term momentum";
            if (t.macd_hist > 0.0001) macdExplain = "Bullish momentum (price trend is shifting upwards, suggesting buying interest is accelerating)";
            else if (t.macd_hist < -0.0001) macdExplain = "Bearish momentum (price trend is shifting downwards, suggesting selling pressure is accelerating)";
            techList.innerHTML += `<li><b>MACD (Trend Shifts)</b>: <span>${t.macd_hist.toFixed(4)}</span> — ${macdExplain}.</li>`;
            
            let bbExplain = "Normal range";
            if (t.bb_position > 1.0) bbExplain = "Above upper range (unusually high price)";
            else if (t.bb_position < 0.0) bbExplain = "Below lower range (unusually low price)";
            techList.innerHTML += `<li><b>Bollinger Position (Price relative to average)</b>: <span>${t.bb_position.toFixed(2)}</span> — ${bbExplain}.</li>`;
            
            techList.innerHTML += `<li><b>Trading Volume</b>: <span>${t.volume_to_ma_20.toFixed(2)}x standard volume</span> — shows investor interest compared to 20-day average.</li>`;
        } else {
            techList.innerHTML = '<li>Technical indicators are calculated after setup completes.</li>';
        }
        
        // Populate News
        const newsListContainer = document.getElementById('forensic-news-list');
        newsListContainer.innerHTML = '';
        if (data.news && data.news.length > 0) {
            data.news.forEach(n => {
                const sCls = n.sentiment_label === 'POSITIVE' ? 'pos' : (n.sentiment_label === 'NEGATIVE' ? 'neg' : '');
                newsListContainer.innerHTML += `
                    <div class="forensic-news-item">
                        <div class="forensic-news-title">${n.headline}</div>
                        <div class="forensic-news-meta">
                            <span>Source: ${n.source}</span>
                            <span class="n-sent ${sCls}">${n.sentiment_label}</span>
                        </div>
                    </div>
                `;
            });
        } else {
            newsListContainer.innerHTML = '<div style="font-size:0.82rem;color:var(--text-muted);">No news published on or just before this date.</div>';
        }
        
        // Populate Similarity
        const s = data.similarity;
        const simStatsContainer = document.getElementById('forensic-similarity-stats');
        if (s && s.events && s.events.length > 0) {
            let simText = `Similarity engine identified <b>${s.similar_events_count}</b> comparable historical states. `;
            simText += `Following these analog states, the stock rose 5 days later <b>${Math.round(s.positive_outcome_rate_5d*100)}%</b> of the time, `;
            simText += `yielding an average post-event return of <b>${(s.avg_return_5d*100).toFixed(2)}%</b>.`;
            simStatsContainer.innerHTML = simText;
        } else {
            simStatsContainer.innerText = 'No similar historical market states matched.';
        }
        
    } catch(err) {
        console.error("Forensic fetch failed", err);
        document.getElementById('forensic-market-context').innerText = "Failed loading forensic attribution.";
    }
}

async function downloadReport() {
    if (!currentBank) return;
    const btn = document.getElementById('download-report-btn');
    const oldText = btn.innerHTML;
    btn.disabled = true;
    btn.innerText = "Downloading...";
    
    let chartBase64 = null;
    if (chartInstance) {
        chartBase64 = chartInstance.toBase64Image();
    }
    
    try {
        const res = await fetch(`${API_BASE}/report/download`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
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
        alert("Failed to download PDF report. Please verify data connection.");
    } finally {
        btn.disabled = false;
        btn.innerHTML = oldText;
    }
}

async function sendEmailReport() {
    if (!currentBank) return;
    const email = document.getElementById('report-email').value;
    const submitBtn = document.getElementById('submit-email-report-btn');
    const statusDiv = document.getElementById('email-report-status');
    
    submitBtn.disabled = true;
    submitBtn.innerText = "Sending...";
    statusDiv.classList.remove('hidden');
    statusDiv.style.color = '#3b82f6';
    statusDiv.innerText = "Compiling report and sending email...";
    
    let chartBase64 = null;
    if (chartInstance) {
        chartBase64 = chartInstance.toBase64Image();
    }
    
    try {
        const res = await fetch(`${API_BASE}/report/email`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                symbol: currentBank,
                date: selectedForensicDate,
                chart_image: chartBase64,
                email: email
            })
        });
        
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Failed sending email report.");
        
        statusDiv.style.color = '#10b981';
        statusDiv.innerText = "Report successfully sent to your inbox!";
        
        setTimeout(() => {
            document.getElementById('email-modal').classList.add('hidden');
        }, 2000);
    } catch (e) {
        console.error(e);
        statusDiv.style.color = '#ef4444';
        statusDiv.innerText = e.message || "Failed to send report email. Please check server configuration.";
        submitBtn.disabled = false;
        submitBtn.innerText = "Send Report";
    }
}

async function subscribeAlerts() {
    if (!currentBank) return;
    const emailInput = document.getElementById('subscribe-email');
    const email = emailInput.value;
    const btn = document.getElementById('subscribe-btn');
    const statusDiv = document.getElementById('subscribe-status');
    
    btn.disabled = true;
    statusDiv.classList.remove('hidden');
    statusDiv.style.color = '#3b82f6';
    statusDiv.innerText = "Subscribing...";
    
    try {
        const res = await fetch(`${API_BASE}/subscribe`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                email: email,
                symbol: currentBank
            })
        });
        
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Subscription request failed.");
        
        statusDiv.style.color = '#10b981';
        statusDiv.innerText = "Successfully subscribed to daily alerts!";
        emailInput.value = '';
    } catch (e) {
        console.error(e);
        statusDiv.style.color = '#ef4444';
        statusDiv.innerText = e.message || "Subscription failed.";
    } finally {
        btn.disabled = false;
        setTimeout(() => {
            statusDiv.classList.add('hidden');
        }, 4000);
    }
}
