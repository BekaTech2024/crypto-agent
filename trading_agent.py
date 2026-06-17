"""
Crypto Trading Agent ULTIMATE — Berkan
Analyse multi-dimensionnelle : technique + macro + news + sentiment + corrélations
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timedelta
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
    "max_trade_pct":         0.25,
    "trailing_stop_pct":     0.10,
    "take_profit_pct":       0.25,
    "min_confidence":        75,
    "simulation_mode":       True,
    "alert_threshold":       2.5,
    "min_profit_after_fees": 1.2,
    "trading_fee":           0.1,
    "min_volume_m":          3.0,
    "max_positions":         5,
    "position_sizing":       "dynamic",
}

INITIAL_VALUE = 1000.0

PORTFOLIO = {
    "USDT": 1000.0,
    "BTC": 0.0, "ETH": 0.0, "SOL": 0.0,
    "ADA": 0.0, "AVAX": 0.0, "LINK": 0.0,
    "DOT": 0.0, "XRP": 0.0,
}

PRICE_HIGHS    = {}
PRICE_LOWS     = {}
ENTRY_PRICES   = {}
TRADE_HISTORY  = []
MARKET_MEMORY  = []
prev_prices    = {}
cycle_count    = 0


def telegram(msg):
    try:
        clean = msg.replace("*", "").replace("_", "").replace("`", "")
        parts = [clean[i:i+2000] for i in range(0, len(clean), 2000)]
        for part in parts:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": part},
                timeout=10
            )
            log.info(f"Telegram part: {r.status_code} — {len(part)} chars")
            time.sleep(0.5)
    except Exception as e:
        log.error(f"Telegram error: {e}")


def telegram_alert(title, body, emoji="🤖"):
    telegram(f"{emoji} *{title}*\n\n{body}")


def get_prices():
    try:
        pairs_map = {
            "XBTUSD": "BTC", "ETHUSD": "ETH", "SOLUSD": "SOL",
            "ADAUSD": "ADA", "AVAXUSD": "AVAX", "LINKUSD": "LINK",
            "DOTUSD": "DOT", "XRPUSD": "XRP",
        }
        r = requests.get("https://api.kraken.com/0/public/Ticker", timeout=15)
        data = r.json()
        if data.get("error"):
            return {}
        result = data.get("result", {})
        prices = {}
        for pair, symbol in pairs_map.items():
            if pair in result:
                val = result[pair]
                price = float(val["c"][0])
                prices[symbol] = {
                    "price":   price,
                    "change":  float(val["p"][1]),
                    "volume":  float(val["v"][1]),
                    "high24":  float(val["h"][1]),
                    "low24":   float(val["l"][1]),
                    "vwap24":  float(val["p"][1]),
                    "trades":  int(val["t"][1]),
                }
                if symbol not in PRICE_HIGHS or price > PRICE_HIGHS[symbol]:
                    PRICE_HIGHS[symbol] = price
                if symbol not in PRICE_LOWS or price < PRICE_LOWS[symbol]:
                    PRICE_LOWS[symbol] = price
        log.info(f"Prix: {len(prices)} cryptos")
        return prices
    except Exception as e:
        log.error(f"Erreur prix: {e}")
        return {}


def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        data = r.json()
        val = data["data"][0]
        return {"value": int(val["value"]), "label": val["value_classification"]}
    except:
        return {"value": 50, "label": "Neutral"}


def get_market_news():
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{
                "role": "user",
                "content": (
                    "Cherche les news crypto et macro-économiques importantes des dernières 6 heures. "
                    "Inclus: Bitcoin, Ethereum, Fed/banques centrales, régulation crypto, DeFi, "
                    "indices boursiers SP500/Nasdaq, dollar index. "
                    "Format: liste de 5 points maximum, très concis, en français."
                )
            }]
        )
        return " ".join([b.text for b in msg.content if hasattr(b, "text")])[:800]
    except Exception as e:
        log.error(f"Erreur news: {e}")
        return "News non disponibles."


def compute_technicals(symbol, prices):
    """Calcule les indicateurs techniques disponibles"""
    data = prices.get(symbol, {})
    if not data:
        return {}

    price  = data["price"]
    high24 = data["high24"]
    low24  = data["low24"]
    change = data["change"]
    volume = data["volume"]

    range24    = high24 - low24
    position   = ((price - low24) / range24 * 100) if range24 > 0 else 50
    volatility = (range24 / low24 * 100) if low24 > 0 else 0

    rsi_approx = 50 + (change * 2)
    rsi_approx = max(0, min(100, rsi_approx))

    held = PORTFOLIO.get(symbol, 0)
    entry = ENTRY_PRICES.get(symbol, price)
    pnl_pct = ((price - entry) / entry * 100) if entry > 0 and held > 0 else 0

    trailing_stop = PRICE_HIGHS.get(symbol, price) * (1 - RISK["trailing_stop_pct"])
    stop_distance = ((price - trailing_stop) / price * 100)

    return {
        "rsi_approx":     round(rsi_approx, 1),
        "position_24h":   round(position, 1),
        "volatility_pct": round(volatility, 2),
        "pnl_pct":        round(pnl_pct, 2),
        "trailing_stop":  round(trailing_stop, 4),
        "stop_distance":  round(stop_distance, 2),
        "volume_m":       round(volume / 1e6, 2),
    }


def check_trailing_stops(prices):
    for symbol, data in prices.items():
        held = PORTFOLIO.get(symbol, 0)
        if held <= 0:
            continue
        price    = data["price"]
        volume_m = data["volume"] / 1e6
        highest  = PRICE_HIGHS.get(symbol, price)
        drop     = ((price - highest) / highest) * 100

        if drop <= -(RISK["trailing_stop_pct"] * 100):
            if volume_m < RISK["min_volume_m"]:
                telegram(
                    f"⚠️ *Stop {symbol} ignoré* — volume ${volume_m:.1f}M trop faible\n"
                    f"Chute {drop:.1f}% = probable faux signal. On surveille."
                )
            else:
                result = execute_virtual_trade(symbol, "SELL", 100, prices)
                telegram(
                    f"🛑 *Trailing stop {symbol}*\n"
                    f"Chute {drop:.1f}% depuis plus haut ${highest:,.2f}\n"
                    f"Volume confirmé ${volume_m:.1f}M\n{result}"
                )


def execute_virtual_trade(symbol, action, amount_pct, prices):
    if symbol not in prices:
        return None
    price = prices[symbol]["price"]
    portfolio_value = PORTFOLIO["USDT"]
    for sym, d in prices.items():
        portfolio_value += PORTFOLIO.get(sym, 0) * d["price"]

    open_positions = sum(1 for s in PORTFOLIO if s != "USDT" and PORTFOLIO[s] > 0)

    if action == "BUY":
        if open_positions >= RISK["max_positions"]:
            return f"⏭ Max positions atteint ({RISK['max_positions']})"
        trade_value = portfolio_value * (amount_pct / 100)
        fee  = trade_value * (RISK["trading_fee"] / 100)
        cost = trade_value + fee
        if PORTFOLIO["USDT"] < cost:
            return f"⚠️ Cash insuffisant (${PORTFOLIO['USDT']:.0f} < ${cost:.0f})"
        qty = trade_value / price
        PORTFOLIO["USDT"]  -= cost
        PORTFOLIO[symbol]   = PORTFOLIO.get(symbol, 0) + qty
        ENTRY_PRICES[symbol] = price
        PRICE_HIGHS[symbol]  = price
        TRADE_HISTORY.append({"time": datetime.now().strftime("%H:%M"), "action": "BUY", "symbol": symbol, "price": price, "value": trade_value})
        return f"✅ *ACHAT {symbol}* {qty:.4f} @ ${price:,.4f} | frais ${fee:.2f}"

    elif action == "SELL":
        held = PORTFOLIO.get(symbol, 0)
        if held <= 0:
            return f"⚠️ Pas de {symbol}"
        sell_qty = held * (amount_pct / 100)
        revenue  = sell_qty * price * (1 - RISK["trading_fee"] / 100)
        entry    = ENTRY_PRICES.get(symbol, price)
        pnl_pct  = ((price - entry) / entry * 100)
        PORTFOLIO[symbol]  -= sell_qty
        PORTFOLIO["USDT"]  += revenue
        if PORTFOLIO[symbol] <= 0.0001:
            PORTFOLIO[symbol] = 0
            ENTRY_PRICES.pop(symbol, None)
            PRICE_HIGHS.pop(symbol, None)
        TRADE_HISTORY.append({"time": datetime.now().strftime("%H:%M"), "action": "SELL", "symbol": symbol, "price": price, "value": revenue, "pnl_pct": pnl_pct})
        return f"🔴 *VENTE {symbol}* {sell_qty:.4f} @ ${price:,.4f} | P&L: {pnl_pct:+.2f}% | reçu ${revenue:.2f}"

    return None


def quick_analysis(prices):
    global prev_prices
    check_trailing_stops(prices)
    alerts = []
    for symbol, data in prices.items():
        if symbol in prev_prices:
            prev = prev_prices[symbol]["price"]
            curr = data["price"]
            chg  = ((curr - prev) / prev) * 100
            vol  = data["volume"] / 1e6
            if abs(chg) >= RISK["alert_threshold"]:
                quality = "signal fort" if vol >= RISK["min_volume_m"] else "volume faible"
                icon = "🚀" if chg > 0 else "📉"
                alerts.append(f"{icon} *{symbol}* {chg:+.2f}% — ${curr:,.4f} ({quality})")
    if alerts:
        telegram("⚡ *Mouvement détecté*\n\n" + "\n".join(alerts))
    prev_prices = dict(prices)


def deep_analysis(prices):
    global cycle_count, MARKET_MEMORY
    if not prices:
        return
    cycle_count += 1

    try:
        portfolio_value = PORTFOLIO["USDT"]
        for sym, d in prices.items():
            portfolio_value += PORTFOLIO.get(sym, 0) * d["price"]
        pnl     = portfolio_value - INITIAL_VALUE
        pnl_pct = (pnl / INITIAL_VALUE) * 100

        fg      = get_fear_greed()
        news    = get_market_news()

        technicals = {sym: compute_technicals(sym, prices) for sym in prices}

        market_correlation = []
        changes = [d["change"] for d in prices.values()]
        avg_change = sum(changes) / len(changes) if changes else 0
        if avg_change < -3:
            market_correlation.append("CORRECTION GLOBALE — tout le marché baisse ensemble")
        elif avg_change > 3:
            market_correlation.append("RALLY GLOBAL — marché haussier généralisé")
        else:
            divergents = [s for s, d in prices.items() if abs(d["change"] - avg_change) > 5]
            if divergents:
                market_correlation.append(f"Divergence: {', '.join(divergents)} se démarquent du marché")

        open_positions = []
        for sym in PORTFOLIO:
            if sym != "USDT" and PORTFOLIO[sym] > 0:
                val   = PORTFOLIO[sym] * prices.get(sym, {}).get("price", 0)
                entry = ENTRY_PRICES.get(sym, 0)
                curr  = prices.get(sym, {}).get("price", 0)
                pnl_p = ((curr - entry) / entry * 100) if entry > 0 else 0
                open_positions.append(f"  {sym}: {PORTFOLIO[sym]:.4f} = ${val:.2f} | P&L: {pnl_p:+.2f}% | stop: ${PRICE_HIGHS.get(sym,curr)*(1-RISK['trailing_stop_pct']):.4f}")

        recent_trades_str = "\n".join([
            f"  {t['time']} {t['action']} {t['symbol']} @ ${t['price']:,.4f}"
            for t in TRADE_HISTORY[-8:]
        ]) or "  Aucun trade"

        tech_summary = "\n".join([
            f"  {sym}: RSI~{t['rsi_approx']} | vol ${t['volume_m']}M | volatilité {t['volatility_pct']}% | pos 24h {t['position_24h']}%"
            for sym, t in technicals.items()
        ])

        memory_str = "\n".join(MARKET_MEMORY[-3:]) if MARKET_MEMORY else "Premier cycle"

        prompt = f"""Tu es un trader quantitatif expert et psychopathe de l'analyse. Tu ne laisses rien au hasard.
Tu relies TOUT : macro, technique, volume, sentiment, corrélations, mémoire des cycles précédents.
Tu identifies les pièges, les faux signaux, les opportunités cachées.
Tu penses comme un hedge fund — chaque décision est justifiée par plusieurs facteurs convergents.

=== ACTUALITÉS TEMPS RÉEL ===
{news}

=== SENTIMENT MARCHÉ ===
Fear & Greed Index: {fg['value']}/100 — {fg['label']}
(0=peur extrême=opportunité achat, 100=avidité extrême=signal vente)

=== CORRÉLATION MARCHÉ ===
Variation moyenne toutes cryptos: {avg_change:+.2f}%
{chr(10).join(market_correlation)}

=== DONNÉES TECHNIQUES ===
{tech_summary}

=== PRIX DÉTAILLÉS ===
{chr(10).join([f"  {s}: ${d['price']:,.4f} | {d['change']:+.2f}% 24h | H:{d['high24']:,.4f} L:{d['low24']:,.4f} | vol ${d['volume']/1e6:.1f}M | {d['trades']} trades" for s,d in prices.items()])}

=== PORTEFEUILLE (départ ${INITIAL_VALUE:.0f}) ===
Valeur totale: ${portfolio_value:,.2f} ({pnl_pct:+.2f}% | {pnl:+.2f}$)
Cash USDT: ${PORTFOLIO['USDT']:,.2f}
Positions ouvertes ({len(open_positions)}/{RISK['max_positions']}):
{chr(10).join(open_positions) if open_positions else '  Aucune position'}

=== DERNIERS TRADES ===
{recent_trades_str}

=== MÉMOIRE CYCLES PRÉCÉDENTS ===
{memory_str}

=== RÈGLES STRICTES ===
- Volume < ${RISK['min_volume_m']}M = faux signal potentiel, prudence maximale
- Trailing stop: -{RISK['trailing_stop_pct']*100:.0f}% depuis plus haut (déjà géré automatiquement)
- Max {RISK['max_positions']} positions simultanées
- Si CORRECTION GLOBALE: chercher les plus forts pour rebond, pas les plus faibles
- Si Fear & Greed < 25: zone achat (tout le monde a peur = opportunité)
- Si Fear & Greed > 75: zone vente (tout le monde est euphorique = danger)
- Ne jamais vendre sur panique sans volume confirmé
- Frais: {RISK['trading_fee']*2:.1f}% aller-retour | Profit min net: +{RISK['min_profit_after_fees']}%
- Confiance minimum pour agir: {RISK['min_confidence']}%

Analyse TOUT de façon exhaustive. Fais les liens. Sois précis et justifié.
Réponds UNIQUEMENT en JSON valide:
{{
  "decisions": [
    {{
      "symbol": "BTC",
      "action": "BUY|SELL|HOLD",
      "amount_pct": 20,
      "confidence": 82,
      "estimated_profit_pct": 8.5,
      "reason": "analyse multi-facteurs détaillée",
      "risk_factors": "risques identifiés",
      "macro_link": "lien avec contexte macro"
    }}
  ],
  "market_summary": "analyse globale 3 phrases max",
  "risk_level": "LOW|MEDIUM|HIGH|EXTREME",
  "macro_alert": "alerte macro critique ou null",
  "best_opportunity": "SYMBOL — analyse complète",
  "worst_risk": "SYMBOL ou situation à éviter",
  "cycle_note": "note pour mémoriser ce cycle (1 phrase)"
}}"""

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )

        raw      = message.content[0].text.strip().replace("```json","").replace("```","").strip()
        analysis = json.loads(raw)

        if analysis.get("cycle_note"):
            MARKET_MEMORY.append(f"Cycle {cycle_count} ({datetime.now().strftime('%H:%M')}): {analysis['cycle_note']}")
            if len(MARKET_MEMORY) > 10:
                MARKET_MEMORY.pop(0)

        pnl_icon   = "📈" if pnl >= 0 else "📉"
        fg_icon    = "😱" if fg["value"] < 25 else "😨" if fg["value"] < 45 else "😐" if fg["value"] < 55 else "😊" if fg["value"] < 75 else "🤑"
        macro_alert = analysis.get("macro_alert")
        worst_risk  = analysis.get("worst_risk")

        header = (
            f"🧠 *Analyse #{cycle_count}* — {datetime.now().strftime('%H:%M')}\n"
            f"{'🔴 RÉEL' if not RISK['simulation_mode'] else '🟡 SIMULATION'} | Risque: {analysis.get('risk_level','?')}\n"
            f"{pnl_icon} Portfolio: ${portfolio_value:,.2f} ({pnl_pct:+.2f}% | {pnl:+.2f}$)\n"
            f"💵 Cash: ${PORTFOLIO['USDT']:,.2f}\n"
            f"{fg_icon} Fear&Greed: {fg['value']}/100 — {fg['label']}\n"
        )
        if macro_alert:
            header += f"⚠️ *MACRO:* {macro_alert}\n"
        if worst_risk:
            header += f"🚫 *Risque:* {worst_risk}\n"

        header += (
            f"💡 *Opportunité:* {analysis.get('best_opportunity','—')}\n\n"
            f"_{analysis.get('market_summary','')}_\n\n"
            f"*Décisions:*\n"
        )

        results = []
        for d in analysis.get("decisions", []):
            sym        = d.get("symbol","?")
            action     = d["action"]
            conf       = d["confidence"]
            reason     = d["reason"]
            risk_f     = d.get("risk_factors","")
            macro_link = d.get("macro_link","")
            profit     = d.get("estimated_profit_pct", 0)
            net_profit = profit - (RISK["trading_fee"] * 2)
            volume_m   = prices.get(sym, {}).get("volume", 0) / 1e6

            if conf < RISK["min_confidence"]:
                results.append(f"⏭ *{sym}* ignoré — confiance {conf}%")
                continue

            if action in ("BUY", "SELL"):
                if volume_m < RISK["min_volume_m"] and action == "BUY":
                    results.append(f"⏭ *{sym}* ignoré — volume ${volume_m:.1f}M insuffisant")
                    continue
                if action == "BUY" and net_profit < RISK["min_profit_after_fees"]:
                    results.append(f"⏭ *{sym}* ignoré — profit net {net_profit:.1f}% insuffisant")
                    continue
                trade_result = execute_virtual_trade(sym, action, d.get("amount_pct", 20), prices)
                if trade_result:
                    results.append(trade_result)
                    results.append(f"   _{reason}_")
                    if risk_f:
                        results.append(f"   Risques: {risk_f}")
                    if macro_link:
                        results.append(f"   Macro: {macro_link}")
            else:
                results.append(f"⏸ *HOLD {sym}* (conf {conf}%)\n   _{reason}_")

        if not results:
            results.append("⏸ Aucune action — signal insuffisant, on protège le capital.")

        portfolio_lines = [f"  USDT: ${PORTFOLIO['USDT']:,.2f}"]
        for sym, d in prices.items():
            held = PORTFOLIO.get(sym, 0)
            if held > 0:
                val   = held * d["price"]
                entry = ENTRY_PRICES.get(sym, d["price"])
                pnl_p = ((d["price"] - entry) / entry * 100)
                stop  = PRICE_HIGHS.get(sym, d["price"]) * (1 - RISK["trailing_stop_pct"])
                portfolio_lines.append(f"  {sym}: {held:.4f} = ${val:.2f} | {pnl_p:+.2f}% | stop ${stop:,.4f}")

        footer = "\n\n💼 *Positions:*\n" + "\n".join(portfolio_lines)

        if len(TRADE_HISTORY) > 0:
            last_trades = TRADE_HISTORY[-3:]
            footer += "\n\n📋 *Derniers trades:*\n"
            for t in last_trades:
                pnl_str = f" | P&L {t.get('pnl_pct',0):+.2f}%" if "pnl_pct" in t else ""
                footer += f"  {t['time']} {t['action']} {t['symbol']} @ ${t['price']:,.4f}{pnl_str}\n"

        telegram(header + "\n".join(results) + footer)
        log.info(f"Analyse #{cycle_count} terminée — ${portfolio_value:,.2f}")

    except Exception as e:
        log.error(f"Erreur analyse: {e}", exc_info=True)
        telegram_alert("Erreur", str(e)[:500], "⚠️")


def cycle_rapide():
    log.info("Cycle rapide")
    prices = get_prices()
    if prices:
        quick_analysis(prices)


def cycle_profond():
    log.info("Cycle approfondi")
    prices = get_prices()
    deep_analysis(prices)


def main():
    log.info("Agent ULTIMATE démarré")
    telegram_alert(
        "Agent ULTIMATE actif",
        "Analyse multi-dimensionnelle:\n"
        "- Technique (RSI, volatilite, position 24h)\n"
        "- Volume (filtre faux signaux)\n"
        "- Macro (news temps reel)\n"
        "- Sentiment (Fear & Greed Index)\n"
        "- Correlation marche global\n"
        "- Memoire des cycles precedents\n"
        "- Trailing stop dynamique\n"
        "- Max 5 positions simultanees\n\n"
        f"Portfolio: ${INITIAL_VALUE:.0f} USDT virtuel\n"
        "Cycle rapide: 15min | Analyse: 1h",
        "🧠"
    )
    cycle_profond()
    schedule.every(15).minutes.do(cycle_rapide)
    schedule.every(1).hours.do(cycle_profond)
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
