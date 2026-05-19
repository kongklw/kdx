import os
import sys
from pathlib import Path
from loguru import logger


def setup_logging(log_level: str = "INFO", log_dir: str = None):
    """
    Configure loguru to output to both console and file.

    :param log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    :param log_dir: Directory to store log files. Defaults to 'logs' in project root.
    """
    # Determine log directory
    if log_dir is None:
        base_dir = Path(__file__).resolve().parent.parent.parent
        log_dir = base_dir / "logs"
    else:
        log_dir = Path(log_dir)

    # Create log directory if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)

    # Remove default handler
    logger.remove()

    # Add console handler with color
    logger.add(
        sys.stdout,
        level=log_level.upper(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
        colorize=True,
    )

    # Add file handler with rotation
    log_file = log_dir / "kdx-ws-be_{time:YYYY-MM-DD}.log"
    logger.add(
        str(log_file),
        level=log_level.upper(),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="1 day",      # Rotate daily
        retention="7 days",    # Keep logs for 7 days
        compression="zip",     # Compress old logs
        encoding="utf-8",
    )

    logger.info(f"Logging configured with level: {log_level}, log_dir: {log_dir}")
    return logger
