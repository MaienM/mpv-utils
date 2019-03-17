from collections import defaultdict
import json
import socket
import sys
import threading

import _logging as logging


class EventWithMessage(threading.Event):
	""" A subclass of threading.Event that can pass more data along than just set/not set. """
	def __init__(self, *args, **kwargs):
		super(EventWithMessage, self).__init__(*args, **kwargs)
		self.data = None

	def set(self, data):
		if self.is_set():
			raise Exception('Cannot set twice')
		self.data = data
		super(EventWithMessage, self).set()

	def clear(self):
		super(EventWithMessage, self).clear()
		self.data = None

	def wait(self, *args, **kwargs):
		super(EventWithMessage, self).wait(*args, **kwargs)
		return self.data


class MPVError(Exception):
	""" An error that was received in response to an MPV IPC call. """


class MPV(threading.Thread):
	""" Integration with MPV over the IPC socket. """

	def __init__(self, socket_path, reconnect = True):
		super(MPV, self).__init__()

		self.log = logging.getLogger(__name__, MPV)

		self.socket_path = socket_path
		self.reconnect = reconnect
		self.stop_requested = threading.Event()

		# Data to be sent to the client.
		self.send_buffer = b''
		self.send_lock = threading.Lock()

		# Used to store listeners and responses.
		self.request_id = 1
		self.listeners = {}
		self.listener_lock = threading.Lock()

		# Used to store event listeners.
		self.handlers = defaultdict(lambda: [])
		self.handler_lock = threading.Lock()

		# Used to store observe listeners.
		self.observer_id = 1
		self.observers = defaultdict(lambda: [])
		self.observer_ids = {}
		self.observer_lock = threading.Lock()

		# Handle property-change events, for the observers.
		self.handlers['property-change'].append(self._observe_handler)

	def stop(self):
		self.stop_requested.set()

	def run(self):
		try:
			self._run()
		except Exception as e:
			self.log.exception(e)

	def _run(self):
		self._connect_and_process()
		if self.reconnect:
			while not self.stop_requested.is_set():
				self._connect_and_process()

	def _connect_and_process(self):
		with socket.socket(socket.AF_UNIX) as client:
			client.settimeout(1)
			client.connect(self.socket_path)

			buffer = ''
			while not self.stop_requested.is_set():
				if self.send_buffer:
					with self.send_lock:
						client.sendall(self.send_buffer)
						self.send_buffer = b''
				try:
					received_bytes = client.recv(1024)
				except socket.timeout:
					continue
				buffer += received_bytes.decode('utf-8')
				while '\n' in buffer:
					message, buffer = buffer.split('\n', 1)
					message = json.loads(message)
					if 'request_id' in message:
						request_id = message['request_id']
						with self.listener_lock:
							listener = self.listeners.get(request_id)
							if listener:
								self.log.debug(f'Received response for request {request_id}: {message}')
								listener.set(message)
							else:
								self.log.warn(f'Received response for request {request_id}, but there is no listener: {message}')
					elif 'event' in message:
						event = message['event']
						self.log.debug(f'Received event {event}: {message}')
						with self.handler_lock:
							for handler in self.handlers[event]:
								handler(message)
					else:
						self.log.warn(f'Received unknown message: {message}')

	def _send(self, data):
		self.log.debug(f'Adding message to send buffer: {data}')
		with self.send_lock:
			self.send_buffer += (data + '\n').encode('utf-8')

	def command(self, command, *args):
		""" Send a command to MPV, and wait for a response. """
		event = EventWithMessage()
		with self.listener_lock:
			request_id = self.request_id
			self.request_id += 1
			self.listeners[request_id] = event

		try:
			command_data = {
				'command': [command, *args],
				'request_id': request_id,
			}
			self._send(json.dumps(command_data))

			response = event.wait(5)
			if response['error'] != 'success':
				raise MPVError(response['error'])
			return response.get('data')
		finally:
			with self.listener_lock:
				del self.listeners[request_id]

	def on(self, event, handler):
		""" Listen to an MPV event. """
		self.log.info(f'Adding handler {handler} to event {event}')
		with self.handler_lock:
			self.handlers[event].append(handler)
		return lambda: self.off(event, handler)
	
	def off(self, event, handler):
		""" Stop listening to an MPV event. """
		self.log.info(f'Removing handler {handler} from event {event}')
		with self.handler_lock:
			self.handlers[event].remove(handler)

	def observe(self, prop, handler, request_initial = False):
		""" Listen to changes to an MPV property. """
		self.log.info(f'Adding observer {handler} to property {prop}')
		with self.observer_lock:
			self.observers[prop].append(handler)
			if prop not in self.observer_ids:
				# First observer of this property, so start listening
				observer_id = self.observer_id
				self.observer_id += 1
				self.observer_ids[prop] = observer_id
				self.command('observe_property', observer_id, prop)
		if request_initial:
			handler(self.command('get_property', prop))
		return lambda: self.unobserve(prop, handler)

	def unobserve(self, prop, handler):
		""" Stop listening to changes to an MPV property. """
		self.log.info(f'Removing observer {handler} from property {prop}')
		with self.observer_lock:
			self.observers[prop].remove(handler)
			if not self.observers[prop]:
				# Last observer of this property, so stop listening
				observer_id = self.observer_ids[prop]
				del self.observer_ids[prop]
				self.command('unobserve-property', observer_id)

	def _observe_handler(self, message):
		""" Handles all property-change events, and triggers observers from it. """
		with self.observer_lock:
			data = message['data']
			for handler in self.observers[message['name']]:
				handler(data)
