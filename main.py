import threading
import logging
import os

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

from agent.trading_agent import main as run_agent
from agent.telegram_bot import run_telegram_bot

if __name__ == "__main__":
    t1 = threading.Thread(target=run_agent, daemon=True)
    t1.start()
    run_telegram_bot()
