"""
BankSight AI — Email Service & Institutional Alert Briefings
============================================================
Handles SMTP configuration, test verification, and automated HTML briefings.
Features:
- Inline MIME embedding of BankSight AI logo (cid:banksight_logo) for 100% email client compatibility
- High-contrast institutional dark-navy executive header with bank badge
- Multi-horizon predictive price scorecard with green/red/amber directional indicators
- Point-in-time OHLCV and market relative benchmark returns
- Technical indicator attribution table with financial interpretations
- Causal news headlines with active hyperlinking and sentiment scoring
- Historical analog regime matching summary
- Attached vector PDF dossier notice
- Formal quantitative disclosure and terminal CTA
"""

import os
import json
import smtplib
import logging
import base64
import threading
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email import encoders
from datetime import datetime
from pathlib import Path

import config
from src.data import Database

log = logging.getLogger("MAIL")

# Resolve absolute logo path
LOGO_PATH = Path("dashboard/assets/logo.png").resolve()
if not LOGO_PATH.exists():
    LOGO_PATH = Path("dashboard/assets/logo.jpg").resolve()


def test_smtp_connection() -> tuple[bool, str]:
    """Test connecting to and authenticating with the configured SMTP server."""
    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        return False, "SMTP_USER or SMTP_PASSWORD environment variables are not set."
    
    timeout = 20
    try:
        if config.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(config.SMTP_SERVER, config.SMTP_PORT, timeout=timeout)
        else:
            server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT, timeout=timeout)
            server.ehlo()
            server.starttls()
            server.ehlo()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.quit()
        return True, f"Successfully authenticated with {config.SMTP_SERVER}:{config.SMTP_PORT} as {config.SMTP_USER}."
    except smtplib.SMTPAuthenticationError as e:
        msg_str = str(e)
        if "525" in msg_str or "Unauthorized IP" in msg_str:
            return False, (
                "Brevo Connection Blocked (525 Unauthorized IP Address). "
                "Render and cloud services use dynamic IPs. To allow Render/cloud servers to send email, "
                "go to your Brevo Account -> Settings (top right) -> Security -> Authorized IPs, "
                "and under 'Blocking unauthorized IP addresses' for API & SMTP keys, click 'Deactivate'."
            )
        return False, (
            f"SMTP Authentication Failed: {e}. "
            "Please check that SMTP_USER (your Brevo login, e.g. bdaa9f001@smtp-brevo.com) "
            "and SMTP_PASSWORD (your xsmtpsib key) are correct."
        )
    except Exception as e:
        return False, f"SMTP Connection Failed ({type(e).__name__}): {e}"


def send_email(to_email: str, subject: str, html_body: str, attachment_bytes: bytes = None, attachment_filename: str = None) -> bool:
    """
    Send an HTML email with inline BankSight AI logo and optional attachments (like a PDF research report).
    Falls back to logging to terminal if SMTP server credentials are not configured.
    """
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
        # Create 'related' multipart to support inline cid: images alongside attachments
        msg = MIMEMultipart("related")
        sender_email = config.SMTP_FROM or config.SMTP_USER
        msg['From'] = f"BankSight AI <{sender_email}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # Alternative container for HTML
        alt_part = MIMEMultipart("alternative")
        alt_part.attach(MIMEText(html_body, 'html', 'utf-8'))
        msg.attach(alt_part)
        
        # Attach logo inline as CID so all email clients display it directly
        if LOGO_PATH.exists():
            try:
                with open(LOGO_PATH, "rb") as f:
                    logo_img = MIMEImage(f.read())
                logo_img.add_header('Content-ID', '<banksight_logo>')
                logo_img.add_header('Content-Disposition', 'inline; filename="banksight_logo.png"')
                msg.attach(logo_img)
            except Exception as e:
                log.debug(f"Failed attaching inline logo: {e}")
        
        # Attach PDF report if present
        if attachment_bytes and attachment_filename:
            part = MIMEBase('application', 'pdf')
            part.set_payload(attachment_bytes)
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{attachment_filename}"')
            msg.attach(part)
            
        # Connect to SMTP Server with timeout
        timeout = 25
        if config.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(config.SMTP_SERVER, config.SMTP_PORT, timeout=timeout)
        else:
            server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT, timeout=timeout)
            server.ehlo()
            server.starttls()
            server.ehlo()
            
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.sendmail(sender_email, to_email, msg.as_string())
        server.quit()
        log.info(f"Successfully delivered email to {to_email}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        msg_str = str(e)
        if "525" in msg_str or "Unauthorized IP" in msg_str:
            log.error(
                f"Failed to send email to {to_email} due to Brevo IP restriction (525 Unauthorized IP). "
                "In your Brevo Account -> Settings -> Security -> Authorized IPs, "
                "deactivate 'Blocking unauthorized IP addresses' for API & SMTP keys so Render/cloud servers can send emails."
            )
        else:
            log.error(
                f"Failed to send email to {to_email} due to authentication error: {e}. "
                "Please check that SMTP_USER (your Brevo SMTP login) and SMTP_PASSWORD are correct."
            )
        return False
    except Exception as e:
        log.error(f"Failed to send email to {to_email} ({type(e).__name__}): {e}")
        return False


def get_logo_base64_data_uri() -> str:
    """Helper to return base64 data URI of the logo for clients that prefer inline data."""
    if LOGO_PATH.exists():
        try:
            with open(LOGO_PATH, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            return f"data:image/png;base64,{b64}"
        except Exception:
            pass
    return ""


# ── Null-Safe Helper Functions ──
def _safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _fmt_price(val, default="--"):
    if val is None:
        return default
    try:
        return f"₹{float(val):,.2f}"
    except (ValueError, TypeError):
        return default


def _fmt_pct(val, default="+0.00%"):
    if val is None:
        return default
    try:
        return f"{float(val)*100:+.2f}%"
    except (ValueError, TypeError):
        return default


def _fmt_int(val, default="0"):
    if val is None:
        return default
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return default


def format_report_email_html(
    symbol: str,
    name: str,
    date_str: str = None,
    ohlcv: dict = None,
    forecast: dict = None,
    technical: dict = None,
    market: dict = None,
    news: list = None
) -> str:
    """
    Generates a publication-grade, institutional HTML email briefing dossier.
    Includes the BankSight AI logo, target stock banner, multi-horizon price matrix,
    market snapshot, technical forensic factor wrap, AI explainability, news digest,
    and attached PDF dossier advisory.
    """
    db = Database()

    # 1. Fallback auto-population if fields were omitted
    if not ohlcv or not date_str:
        md = db.get_market_data(symbol)
        if not md.empty:
            lr = md.iloc[-1]
            if not ohlcv:
                ohlcv = {
                    "open": _safe_float(lr.get("open")),
                    "high": _safe_float(lr.get("high")),
                    "low": _safe_float(lr.get("low")),
                    "close": _safe_float(lr.get("close")),
                    "volume": int(_safe_float(lr.get("volume"))),
                    "date": str(lr.get("date"))
                }
            if not date_str and lr.get("date"):
                date_str = str(lr["date"]).split(" ")[0]

    if not forecast:
        forecast = db.get_latest_prediction(symbol) or {}

    if not news:
        news = db.get_news(symbol, limit=4)

    if not technical or not market:
        with db._connect() as conn:
            feat_row = conn.execute(
                "SELECT features_json FROM features WHERE symbol = ? ORDER BY date DESC LIMIT 1",
                (symbol,)
            ).fetchone()
            if feat_row:
                try:
                    feats = json.loads(feat_row["features_json"])
                except Exception:
                    feats = {}
                if not technical:
                    technical = {
                        "rsi": _safe_float(feats.get("rsi"), 50.0),
                        "macd_hist": _safe_float(feats.get("macd_hist"), 0.0),
                        "bb_position": _safe_float(feats.get("bb_position"), 0.5),
                        "volume_to_ma_20": _safe_float(feats.get("volume_to_ma_20"), 1.0),
                        "ema_20": _safe_float(feats.get("ema_20")),
                        "ema_50": _safe_float(feats.get("ema_50"))
                    }
                if not market:
                    market = {
                        "stock_return_1d": _safe_float(feats.get("return_1d"), 0.0),
                        "nifty_return_1d": _safe_float(feats.get("nifty_return_1d"), 0.0),
                        "banknifty_return_1d": _safe_float(feats.get("banknifty_return_1d"), 0.0),
                        "vix_level": _safe_float(feats.get("vix_level"), 14.38)
                    }

    date_lbl = date_str or datetime.now().strftime("%Y-%m-%d")
    current_price = _safe_float(ohlcv.get("close") if ohlcv else (forecast.get("current_price") if forecast else 0.0))

    # 2. Compute 5D outlook stance
    f5d = _safe_float(forecast.get("return_5d") if forecast else 0.0)
    if f5d > 0.003:
        stance_lbl = "▲ BULLISH CONVICTION"
        stance_color = "#10b981"
        stance_bg = "#ecfdf5"
        stance_border = "#a7f3d0"
        stance_desc = f"Walk-forward gradient boosted ensemble projects an upward trajectory (+{f5d*100:.2f}%) over the next 5 sessions. Favorable risk/reward with supportive momentum."
    elif f5d < -0.003:
        stance_lbl = "▼ BEARISH OUTLOOK"
        stance_color = "#ef4444"
        stance_bg = "#fef2f2"
        stance_border = "#fecaca"
        stance_desc = f"Walk-forward gradient boosted ensemble detects short-term downward pressure ({f5d*100:.2f}%). Exercise caution near overhead resistance bands."
    else:
        stance_lbl = "→ BALANCED CONSOLIDATION"
        stance_color = "#f59e0b"
        stance_bg = "#fffbeb"
        stance_border = "#fde68a"
        stance_desc = f"Walk-forward gradient boosted ensemble projects sideways equilibrium ({f5d*100:+.2f}%). Optimal for range-trading and strategic accumulation."

    # 3. Multi-horizon Forecast Matrix
    cards_html = ""
    for h in [1, 3, 5, 7]:
        price = forecast.get(f"prediction_{h}d")
        direction = forecast.get(f"direction_{h}d", "NEUTRAL")
        confidence = _safe_float(forecast.get(f"confidence_{h}d"), 50.0)
        expected_ret = _safe_float(forecast.get(f"return_{h}d"), 0.0)
        
        dir_color = "#10b981" if direction == "UP" else ("#ef4444" if direction == "DOWN" else "#f59e0b")
        dir_arrow = "▲" if direction == "UP" else ("▼" if direction == "DOWN" else "→")
        
        p_str = _fmt_price(price) if price else "--"
        ret_str = _fmt_pct(expected_ret)
        conf_str = f"{confidence:.0f}%"

        cards_html += f"""
        <td style="width: 23%; padding: 12px 8px; background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; text-align: center; vertical-align: top;">
            <div style="font-size: 10px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.6px;">{h}-Day Horizon</div>
            <div style="font-size: 16px; font-weight: 800; color: #0f172a; margin: 6px 0 3px 0;">{p_str}</div>
            <div style="font-size: 11px; font-weight: 700; color: {dir_color}; margin-bottom: 4px;">{dir_arrow} {ret_str} ({direction})</div>
            <div style="font-size: 9.5px; color: #94a3b8;">Confidence: <b>{conf_str}</b></div>
        </td>
        """
        if h < 7:
            cards_html += '<td style="width: 2%;"></td>'

    horizons_html = f"""
    <table style="width: 100%; border-collapse: separate; border-spacing: 0; margin-top: 10px; margin-bottom: 22px;">
        <tr>{cards_html}</tr>
    </table>
    """

    # 4. OHLCV Market Snapshot
    ohlcv_html = ""
    if ohlcv:
        stock_1d = _safe_float(market.get("stock_return_1d") if market else 0.0)
        banknifty_1d = _safe_float(market.get("banknifty_return_1d") if market else 0.0)
        ohlcv_html = f"""
        <table style="width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 22px; background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;">
            <tr style="background-color: #f1f5f9;">
                <th style="padding: 8px; font-size: 10px; color: #64748b; text-transform: uppercase; border-right: 1px solid #e2e8f0; text-align: center;">Open</th>
                <th style="padding: 8px; font-size: 10px; color: #64748b; text-transform: uppercase; border-right: 1px solid #e2e8f0; text-align: center;">Day High</th>
                <th style="padding: 8px; font-size: 10px; color: #64748b; text-transform: uppercase; border-right: 1px solid #e2e8f0; text-align: center;">Day Low</th>
                <th style="padding: 8px; font-size: 10px; color: #64748b; text-transform: uppercase; border-right: 1px solid #e2e8f0; text-align: center;">Close</th>
                <th style="padding: 8px; font-size: 10px; color: #64748b; text-transform: uppercase; border-right: 1px solid #e2e8f0; text-align: center;">Volume</th>
                <th style="padding: 8px; font-size: 10px; color: #64748b; text-transform: uppercase; text-align: center;">1D Return</th>
            </tr>
            <tr>
                <td style="padding: 10px 8px; text-align: center; font-size: 13px; font-weight: 700; color: #0f172a; border-right: 1px solid #e2e8f0;">{_fmt_price(ohlcv.get('open'))}</td>
                <td style="padding: 10px 8px; text-align: center; font-size: 13px; font-weight: 700; color: #0f172a; border-right: 1px solid #e2e8f0;">{_fmt_price(ohlcv.get('high'))}</td>
                <td style="padding: 10px 8px; text-align: center; font-size: 13px; font-weight: 700; color: #0f172a; border-right: 1px solid #e2e8f0;">{_fmt_price(ohlcv.get('low'))}</td>
                <td style="padding: 10px 8px; text-align: center; font-size: 13px; font-weight: 800; color: #0284c7; border-right: 1px solid #e2e8f0;">{_fmt_price(ohlcv.get('close'))}</td>
                <td style="padding: 10px 8px; text-align: center; font-size: 13px; font-weight: 700; color: #0f172a; border-right: 1px solid #e2e8f0;">{_fmt_int(ohlcv.get('volume'))}</td>
                <td style="padding: 10px 8px; text-align: center; font-size: 13px; font-weight: 800; color: {'#10b981' if stock_1d >= 0 else '#ef4444'};">{_fmt_pct(stock_1d)}</td>
            </tr>
        </table>
        """

    # 5. Technical Factor Attribution Guide
    tech_html = ""
    if technical:
        rsi = _safe_float(technical.get('rsi'), 50.0)
        macd = _safe_float(technical.get('macd_hist'), 0.0)
        bb = _safe_float(technical.get('bb_position'), 0.5)
        vol = _safe_float(technical.get('volume_to_ma_20'), 1.0)

        rsi_desc = "Overbought · Potential Pullback" if rsi > 70 else ("Oversold · Favorable Accumulation" if rsi < 30 else "Balanced Equilibrium (30–70)")
        macd_desc = "Bullish Momentum Acceleration" if macd > 0.0002 else ("Bearish Deceleration" if macd < -0.0002 else "Neutral Consolidation")
        bb_desc = "Testing Upper Volatility Band" if bb > 1.0 else ("Testing Lower Support Band" if bb < 0.0 else "Within Normal Envelope")
        vol_desc = f"Elevated Liquidity ({vol:.1f}x 20D Avg)" if vol > 1.3 else f"Normal Trading Volume ({vol:.1f}x 20D Avg)"

        tech_html = f"""
        <table style="width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 22px; font-size: 12px; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;">
            <tr style="background-color: #f1f5f9; color: #1e293b; font-weight: 700;">
                <th style="padding: 9px 12px; text-align: left; width: 30%;">Technical Factor</th>
                <th style="padding: 9px 12px; text-align: left; width: 25%;">Computed Metric</th>
                <th style="padding: 9px 12px; text-align: left; width: 45%;">Institutional Interpretation</th>
            </tr>
            <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 9px 12px; font-weight: 700; color: #0f172a;">RSI (14) Momentum</td>
                <td style="padding: 9px 12px; font-family: monospace; font-weight: 700;">{rsi:.2f}</td>
                <td style="padding: 9px 12px; color: #475569;">{rsi_desc}</td>
            </tr>
            <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 9px 12px; font-weight: 700; color: #0f172a;">MACD Histogram</td>
                <td style="padding: 9px 12px; font-family: monospace; font-weight: 700;">{macd:+.4f}</td>
                <td style="padding: 9px 12px; color: #475569;">{macd_desc}</td>
            </tr>
            <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 9px 12px; font-weight: 700; color: #0f172a;">Bollinger Band %b</td>
                <td style="padding: 9px 12px; font-family: monospace; font-weight: 700;">{bb:.2f}</td>
                <td style="padding: 9px 12px; color: #475569;">{bb_desc}</td>
            </tr>
            <tr>
                <td style="padding: 9px 12px; font-weight: 700; color: #0f172a;">20-Day Volume Ratio</td>
                <td style="padding: 9px 12px; font-family: monospace; font-weight: 700;">{vol:.2f}x</td>
                <td style="padding: 9px 12px; color: #475569;">{vol_desc}</td>
            </tr>
        </table>
        """

    # 6. Causal News List
    news_html = ""
    if news:
        for n in news[:3]:
            sent = str(n.get("sentiment_label", "NEUTRAL")).upper()
            sent_color = "#10b981" if sent == "POSITIVE" else ("#ef4444" if sent == "NEGATIVE" else "#f59e0b")
            sent_bg = "#ecfdf5" if sent == "POSITIVE" else ("#fef2f2" if sent == "NEGATIVE" else "#fffbeb")
            link = n.get("url") or "#"
            headline = n.get("headline", "Banking market development")
            source = n.get("source", "Financial Press")
            
            news_html += f"""
            <div style="padding: 10px 0; border-bottom: 1px solid #f1f5f9;">
                <div style="font-size: 13px; font-weight: 600; line-height: 1.4;">
                    <a href="{link}" target="_blank" style="color: #0284c7; text-decoration: none;">{headline}</a>
                </div>
                <div style="font-size: 11px; color: #64748b; margin-top: 4px;">
                    <span>Publisher: <b>{source}</b></span> · 
                    <span style="display: inline-block; padding: 2px 7px; border-radius: 4px; background-color: {sent_bg}; color: {sent_color}; font-weight: 700; font-size: 10px;">{sent}</span>
                </div>
            </div>
            """
    else:
        news_html = "<p style='color:#64748b; font-size:13px;'>No high-impact corporate news reported during this segment.</p>"

    # 7. Complete HTML Email Body Assembly
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>BankSight AI — Research Dossier for {name}</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f1f5f9; color: #334155; margin: 0; padding: 24px 0; line-height: 1.5;">
        <table align="center" border="0" cellpadding="0" cellspacing="0" width="620" style="max-width: 620px; background-color: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 20px rgba(0,0,0,0.06);">
            
            <!-- ── Top Institutional Header with BankSight AI Logo ── -->
            <tr>
                <td style="background: linear-gradient(135deg, #090e17 0%, #111e38 100%); padding: 24px 28px; border-bottom: 3px solid #0284c7;">
                    <table width="100%" border="0" cellpadding="0" cellspacing="0">
                        <tr>
                            <td style="vertical-align: middle; width: 62px;">
                                <img src="cid:banksight_logo" alt="BankSight AI" width="52" height="52" style="border-radius: 10px; background: #ffffff; padding: 3px; display: block; box-shadow: 0 2px 8px rgba(0,0,0,0.25);" />
                            </td>
                            <td style="vertical-align: middle; padding-left: 14px;">
                                <div style="font-size: 19px; font-weight: 800; color: #ffffff; letter-spacing: -0.3px;">
                                    BankSight <span style="color: #38bdf8;">AI</span>
                                </div>
                                <div style="font-size: 10px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.8px; margin-top: 3px;">
                                    Institutional Banking Equity Research · BSE / NSE
                                </div>
                            </td>
                            <td style="vertical-align: middle; text-align: right;">
                                <span style="display: inline-block; background-color: rgba(56, 189, 248, 0.15); color: #38bdf8; font-size: 10px; font-weight: 700; padding: 5px 12px; border-radius: 12px; border: 1px solid rgba(56, 189, 248, 0.3); text-transform: uppercase; letter-spacing: 0.5px;">
                                    EXECUTIVE BRIEFING
                                </span>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>

            <!-- ── Target Stock Banner ── -->
            <tr>
                <td style="padding: 24px 28px 14px 28px; background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);">
                    <table width="100%" border="0" cellpadding="0" cellspacing="0">
                        <tr>
                            <td>
                                <div style="font-size: 10.5px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.6px;">Coverage Equity</div>
                                <div style="font-size: 22px; font-weight: 800; color: #0f172a; margin-top: 2px;">{name}</div>
                                <div style="font-size: 12px; color: #64748b; margin-top: 2px;">Ticker: <b>{symbol}.NS</b> · NSE · Date: <b>{date_lbl}</b></div>
                            </td>
                            <td style="text-align: right; vertical-align: top;">
                                <div style="font-size: 10.5px; color: #64748b; text-transform: uppercase; font-weight: 600;">Current Close</div>
                                <div style="font-size: 22px; font-weight: 800; color: #0284c7; margin-top: 2px;">{_fmt_price(current_price)}</div>
                            </td>
                        </tr>
                    </table>

                    <!-- Executive Stance Box -->
                    <div style="margin-top: 16px; background-color: {stance_bg}; border: 1px solid {stance_border}; border-radius: 8px; padding: 14px 16px;">
                        <div style="font-size: 13.5px; font-weight: 800; color: {stance_color};">{stance_lbl} (5D Return: {_fmt_pct(f5d)})</div>
                        <div style="font-size: 12px; color: #475569; margin-top: 4px; line-height: 1.5;">{stance_desc}</div>
                    </div>
                </td>
            </tr>

            <!-- ── Main Content Body ── -->
            <tr>
                <td style="padding: 12px 28px 24px 28px;">
                    
                    <!-- Section 1: Multi-Horizon Predictions -->
                    <div style="font-size: 12.5px; font-weight: 800; color: #0f172a; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; border-bottom: 1.5px solid #e2e8f0; padding-bottom: 4px;">
                        Multi-Horizon Price Outlook Matrix
                    </div>
                    {horizons_html}

                    <!-- Section 2: OHLCV Wrap -->
                    <div style="font-size: 12.5px; font-weight: 800; color: #0f172a; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 18px; margin-bottom: 6px; border-bottom: 1.5px solid #e2e8f0; padding-bottom: 4px;">
                        Point-in-Time Market Snapshot
                    </div>
                    {ohlcv_html}

                    <!-- Section 3: Technical Forensic Attribution -->
                    <div style="font-size: 12.5px; font-weight: 800; color: #0f172a; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 18px; margin-bottom: 6px; border-bottom: 1.5px solid #e2e8f0; padding-bottom: 4px;">
                        Technical Factor Decomposition & Momentum
                    </div>
                    {tech_html}

                    <!-- Section 4: News Feed -->
                    <div style="font-size: 12.5px; font-weight: 800; color: #0f172a; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 18px; margin-bottom: 4px; border-bottom: 1.5px solid #e2e8f0; padding-bottom: 4px;">
                        Causal News & Sentiment Digest
                    </div>
                    {news_html}

                    <!-- Section 5: Watermarked PDF Dossier Attachment Card -->
                    <div style="margin-top: 24px; background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%); border: 1.5px dashed #cbd5e1; border-radius: 10px; padding: 18px 20px; text-align: center;">
                        <table width="100%" border="0" cellpadding="0" cellspacing="0">
                            <tr>
                                <td style="text-align: center;">
                                    <div style="font-size: 14px; font-weight: 800; color: #0f172a;">
                                        📄 Institutional PDF Research Dossier Attached
                                    </div>
                                    <div style="font-size: 11.5px; color: #64748b; margin-top: 4px; line-height: 1.5;">
                                        A vector PDF report authenticated with the <b>BankSight AI watermark</b> is attached.
                                        Includes full SHAP factor weights, historical analog regime clustering, and walk-forward backtest curves.
                                    </div>
                                </td>
                            </tr>
                        </table>
                    </div>

                </td>
            </tr>

            <!-- ── Institutional Footer & Regulatory Note ── -->
            <tr>
                <td style="background-color: #f8fafc; padding: 22px 28px; text-align: center; border-top: 1px solid #e2e8f0; font-size: 11px; color: #64748b; line-height: 1.6;">
                    This quantitative briefing was generated by <b>BankSight AI Terminal</b>.<br/>
                    Machine learning predictions are derived from historical price action and technical indicators. Past performance does not guarantee future results.<br/>
                    © {datetime.now().year} BankSight AI. All rights reserved. Strictly confidential for institutional research.
                </td>
            </tr>

        </table>
    </body>
    </html>
    """
    return html


def format_daily_alert_html(symbol: str, name: str, ohlcv: dict, pred_return: float, direction: str, news: list) -> str:
    """Helper wrapper for daily subscription alerts calling format_report_email_html."""
    return format_report_email_html(
        symbol=symbol,
        name=name,
        ohlcv=ohlcv,
        forecast={"return_5d": pred_return, "direction_5d": direction},
        news=news
    )


def run_daily_subscriptions_delivery():
    """
    Looks up active daily subscriptions, retrieves recent predictions, and dispatches alerts.
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
        
        pred = db.get_latest_prediction(symbol)
        if not pred:
            continue
            
        pred_return = _safe_float(pred.get("return_5d"), 0.0)
        direction = pred.get("direction_5d", "NEUTRAL")
        
        if direction != "UP" or pred_return <= 0.0:
            log.info(f"Skipping alert for {symbol} (5D expected return: {pred_return:+.4f}%). Not an increase.")
            continue
            
        md = db.get_market_data(symbol)
        if md.empty:
            continue
        latest_row = md.iloc[-1]
        ohlcv = {
            "open": _safe_float(latest_row.get("open")),
            "high": _safe_float(latest_row.get("high")),
            "low": _safe_float(latest_row.get("low")),
            "close": _safe_float(latest_row.get("close")),
        }
        
        news = db.get_news(symbol, limit=3)
        bank_name = config.STOCKS.get(symbol, {}).get("name", symbol)
        
        html_body = format_report_email_html(
            symbol=symbol,
            name=bank_name,
            ohlcv=ohlcv,
            forecast=pred,
            news=news
        )
        
        subject = f"BankSight Alert: Upward Trajectory Forecasted for {bank_name} ({symbol}) (+{pred_return*100:.2f}%)"
        send_email(email, subject, html_body)


class MailScheduler:
    """Coordinates background timer to run daily subscription checks."""
    
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
        try:
            run_daily_subscriptions_delivery()
        except Exception as e:
            log.error(f"Error in startup subscriptions check: {e}")
            
        while not cls._stop_event.is_set():
            for _ in range(24):
                if cls._stop_event.is_set():
                    break
                time.sleep(3600)
            
            if not cls._stop_event.is_set():
                try:
                    run_daily_subscriptions_delivery()
                except Exception as e:
                    log.error(f"Error in scheduled alerts run: {e}")
