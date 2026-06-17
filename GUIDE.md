"""
Bot Telegram de contrôle — commandes manuelles pour l'agent
"""

import os
import json
import requests
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# État partagé de l'agent (chargé depuis fichier)
def load_state():
    try:
        with open("config/state.json") as f:
            return json.load(f)
    except:
        return {"paused": False, "simulation": True, "risk_level": "MEDIUM"}

def save_state(state):
    os.makedirs("config", exist_ok=True)
    with open("config/state.json", "w") as f:
        json.dump(state, f, indent=2)

# ─── COMMANDES ───────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 Statut", callback_data="status"),
         InlineKeyboardButton("⏸ Pause", callback_data="pause")],
        [InlineKeyboardButton("▶️ Reprendre", callback_data="resume"),
         InlineKeyboardButton("🔄 Forcer analyse", callback_data="force")],
        [InlineKeyboardButton("⚙️ Paramètres risque", callback_data="settings"),
         InlineKeyboardButton("📈 Portfolio", callback_data="portfolio")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 *Agent Crypto — Panneau de contrôle*\n\nChoisissez une action :",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    state = load_state()
    data = query.data

    if data == "status":
        mode = "🔴 RÉEL" if not state.get("simulation") else "🟡 SIMULATION"
        paused = "⏸ EN PAUSE" if state.get("paused") else "✅ ACTIF"
        msg = (
            f"📊 *Statut de l'agent*\n\n"
            f"État: {paused}\n"
            f"Mode: {mode}\n"
            f"Risque max/trade: {state.get('max_trade_pct', 20)}%\n"
            f"Stop-loss: -{state.get('stop_loss_pct', 8)}%\n"
            f"Confiance min: {state.get('min_confidence', 70)}%"
        )
        await query.edit_message_text(msg, parse_mode="Markdown")

    elif data == "pause":
        state["paused"] = True
        save_state(state)
        await query.edit_message_text("⏸ *Agent mis en pause*\nAucun trade ne sera exécuté.", parse_mode="Markdown")

    elif data == "resume":
        state["paused"] = False
        save_state(state)
        await query.edit_message_text("▶️ *Agent relancé*\nProchain cycle dans max 1h.", parse_mode="Markdown")

    elif data == "force":
        state["force_run"] = True
        save_state(state)
        await query.edit_message_text("🔄 *Analyse forcée déclenchée*\nRésultat dans quelques secondes...", parse_mode="Markdown")

    elif data == "settings":
        keyboard = [
            [InlineKeyboardButton("Risque faible (10%/trade)", callback_data="risk_low")],
            [InlineKeyboardButton("Risque moyen (20%/trade)", callback_data="risk_medium")],
            [InlineKeyboardButton("Risque élevé (35%/trade)", callback_data="risk_high")],
        ]
        await query.edit_message_text(
            "⚙️ *Choisissez votre niveau de risque:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("risk_"):
        levels = {"risk_low": 10, "risk_medium": 20, "risk_high": 35}
        pct = levels[data]
        state["max_trade_pct"] = pct
        save_state(state)
        await query.edit_message_text(f"✅ *Risque mis à jour*\nMax {pct}% du portfolio par trade.", parse_mode="Markdown")

    elif data == "portfolio":
        # Dans un vrai déploiement, on lirait le vrai portfolio
        await query.edit_message_text(
            "📈 *Portfolio (simulation)*\n\n"
            "BTC: 0.05 = $3,371\n"
            "ETH: 0.30 = $1,062\n"
            "SOL: 2.00 = $344\n"
            "BNB: 0.50 = $299\n"
            "USDT: $4,924\n\n"
            "*Total: ~$10,000*",
            parse_mode="Markdown"
        )

async def stop_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    state["paused"] = True
    save_state(state)
    await update.message.reply_text("⏹ *Agent arrêté.*", parse_mode="Markdown")

async def go_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    state["paused"] = False
    save_state(state)
    await update.message.reply_text("▶️ *Agent relancé !*", parse_mode="Markdown")

# ─── DÉMARRAGE ───────────────────────────────────────────────────────────────

def run_telegram_bot():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("go", go_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    log.info("Bot Telegram démarré")
    app.run_polling()

if __name__ == "__main__":
    run_telegram_bot()
