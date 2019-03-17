import logging


CONFIG = {
	'filename': 'log',
	'filemode': 'w',
	'level': logging.DEBUG,
	'format': '%(asctime)s - %(levelname)s - %(name)s - %(funcName)s - %(message)s',
}
logging.basicConfig(**CONFIG)


def getLogger(*name):
	return logging.getLogger('.'.join([getattr(n, '__name__', str(n)) for n in name]))
