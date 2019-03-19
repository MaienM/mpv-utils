import json
import requests
import threading
import time
import weakref

import colr

from config import Configurable
import _logging as logging
from symbols import BADGES
from utils import format_timestamp


class TwitchCommenter(object):
	""" A class representing a Twitch chat member. """

	INSTANCES = weakref.WeakValueDictionary()

	def __init__(self, data):
		self.id = data['_id']
		self.name = data.get('display_name', data.get('name', 'Unknown'))

	@classmethod
	def get(cls, data):
		_id = data['_id']
		try:
			return cls.INSTANCES[_id]
		except KeyError:
			cls.INSTANCES[_id] = instance = cls(data)
			return instance

	def __repr__(self):
		return f'TwitchCommenter<id={repr(self.id)},name={repr(self.name)}>'


class TwitchMessage(object):
	""" A class representing a Twitch chat message. """

	def __init__(self, data):
		self.id = data['_id']
		self.timestamp = data['content_offset_seconds']
		message = data['message']
		self.message = message['body']
		badge_ids = [badge['_id'] for badge in message.get('user_badges', [])]
		self.badges = [BADGES[_id] for _id in badge_ids if _id in BADGES]
		self.commenter = TwitchCommenter.get(data['commenter'])
		if 'user_color' in message:
			self.color = self._shift_color(colr.hex2rgb(message['user_color']))
		else:
			self.color = 'white'

	@classmethod
	def configure(cls, config):
		background = config.get_enum('core', 'background', ('light', 'dark', 'unknown'))
		if background == 'light':
			cls._shift_color = cls._shift_color_light
		elif background == 'dark':
			cls._shift_color = cls._shift_color_light

	@staticmethod
	def _shift_color(color):
		return color

	@staticmethod
	def _shift_color_dark(color):
		return tuple(c * 0.75 + 63 for c in color)

	@staticmethod
	def _shift_color_light(color):
		return tuple(c * 0.75 for c in color)

	def print(self):
		print(
			f'{format_timestamp(self.timestamp)} '
			f'<{"".join(self.badges)}{colr.color(self.commenter.name, fore = self.color)}> '
			f'{self.message}'
		)

	def __repr__(self):
		return (
			f'TwitchMessage<id={repr(self.id)},timestamp={self.timestamp},commenter={repr(self.commenter)},'
			f'color={self.color}>'
		)


class TwitchChat(threading.Thread, Configurable):
	""" A class representing the chat for a given VOD. """

	# The amount of time (in seconds) before the last message is reached that we will start loading more messages.
	LOAD_MORE_TRESHOLD = 30

	# The minimum amount of old (that is, before the last requested timestamp) messages to keep. It is possible that
	# more messages are kept at times (or less, if less messages than this exist). Can be useful to prevent having to
	# re-load all messages when a backwards jump in time happens.
	KEEP_MESSAGES_BEHIND = 500

	# The amount of messages to have that lie in the future (that is, after the last requested timestamp) when loading
	# more messages. It's possible that less (or slightly more) messages than this exist at any time, but this is the
	# target when loading more.
	LOAD_MESSAGES_AHEAD = 1000

	def __init__(self, vodid, start = 0):
		super(TwitchChat, self).__init__()

		self.log = logging.getLogger(__name__, TwitchChat, vodid)

		self.vodid = vodid
		self.stop_requested = threading.Event()

		# The messages are stores in a list, in chronological order. The time_slices variable is a mapping of timestamp
		# (rounded down to the second) to the index of the first message and last message in that second.
		self.lock = threading.RLock()
		self.data_loaded = threading.Condition()
		self.needs_loading = threading.Condition()
		self.messages = []
		self.time_slices = {}
		self.loaded_range = (-1, -1)
		self.last_requested_position = start

	@classmethod
	def configure(cls, config):
		cls.client_id = config.get_str('twitch', 'client_id')

	def stop(self):
		self.stop_requested.set()
		with self.needs_loading:
			self.needs_loading.notify()

	def run(self):
		try:
			self._run()
		except Exception as e:
			self.log.exception(e)

	def _run(self):
		while not self.stop_requested.is_set():
			# Check whether we need to load more messages
			if self.last_requested_position + TwitchChat.LOAD_MORE_TRESHOLD >= self.loaded_range[1]:
				self._load_more()
			if self.stop_requested.is_set():
				return

			# Wait until a sufficient amount of time has passed, but allow earlier triggering by use of a condition.
			self.log.debug('Waiting for timer/interrupt')
			with self.needs_loading:
				self.needs_loading.wait(30)
			self.log.debug('Checking whether we need to load more')

	def __getitem__(self, timestamp):
		# Load more if the timestamp is outside of what is currently loaded.
		if timestamp not in range(self.loaded_range[0], self.loaded_range[1] + 1):
			self.log.info(
				f'Requested timestamp ({format_timestamp(timestamp)}) is outside of the loaded range '
				f'{format_timestamp(self.loaded_range[0])} - {format_timestamp(self.loaded_range[1])}, '
				'sending interrupt to load more'
			)
			with self.lock:
				self.last_requested_position = timestamp
			with self.data_loaded:
				with self.needs_loading:
					self.needs_loading.notify()
				self.log.debug(f'Waiting for requested timestamp ({format_timestamp(timestamp)}) to become available')
				self.data_loaded.wait_for(lambda: timestamp in range(self.loaded_range[0], self.loaded_range[1] + 1))
			self.log.debug(f'Requested timestamp ({format_timestamp(timestamp)}) has become available, proceeding')

		with self.lock:
			slice = self.time_slices.get(timestamp, (0, -1))
			return self.messages[slice[0]:slice[1] + 1]

	def _get_next_timestamp_index(self, time):
		"""
		Get the index that messages for the given timestamp start at in the message list.

		This will return the index for the next message after the given timestamp if none exist at the timestamp itself.
		"""
		with self.lock:
			if not self.time_slices:
				return 0
			if time not in self.time_slices:
				times_ahead = [t for t in self.time_slices.keys() if t > time]
				if not times_ahead:
					return len(self.messages)
				time = min(times_ahead)
			return self.time_slices[time][0]

	def _update_indexes(self):
		""" Re-scans the message list and updates the time slices and loaded range based on it. """
		with self.lock:
			# Update the time slices.
			self.time_slices.clear()
			start_index = -1
			current_timestamp = -1
			for i, message in enumerate(self.messages):
				timestamp = int(message.timestamp)
				if timestamp != current_timestamp:
					self.time_slices[current_timestamp] = (start_index, i - 1)
					start_index = i
					current_timestamp = timestamp
			self.time_slices[current_timestamp] = (start_index, i - 1)
			del self.time_slices[-1]

			slices_debug = sorted(self.time_slices.items(), key = lambda p: p[0])
			slices_debug = [(format_timestamp(k), v[1] - v[0] + 1) for k, v in slices_debug]
			self.log.debug(f'Slices: {slices_debug}')

			# Update the loaded range. We subtract one from the highest known timestamp because there is no guarantee
			# that we have _all_ messages for that timestamp.
			self.loaded_range = (
				min(self.last_requested_position, *self.time_slices.keys()),
				max(self.time_slices.keys()) - 1,
			)
			self.log.info(f'Range: {format_timestamp(self.loaded_range[0])} - {format_timestamp(self.loaded_range[1])}')

	def _clean_stored_messages(self):
		""" Trim the message list to the messages that are still relevant given the current position and settings. """
		with self.lock:
			# If we go back to before the currently loaded range, we simply clear the entire list.
			# TODO: this is not optimal if we go back to only a little bit before the currently loaded range.
			if self.last_requested_position < self.loaded_range[0]:
				del self.messages[:]
				return

			# Remove old messages beyond the specified buffer.
			first_index_of_next_timestamp = self._get_next_timestamp_index(self.last_requested_position)
			cutoff_index = min(first_index_of_next_timestamp - TwitchChat.KEEP_MESSAGES_BEHIND, 0)
			self.log.info(f'Clearing {cutoff_index} old messages')
			del self.messages[:cutoff_index]

			# Update the indexes.
			self._update_indexes()

	def _process_messages(self, messages):
		messages = [TwitchMessage(message) for message in messages]
		self.log.debug(f'Processing {len(messages)} messages: {messages}')
		with self.lock:
			# The API appears to return some more messages than needed, at least on the first request. Drop all messages
			# that we already have.
			if self.messages and messages[0].timestamp < self.messages[-1].timestamp:
				last_message = self.messages[-1]
				self.log.info(f'Possible duplicate messages, dropping messages until we find message {last_message}')
				for i, message in enumerate(messages):
					if message == last_message:
						del messages[:i + 1]
						self.log.info(
							f'Found last known message in new received list at position {i}. '
							f'Dropping everything up to and including this message, keeping {len(messages)}.'
						)
						break
				else:
					self.log.warn(
						f"Unable to find last known message in the received list. Keeping all messages. "
						"It's possible this means duplicates were kept."
					)

			self.messages += messages
			self._update_indexes()
		self.log.info(f'Message buffer size: {len(self.messages)}')
		self.log.debug(f'Message buffer: {self.messages}')

		# Notify listeners that the data has been updated.
		with self.data_loaded:
			self.data_loaded.notify_all()

	def _load_more(self):
		self.log.info('Starting load')
		# Determine the amount of messages that need to be loaded to get back to the LOAD_MESSAGES_AHEAD size.
		with self.lock:
			next_timestamp_index = self._get_next_timestamp_index(self.last_requested_position)
			num_messages_ahead = max(0, len(self.messages) - next_timestamp_index)

		# Load messages until the amount of loaded messages + the existing buffer bring us to the treshold, or until
		# there are no more messages.
		to_load = TwitchChat.LOAD_MESSAGES_AHEAD - num_messages_ahead
		cursor = None
		session = requests.Session()
		session.headers = { 'Client-ID': self.client_id, 'Accept': 'application/vnd.twitchtv.v5+json' }

		def load_with_qargs(qargs):
			nonlocal cursor, to_load
			self.log.debug(f'Loading with args {qargs}')
			response = session.get(f'https://api.twitch.tv/v5/videos/{self.vodid}/comments?{qargs}', timeout = 10)
			response.raise_for_status()
			data = response.json()
			cursor = data['_next']
			messages = data['comments']
			to_load -= len(messages)
			self._process_messages(messages)

		self.log.debug(f'{to_load} messages remaining')
		start_time = max(self.last_requested_position, self.loaded_range[1] + 1)
		load_with_qargs(f'content_offset_seconds={start_time}')
		while cursor and to_load > 0 and not self.stop_requested.is_set():
			time.sleep(0.1)
			self.log.debug(f'{to_load} messages remaining')
			load_with_qargs(f'cursor={cursor}')
		if not cursor:
			# This means all messages have been loaded, which means the loaded_range should stretch to the end of the
			# video.
			with self.lock:
				self.loaded_range = (self.loaded_range[0], float('inf'))
		if self.loaded_range[1] - self.last_requested_position < TwitchChat.LOAD_MORE_TRESHOLD:
			self.log.warn(
				f'After filling the message buffer to the max ({TwitchChat.LOAD_MESSAGES_AHEAD}), '
				f'it only covers up to {self.loaded_range[1] - self.last_requested_position} seconds ahead, '
				f'which is less than the load-more treshold ({TwitchChat.LOAD_MORE_TRESHOLD})'
			)
		self.log.info('Finished loading')
