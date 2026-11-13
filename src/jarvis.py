import logging
from logger import setup_logger

logger = logging.getLogger(__name__)


def main():
    setup_logger()
    logger.info("Starting JARVIS...")
    
    # Imported here, not at the top: importing state_machine loads every model (several seconds), and a
    # Ctrl-C during that should exit cleanly too.
    from state_machine import JarvisMachine
    JarvisMachine()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:  # Ctrl-C; not an Exception subclass, so nothing below catches it on the way up
        logger.info("Shutting down.")
