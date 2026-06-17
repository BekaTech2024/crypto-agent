"""
Crypto Trading Agent v2 — Berkan
Analyse hybride : rapide (15min) + approfondie (1h) avec Claude Sonnet
"""

import os
import json
import time
import logging
import requests
from datetime import datetime
import anthropic
import schedule

os.makedirs('logs', exist_ok=True)
os.makedirs('config', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/agent.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID")

RISK = {
    "max_trade_pct":   0.20,
    "stop_loss_pct":   0.08,
    "take_profit_pct": 0.15,
    "min_confidence":  70,
    "simulation_mode": True,
    "alert_threshold": 3.0,
    "min_profit_after_fees": 1.5,
    "trading_fee": 0.1,
}

PORTFOLIO = {
    "USDT": 1000.0,
    "BTC":  0.0,
    "ETH":  0.0,
    "SOL":  0.0,
    "BNB":  0.0,
    "ADA":  0.0,
    "AVAX": 0.0,
    "LINK": 0.0,
    "DOT":  0.0,
    "XRP":  0.0,
    "MATIC": 0.0,
}

INITIAL_VALUE = 1000.0

prev_prices = {}

def telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        log.error(f"Telegram error: {e}")

def telegram_alert(title, body, emoji="🤖"):
    telegram(f"{emoji} *{title}*\n\n{body}")

def get_prices():
    try:
        pairs_map = {
            "XBTUSD":  "BTC",
            "ETHUSD":  "ETH",
            "SOLUSD":  "SOL",
            "ADAUSD":  "ADA",
            "AVAXUSD": "AVAX",
            "LINKUSD": "LINK",
            "DOTUSD":  "DOT",
            "XRPUSD":  "XRP",
        }
        url = "https://api.kraken.com/0/public/Ticker"
        r = requests.get(url, timeout=15)
        data = r.json()
        if data.get("error"):
            log.error(f"Erreur Kraken: {data['error']}")
            return {}
        prices = {}
        result = data.get("result", {})
        for pair, symbol in pairs_map.items():
            if pair in result:
                val = result[pair]
                prices[symbol] = {
                    "price":  float(val["c"][0]),
                    "change": float(val["p"][1]),
                    "volume": float(val["v"][1]),
                }
        log.info(f"Prix récupérés: {len(prices)} cryptos")
        return prices
    except Exception as e:
        log.error(f"Erreur prix: {e}")
        return {}

def quick_analysis(prices):
    global prev_prices
    alerts = []
    for symbol, data in prices.items():
        if symbol in prev_prices:
            prev = prev_prices[symbol]["price"]
            curr = data["price"]
            change_pct = ((curr - prev) / prev) * 100
            if abs(change_pct) >= RISK["alert_threshold"]:
                direction = "🚀" if change_pct > 0 else "📉"
                alerts.append(
                    f"{direction} *{symbol}*: {change_pct:+.2f}% en 15min\n"
                    f"   Prix: ${curr:,.4f}"
                )
    if alerts:
        telegram("⚡ *Alerte mouvement rapide*\n\n" + "\n".join(alerts))
    prev_prices = {s: d for s, d in prices.items()}

def deep_analysis(prices):
    if not prices:
        log.error("Pas de prix disponibles")
        telegram_alert("Erreur", "Impossible de récupérer les prix", "⚠️")
        return
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        portfolio_value = PORTFOLIO.get("USDT", 0)
        pnl = portfolio_value - INITIAL_VALUE
pnl_pct = (pnl / INITIAL_VALUE) * 100
        for symbol, data in prices.items():
            portfolio_value += PORTFOLIO.get(symbol, 0) * data["price"]

        fee_pct = RISK["trading_fee"] * 2
        min_profit = RISK["min_profit_after_fees"]

        price_lines = "\n".join([
            f"  {sym}: ${d['price']:,.4f} ({d['change']:+.2f}% 24h, vol ${d['volume']/1e6:.0f}M)"
            for sym, d in prices.items()
        ])
        holdings_lines = "\n".join([
            f"  {sym}: {PORTFOLIO.get(sym,0)} = ${PORTFOLIO.get(sym,0)*d['price']:,.0f}"
            for sym, d in prices.items()
            if PORTFOLIO.get(sym, 0) > 0
        ])

        prompt = f"""Tu es un agent de trading crypto autonome expert. Analyse et génère des décisions précises.

MARCHÉ ({datetime.now().strftime('%Y-%m-%d %H:%M')} UTC):
{price_lines}

PORTEFEUILLE SIMULÉ (total ~${portfolio_value:,.0f} USDT):
  Cash USDT: ${PORTFOLIO.get('USDT', 0):,.2f}
{holdings_lines}

RÈGLES IMPORTANTES:
- Frais par trade: {fee_pct:.1f}% aller-retour
- Profit minimum net après frais: +{min_profit}%
- Ne pas trader si profit estimé < {min_profit + fee_pct}% brut
- Max {RISK['max_trade_pct']*100:.0f}% du portfolio par trade
- Stop-loss: -{RISK['stop_loss_pct']*100:.0f}%
- Take-profit: +{RISK['take_profit_pct']*100:.0f}%
- Confiance minimum: {RISK['min_confidence']}%

Réponds UNIQUEMENT en JSON valide:
{{
  "decisions": [
    {{
      "symbol": "BTC",
      "action": "BUY|SELL|HOLD",
      "amount_pct": 10,
      "reason": "raison courte",
      "confidence": 78,
      "estimated_profit_pct": 5.2,
      "stop_loss": 61000,
      "take_profit": 78000
    }}
  ],
  "market_summary": "résumé global en 1-2 phrases",
  "risk_level": "LOW|MEDIUM|HIGH",
  "best_opportunity": "SYMBOL — pourquoi"
}}"""

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip().replace("```json","").replace("```","").strip()
        analysis = json.loads(raw)

        mode = "🔴 RÉEL" if not RISK["simulation_mode"] else "🟡 SIMULATION"
        best = analysis.get("best_opportunity", "—")
        header = (
    f"📊 *Analyse approfondie* — {datetime.now().strftime('%H:%M')}\n"
    f"Mode: {mode} | Risque: {analysis.get('risk_level','?')}\n"
    f"💰 Portfolio: ${portfolio_value:,.2f} "
    f"({'+'if pnl>=0 else ''}{pnl_pct:.2f}% depuis début)\n"
    f"💡 Meilleure opportunité: {best}\n\n"
    f"_{analysis.get('market_summary','')}_\n\n"
)

        results = []
        for d in analysis.get("decisions", []):
            sym = d.get("symbol","?")
            action = d["action"]
            confidence = d["confidence"]
            reason = d["reason"]
            profit = d.get("estimated_profit_pct", 0)
            fee_total = RISK["trading_fee"] * 2
            net_profit = profit - fee_total

            if confidence < RISK["min_confidence"]:
                continue
            if action in ("BUY","SELL") and net_profit < RISK["min_profit_after_fees"]:
                results.append(f"⏭ *{sym}*: ignoré (profit net {net_profit:.1f}% < minimum {RISK['min_profit_after_fees']}%)")
                continue
            if action == "BUY":
                results.append(f"✅ *ACHAT {sym}* (confiance {confidence}%)\n   Profit estimé net: +{net_profit:.1f}%\n   {reason}")
            elif action == "SELL":
                results.append(f"🔴 *VENTE {sym}* (confiance {confidence}%)\n   {reason}")
            else:
                results.append(f"⏸ *HOLD {sym}* — {reason}")

        if not results:
            results.append("⏸ Aucune action — marché incertain, on attend.")

        telegram(header + "\n".join(results))
        log.info(f"Analyse terminée — {len(results)} décisions")

    except Exception as e:
        log.error(f"Erreur analyse Claude: {e}", exc_info=True)
        telegram_alert("Erreur analyse", str(e), "⚠️")

def cycle_rapide():
    log.info("Cycle rapide 15min")
    prices = get_prices()
    if prices:
        quick_analysis(prices)

def cycle_profond():
    log.info("Cycle approfondi 1h")
    prices = get_prices()
    deep_analysis(prices)

def main():
    log.info("Agent crypto v2 démarré")
    telegram_alert(
        "Agent v2 démarré 🚀",
        f"Mode: {'SIMULATION' if RISK['simulation_mode'] else 'RÉEL'}\n"
        f"Cryptos: BTC ETH SOL BNB ADA AVAX LINK DOT XRP MATIC\n"
        f"Analyse rapide: toutes les 15min\n"
        f"Analyse Claude: toutes les heures\n"
        f"Frais pris en compte: {RISK['trading_fee']*2:.1f}% aller-retour",
        "🚀"
    )
    cycle_profond()
    schedule.every(15).minutes.do(cycle_rapide)
    schedule.every(1).hours.do(cycle_profond)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
