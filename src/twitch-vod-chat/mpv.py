import json
import socket
import sys
import threading


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

	def wait(self, *args, **kwargs):
		super(EventWithMessage, self).wait(*args, **kwargs)
		return self.data


class MPVError(Exception):
	""" An error that was received in response to an MPV IPC call. """


class MPV(threading.Thread):
	""" Integration with MPV over the IPC socket. """

	def __init__(self, socket_path, reconnect = True):
		super(MPV, self).__init__()

		self.socket_path = socket_path
		self.reconnect = reconnect
		self.stop_requested = threading.Event()

		# Data to be sent to the client. Lock must be used when using this variable.
		self.send_buffer = b''
		self.send_lock = threading.Lock()

		# Used to store listeners and responses. Lock must be used when using either of these variables.
		self.request_id = 1
		self.listeners = {}
		self.listener_lock = threading.Lock()

	def stop(self):
		self.stop_requested.set()

	def run(self):
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
					if 'request_id' not in message:
						print('Received a message without a request id, ignoring it', message, file = sys.stderr)
						continue
					request_id = message['request_id']
					with self.listener_lock:
						listener = self.listeners[request_id]
						if listener:
							listener.set(message)
						else:
							print('Received a message, but nothing listened', message, file = sys.stderr)

	def send(self, data):
		with self.send_lock:
			self.send_buffer += (data + '\n').encode('utf-8')

	def command(self, command, *args):
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
			self.send(json.dumps(command_data))

			response = event.wait(5)
			if response['error'] != 'success':
				raise MPVError(response['data'])
			return response['data']
		finally:
			with self.listener_lock:
				del self.listeners[request_id]
