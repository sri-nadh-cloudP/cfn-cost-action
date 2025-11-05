"""
This Module serves as a Logging Configuration for CFN Cost Action.

Provides centralized logging setup with GitHub Actions integration.
Supports log levels, GitHub Actions workflow commands, and log grouping.
"""

import logging
import os
import sys
from contextlib import contextmanager
from typing import Optional


class GitHubActionsFormatter(logging.Formatter):
    """
    Custom formatter that outputs GitHub Actions workflow commands.
    
    Converts log levels to GitHub Actions commands:
    - DEBUG -> ::debug::
    - WARNING -> ::warning::
    - ERROR -> ::error::
    - INFO -> plain output (for normal flow)
    """
    
    LEVEL_COMMANDS = {
        logging.DEBUG: '::debug::',
        logging.WARNING: '::warning::',
        logging.ERROR: '::error::',
    }
    
    def format(self, record):
        msg = record.getMessage()
        
        if record.levelno in self.LEVEL_COMMANDS:
            return f"{self.LEVEL_COMMANDS[record.levelno]}{msg}"
        else:
            # INFO and other levels output normally (user-facing messages)
            return msg


class StandardFormatter(logging.Formatter):
    """
    Standard formatter for local development/testing.
    """
    
    def __init__(self):
        super().__init__(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )


def setup_logging(log_level: Optional[str] = None) -> logging.Logger:
    """
    Setup logging configuration for the GitHub Action.
    
    Args:
        log_level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                  If None, reads from INPUT_LOG_LEVEL env var or defaults to INFO.
    
    Returns:
        Configured root logger
    """
    # Determine log level
    if log_level is None:
        log_level = os.environ.get('INPUT_LOG_LEVEL', 'INFO').upper()
    
    # Convert string to logging level
    numeric_level = getattr(logging, log_level, logging.INFO)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    
    # Use GitHub Actions formatter if in GitHub Actions environment
    if os.environ.get('GITHUB_ACTIONS'):
        formatter = GitHubActionsFormatter()
    else:
        formatter = StandardFormatter()
    
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    return root_logger


@contextmanager
def log_group(title: str):
    """
    Context manager for GitHub Actions log groups.
    
    Creates collapsible sections in GitHub Actions logs.
    Falls back to simple headers for local execution.
    
    Args:
        title: Title of the log group
        
    Example:
        with log_group("Processing CDK Files"):
            logger.info("Processing file 1...")
            logger.info("Processing file 2...")
    """
    if os.environ.get('GITHUB_ACTIONS'):
        print(f"::group::{title}")
    else:
        # For local execution, just print a nice header
        print(f"\n{'='*60}")
        print(title)
        print(f"{'='*60}\n")
    
    try:
        yield
    finally:
        if os.environ.get('GITHUB_ACTIONS'):
            print("::endgroup::")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# Convenience functions for common log patterns

def log_section_header(logger: logging.Logger, title: str):
    """Log a section header with visual separators."""
    logger.info(f"\n{'='*60}")
    logger.info(title)
    logger.info(f"{'='*60}\n")


def log_section_footer(logger: logging.Logger, title: str, count: int):
    """Log a section footer with summary."""
    logger.info(f"\n{'='*60}")
    logger.info(title)
    logger.info(f"{'='*60}")
    logger.info(f"{'='*60}\n")

