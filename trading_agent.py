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

# ─── CONFIG ──────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN     = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

RISK = {
    "max_trade_pct":   0.20,
    "stop_loss_pct":   0.08,
    "take_profit_pct": 0.15,
    "min_confidence":  70,
    "simulation_mode": True,
    "alert_threshold": 3.0,  # % de variation pour alerte rapide
}

COINS = [
    "bitcoin", "ethereum", "solana", "binancecoin",
    "cardano", "avalanche-2", "chainlink", "polkadot",
    "ripple", "matic-network"
]

SYMBOLS = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL",
    "binancecoin": "BNB", "cardano": "ADA", "avalanche-2": "AVAX",
    "chainlink": "LINK", "polkadot": "DOT", "ripple": "XRP",
    "matic-network": "MATIC"
}

# Portfolio simulé
PORTFOLIO = {
    "USDT": 8000.0,
    "BTC":  0.05,
    "ETH":  0.30,
    "SOL":  2.00,
    "BNB":  0.50,
    "ADA":  100.0,
    "AVAX": 3.0,
    "LINK": 10.0,
    "DOT":  5.0,
    "XRP":  50.0,
    "MATIC": 100.0,
}

prev_prices = {}

# ─── TELEGRAM ────────────────────────────────────────────────────────────────

def telegram(msg: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        log.error(f"Telegram error: {e}")

def telegram_alert(title: str, body: str, emoji="🤖"):
    telegram(f"{emoji} *{title}*\n\n{body}")

# ─── PRIX ────────────────────────────────────────────────────────────────────

def get_prices() -> dict:
    try:
        ids = ",".join(COINS)
        url = (
            f"https://api.coingecko.com/api/v3/simple/price"
            f"?ids={ids}&vs_currencies=usd"
            f"&include_24hr_change=true&include_24hr_vol=true"
        )
        headers = {"accept": "application/json"}
        r = requests.get(url, timeout=15, headers=headers)
        data = r.json()
        prices = {}
        for coin_id in COINS:
            if coin_id in data and "usd" in data[coin_id]:
                prices[SYMBOLS[coin_id]] = {
                    "price":  data[coin_id]["usd"],
                    "change": data[coin_id].get("usd_24h_change", 0),
                    "volume": data[coin_id].get("usd_24h_vol", 0),
                    "id":     coin_id
                }
        log.info(f"Prix récupérés: {len(prices)} cryptos")
        return prices
    except Exception as e:
        log.error(f"Erreur CoinGecko: {e}")
        return {}

# ─── ANALYSE RAPIDE (sans Claude) ────────────────────────────────────────────

def quick_analysis(prices: dict):
    """Analyse rapide toutes les 15min — détecte les mouvements brusques"""
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
                    f"{direction} *{symbol}* : {change_pct:+.2f}% en 15min\n"
                    f"   Prix: ${curr:,.2f}"
                )

    if alerts:
        msg = "⚡ *Alerte mouvement rapide*\n\n" + "\n".join(alerts)
        telegram(msg)
        log.info(f"Alertes envoyées: {len(alerts)}")

    prev_prices = {s: d for s, d in prices.items()}

# ─── ANALYSE APPROFONDIE (avec Claude) ───────────────────────────────────────

def deep_analysis(prices: dict):
    """Analyse complète toutes les heures avec Claude Sonnet"""
    if not prices:
        log.error("Pas de prix disponibles")
        telegram_alert("Erreur", "Impossible de récupérer les prix", "⚠️")
        return

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        portfolio_value = PORTFOLIO.get("USDT", 0)
        for symbol, data in prices.items():
            held = PORTFOLIO.get(symbol, 0)
            portfolio_value += held * data["price"]

        price_lines = "\n".join([
            f"  {sym}: ${d['price']:,.4f} ({d['change']:+.2f}% 24h, vol ${d['volume']/1e6:.0f}M)"
            for sym, d in prices.items()
        ])

        holdings_lines = "\n".join([
            f"  {sym}: {PORTFOLIO.get(sym, 0)} = ${PORTFOLIO.get(sym, 0) * d['price']:,.0f}"
            for sym, d in prices.items()
            if PORTFOLIO.get(sym, 0) > 0
        ])

        prompt = f"""Tu es un agent de trading crypto autonome expert. Analyse ces données et génère des décisions précises.

MARCHÉ ({datetime.now().strftime('%Y-%m-%d %H:%M')} UTC):
{price_lines}

PORTEFEUILLE SIMULÉ (total ~${portfolio_value:,.0f} USDT):
  Cash USDT: ${PORTFOLIO.get('USDT', 0):,.2f}
{holdings_lines}

RÈGLES:
- Max {RISK['max_trade_pct']*100:.0f}% du portfolio par trade
- Stop-loss: -{RISK['stop_loss_pct']*100:.0f}%
- Take-profit: +{RISK['take_profit_pct']*100:.0f}%
- Exécuter seulement si confiance >= {RISK['min_confidence']}%
- Analyse momentum, volume, tendance 24h

Réponds UNIQUEMENT en JSON valide:
{{
  "decisions": [
    {{
      "symbol": "BTC",
      "action": "BUY|SELL|HOLD",
      "amount_pct": 10,
      "reason": "raison courte",
      "confidence": 78,
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

        raw = message.content[0].text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        analysis = json.loads(raw)

        # Construire le rapport Telegram
        mode = "🔴 RÉEL" if not RISK["simulation_mode"] else "🟡 SIMULATION"
        best = analysis.get("best_opportunity", "—")

        header = (
            f"📊 *Analyse approfondie* — {datetime.now().strftime('%H:%M')}\n"
            f"Mode: {mode} | Risque: {analysis.get('risk_level','?')}\n"
            f"💡 Meilleure opportunité: {best}\n\n"
            f"_{analysis.get('market_summary','')}_\n\n"
        )

        results = []
        for d in analysis.get("decisions", []):
            sym = d.get("symbol", "?")
            action = d["action"]
            confidence = d["confidence"]
            reason = d["reason"]

            if confidence < RISK["min_confidence"]:
                continue

            if action == "BUY":
                results.append(f"✅ *ACHAT {sym}* (confiance {confidence}%)\n   {reason}")
            elif action == "SELL":
                results.append(f"🔴 *VENTE {sym}* (confiance {confidence}%)\n   {reason}")
            else:
                results.append(f"⏸ *HOLD {sym}*\n   {reason}")

        if not results:
            results.append("⏸ Aucune action — marché incertain, on attend.")

        telegram(header + "\n".join(results))
        log.info(f"Analyse approfondie terminée — {len(results)} décisions")

    except Exception as e:
        log.error(f"Erreur analyse Claude: {e}", exc_info=True)
        telegram_alert("Erreur analyse", str(e), "⚠️")

# ─── CYCLES ──────────────────────────────────────────────────────────────────

def cycle_rapide():
    log.info("Cycle rapide 15min")
    prices = get_prices()
    if prices:
        quick_analysis(prices)

def cycle_profond():
    log.info("Cycle approfondi 1h")
    prices = get_prices()
    deep_analysis(prices)

# ─── DÉMARRAGE ───────────────────────────────────────────────────────────────

def main():
    log.info("Agent crypto v2 démarré")
    telegram_alert(
        "Agent v2 démarré 🚀",
        f"Mode: {'SIMULATION' if RISK['simulation_mode'] else 'RÉEL'}\n"
        f"Cryptos suivies: {len(COINS)}\n"
        f"Analyse rapide: toutes les 15min\n"
        f"Analyse Claude: toutes les heures\n"
        f"Seuil alerte: {RISK['alert_threshold']}% de variation",
        "🚀"
    )

    # Premier cycle immédiat
    cycle_profond()

    # Analyse rapide toutes les 15 minutes
    schedule.every(15).minutes.do(cycle_rapide)

    # Analyse approfondie toutes les heures
    schedule.every(1).hours.do(cycle_profond)

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
