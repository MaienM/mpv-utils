import logging


logging.basicConfig(
	level = logging.DEBUG,
	format = '%(asctime)s - %(levelname)s - %(name)s - %(funcName)s - %(message)s',
)


def getLogger(*name):
	return logging.getLogger('.'.join([getattr(n, '__name__', str(n)) for n in name]))
