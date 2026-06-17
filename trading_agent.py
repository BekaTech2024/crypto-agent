"""
Crypto Trading Agent — Berkan
Agent autonome connecté à Claude Sonnet, Binance et Telegram
"""

import os
import json
import time
import logging
import requests
from datetime import datetime
from binance.client import Client
from binance.exceptions import BinanceAPIException
import anthropic
import schedule

os.makedirs('logs', exist_ok=True)
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

ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY")
BINANCE_API_KEY     = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY  = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN      = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID")

# Paramètres de risque — modifiables sans toucher au code
RISK = {
    "max_trade_pct":    0.20,   # max 20% du portfolio par trade
    "stop_loss_pct":    0.08,   # stop-loss à -8%
    "take_profit_pct":  0.15,   # take-profit à +15%
    "min_confidence":   70,     # confiance IA minimum pour exécuter
    "simulation_mode":  True,   # ← mettre False pour vrais trades
}

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

# ─── TELEGRAM ────────────────────────────────────────────────────────────────

def telegram(msg: str, parse_mode="Markdown"):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": parse_mode},
            timeout=10
        )
    except Exception as e:
        log.error(f"Telegram error: {e}")

def telegram_alert(title: str, body: str, emoji="🤖"):
    telegram(f"{emoji} *{title}*\n\n{body}")

# ─── MARCHÉ ──────────────────────────────────────────────────────────────────

def get_prices() -> dict:
    """Prix + variation 24h via CoinGecko (gratuit, pas de clé)"""
    ids = "bitcoin,ethereum,solana,binancecoin"
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true&include_24hr_vol=true"
    r = requests.get(url, timeout=10)
    data = r.json()
    mapping = {
        "BTCUSDT": "bitcoin",
        "ETHUSDT": "ethereum",
        "SOLUSDT": "solana",
        "BNBUSDT": "binancecoin"
    }
    return {
        symbol: {
            "price":  data[cg_id]["usd"],
            "change": data[cg_id].get("usd_24h_change", 0),
            "volume": data[cg_id].get("usd_24h_vol", 0)
        }
        for symbol, cg_id in mapping.items()
        if cg_id in data
    }

def get_portfolio(client: Client) -> dict:
    """Récupère le solde réel depuis Binance"""
    if RISK["simulation_mode"]:
        return {
            "USDT":  10000.0,
            "BTC":   0.05,
            "ETH":   0.30,
            "SOL":   2.00,
            "BNB":   0.50
        }
    account = client.get_account()
    return {
        b["asset"]: float(b["free"])
        for b in account["balances"]
        if float(b["free"]) > 0
    }

# ─── ANALYSE IA ──────────────────────────────────────────────────────────────

def analyze_with_claude(prices: dict, portfolio: dict) -> dict:
    """Envoie les données à Claude et récupère les décisions"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    portfolio_value = portfolio.get("USDT", 0)
    for symbol, data in prices.items():
        asset = symbol.replace("USDT", "")
        held = portfolio.get(asset, 0)
        portfolio_value += held * data["price"]

    price_lines = "\n".join([
        f"  {s}: ${d['price']:,.2f} ({d['change']:+.2f}% 24h, vol ${d['volume']/1e6:.0f}M)"
        for s, d in prices.items()
    ])

    holdings_lines = "\n".join([
        f"  {s.replace('USDT','')}: {portfolio.get(s.replace('USDT',''), 0):.4f} "
        f"= ${portfolio.get(s.replace('USDT',''), 0) * d['price']:,.0f}"
        for s, d in prices.items()
    ])

    prompt = f"""Tu es un agent de trading crypto autonome. Analyse les données suivantes et génère des décisions précises.

MARCHÉ ({datetime.now().strftime('%Y-%m-%d %H:%M')} UTC):
{price_lines}

PORTEFEUILLE (total ~${portfolio_value:,.0f} USDT):
  Cash USDT: ${portfolio.get('USDT', 0):,.2f}
{holdings_lines}

RÈGLES DE RISQUE:
- Max {RISK['max_trade_pct']*100:.0f}% du portfolio par trade
- Stop-loss: -{RISK['stop_loss_pct']*100:.0f}%
- Take-profit: +{RISK['take_profit_pct']*100:.0f}%
- N'exécuter que si confiance >= {RISK['min_confidence']}%

Réponds UNIQUEMENT en JSON valide (pas de markdown):
{{
  "decisions": [
    {{
      "symbol": "BTCUSDT",
      "action": "BUY|SELL|HOLD",
      "amount_pct": 10,
      "reason": "explication courte",
      "confidence": 78,
      "stop_loss": 61000,
      "take_profit": 78000
    }}
  ],
  "market_summary": "résumé global du marché en 1-2 phrases",
  "risk_level": "LOW|MEDIUM|HIGH"
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

# ─── EXÉCUTION ───────────────────────────────────────────────────────────────

def execute_trade(client: Client, symbol: str, action: str, amount_pct: float,
                  portfolio: dict, prices: dict) -> str:
    """Exécute un trade sur Binance (ou simule)"""
    asset = symbol.replace("USDT", "")
    price = prices[symbol]["price"]
    portfolio_value = portfolio.get("USDT", 0)
    for s, d in prices.items():
        portfolio_value += portfolio.get(s.replace("USDT", ""), 0) * d["price"]

    trade_value = portfolio_value * (amount_pct / 100)

    if RISK["simulation_mode"]:
        log.info(f"[SIM] {action} {asset} — ${trade_value:.0f} @ ${price:,.2f}")
        return f"✅ *[SIMULATION]* {action} {asset}\n💰 Montant: ${trade_value:.0f}\n📈 Prix: ${price:,.2f}"

    try:
        if action == "BUY":
            qty = round(trade_value / price, 6)
            order = client.order_market_buy(symbol=symbol, quantity=qty)
        elif action == "SELL":
            qty = min(round(trade_value / price, 6), portfolio.get(asset, 0))
            if qty <= 0:
                return f"⚠️ Pas assez de {asset} à vendre"
            order = client.order_market_sell(symbol=symbol, quantity=qty)
        else:
            return f"⏸ {asset}: HOLD — aucune action"

        return f"✅ *{action} {asset} exécuté*\nOrdre ID: {order['orderId']}\nQté: {qty}\nPrix: ${price:,.2f}"
    except BinanceAPIException as e:
        log.error(f"Binance error: {e}")
        return f"❌ Erreur Binance: {e.message}"

# ─── CYCLE PRINCIPAL ─────────────────────────────────────────────────────────

def run_cycle(binance_client: Client):
    log.info("═══ Nouveau cycle d'analyse ═══")
    try:
        prices    = get_prices()
        portfolio = get_portfolio(binance_client)
        analysis  = analyze_with_claude(prices, portfolio)

        mode = "🔴 RÉEL" if not RISK["simulation_mode"] else "🟡 SIMULATION"
        header = (
            f"📊 *Rapport agent* — {datetime.now().strftime('%H:%M')}\n"
            f"Mode: {mode}\n"
            f"Risque marché: {analysis.get('risk_level','?')}\n\n"
            f"_{analysis.get('market_summary','')}_\n\n"
        )

        results = []
        for d in analysis.get("decisions", []):
            if d["confidence"] < RISK["min_confidence"]:
                log.info(f"Skip {d['symbol']} — confiance {d['confidence']}% < {RISK['min_confidence']}%")
                results.append(f"⏭ {d['symbol'].replace('USDT','')}: ignoré (confiance {d['confidence']}%)")
                continue

            if d["action"] in ("BUY", "SELL"):
                result = execute_trade(
                    binance_client, d["symbol"], d["action"],
                    d.get("amount_pct", 10), portfolio, prices
                )
                results.append(result)
                results.append(f"   💬 {d['reason']}")
            else:
                results.append(f"⏸ {d['symbol'].replace('USDT','')}: HOLD — {d['reason']}")

        telegram(header + "\n".join(results))
        log.info("Cycle terminé — rapport envoyé sur Telegram")

    except Exception as e:
        log.error(f"Erreur cycle: {e}", exc_info=True)
        telegram_alert("Erreur agent", str(e), "⚠️")

# ─── DÉMARRAGE ───────────────────────────────────────────────────────────────

def main():
    log.info("Agent crypto démarré")
    telegram_alert(
        "Agent démarré",
        f"Mode: {'SIMULATION' if RISK['simulation_mode'] else 'RÉEL'}\n"
        f"Coins: {', '.join(COINS)}\n"
        f"Analyse toutes les heures",
        "🚀"
    )

    binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

    # Premier cycle immédiat
    run_cycle(binance_client)

    # Ensuite toutes les heures
    schedule.every(1).hours.do(run_cycle, binance_client=binance_client)

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
