from collections import OrderedDict
import os
import os.path
import sys

from configupdater import ConfigUpdater
from configupdater.configupdater import Section, Option

import _logging as logging


DEFAULT_CONFIG_PATH = os.path.realpath(os.path.join(os.path.dirname(__file__), 'config.ini'))

if sys.platform in 'win32':
	CONFIG_PATH = os.environ.get('APPDATA', os.path.expanduser('~'))
else:
	CONFIG_PATH = os.environ.get('XDG_CONFIG_HOME', os.path.join(os.path.expanduser('~'), '.config'))
CONFIG_PATH = os.path.join(CONFIG_PATH, 'mpv-utils.ini')


class Configurable(object):
	""" Abstract class for classes that need items from the config. """

	@classmethod
	def configure(cls, config):
		"""
		Apply the loaded config to the class.

		Will be invoked on all subclasses of Configurable when Config.apply() is called.
		"""
		raise NotImplementedError()


class Config(ConfigUpdater):
	""" Handles everything configuration related. """

	def __init__(self):
		super(Config, self).__init__()

		self.log = logging.getLogger(Config)

		# Load the default config.
		self.log.debug(f'Loading default config from {DEFAULT_CONFIG_PATH}')
		default_config = ConfigUpdater()
		default_config.read(DEFAULT_CONFIG_PATH)

		# If the config does not exist, write the default config and exit.
		if not os.path.exists(CONFIG_PATH):
			self.log.error('No user config found. Writing default config to {CONFIG_PATH} and exiting.')
			os.makedirs(os.path.realpath(os.path.dirname(CONFIG_PATH)), exist_ok = True)
			with open(CONFIG_PATH, 'w') as f:
				default_config.write(f)
			sys.exit(1)

		# Read the user config into a separate instance.
		self.log.debug(f'Loading user config from {CONFIG_PATH}')
		user_config = ConfigUpdater()
		user_config.read(CONFIG_PATH)

		# Fill this instance with values from the two configs. The order and values from the user config are used, and
		# when they are not present we fallback to the default config. For new sections/options, try to put them after the
		# section/option they appear after in the default config.
		self.log.debug('Merging configs')
		default_sections = dict(default_config.items())
		user_sections = dict(user_config.items())
		for section in Config._get_order(default_config.sections(), user_config.sections()):
			# Get the sections. If the section is only present in one of the configs, just copy it and move on.
			default_section = default_sections.get(section)
			user_section = user_sections.get(section)
			if default_section is None or user_section is None:
				self.add_section(user_section or default_section)
				continue

			# Create a new seciton, and add it.
			sobject = Section(section, self)
			self.add_section(sobject)

			# Determine the order of options, based only on names, and add the items to the section in this order.
			default_groups = Config._get_section_item_groups(default_section)
			user_groups = Config._get_section_item_groups(user_section)
			for key in Config._get_order(default_groups.keys(), user_groups.keys()):
				group = user_groups.get(key, default_groups.get(key))
				for item in group['items']:
					sobject.add_option(item)

		if self.get_bool('core', 'update_config'):
			self.log.debug(f'Writing merged config to {CONFIG_PATH}')
			with open(CONFIG_PATH, 'w') as f:
				self.write(f)

	@staticmethod
	def _get_section_item_groups(section):
		"""
		Get the items in a section, grouped to the option they (probably) belong to.

		All non-option items are added to the option directly following them. The one exception to this is items that are
		after the last option, which are added to a special option with None as key.
		"""
		groups = OrderedDict()
		leading = []
		for item in section.keys():
			if isinstance(item, Option):
				groups[item.key] = {
					'option': item,
					'items': leading + [item],
				}
				leading = []
			else:
				leading.append(item)
		if leading:
			groups[None] = {
				'option': None,
				'items': leading,
			}
		return groups

	@staticmethod
	def _get_order(default_order, user_order):
		"""
		Determines the order that items should be in, based on both the user and default order.

		Items that are in the user order stay in that order. Items that are in the default order but not in the user order
		are inserted relative to what is before them by default. So if new section 'a' normally appears at the beginning, it
		will be inserted at the beginning, and if new section 'c' normally appears after section 'b', it will be
		positioned after 'b'.

		>>> Config._get_order(['a', 'b', 'c'], ['b', 'a', 'c'])
		['b', 'a', 'c']
		>>> Config._get_order(['a', 'b', 'c'], ['c', 'b'])
		['a', 'c', 'b']
		>>> Config._get_order(['a', 'b', 'c'], ['b'])
		['a', 'b', 'c']
		>>> Config._get_order(['a', 'b', 'c', 'd', 'e'], ['d', 'c'])
		['a', 'b', 'd', 'e', 'c']
		"""
		order = list(user_order)
		default_order = list(default_order)
		for i, item in enumerate(default_order):
			if item not in order:
				if i == 0:
					index = 0
				else:
					index = order.index(default_order[i - 1]) + 1
				order.insert(index, item)
		return order

	def apply(self):
		""" Applies the config to all Configurable classes. """
		for subclass in Configurable.__subclasses__():
			self.log.info(f'Configuring {subclass.__module__}.{subclass.__name__}')
			subclass.configure(self)

	def get_str(self, section, key):
		try:
			value = self.get(section, key).value
			self.log.info(f'Getting property {section}.{key}: {value}')
			return value
		except KeyError:
			self.log.error(f'Attempted to get property {section}.{key}, which does not exist')
			raise

	def get_int(self, section, key):
		value = self.get_str(section, key)
		try:
			return int(value)
		except ValueError:
			raise ValueError(f"Invalid value for integer property {section}.{key}: '{value}'.")

	def get_float(self, section, key):
		value = self.get_str(section, key)
		try:
			return float(value)
		except ValueError:
			raise ValueError(f"Invalid value for numeric property {section}.{key}: '{value}'.")

	def get_bool(self, section, key):
		value = self.get_str(section, key)
		if value.lower() in ['yes', 'true', '1']:
			return True
		elif value.lower() in ['no', 'false', '0']:
			return False
		else:
			raise ValueError(
				f"Invalid value for boolean property {section}.{key}: '{value}'. "
				'Valid options are: yes, no, true, false, 0, 1.'
			)

	def get_enum(self, section, key, options):
		value = self.get_str(section, key)
		if value.lower() not in options:
			raise ValueError(
				f"Invalid value for property {section}.{key}: '{value}'. "
				f'Valid options are: {", ".join(options)}'
			)

