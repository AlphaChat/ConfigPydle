# ConfigPydle - Specialised subclass of the Pydle IRC Client Framework
#
# Copyright (C) 2020 Aaron M. D. Jones <aaron@alphachat.net>
#
# This class' constructor parses a configuration file to determine the
# parameters to use for Pydle's constructor and connect functions, and
# provides some extra useful functionality for AlphaChat's various IRC
# bots.
#
# For more information, please see the following:
#     <https://pydle.readthedocs.io/en/latest/>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

from datetime import datetime, timezone

import asyncio
import configparser
import pydle



_boolean_false_values = [
	'false',
	'no',
]

_boolean_true_values = [
	'true',
	'yes',
]

_connect_whitelist = [
	'hostname',
	'password',
	'port',
	'tls',
]

_ctor_whitelist = [
	'nickname',
	'realname',
	'sasl_identity',
	'sasl_mechanism',
	'sasl_password',
	'sasl_username',
	'tls_client_cert',
	'tls_client_cert_key',
	'tls_client_cert_password',
	'username',
]

_default_config_keys = {
	'connect_timeout':  '10',
	'port':             '6697',
	'sasl_mechanism':   'EXTERNAL',
	'tls':              'True',
	'tls_verify':       'True',
}

_required_config_keys = [
	'hostname',
	'nickname',
	'realname',
	'username',
]

_var_int_max = {
	'connect_timeout':  30,
	'port':             65535,
}



class Client(pydle.Client):

	def __init__(self, path=None, eventloop=None, default_config_keys={}, required_config_keys=[]):

		self.autoperform_done = False
		self.phcfg = {}

		if path is None:
			raise ValueError('The path to the configuration file must be given')

		for key in _default_config_keys:
			if key not in default_config_keys:
				default_config_keys[key] = _default_config_keys[key]

		for key in _required_config_keys:
			if key not in required_config_keys:
				required_config_keys.append(key)

		with open(path) as f:
			_parser = configparser.ConfigParser(defaults=default_config_keys, default_section='config',
			                                    interpolation=configparser.ExtendedInterpolation())
			_parser.read_file(f)
			for key in _parser['config']:
				self.phcfg[key] = _parser['config'][key]

				# Integers
				try:
					if not isinstance(self.phcfg[key], bool):
						val = int(self.phcfg[key])
						self.phcfg[key] = val
				except (TypeError, ValueError):
					pass

				# Booleans
				if str(self.phcfg[key]).lower() in _boolean_false_values:
					self.phcfg[key] = False
				if str(self.phcfg[key]).lower() in _boolean_true_values:
					self.phcfg[key] = True

				# None
				if str(self.phcfg[key]).lower() == 'none':
					self.phcfg[key] = None

		for key in required_config_keys:
			if key not in self.phcfg:
				raise KeyError(f'Required key {key} in config file is missing')

		for var in _var_int_max.keys():
			if not isinstance(self.phcfg[var], int):
				raise ValueError(f'The {var} variable must be an integer')
			if self.phcfg[var] < 1:
				raise ValueError(f'The {var} variable must be greater than or equal to 1')
			if self.phcfg[var] > _var_int_max[var]:
				raise ValueError(f'The {var} variable must be less than or equal to ' \
				                 f'{_var_int_max[var]}')

		# This is because super().__init__() doesn't silently ignore keys it doesn't use...
		_kwargs = {}
		for key in _ctor_whitelist:
			if key in self.phcfg:
				_kwargs[key] = self.phcfg[key]

		super().__init__(eventloop=eventloop, **_kwargs)



	def run(self):

		try:
			self.eventloop.run_until_complete(self.connect())
			self.eventloop.run_forever()
		finally:
			self.eventloop.stop()



	async def connect(self, reconnect=False):

		# This is because super().connect() doesn't silently ignore keys it doesn't use...
		_kwargs = {}
		for key in _connect_whitelist:
			if key in self.phcfg:
				_kwargs[key] = self.phcfg[key]

		_rem = 20 * self.phcfg['connect_timeout']
		await super().connect(reconnect=reconnect, **_kwargs)
		while _rem and not self.connected:
			await asyncio.sleep(0.05)
			_rem -= 1



	async def on_connect(self):

		await super().on_connect()

		if self.nickname != self.phcfg['nickname']:
			_rem = 100
			await self.message('NickServ', f'RELEASE {self.phcfg["nickname"]}')
			await self.message('NickServ', f'REGAIN {self.phcfg["nickname"]}')
			while _rem and self.nickname != self.phcfg['nickname']:
				await asyncio.sleep(0.05)
				_rem -= 1

		if 'oper_username' in self.phcfg and 'oper_password' in self.phcfg:
			await self.raw(f'OPER {self.phcfg["oper_username"]} {self.phcfg["oper_password"]}\r\n')

		if 'connect_modes' in self.phcfg:
			await self.raw(f'MODE {self.nickname} {self.phcfg["connect_modes"]}\r\n')

		if 'away_message' in self.phcfg:
			await self.away(self.phcfg['away_message'])

		self.autoperform_done = True



	async def on_disconnect(self, expected):

		await super().on_disconnect(expected)

		self.autoperform_done = False



	async def message(self, target, message):

		if not self.connected:
			return

		if self.is_channel(target) and not self.in_channel(target):
			try:
				await self.join(target)
			except:
				pass

		await super().message(target, message)



	async def notice(self, target, message):

		if not self.connected:
			return

		if self.is_channel(target) and not self.in_channel(target):
			try:
				await self.join(target)
			except:
				pass

		await super().notice(target, message)



	async def on_ctcp_ping(self, source, target, contents):
		await self.ctcp_reply(source, 'PING', contents)

	async def on_ctcp_time(self, source, target, contents):
		await self.ctcp_reply(source, 'TIME', datetime.now(tz=timezone.utc).isoformat(timespec='seconds'))

	async def on_raw_306(self, message):
		pass

	async def on_raw_381(self, message):
		pass

	async def on_raw_458(self, message):
		pass

	async def on_raw_470(self, message):
		pass

	async def on_raw_473(self, message):
		pass
