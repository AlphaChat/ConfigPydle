# ConfigPydle - Specialised subclass of the Pydle IRC Client Framework
#
# Copyright (C) 2020-2025 Aaron M. D. Jones <aaron@alphachat.net>
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

import asyncio
import textwrap
import yaml

from datetime import datetime, timezone
from pydle import Client as PydleClient



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
}

_required_config_keys = [
	'hostname',
	'nickname',
	'realname',
	'username',
]

_integer_minmax = {
	'connect_timeout':  [ 1, 30 ],
	'port':             [ 1, 65535 ],
}



class ConfigPydleClient(PydleClient):

	def __init__(self, path, default_config_keys={}, required_config_keys=[]):

		self.autoperform_done = False
		self.acchannels = set()
		self.acconfig = {}
		self.ev_tasks = set()
		self.text_wrapper = textwrap.TextWrapper(width=64, expand_tabs=False, tabsize=1,
		                                         replace_whitespace=True, drop_whitespace=True)

		with open(path) as file:
			self.acconfig = yaml.safe_load(file.read())

		for key in self.acconfig:
			if key == 'none':
				self.acconfig[key] = None

		for key in default_config_keys:
			if key not in self.acconfig:
				self.acconfig[key] = default_config_keys[key]

		for key in _default_config_keys:
			if key not in self.acconfig:
				self.acconfig[key] = _default_config_keys[key]

		for key in required_config_keys:
			if key not in self.acconfig:
				raise KeyError(f'Required key {key} in config file is missing')

		for key in _required_config_keys:
			if key not in self.acconfig:
				raise KeyError(f'Required key {key} in config file is missing')

		for key in _integer_minmax:
			try:
				vmin = _integer_minmax[key][0]
				vmax = _integer_minmax[key][1]
				var = int(self.acconfig[key])
				self.acconfig[key] = var
				if var < vmin or var > vmax:
					raise ValueError('Integer variable out of range')
			except:
					raise ValueError(f'The {var} variable must be an integer with a ' \
					                 f'value between {vmin} and {vmax} (inclusive)')

		# This is because super().__init__() doesn't silently ignore keys it doesn't use...
		_kwargs = {}
		for key in _ctor_whitelist:
			if key in self.acconfig:
				_kwargs[key] = self.acconfig[key]

		super().__init__(**_kwargs)



	async def add_ev_task(self, coro):

		task = asyncio.create_task(coro)
		task.add_done_callback(self.ev_tasks.discard)
		self.ev_tasks.add(task)



	async def connect(self, reconnect=False):

		# This is because super().connect() doesn't silently ignore keys it doesn't use...
		_kwargs = {}
		for key in _connect_whitelist:
			if key in self.acconfig:
				_kwargs[key] = self.acconfig[key]

		await super().connect(reconnect=reconnect, **_kwargs)

		_rem = self.acconfig['connect_timeout']
		while _rem and not self.connected:
			await asyncio.sleep(1)
			_rem -= 1



	async def on_raw_001(self, message):

		await super().on_raw_001(message)

		if self.nickname != self.acconfig['nickname']:
			nickname = self.acconfig['nickname']
			await self.raw(f'PRIVMSG NickServ :RELEASE {nickname}\r\n')
			await self.raw(f'PRIVMSG NickServ :REGAIN {nickname}\r\n')
			_rem = 10
			while _rem and self.nickname != nickname:
				await asyncio.sleep(1)
				_rem -= 1

		if 'oper_username' in self.acconfig and 'oper_password' in self.acconfig:
			oper_username = self.acconfig['oper_username']
			oper_password = self.acconfig['oper_password']
			await self.raw(f'OPER {oper_username} {oper_password}\r\n')

		if 'connect_modes' in self.acconfig:
			connect_modes = self.acconfig['connect_modes']
			await self.raw(f'MODE {self.nickname} {connect_modes}\r\n')

		if 'away_message' in self.acconfig:
			away_message = self.acconfig['away_message']
			await self.away(away_message)

		await self.add_ev_task(self.check_membership())

		self.autoperform_done = True



	async def on_disconnect(self, expected):

		await super().on_disconnect(expected)

		self.autoperform_done = False

		for task in self.ev_tasks:

			try:
				task.cancel()
				await task
			except:
				pass

			try:
				self.ev_tasks.discard(task)
			except:
				pass



	async def check_membership(self):

		while await asyncio.sleep(1, result=True):

			if not (self.connected and self.autoperform_done):
				continue

			for channel in self.acchannels:
				if not self.in_channel(channel):
					try:
						await self.join(channel)
					except:
						pass
					await asyncio.sleep(1)



	async def message_or_notice(self, target, message, wrap, is_notice):

		if is_notice:
			func = super().notice
		else:
			func = super().message

		while not (self.connected and self.autoperform_done):
			await asyncio.sleep(1)

		if self.is_channel(target):
			while not self.in_channel(target):
				try:
					await self.join(target)
				except:
					pass
				await asyncio.sleep(1)

		if message and wrap:
			for line in self.text_wrapper.wrap(message):
				await func(target, line)
			await func(target, ' ')
		elif message:
			await func(target, message)
		else:
			await func(target, ' ')



	async def message(self, target, message):
		await self.message_or_notice(target, message, False, False)

	async def notice(self, target, message):
		await self.message_or_notice(target, message, False, True)

	async def wmessage(self, target, message):
		await self.message_or_notice(target, message, True, False)

	async def wnotice(self, target, message):
		await self.message_or_notice(target, message, True, True)

	async def on_ctcp_ping(self, source, target, contents):
		await self.ctcp_reply(source, 'PING', contents)

	async def on_ctcp_time(self, source, target, contents):
		await self.ctcp_reply(source, 'TIME', datetime.now(tz=timezone.utc).isoformat(timespec='seconds'))

	async def on_raw_276(self, message):
		pass

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
