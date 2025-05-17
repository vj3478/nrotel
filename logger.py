import logging
import sys

# Create a custom logger
logger = logging.getLogger("newrelic_updater")
logger.setLevel(logging.DEBUG)  # Set to INFO or WARNING in production

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)

# Formatter
formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)s in %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console_handler.setFormatter(formatter)

# Prevent duplicate handlers
if not logger.handlers:
    logger.addHandler(console_handler)

# Optional: prevent log propagation to root logger
logger.propagate = False
