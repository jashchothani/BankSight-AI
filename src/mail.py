"""
BankSight AI — Mail Dispatcher & Scheduler
===========================================
Handles compiling MIME emails, sending PDF reports, formatting HTML daily alerts,
and coordinating background subscription alerts.
"""

import logging
import smtplib
import threading
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import config
from src.data import Database

log = logging.getLogger("MAIL")

def send_email(to_email: str, subject: str, html_body: str, attachment_bytes: bytes = None, attachment_filename: str = None) -> bool:
    """
    Send an HTML email, optionally attaching a file (like a PDF report).
    Falls back to logging to terminal if SMTP server credentials are not configured.
    """
    # 1. Check if SMTP configuration is set
    smtp_configured = bool(config.SMTP_USER and config.SMTP_PASSWORD)
    
    if not smtp_configured:
        log.warning("--- SMTP EMAIL OUTBOX MOCK (SMTP_USER/PASSWORD NOT CONFIGURED) ---")
        log.warning(f"To: {to_email}")
        log.warning(f"Subject: {subject}")
        log.warning(f"Body Preview: {html_body[:300]}...")
        if attachment_bytes:
            log.warning(f"Attached File: {attachment_filename} ({len(attachment_bytes)} bytes)")
        log.warning("------------------------------------------------------------------")
        return True

    try:
        # Create Message container
        msg = MIMEMultipart()
        msg['From'] = config.SMTP_FROM
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # Attach HTML body
        msg.attach(MIMEText(html_body, 'html'))
        
        # Attach file if present
        if attachment_bytes and attachment_filename:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment_bytes)
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{attachment_filename}"')
            msg.attach(part)
            
        # Connect to SMTP Server
        server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
        server.starttls()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        
        # Send Email
        server.sendmail(config.SMTP_FROM, to_email, msg.as_string())
        server.quit()
        log.info(f"Successfully sent email to {to_email}")
        return True
    except Exception as e:
        log.error(f"Failed to send email to {to_email}: {e}")
        return False


def format_daily_alert_html(symbol: str, name: str, ohlcv: dict, pred_return: float, direction: str, news: list) -> str:
    """
    Generates a premium, clean HTML daily digest.
    Color codes the alert based on predicted price changes.
    """
    # Color scheme selection
    if pred_return >= 0.015:
        header_color = "#10b981"  # Vibrant Green
        alert_tag = "BULLISH ACCELERATION"
        msg_text = "Our models detect a strong positive price trend over the next 5 trading days."
    elif pred_return >= 0.0:
        header_color = "#f59e0b"  # Warm Yellow
        alert_tag = "NEUTRAL POSITIVE"
        msg_text = "Our models detect mild positive/stable movements over the next 5 trading days."
    else:
        header_color = "#ef4444"  # Alert Red
        alert_tag = "BEARISH OUTLOOK"
        msg_text = "Our models detect short-term downward pressure. Trade with caution."

    news_html = ""
    if news:
        for idx, n in enumerate(news[:3]):
            s_label = n.get("sentiment_label", "NEUTRAL")
            s_color = "#10b981" if s_label == "POSITIVE" else ("#ef4444" if s_label == "NEGATIVE" else "#6b7280")
            news_html += f"""
            <div style="margin-bottom: 12px; border-bottom: 1px solid #f1f5f9; padding-bottom: 8px;">
                <div style="font-weight: 600; font-size: 0.95rem; color: #1e293b;">
                    <a href="{n.get('url') or '#'}" target="_blank" style="color: #2563eb; text-decoration: none;">{n.get('headline')}</a>
                </div>
                <div style="font-size: 0.8rem; margin-top: 4px; color: #64748b;">
                    <span>Source: {n.get('source')}</span> | 
                    <span style="color: {s_color}; font-weight: bold;">{s_label}</span>
                </div>
            </div>
            """
    else:
        news_html = "<div style='color:#64748b; font-size:0.9rem;'>No major company-specific news updates for today.</div>"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: 'Inter', Arial, sans-serif; margin: 0; padding: 0; background-color: #f8fafc; color: #334155; }}
            .container {{ max-width: 600px; margin: 20px auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; }}
            .header {{ background-color: {header_color}; padding: 30px; text-align: center; color: white; }}
            .header h1 {{ margin: 0; font-size: 1.6rem; font-weight: 700; letter-spacing: -0.025em; }}
            .tag {{ display: inline-block; background-color: rgba(255,255,255,0.25); padding: 4px 10px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; margin-top: 8px; text-transform: uppercase; }}
            .content {{ padding: 30px; }}
            .ohlcv-grid {{ display: table; width: 100%; margin-top: 15px; margin-bottom: 20px; }}
            .ohlcv-item {{ display: table-cell; text-align: center; border-right: 1px solid #f1f5f9; }}
            .ohlcv-item:last-child {{ border-right: none; }}
            .ohlcv-lbl {{ font-size: 0.75rem; color: #64748b; text-transform: uppercase; }}
            .ohlcv-val {{ font-weight: bold; font-size: 1.1rem; color: #1e293b; margin-top: 4px; }}
            .forecast-box {{ background-color: #f8fafc; border-left: 4px solid {header_color}; padding: 15px 20px; border-radius: 4px; margin-bottom: 25px; }}
            .section-title {{ font-size: 1.1rem; font-weight: 700; margin-bottom: 12px; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 4px; }}
            .footer {{ background-color: #f1f5f9; padding: 20px; text-align: center; font-size: 0.75rem; color: #64748b; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>{name} ({symbol}.NS)</h1>
                <div class="tag">{alert_tag}</div>
            </div>
            <div class="content">
                <div class="forecast-box">
                    <div style="font-weight: bold; color: {header_color}; font-size: 1.1rem;">Expected 5D Change: {pred_return*100:+.2f}% ({direction})</div>
                    <div style="margin-top: 6px; font-size: 0.9rem; color: #475569;">{msg_text}</div>
                </div>

                <div class="section-title">Today's Market Wrap (EOD)</div>
                <div class="ohlcv-grid">
                    <div class="ohlcv-item">
                        <div class="ohlcv-lbl">Open</div>
                        <div class="ohlcv-val">₹{ohlcv.get('open', 0.0):.2f}</div>
                    </div>
                    <div class="ohlcv-item">
                        <div class="ohlcv-lbl">Close</div>
                        <div class="ohlcv-val">₹{ohlcv.get('close', 0.0):.2f}</div>
                    </div>
                    <div class="ohlcv-item">
                        <div class="ohlcv-lbl">High</div>
                        <div class="ohlcv-val">₹{ohlcv.get('high', 0.0):.2f}</div>
                    </div>
                    <div class="ohlcv-item">
                        <div class="ohlcv-lbl">Low</div>
                        <div class="ohlcv-val">₹{ohlcv.get('low', 0.0):.2f}</div>
                    </div>
                </div>

                <div class="section-title" style="margin-top: 30px;">Causal News Intelligence</div>
                {news_html}
            </div>
            <div class="footer">
                This is an automated intelligence briefing compiled by BankSight AI.<br/>
                All forecasts are driven by walk-forward ML models (XGBoost/LightGBM). Trade responsibly.<br/>
                © {datetime.now().year} BankSight AI Ltd.
            </div>
        </div>
    </body>
    </html>
    """
    return html


def run_daily_subscriptions_delivery():
    """
    Looks up active daily subscriptions, retrieves recent predictions, and dispatches alerts.
    Designed to run inside a separate background thread or worker task.
    """
    db = Database()
    subscriptions = db.get_subscriptions()
    if not subscriptions:
        log.info("No active email subscriptions found.")
        return

    log.info(f"Checking subscriptions delivery for {len(subscriptions)} users...")
    
    for sub in subscriptions:
        email = sub["email"]
        symbol = sub["symbol"]
        
        # 1. Fetch latest predictions
        pred = db.get_latest_prediction(symbol)
        if not pred:
            continue
            
        pred_return = pred.get("return_5d", 0.0)
        direction = pred.get("direction_5d", "NEUTRAL")
        
        if direction != "UP" or pred_return <= 0.0:
            log.info(f"Skipping alert for {symbol} (5D expected return: {pred_return:+.4f}%). Not an increase.")
            continue
            
        # 2. Get latest OHLCV
        md = db.get_market_data(symbol)
        if md.empty:
            continue
        latest_row = md.iloc[-1]
        ohlcv = {
            "open": float(latest_row["open"]),
            "high": float(latest_row["high"]),
            "low": float(latest_row["low"]),
            "close": float(latest_row["close"]),
        }
        
        # 3. Get latest news
        news = db.get_news(symbol, limit=3)
        
        # Get bank name
        bank_name = config.STOCKS.get(symbol, {}).get("name", symbol)
        
        # 4. Render HTML Body
        html_body = format_daily_alert_html(
            symbol=symbol,
            name=bank_name,
            ohlcv=ohlcv,
            pred_return=pred_return,
            direction=direction,
            news=news
        )
        
        # 5. Send Alert
        subject = f"BankSight Alert: Potential Increase Forecasted for {symbol} (+{pred_return*100:.2f}%)"
        send_email(email, subject, html_body)


class MailScheduler:
    """Coordinates simple background timers to run daily subscription checks."""
    
    _thread = None
    _stop_event = threading.Event()
    
    @classmethod
    def start(cls):
        if cls._thread and cls._thread.is_alive():
            return
            
        cls._stop_event.clear()
        cls._thread = threading.Thread(target=cls._loop, daemon=True)
        cls._thread.start()
        log.info("Background Mail Delivery scheduler started.")
        
    @classmethod
    def stop(cls):
        cls._stop_event.set()
        if cls._thread:
            cls._thread.join(timeout=2)
            
    @classmethod
    def _loop(cls):
        # Run alert delivery on start to verify, then run every 24 hours
        try:
            run_daily_subscriptions_delivery()
        except Exception as e:
            log.error(f"Error in startup subscriptions check: {e}")
            
        while not cls._stop_event.is_set():
            for _ in range(24):
                if cls._stop_event.is_set():
                    break
                time.sleep(3600)  # 1 hour
            
            if not cls._stop_event.is_set():
                try:
                    run_daily_subscriptions_delivery()
                except Exception as e:
                    log.error(f"Error in scheduled alerts run: {e}")


def format_report_email_html(symbol: str, name: str, date_str: str, ohlcv: dict, forecast: dict, technical: dict, market: dict, news: list) -> str:
    """
    Generates a premium, highly detailed HTML email body summarizing the stock report.
    Includes forecast numbers, detailed news list with active hyperlinks, and technical indicators.
    """
    date_lbl = date_str or datetime.now().strftime("%Y-%m-%d")
    
    # 1. Forecast horizons formatting
    horizons_html = ""
    if forecast:
        horizons_html += """
        <div style="display: table; width: 100%; margin-bottom: 25px;">
        """
        for h in [1, 3, 5, 7]:
            price = forecast.get(f"prediction_{h}d")
            direction = forecast.get(f"direction_{h}d", "NEUTRAL")
            confidence = forecast.get(f"confidence_{h}d")
            expected_ret = forecast.get(f"return_{h}d", 0.0)
            
            dir_color = "#10b981" if direction == "UP" else ("#ef4444" if direction == "DOWN" else "#f59e0b")
            
            # Safe parsing
            p_str = f"₹{price:,.2f}" if price else "--"
            ret_str = f"{expected_ret*100:+.2f}%" if expected_ret else "--%"
            conf_str = f"{confidence:.0f}%" if confidence else "--%"
            
            horizons_html += f"""
            <div style="display: table-cell; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; text-align: center; background: #fafafb; width: 22%;">
                <div style="font-size: 0.72rem; color: #64748b; font-weight: bold; text-transform: uppercase;">{h}D Forecast</div>
                <div style="font-size: 1.05rem; font-weight: bold; color: #0f172a; margin-top: 6px;">{p_str}</div>
                <div style="font-size: 0.78rem; font-weight: bold; color: {dir_color}; margin-top: 4px;">{ret_str} ({direction})</div>
                <div style="font-size: 0.7rem; color: #94a3b8; margin-top: 2px;">Conf: {conf_str}</div>
            </div>
            <div style="display: table-cell; width: 4%;"></div>
            """
        # trim last spacing
        horizons_html = horizons_html.rsplit('<div style="display: table-cell; width: 4%;"></div>', 1)[0]
        horizons_html += "</div>"
    else:
        horizons_html = "<p style='color:#64748b; font-size:0.9rem;'>Forecast predictions temporarily unavailable.</p>"

    # 2. News list with hyperlinks
    news_html = ""
    if news:
        for n in news[:5]:
            sent = n.get("sentiment_label", "NEUTRAL")
            sent_color = "#10b981" if sent == "POSITIVE" else ("#ef4444" if sent == "NEGATIVE" else "#475569")
            link = n.get("url") or "#"
            news_html += f"""
            <div style="margin-bottom: 15px; padding-bottom: 12px; border-bottom: 1px solid #f1f5f9;">
                <div style="font-size: 0.95rem; font-weight: 600; line-height: 1.4; margin-bottom: 4px;">
                    <a href="{link}" target="_blank" style="color: #2563eb; text-decoration: none; word-break: break-word;">{n.get('headline')}</a>
                </div>
                <div style="font-size: 0.78rem; color: #64748b;">
                    <span>Source: {n.get('source')}</span> | 
                    <span>Sentiment: <b style="color: {sent_color};">{sent}</b> ({n.get('sentiment_score', 0.0):+.2f})</span>
                </div>
            </div>
            """
    else:
        news_html = "<p style='color:#64748b; font-size:0.9rem;'>No major company-specific news reported during this segment.</p>"

    # 3. Technical attribution guide
    tech_html = ""
    if technical:
        rsi_val = technical.get('rsi', 50.0)
        macd_val = technical.get('macd_hist', 0.0)
        bb_pos = technical.get('bb_position', 0.5)
        vol_ma = technical.get('volume_to_ma_20', 1.0)
        
        rsi_desc = "Overbought (sell zone)" if rsi_val > 70 else ("Oversold (buy zone)" if rsi_val < 30 else "Neutral range")
        macd_desc = "Bullish trend acceleration" if macd_val > 0 else "Bearish momentum warning"
        bb_desc = "Trading above limits" if bb_pos > 1.0 else ("Trading below limits" if bb_pos < 0.0 else "Within normal range")
        vol_desc = "High trading interest" if vol_ma > 1.5 else "Average/quiet trading"
        
        tech_html += f"""
        <table style="width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.85rem;">
            <tr style="background-color: #f8fafc; border-bottom: 1px solid #e2e8f0; font-weight: bold; color: #475569;">
                <th style="text-align: left; padding: 8px;">Technical Factor</th>
                <th style="text-align: left; padding: 8px;">Value</th>
                <th style="text-align: left; padding: 8px;">Interpretation</th>
            </tr>
            <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 8px; font-weight: bold;">RSI (14)</td>
                <td style="padding: 8px; font-family: monospace;">{rsi_val:.2f}</td>
                <td style="padding: 8px; color: #475569;">{rsi_desc}</td>
            </tr>
            <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 8px; font-weight: bold;">MACD Histogram</td>
                <td style="padding: 8px; font-family: monospace;">{macd_val:.4f}</td>
                <td style="padding: 8px; color: #475569;">{macd_desc}</td>
            </tr>
            <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 8px; font-weight: bold;">Bollinger Position</td>
                <td style="padding: 8px; font-family: monospace;">{bb_pos:.2f}</td>
                <td style="padding: 8px; color: #475569;">{bb_desc}</td>
            </tr>
            <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 8px; font-weight: bold;">Relative Volume</td>
                <td style="padding: 8px; font-family: monospace;">{vol_ma:.2f}x</td>
                <td style="padding: 8px; color: #475569;">{vol_desc}</td>
            </tr>
        </table>
        """
    else:
        tech_html = "<p style='color:#64748b; font-size:0.9rem;'>Technical attribution features are not active for the latest date.</p>"

    # 4. Market returns wrap
    mkt_html = ""
    if market:
        stock_ret = market.get("stock_return_1d", 0.0) or 0.0
        nifty_ret = market.get("nifty_return_1d", 0.0) or 0.0
        bn_ret = market.get("banknifty_return_1d", 0.0) or 0.0
        mkt_html += f"""
        <div style="font-size: 0.85rem; background-color: #fafafb; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; margin-top: 10px; line-height: 1.6;">
            • <b>Stock 1D Return</b>: <span style="color: {'#10b981' if stock_ret >= 0 else '#ef4444'}; font-weight: bold;">{stock_ret*100:+.2f}%</span><br/>
            • <b>Nifty 50 Index Return</b>: <span style="color: {'#10b981' if nifty_ret >= 0 else '#ef4444'}; font-weight: bold;">{nifty_ret*100:+.2f}%</span><br/>
            • <b>Bank Nifty Index Return</b>: <span style="color: {'#10b981' if bn_ret >= 0 else '#ef4444'}; font-weight: bold;">{bn_ret*100:+.2f}%</span>
        </div>
        """
    else:
        mkt_html = "<p style='color:#64748b; font-size:0.9rem;'>Market index benchmarks are not active for the latest date.</p>"

    ohlcv_html = ""
    if ohlcv:
        ohlcv_html += f"""
        <div style="display: table; width: 100%; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; margin-top: 10px; background-color: #fafafb;">
            <div style="display: table-cell; text-align: center; border-right: 1px solid #e2e8f0; width: 20%;">
                <div style="font-size: 0.72rem; color: #64748b; text-transform: uppercase;">Open</div>
                <div style="font-size: 0.95rem; font-weight: bold; color: #0f172a; margin-top: 4px;">₹{ohlcv.get('open', 0.0):,.2f}</div>
            </div>
            <div style="display: table-cell; text-align: center; border-right: 1px solid #e2e8f0; width: 20%;">
                <div style="font-size: 0.72rem; color: #64748b; text-transform: uppercase;">Close</div>
                <div style="font-size: 0.95rem; font-weight: bold; color: #0f172a; margin-top: 4px;">₹{ohlcv.get('close', 0.0):,.2f}</div>
            </div>
            <div style="display: table-cell; text-align: center; border-right: 1px solid #e2e8f0; width: 20%;">
                <div style="font-size: 0.72rem; color: #64748b; text-transform: uppercase;">High</div>
                <div style="font-size: 0.95rem; font-weight: bold; color: #0f172a; margin-top: 4px;">₹{ohlcv.get('high', 0.0):,.2f}</div>
            </div>
            <div style="display: table-cell; text-align: center; border-right: 1px solid #e2e8f0; width: 20%;">
                <div style="font-size: 0.72rem; color: #64748b; text-transform: uppercase;">Low</div>
                <div style="font-size: 0.95rem; font-weight: bold; color: #0f172a; margin-top: 4px;">₹{ohlcv.get('low', 0.0):,.2f}</div>
            </div>
            <div style="display: table-cell; text-align: center; width: 20%;">
                <div style="font-size: 0.72rem; color: #64748b; text-transform: uppercase;">Volume</div>
                <div style="font-size: 0.95rem; font-weight: bold; color: #0f172a; margin-top: 4px;">{ohlcv.get('volume', 0):,}</div>
            </div>
        </div>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="font-family: 'Inter', Arial, sans-serif; background-color: #f8fafc; color: #334155; margin: 0; padding: 0; line-height: 1.5;">
        <div style="max-width: 650px; margin: 20px auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
            <div style="background-color: #0f172a; padding: 24px; color: #ffffff; text-align: center;">
                <h1 style="margin: 0; font-size: 1.45rem; font-weight: 700; letter-spacing: -0.02em;">BankSight AI Research Briefing</h1>
                <div style="font-size: 0.85rem; color: #94a3b8; margin-top: 4px;">{name} ({symbol}.NS) | Reference Date: {date_lbl}</div>
            </div>
            
            <div style="padding: 24px;">
                <p style="font-size: 0.9rem; color: #475569; margin-top: 0; margin-bottom: 20px;">
                    Here is your compiled market-intelligence digest for <b>{name}</b>. A complete visual PDF report containing timeline charts, out-of-sample metrics, and historical similarity plots is also attached to this email.
                </p>

                <div style="font-size: 1rem; font-weight: bold; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 4px; margin-bottom: 12px;">Model Prediction Horizon Outlook</div>
                {horizons_html}

                {"<div style='font-size: 1rem; font-weight: bold; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 4px; margin-bottom: 12px; margin-top: 25px;'>Point-in-Time Forensic Wrap</div>" if (ohlcv or technical or market) else ""}
                {ohlcv_html}
                {mkt_html}
                {tech_html}

                <div style="font-size: 1rem; font-weight: bold; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 4px; margin-bottom: 12px; margin-top: 30px;">Causal News & Market Intelligence (Hyperlinked)</div>
                <div style="font-size: 0.82rem; color: #64748b; margin-bottom: 12px;">Click headlines to read full news articles directly on their publisher's pages:</div>
                {news_html}
            </div>

            <div style="background-color: #f1f5f9; padding: 20px; text-align: center; font-size: 0.72rem; color: #64748b;">
                This automated briefing was compiled by BankSight AI using live stock market and news data.<br/>
                Predictions are generated using walk-forward ML ensembles. Past performance does not guarantee future results.<br/>
                © {datetime.now().year} BankSight AI. For research purposes only.
            </div>
        </div>
    </body>
    </html>
    """
    return html
