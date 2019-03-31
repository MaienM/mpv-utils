def format_timestamp(timestamp):
	""" Convert a time in seconds to a human readable format. """
	return f'{int(timestamp / 3600)}:{int((timestamp % 3600) / 60):02}:{int(timestamp % 60):02}'

def format_timestamp_ms(timestamp):
	""" Convert a time in seconds to a human readable format, with milliseconds. """
	return f'{format_timestamp(timestamp)}.{int((timestamp % 1) * 1000):03}'
