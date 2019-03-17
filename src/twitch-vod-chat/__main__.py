import re
import threading
import time

from config import Config
import _logging as logging
from mpv import MPV
from printer import TwitchChatPrinter
from twitch_chat import TwitchChat
from utils import format_timestamp, format_timestamp_ms


TWITCH_VOD_RE = re.compile('https?://(www\.)?twitch.tv/videos/(?P<id>\d+)/?')


def main():
	log = logging.getLogger(__name__)

	# Load the config.
	config = Config()

	# Connect to MPV.
	mpv = MPV(config.get_str('core', 'socket_path'))
	mpv.start()

	# Listen to changes in the file that is being played.
	previous_path = None
	printer = None
	twitch = None
	def path_change(path):
		nonlocal previous_path, printer, twitch

		log.debug(f'Path change from {previous_path} to {path}.')
		if path == previous_path:
			return
		previous_path = path

		if printer:
			printer.stop()
			printer.join()
		if twitch:
			twitch.stop()
			twitch.join()

		match = TWITCH_VOD_RE.match(path)
		if not match:
			log.info('\nCurrent video is not a twitch vod, no chat to show...')
			return

		log.info(f'\nNew twitch vod started ({path}), showing chat...')
		vod_id = match.group('id')
		position = int(float(mpv.command('get_property', 'playback-time')))
		twitch = TwitchChat(config.get_str('twitch', 'client_id'), vod_id, start = position)
		twitch.start()
		printer = TwitchChatPrinter(mpv, twitch)
		printer.start()
	mpv.observe('path', path_change, request_initial = True)

	try:
		while True:
			time.sleep(30)
	except KeyboardInterrupt:
		print()
		if printer:
			print('Stopping printer...')
			printer.stop()
			printer.join()
		if twitch:
			print('Stopping chat fetcher...')
			twitch.stop()
			twitch.join()
		print('Stopping mpv wrapper...')
		mpv.stop()
		mpv.join()


if __name__ == '__main__':
	main()
