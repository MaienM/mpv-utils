import threading
import time

import _logging as logging
from utils import format_timestamp, format_timestamp_ms


class TwitchChatPrinter(threading.Thread):
	"""
	Output relevant Twitch chat messages for an MPV instance.

	This keep tracks of the playback position of an MPV instance, and outputs the chat messages provided by TwitchChat
	with the corresponding timestamps.
	"""

	# Messages that have less than this amount of time between them are considered to happen at the same time.
	MIN_RESOLUTION = 0.05

	# The amount of seconds between syncing the position with MPV.
	MPV_SYNC_INTERVAL = 5

	# The maximum amount of time to correct without skipping messages when out of sync. When we're lagging behind more
	# than this, we'll drop a bunch of messages.
	MAX_CORRECTION_WITHOUT_JUMP = 10

	def __init__(self, mpv, twitch):
		super(TwitchChatPrinter, self).__init__()

		self.log = logging.getLogger(__name__, TwitchChatPrinter)

		self.mpv = mpv
		self.twitch = twitch
		self.stop_requested = threading.Event()

		self.buffer = []
		self.current_timestamp = 0.0
		self.next_request_timestamp = 0
		self.last_sync = float('-inf')

		self.is_paused = None
		self.pause_cond = threading.Condition()

	def stop(self):
		self.stop_requested.set()
		with self.pause_cond:
			self.is_paused = False
			self.pause_cond.notify_all()

	def run(self):
		try:
			self.mpv.on('pause', self._handle_pause)
			self.mpv.on('unpause', self._handle_unpause)
			self._run()
		except Exception as e:
			self.log.exception(e)

	def _run(self):
		self.is_paused = self.mpv.command('get_property', 'pause') == 'true'
		next_messages = []
		last_start = time.time()
		while not self.stop_requested.is_set():
			# Re-sync time if needed.
			time_since_sync = abs(self.current_timestamp - self.last_sync)
			if time_since_sync >= TwitchChatPrinter.MPV_SYNC_INTERVAL:
				self.log.debug(f'{time_since_sync} seconds since last sync, resync is needed')
				old_timestamp = self.current_timestamp
				self._sync_timestamp()
				# If the time changed too much, clear the buffer and start anew.
				if abs(self.current_timestamp - old_timestamp) > TwitchChatPrinter.MAX_CORRECTION_WITHOUT_JUMP:
					print(f'Time changed too much, jumping from {format_timestamp_ms(old_timestamp)} to {format_timestamp_ms(self.current_timestamp)}')
					next_messages = []
					self.buffer = []
					self.next_request_timestamp = int(self.current_timestamp) - TwitchChatPrinter.MAX_CORRECTION_WITHOUT_JUMP

			# Get the next batch of messages, if needed.
			if not next_messages:
				self._ensure_buffer()
				next_messages = [self.buffer.pop(0)]
				cutoff_timestamp = max(next_messages[0].timestamp, self.current_timestamp) + TwitchChatPrinter.MIN_RESOLUTION
				self._ensure_buffer()
				while self.buffer[0].timestamp <= cutoff_timestamp:
					next_messages.append(self.buffer.pop(0))
					self._ensure_buffer()
				self.log.debug(f'Next batch of messages is at {format_timestamp_ms(next_messages[0].timestamp)}')

			# If it is still too early to print these messages, wait for a bit.
			time_til_next_message = next_messages[0].timestamp - self.current_timestamp
			time_til_next_second = 1 - (self.current_timestamp % 1)
			if time_til_next_second < TwitchChatPrinter.MIN_RESOLUTION:
				time_til_next_second += 1
			sleep = min(time_til_next_message, time_til_next_second)
			if sleep >= TwitchChatPrinter.MIN_RESOLUTION:
				self._sleep(sleep)
				self.current_timestamp += sleep
				self._print_timestamp()
				continue

			# Print the messages.
			print('\r', end = '', flush = True)
			for message in next_messages:
				message.print()
			next_messages = []
			self._print_timestamp()

		# Make sure we've moved to the next line. If we don't do this, it's possible that the next print ends up at the
		# end of our timestamp line.
		print()

	def _ensure_buffer(self):
		while not self.buffer:
			self.buffer += self.twitch[self.next_request_timestamp]
			self.next_request_timestamp += 1

	def _sync_timestamp(self):
		old_timestamp = self.current_timestamp
		self.current_timestamp = float(self.mpv.command('get_property', 'playback-time'))
		self.last_sync = self.current_timestamp
		self.log.info(
			f'(Re)synced time with video, adjusted {format_timestamp_ms(old_timestamp)} '
			f'to {format_timestamp_ms(self.current_timestamp)}'
		)

	def _print_timestamp(self):
		print(f'\rVideo time: {format_timestamp(self.current_timestamp + 0.05)}', end = '', flush = True)

	def _sleep(self, timeout):
		"""
		Sleeps for the given amount of playback time.

		This means that this sleep will be longer than the given timeout if the playback is paused.
		"""
		start = time.time()

		def are_we_done_yet():
			""" Check how much time has elapsed, and how much longer (if any) we have to sleep for. """
			nonlocal start, timeout
			end = time.time()
			if self.stop_requested.is_set():
				return True
			if start > end:
				# System time changed, so let's just call it good for this sleep, as we have no idea of how long we
				# actually slept for.
				return True
			timeout -= end - start
			if timeout < TwitchChatPrinter.MIN_RESOLUTION:
				return True
			start = end
			return False

		while timeout > TwitchChatPrinter.MIN_RESOLUTION:
			if not self.pause_cond.acquire(timeout = timeout):
				return
			try:
				if are_we_done_yet():
					return
				if not self.pause_cond.wait_for(lambda: self.is_paused, timeout = timeout):
					return
				if are_we_done_yet():
					return
				# Timeout was not hit, which means the condition (being paused) was met, so wait for unpause. This does not
				# count towards the timeout being hit, as the playback time is not progressing.
				self.log.debug('Waiting for video to be unpaused')
				self.pause_cond.wait_for(lambda: not self.is_paused)
				start = time.time()
			finally:
				self.pause_cond.release()

	def _handle_pause(self, data):
		with self.pause_cond:
			self.log.debug('Video is resumed')
			self.is_paused = True
			self.pause_cond.notify_all()

	def _handle_unpause(self, data):
		with self.pause_cond:
			self.log.debug('Video is paused')
			self.is_paused = False
			self.last_sync = float('-inf')
			self.pause_cond.notify_all()

