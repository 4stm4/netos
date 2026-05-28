import logging
from core.interfaces import LoggerPort

class LoggingAdapter(LoggerPort):

    def __init__(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('container_setup.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger()

    def info(self, message: str, *args):
        self.logger.info(message, *args)

    def error(self, message: str, *args):
        self.logger.error(message, *args)
