import logging
import os
from logging.handlers import RotatingFileHandler

# Create logs directory
log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)

logger = logging.getLogger("JobHunter")
logger.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Rotating file handler (5MB max per file, keep 3 backups)
file_handler = RotatingFileHandler(
    os.path.join(log_dir, "job_hunter.log"), 
    maxBytes=5*1024*1024, 
    backupCount=3
)
file_handler.setFormatter(formatter)

# Console handler for debugging
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)
