"""
BankSight AI — Backend API & Dashboard Server
==============================================
Serves API endpoints and static dashboard files.
"""

import os
from flask import Flask, jsonify, send_from_directory, request, send_file
from flask_cors import CORS
from datetime import datetime
from io import BytesIO
import pandas as pd

import config
from src.data import Database, init_pipeline
from src.predict import Predictor
from src.explain import Explainer
from src.evaluation import Evaluator
from src.mail import MailScheduler, send_email, format_report_email_html

app = Flask(__name__, static_folder="dashboard")
CORS(app)

db = Database()
pipeline = init_pipeline()
predictor = Predictor(db)
explainer = Explainer(db)
evaluator = Evaluator(db)

# ---------------------------------------------------------
# Static File Routes (Dashboard)
# ---------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/manual")
def serve_manual():
    return send_from_directory(app.static_folder, "manual.html")

@app.route("/<path:path>")
def serve_static(path):
    if os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")

# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------

def check_market_status() -> str:
    """
    Check if the Indian stock market (NSE) is currently open.
    Trading hours: Monday - Friday, 9:15 AM - 3:30 PM IST.
    """
    from datetime import datetime, time
    import zoneinfo
    try:
        ist_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    except Exception:
        from datetime import timezone, timedelta
        ist_tz = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist_tz)
    
    # Check weekday
    if now_ist.weekday() >= 5:
        return "CLOSED"
        
    market_start = time(9, 15)
    market_end = time(15, 30)
    current_time = now_ist.time()
    
    if market_start <= current_time <= market_end:
        return "OPEN"
    return "CLOSED"

@app.route("/api/health")
def health():
    return jsonify({
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "mode": "DEMO" if config.is_demo_mode() else "LIVE",
        "market_status": check_market_status(),
        "data_status": pipeline.status,
        "smtp_configured": bool(config.SMTP_USER and config.SMTP_PASSWORD),
        "smtp_server": config.SMTP_SERVER if config.SMTP_USER else None
    })


@app.route("/api/market")
def get_market():
    # Return latest Nifty, Bank Nifty, VIX
    res = {}
    for sym, info in config.INDICES.items():
        df = db.get_index_data(sym)
        if not df.empty:
            last_row = df.iloc[-1]
            prev_row = df.iloc[-2] if len(df) > 1 else last_row
            change = (last_row["close"] / prev_row["close"]) - 1
            res[sym] = {
                "name": info["name"],
                "value": float(last_row["close"]),
                "change": float(change)
            }
    return jsonify(res)

@app.route("/api/banks")
def get_banks():
    # Return list of all banks with their latest 5D prediction
    res = []
    for symbol, info in config.STOCKS.items():
        pred = db.get_latest_prediction(symbol)
        if pred:
            res.append({
                "symbol": symbol,
                "name": info["name"],
                "type": info.get("type", "private"),
                "category": info.get("category", "private"),
                "current_price": pred.get("current_price"),
                "prediction_5d": pred.get("prediction_5d"),
                "expected_return": pred.get("return_5d"),
                "direction": pred.get("direction_5d"),
                "confidence": pred.get("confidence_5d"),
                "data_quality": pred.get("data_quality")
            })
        else:
            # Fallback if no prediction
            md = db.get_market_data(symbol)
            price = md.iloc[-1]["close"] if not md.empty else 0
            res.append({
                "symbol": symbol,
                "name": info["name"],
                "type": info.get("type", "private"),
                "category": info.get("category", "private"),
                "current_price": float(price),
                "expected_return": 0.0,
                "direction": "UNKNOWN"
            })
    return jsonify(res)

@app.route("/api/forecast/<symbol>")
def get_forecast(symbol):
    if symbol not in config.STOCKS:
        return jsonify({"error": "Invalid symbol"}), 404
        
    pred = db.get_latest_prediction(symbol)
    if not pred:
        # Try generating one on the fly
        pred = predictor.generate_forecasts(symbol)
        
    if not pred:
        return jsonify({"error": "No forecast available"}), 404
        
    # Get price history for chart
    md = db.get_market_data(symbol)
    history = []
    if not md.empty:
        # Last 30 days
        history = md.tail(30)[["date", "open", "high", "low", "close", "volume"]].to_dict("records")
        for h in history:
            h["date"] = str(h["date"])
            h["open"] = float(h["open"])
            h["high"] = float(h["high"])
            h["low"] = float(h["low"])
            h["volume"] = int(h["volume"])
            
    return jsonify({
        "forecast": pred,
        "history": history
    })

@app.route("/api/news/<symbol>")
def get_news(symbol):
    if symbol not in config.STOCKS:
        return jsonify({"error": "Invalid symbol"}), 404
    news = db.get_news(symbol, limit=10)
    return jsonify(news)

@app.route("/api/explanation/<symbol>")
def get_explanation(symbol):
    if symbol not in config.STOCKS:
        return jsonify({"error": "Invalid symbol"}), 404
    
    horizon = request.args.get("horizon", "5d").lower()
    if horizon not in ["1d", "3d", "5d", "7d"]:
        horizon = "5d"
    
    # SHAP Explanation
    shap_expl = explainer.generate_shap_explanation(symbol, horizon=horizon)
    
    # Text Narrative
    pred = db.get_latest_prediction(symbol)
    narrative = ""
    if pred:
        date_str = pred.get("timestamp", "").split("T")[0]
        narrative = explainer.generate_narrative(symbol, date=date_str, horizon=horizon)
    else:
        narrative = explainer.generate_narrative(symbol, horizon=horizon)
        
    return jsonify({
        "horizon": horizon.upper(),
        "shap": shap_expl,
        "narrative": narrative
    })

@app.route("/api/events/<symbol>")
def get_events(symbol):
    if symbol not in config.STOCKS:
        return jsonify({"error": "Invalid symbol"}), 404
        
    pred = db.get_latest_prediction(symbol)
    if pred and "explanation_json" in pred and isinstance(pred["explanation_json"], str):
        import json
        try:
            expl = json.loads(pred["explanation_json"])
            if expl and "events" in expl and expl["events"]:
                return jsonify(expl.get("events", {}))
        except:
            pass

    # Dynamic fallback: compute top similar events from historical features
    try:
        from src.events import EventSimilarityEngine
        sim_engine = EventSimilarityEngine(db)
        md = db.get_market_data(symbol)
        if not md.empty:
            latest_date = str(md.iloc[-1]["date"]).split()[0]
            sim_data = sim_engine.find_similar_events(symbol, latest_date)
            if "error" not in sim_data:
                return jsonify(sim_data)
    except Exception as e:
        app.logger.warning(f"Event similarity fallback failed for {symbol}: {e}")
            
    return jsonify({"error": "No event similarity data found."})

@app.route("/api/explain/historical")
def get_historical_explanation():
    symbol = request.args.get("symbol")
    date_str = request.args.get("date")
    
    if not symbol or symbol not in config.STOCKS:
        return jsonify({"error": "Invalid or missing symbol"}), 400
    if not date_str:
        return jsonify({"error": "Missing date parameter"}), 400
        
    try:
        date_obj = pd.to_datetime(date_str).date()
        date_formatted = date_obj.strftime("%Y-%m-%d")
    except Exception:
        return jsonify({"error": "Invalid date format"}), 400

    ohlcv_df = db.get_market_data(symbol, start=date_formatted, end=date_formatted + " 23:59:59")
    ohlcv = {}
    if not ohlcv_df.empty:
        row = ohlcv_df.iloc[0]
        ohlcv = {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"])
        }

    technical = {}
    market = {}
    query = "SELECT features_json FROM features WHERE symbol = ? AND (date = ? OR date = ? || ' 00:00:00')"
    with db._connect() as conn:
        feat_row = conn.execute(query, (symbol, date_formatted, date_formatted)).fetchone()
        
    if feat_row:
        import json
        feats = json.loads(feat_row["features_json"])
        technical = {
            "rsi": feats.get("rsi"),
            "macd": feats.get("macd"),
            "macd_signal": feats.get("macd_signal"),
            "macd_hist": feats.get("macd_hist"),
            "bb_position": feats.get("bb_position"),
            "bb_upper": feats.get("bb_upper"),
            "bb_lower": feats.get("bb_lower"),
            "ema_20": feats.get("ema_20"),
            "ema_50": feats.get("ema_50"),
            "price_to_sma_5": feats.get("price_to_sma_5"),
            "volume_to_ma_20": feats.get("volume_to_ma_20")
        }
        market = {
            "stock_return_1d": feats.get("return_1d"),
            "nifty_return_1d": feats.get("nifty_return_1d"),
            "banknifty_return_1d": feats.get("banknifty_return_1d"),
            "rel_return_nifty_1d": feats.get("rel_return_nifty_1d"),
            "rel_return_banknifty_1d": feats.get("rel_return_banknifty_1d"),
            "vix_level": feats.get("vix_level")
        }
    else:
        market = {
            "stock_return_1d": 0.0,
            "nifty_return_1d": 0.0,
            "banknifty_return_1d": 0.0
        }

    news = db.get_news(symbol, limit=5, before_date=date_formatted)
    
    from src.events import EventSimilarityEngine
    sim_engine = EventSimilarityEngine(db)
    sim_stats = sim_engine.find_similar_events(symbol, date_formatted)

    return jsonify({
        "symbol": symbol,
        "date": date_formatted,
        "ohlcv": ohlcv,
        "technical": technical,
        "market": market,
        "news": news,
        "similarity": sim_stats
    })

@app.route("/api/report/download", methods=["POST"])
def download_report():
    data = request.json or {}
    symbol = data.get("symbol")
    chart_image = data.get("chart_image")
    date_str = data.get("date")
    
    if not symbol or symbol not in config.STOCKS:
        return jsonify({"error": "Invalid or missing symbol"}), 400
        
    bank_name = config.STOCKS[symbol]["name"]
    
    forecast = db.get_latest_prediction(symbol)
    
    forensics = None
    if not date_str:
        with db._connect() as conn:
            row = conn.execute("SELECT max(date) as max_date FROM market_data WHERE symbol = ?", (symbol,)).fetchone()
            if row and row["max_date"]:
                date_str = row["max_date"].split(" ")[0]

    if date_str:
        try:
            date_obj = pd.to_datetime(date_str).date()
            date_formatted = date_obj.strftime("%Y-%m-%d")
            
            ohlcv_df = db.get_market_data(symbol, start=date_formatted, end=date_formatted + " 23:59:59")
            ohlcv = {}
            if not ohlcv_df.empty:
                row = ohlcv_df.iloc[0]
                ohlcv = {
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"])
                }
                
            technical = {}
            market = {}
            query = "SELECT features_json FROM features WHERE symbol = ? AND (date = ? OR date = ? || ' 00:00:00')"
            with db._connect() as conn:
                feat_row = conn.execute(query, (symbol, date_formatted, date_formatted)).fetchone()
            if feat_row:
                import json
                feats = json.loads(feat_row["features_json"])
                technical = {
                    "rsi": feats.get("rsi"),
                    "macd": feats.get("macd"),
                    "macd_signal": feats.get("macd_signal"),
                    "macd_hist": feats.get("macd_hist"),
                    "bb_position": feats.get("bb_position"),
                    "bb_upper": feats.get("bb_upper"),
                    "bb_lower": feats.get("bb_lower"),
                    "ema_20": feats.get("ema_20"),
                    "ema_50": feats.get("ema_50"),
                    "price_to_sma_5": feats.get("price_to_sma_5"),
                    "volume_to_ma_20": feats.get("volume_to_ma_20")
                }
                market = {
                    "stock_return_1d": feats.get("return_1d"),
                    "nifty_return_1d": feats.get("nifty_return_1d"),
                    "banknifty_return_1d": feats.get("banknifty_return_1d"),
                    "rel_return_nifty_1d": feats.get("rel_return_nifty_1d"),
                    "rel_return_banknifty_1d": feats.get("rel_return_banknifty_1d"),
                    "vix_level": feats.get("vix_level")
                }
            else:
                market = {
                    "stock_return_1d": 0.0,
                    "nifty_return_1d": 0.0,
                    "banknifty_return_1d": 0.0
                }
                
            news = db.get_news(symbol, limit=5, before_date=date_formatted)
            from src.events import EventSimilarityEngine
            sim_engine = EventSimilarityEngine(db)
            sim_stats = sim_engine.find_similar_events(symbol, date_formatted)
            
            forensics = {
                "date": date_formatted,
                "ohlcv": ohlcv,
                "technical": technical,
                "market": market,
                "news": news,
                "similarity": sim_stats
            }
        except Exception as e:
            app.logger.error(f"Failed loading forensics for PDF report: {e}")

    performance = evaluator.get_system_metrics()
    market_open = check_market_status() == "OPEN"
    
    try:
        from src.report import build_pdf_report
        pdf_bytes = build_pdf_report(
            symbol=symbol,
            bank_name=bank_name,
            chart_base64=chart_image,
            forensics=forensics,
            forecast=forecast,
            performance=performance,
            market_open=market_open
        )
        
        filename = f"BankSight_Report_{symbol}_{date_str or 'latest'}.pdf"
        return send_file(
            BytesIO(pdf_bytes),
            as_attachment=True,
            download_name=filename,
            mimetype="application/pdf"
        )
    except Exception as e:
        app.logger.error(f"Failed generating PDF: {e}")
        return jsonify({"error": f"Failed generating PDF report: {str(e)}"}), 500


@app.route("/api/subscribe", methods=["POST"])
def subscribe():
    data = request.get_json() or {}
    email = data.get("email", "").strip()
    symbol = data.get("symbol", "").strip()
    
    if not email or "@" not in email:
        return jsonify({"error": "Invalid email address."}), 400
    if not symbol or symbol not in config.STOCKS:
        return jsonify({"error": "Invalid stock symbol."}), 400
        
    try:
        db.add_subscription(email, symbol)
        return jsonify({"success": True, "message": f"Successfully subscribed to daily alerts for {symbol}."})
    except Exception as e:
        app.logger.error(f"Subscription failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/report/email", methods=["POST"])
def email_report():
    data = request.get_json() or {}
    symbol = data.get("symbol")
    date_str = data.get("date")
    chart_image = data.get("chart_image")
    email = data.get("email", "").strip()
    
    if not email or "@" not in email:
        return jsonify({"error": "Invalid email address."}), 400
    if not symbol or symbol not in config.STOCKS:
        return jsonify({"error": "Invalid stock symbol"}), 400
        
    bank_name = config.STOCKS[symbol]["name"]
    forecast = None
    pred = db.get_latest_prediction(symbol)
    if pred:
        forecast = pred
        
    forensics = None
    if not date_str:
        with db._connect() as conn:
            row = conn.execute("SELECT max(date) as max_date FROM market_data WHERE symbol = ?", (symbol,)).fetchone()
            if row and row["max_date"]:
                date_str = row["max_date"].split(" ")[0]

    if date_str:
        try:
            date_obj = pd.to_datetime(date_str).date()
            date_formatted = date_obj.strftime("%Y-%m-%d")
            
            ohlcv = {}
            ohlcv_df = db.get_market_data(symbol, start=date_formatted, end=date_formatted + " 23:59:59")
            if not ohlcv_df.empty:
                row = ohlcv_df.iloc[0]
                ohlcv = {
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"])
                }
                
            technical = {}
            market = {}
            query = "SELECT features_json FROM features WHERE symbol = ? AND (date = ? OR date = ? || ' 00:00:00')"
            with db._connect() as conn:
                feat_row = conn.execute(query, (symbol, date_formatted, date_formatted)).fetchone()
            if feat_row:
                import json
                feats = json.loads(feat_row["features_json"])
                technical = {
                    "rsi": feats.get("rsi"),
                    "macd": feats.get("macd"),
                    "macd_signal": feats.get("macd_signal"),
                    "macd_hist": feats.get("macd_hist"),
                    "bb_position": feats.get("bb_position"),
                    "bb_upper": feats.get("bb_upper"),
                    "bb_lower": feats.get("bb_lower"),
                    "ema_20": feats.get("ema_20"),
                    "ema_50": feats.get("ema_50"),
                    "price_to_sma_5": feats.get("price_to_sma_5"),
                    "volume_to_ma_20": feats.get("volume_to_ma_20")
                }
                market = {
                    "stock_return_1d": feats.get("return_1d"),
                    "nifty_return_1d": feats.get("nifty_return_1d"),
                    "banknifty_return_1d": feats.get("banknifty_return_1d"),
                    "rel_return_nifty_1d": feats.get("rel_return_nifty_1d"),
                    "rel_return_banknifty_1d": feats.get("rel_return_banknifty_1d"),
                    "vix_level": feats.get("vix_level")
                }
            else:
                market = {
                    "stock_return_1d": 0.0,
                    "nifty_return_1d": 0.0,
                    "banknifty_return_1d": 0.0
                }
                
            news = db.get_news(symbol, limit=5, before_date=date_formatted)
            from src.events import EventSimilarityEngine
            sim_engine = EventSimilarityEngine(db)
            sim_stats = sim_engine.find_similar_events(symbol, date_formatted)
            
            forensics = {
                "date": date_formatted,
                "ohlcv": ohlcv,
                "technical": technical,
                "market": market,
                "news": news,
                "similarity": sim_stats
            }
        except Exception as e:
            app.logger.error(f"Failed loading forensics for PDF email: {e}")

    performance = evaluator.get_system_metrics()
    market_open = check_market_status() == "OPEN"
    
    try:
        from src.report import build_pdf_report
        pdf_bytes = build_pdf_report(
            symbol=symbol,
            bank_name=bank_name,
            chart_base64=chart_image,
            forensics=forensics,
            forecast=forecast,
            performance=performance,
            market_open=market_open
        )
        
        subject = f"BankSight Intelligence Report: {bank_name} ({symbol})"
        
        f_ohlcv = forensics.get("ohlcv") if forensics else None
        f_tech = forensics.get("technical") if forensics else None
        f_mkt = forensics.get("market") if forensics else None
        f_news = forensics.get("news") if forensics else None
        
        html_body = format_report_email_html(
            symbol=symbol,
            name=bank_name,
            date_str=date_str,
            ohlcv=f_ohlcv,
            forecast=forecast,
            technical=f_tech,
            market=f_mkt,
            news=f_news
        )
        
        filename = f"BankSight_Report_{symbol}_{date_str or 'latest'}.pdf"
        success = send_email(
            to_email=email,
            subject=subject,
            html_body=html_body,
            attachment_bytes=pdf_bytes,
            attachment_filename=filename
        )
        
        if success:
            return jsonify({"success": True, "message": f"Successfully emailed report to {email}."})
        else:
            return jsonify({"error": "Failed sending email. Please verify configuration."}), 500
            
    except Exception as e:
        app.logger.error(f"Failed generating or sending email report: {e}")
        return jsonify({"error": f"Failed generating report: {str(e)}"}), 500

@app.route("/api/model/performance")
def get_performance():
    metrics = evaluator.get_system_metrics()
    return jsonify(metrics)

@app.route("/api/smtp/test", methods=["GET", "POST"])
def test_smtp_endpoint():
    """
    Test endpoint for validating SMTP configuration on Render or local.
    GET: Checks connection & authentication.
    POST: Sends a test email to the provided address: {"email": "..."}
    """
    from src.mail import test_smtp_connection
    
    if request.method == "POST":
        data = request.get_json() or {}
        to_email = data.get("email", "").strip()
        if not to_email or "@" not in to_email:
            return jsonify({"error": "Please provide a valid email address."}), 400
            
        test_html = """
        <div style="font-family: Arial, sans-serif; padding: 20px; color: #1e293b;">
            <h2 style="color: #2563eb;">BankSight AI — SMTP Verification Successful</h2>
            <p>Your SMTP email configuration on Render is working properly!</p>
            <p>You will now be able to receive daily market forecasts and PDF intelligence reports directly in your inbox.</p>
            <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 20px 0;">
            <small style="color: #64748b;">Automated message sent by BankSight AI</small>
        </div>
        """
        success = send_email(
            to_email=to_email,
            subject="BankSight AI — SMTP Test Successful",
            html_body=test_html
        )
        if success:
            return jsonify({"success": True, "message": f"Test email sent successfully to {to_email}."})
        else:
            return jsonify({"error": "Failed sending test email. Check Render environment variables and logs."}), 500

    # GET request: check connection & auth
    ok, msg = test_smtp_connection()
    return jsonify({
        "configured": bool(config.SMTP_USER and config.SMTP_PASSWORD),
        "success": ok,
        "message": msg,
        "server": config.SMTP_SERVER,
        "port": config.SMTP_PORT,
        "user": config.SMTP_USER if config.SMTP_USER else "Not configured"
    }), (200 if ok else (400 if not config.SMTP_USER else 502))


import threading
_schedulers_started = False
_sched_lock = threading.Lock()

def start_background_schedulers():
    global _schedulers_started
    with _sched_lock:
        if _schedulers_started:
            return
        _schedulers_started = True

    import time
    
    # Start background mail scheduler
    try:
        MailScheduler.start()
    except Exception as e:
        print(f"[BACKGROUND ERROR] Mail scheduler failed: {e}")
        
    def update_news_loop():
        # Wait a bit before first background run to let Flask start smoothly
        time.sleep(10)
        while True:
            try:
                from src.news import update_and_analyze_news
                update_and_analyze_news()
                from src.predict import generate_all_predictions
                generate_all_predictions()
            except Exception as e:
                print(f"[BACKGROUND ERROR] News/predictions update failed: {e}")
            time.sleep(300) # Every 5 minutes

    t = threading.Thread(target=update_news_loop, daemon=True)
    t.start()

# When running in production (Gunicorn / Render), auto-start background schedulers
if not config.FLASK_DEBUG or os.environ.get("RENDER") or os.environ.get("GUNICORN_CMD_ARGS"):
    start_background_schedulers()

if __name__ == "__main__":
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not config.FLASK_DEBUG:
        start_background_schedulers()

    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG
    )

