import logging
from logging.handlers import RotatingFileHandler
import sys
import os

def init_logging():
    os.makedirs("logs", exist_ok=True)
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    if logger.handlers:
        return

    # File gets full timestamp and module info
    file_formatter = logging.Formatter('[%(asctime)s] %(levelname)s [%(name)s.%(module)s]: %(message)s')
    file_handler = RotatingFileHandler("logs/indus3d.log", maxBytes=5*1024*1024, backupCount=3)
    file_handler.setFormatter(file_formatter)
    
    # Console gets simple output (we already have emojis for clarity)
    console_formatter = logging.Formatter('%(message)s')
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Reduce noise from werkzeug (Flask's internal server)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

init_logging()
