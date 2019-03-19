#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import setuptools


setuptools.setup(
	name = 'mpv-utils',
	version = '0.1.0',
	license = 'MIT',
	description = "Utility functions for MPV",
	author = 'Michon van Dooren',
	author_email = 'michon1992@gmail.com',
	url = 'https://gitlab.com/maienm/mpv-utils',
	classifiers = [
		'Development Status :: 3 - Alpha'
		'Intended Audience :: Developers',
		'License :: OSI Approved :: MIT License',
		'Operating System :: Unix',
		'Operating System :: POSIX',
		'Programming Language :: Python',
		'Programming Language :: Python :: 3',
		'Programming Language :: Python :: 3.6',
		'Programming Language :: Python :: 3.7',
		'Programming Language :: Python :: Implementation :: CPython',
		'Programming Language :: Python :: Implementation :: PyPy',
		'Topic :: Utilities',
	],
	keywords = [
		'mpv',
	],

	packages = setuptools.find_packages('src'),
	package_dir = { '': 'src' },
	include_package_data = True,
	zip_safe = False,
	install_requires = [
		'colr',
		'configupdater',
		'nerdfonts',
		'requests',
	],
)
