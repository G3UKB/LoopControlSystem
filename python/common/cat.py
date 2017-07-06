#!/usr/bin/env python
#
# cat.py
#
# CAT control for the Mag Loop application
# 
# Copyright (C) 2015 by G3UKB Bob Cowdery
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#    
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#    
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#    
#  The author can be reached by email at:   
#     bob@bobcowdery.plus.com
#

# System imports 
import os,sys
import socket
import serial
import glob
import threading
from time import sleep
import traceback
from collections import deque

sys.path.append('..')
sys.path.append(os.path.join('..', '..'))
# Application imports
from common.defs import *

"""

Control this application from an external CAT cabable tranceiver.
The external control is over UDP or Serial and uses only a few commands.

There are many varients of CAT command sets. There is no attempt here to
cover anything other than the tranceivers I have at my disposal. However,
the command sets are data driven so more can be added.

This class is a service to be called as and when required to set or get
tranceiver data.

To define a new protocol:
	1. Add a new variant
	2. Add a new command set into CAT_COMMAND_SETS
	3. Implement a new class for the variant modelled on FT817 class.
"""

"""

CAT class for all CAT variants.

"""
class CAT:
	
	def __init__(self, variant, cat_settings):
		"""
		Constructor
		
		Arguments
			variant		--	CAT command set and format
			settings	--  see common.py DEFAULT_SETTINGS for structure
		"""
	
		self.__variant 	= variant

		# Get our command set
		if variant not in CAT_COMMAND_SETS:
			raise LookupError
		else:
			self.__command_set = CAT_COMMAND_SETS[variant]
			
		# Sort out what parameters we have.
		self.__ip = None
		self.__port = None
		self.__com = None
		self.__baud = None
		if cat_settings[NETWORK][IP] != None:
			self.__ip = cat_settings[NETWORK][IP]
			self.__port = int(cat_settings[NETWORK][PORT])
		if cat_settings[SERIAL][COM_PORT] != None:		
			self.__com = cat_settings[SERIAL][COM_PORT]
			self.__baud = int(cat_settings[SERIAL][BAUD_RATE])
		# and the selected transport
		self.__transport = cat_settings[SELECT]
		
		# Instance vars
		self.__port_open = False
		self.__ports = []
		self.__device = None
		self.__device = None
		self.__cat_thrd = None
		self.__callback = None
		
		# List the serial ports as we can't do this after we open.
		self.__ports = self.__list_serial_ports()
		
		# Setup transport dependent
		if self.__transport == CAT_UDP and self.__ip != None:
			# UDP transport			
			# Create the UDP socket
			self.__device = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			self.__device.settimeout(3)
		elif self.__transport == CAT_SERIAL and self.__com != None:
			# Serial transport
			# Open the serial port
			try:
				self.__device = serial.Serial(port=self.__com, baudrate=self.__baud, parity=self.__command_set[SERIAL][PARITY], stopbits=self.__command_set[SERIAL][STOP_BITS], timeout=self.__command_set[SERIAL][TIMEOUT])
				self.__port_open = True
			except (OSError, serial.SerialException):
				# Failed to open the port, radio device probably off
				print('Failed to open CAT port %s' % (self.__com))
		
		if (self.__transport == CAT_SERIAL and self.__port_open) or self.__transport == CAT_UDP:	
			# Create the CAT thread
			self.__cat_thrd = CATThrd(variant, self.__command_set, self.__ip, self.__port, self.__transport, self.__device)
			
	def start_thrd(self):
		""" Run the thread """
		
		if (self.__transport == CAT_SERIAL and self.__port_open) or self.__transport == CAT_UDP:
			self.__cat_thrd.start()
			return True
		else:
			# Try to open the serial port again
			try:
				# List the serial ports again as we can't do this after we open.
				self.__ports = self.__list_serial_ports()
				self.__device = serial.Serial(port=self.__com, baudrate=self.__baud, parity=self.__command_set[SERIAL][PARITY], stopbits=self.__command_set[SERIAL][STOP_BITS], timeout=self.__command_set[SERIAL][TIMEOUT])
				self.__port_open = True
			except (OSError, serial.SerialException):
				# Failed to open the port, radio device probably still off
				return False
			if self.__port_open:	
				# Create and start the CAT thread
				self.__cat_thrd = CATThrd(self.__variant, self.__command_set, self.__ip, self.__port, self.__transport, self.__device)
				self.__cat_thrd.start()
				if self.__callback != None: self.__cat_thrd.set_callback(self.__callback)
			return True
		
	def set_callback(self, callback):
		"""
		Callback here with responses
		
		Arguments:
			callback	--	the callable
			
		"""
		
		self.__callback = callback
		if self.__cat_thrd != None:
			self.__cat_thrd.set_callback(callback)
		
	def terminate(self):
		""" Ask the thread to terminate and wait for it to exit """
		
		if self.__cat_thrd != None:
			self.__cat_thrd.terminate()
			# Wait for the thread to exit
			self.__cat_thrd.join()
			
		if self.__device != None:
			self.__device.close()

	def do_command(self, cat_cmd, params = None):
		"""
		Execute a new CAT command
		
		Arguments:
			cat_cmd	-- 	from the CAT command enumerations
			params	--	required parameters for the command
			
		"""
		
		if (self.__transport == CAT_SERIAL and self.__port_open) or self.__transport == CAT_UDP:
			self.__cat_thrd.do_command(cat_cmd, params)
	
	def get_serial_ports(self):
		""" Return available serial port names """
		
		return self.__ports
		
	def __list_serial_ports(self):
		""" Lists available serial port names """
		
		self.__ports = []
		all_ports = []
		if sys.platform.startswith('win'):
			all_ports = ['COM%s' % (i + 1) for i in range(20)]
		elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
			# this excludes your current terminal "/dev/tty"
			all_ports = glob.glob('/dev/tty[A-Za-z]*')
		elif sys.platform.startswith('darwin'):
			all_ports = glob.glob('/dev/tty.*')
	
		for port in all_ports:
			try:
				s = serial.Serial(port)
				s.close()
				self.__ports.append(port)
			except (OSError, serial.SerialException):
				pass
			except Exception:
				pass
		return self.__ports
	
"""

CAT execution thread for all CAT variants.

"""
class CATThrd (threading.Thread):
	
	def __init__(self, variant, command_set, ip, port, transport, device):
		"""
		Constructor
		
		Arguments
			variant		--	CAT command set variant
			command_set	--	command set to use
			ip			--	UDP enpoint
			port		--	UDP endpoint
			transport	--	CAT_UDP | CAT_SERIAL
			device   	--  an open device for the transport
		"""

		super(CATThrd, self).__init__()
		
		self.__variant = variant
		self.__command_set = command_set
		self.__ip = ip
		self.__port = port
		self.__transport = transport
		self.__device = device
		self.__callback = None
		
		# Class vars
		self.__cat_cls_inst = self.__command_set[CLASS](command_set)
		self.__q = deque(maxlen=2)
		# Terminate flag
		self.__terminate = False
	
	def set_callback(self, callback):
		"""
		Callback here with responses
		
		Arguments:
			callback	-- 	the callable
			
		"""
		
		self.__callback = callback
		
	def terminate(self):
		""" Asked to terminate the thread """
		
		self.__terminate = True
		self.join()
	
	def do_command(self, cat_cmd, params):
		"""
		Execute a new CAT command
		
		Arguments:
			cat_cmd	-- 	from the CAT command enumerations
			params	--	required parameters for the command
			
		"""
		
		# We add the command to a thread-safe Q for execution by the thread
		# Note we are only interested in the last frequency and the one potentially being executed.
		# The max_len is therefore set to 2 which discards elements from the opposite end of the q
		# when the queue is full.
		self.__q.append((cat_cmd, params))
				
	def run(self):
		
		""" Thread entry point """
		
		#
		# Handles all CAT interactions with an external tranceiver
		#
		#	Tracking - keep antenna resonance in line with received frequency
		#	Calibration - automatic setpoint calibration - TBD
		#
			
		while not self.__terminate:
			try:
				# Requests are queued
				while len(self.__q) > 0:
					# Get the command,
					cmd, param = self.__q.popleft()
					# format,
					(r, cmd_buf) = self.__cat_cls_inst.format_cat_cmd(cmd, param)
					if r:
						# and send using the appropriate transport
						if self.__transport == CAT_UDP:
							# We assume a response on UDP
							self.__device.sendto(cmd_buf, (self.__ip, self.__port))
							data, addr = self.__device.recvfrom(128)
							# Return data to the caller
							# Note, this is an async return
							response = self.__cat_cls_inst.decode_cat_resp(cmd, data)
							if self.__callback != None: self.__callback(response)
						elif self.__transport == CAT_SERIAL:
							# We do not assume a response on Serial
							self.__device.write(cmd_buf)
							if self.__cat_cls_inst.is_response(cmd):
								if self.__command_set[CLASS] == ICOM:
									data = bytearray(30)
									n = 0
									# Discard the reflected command
									while True:
										ch = self.__device.read()
										data[n:n+1] = ch
										# There will be a terminator at the end of the OK or NG frame
										# skip that and then if there is no data we will timeout and
										# an error response returned from decode.
										if ch == b'\xfd':
											break
										n += 1
									# Get the response message
									n = 0
									while True:
										ch = self.__device.read()
										data[n:n+1] = ch
										# There will be a terminator at the end of the OK or NG frame
										# skip that and then if there is no data we will timeout and
										# an error response returned from decode.
										if ch == b'\xfd':
											break
										n += 1
								else:
									data = self.__device.read(self.__command_set[SERIAL][READ_SZ])
								# Return data to the caller
								# Note, this is an async return
								response = self.__cat_cls_inst.decode_cat_resp(CAT_COMMAND_SETS[self.__variant], cmd, data)
								if self.__callback != None: self.__callback(response)
							else:
								# There may be an ack/nak response or a reflected command
								data = bytearray(30)
								n = 0
								while True:
									ch = self.__device.read()
									data[n:n+1] = ch
									# There will be a terminator at the end of the OK or NG frame
									# skip that and then if there is no data we will timeout and
									# an error response returned from decode.
									if ch == b'\xfd':
										break
									n += 1
								response = self.__cat_cls_inst.ack_nak(CAT_COMMAND_SETS[self.__variant], data)
								if self.__callback != None: self.__callback(response)
				sleep(0.1)
			except Exception as e:
				# Oops
				if self.__callback != None: self.__callback((False, 'ERROR [%s]' % (str(e))))

"""

Implements the FT817 CAT protocol

"""
class YAESU:
	
	"""
	The serial format is 1 start bit, 8 data, parity and stop bits
	are defined in the command set. COM port and baud rate are defined
	in the configuration. If UDP the same command format applies.
	
	Commands are 5 bytes, 4 parameter bytes followed by a command byte.
	Note this class only formats commands, it does not execute them.
	
	"""
	
	def __init__(self, command_set):
		"""
		Constructor
		
		Arguments:
			command_set	--	command set for the FT-817ND
			
		"""
		
		self.__command_set = command_set
		
		# Create the dispatch table
		commands = command_set[COMMANDS]
		self.__dispatch = {
			REFERENCE: CAT_COMMAND_SETS[FT_817ND],
			MAP: {
				CAT_LOCK: [self.__lock, False],
				CAT_PTT: [self.__ptt, False],
				CAT_FREQ_SET: [self.__freq_set, False],
				CAT_MODE_SET: [self.__mode_set, False],
				CAT_FREQ_GET: [self.__freq_mode_get, True],
				CAT_MODE_GET: [self.__freq_mode_get, True],
			}
		}
		
	def format_cat_cmd(self, cat_cmd, param):
		"""
		Format and return the command bytes
		
		Arguments:
			cat_cmd	-- command type
			param	--	command parameters
			
		"""
		
		if not cat_cmd in self.__dispatch[MAP]:
			return False, None
		
		# Format command
		return self.__dispatch[MAP][cat_cmd][0](self.__dispatch[REFERENCE], param)
	
	def decode_cat_resp(self, lookup, cat_cmd, data):
		"""
		Decode and return a tuple according to command type
		
		Arguments:
			cat_cmd	-- command type
			data	--	the response bytes
			
		"""
		 
		if cat_cmd == CAT_FREQ_GET:
			# Data 1-4 is freq MSB first
			# 01, 42, 34, 56, [ 01 ] = 14.23456 MHz
			MHz_100 = ((data[0] & 0xF0) >> 4) * 100000000
			MHz_10 = (data[0] & 0x0F) * 10000000
			MHz_1 = ((data[1] & 0xF0) >> 4) * 1000000
			KHz_100 = (data[1] & 0x0F) * 100000
			KHz_10 = ((data[2] & 0xF0) >> 4) * 10000
			KHz_1 = (data[2] & 0x0F) * 1000
			Hz_100 = ((data[3] & 0xF0) >> 4) * 100
			Hz_10 = (data[3] & 0x0F) * 10
			Hz = MHz_100 + MHz_10 + MHz_1 + KHz_100 + KHz_10 + KHz_1 + Hz_100 + Hz_10
			return True, Hz
		elif cat_cmd == CAT_MODE_GET:
			# Data 4 is mode
			mode_id = data[4]
			mode_str = ''
			for key, value in lookup[MODES].items():
				if value == mode_id:
					mode_str = key
					break
			return True, mode_str
		else:
			return False, None
	
	def ack_nak(self, lookup, data):
		"""
		Decode and return any ack/nak response
		
		Arguments:
			data	--	the response bytes
			
		"""
		
		# Nothing to do
		return True, None
		
	def is_response(self, cmd):
		"""
		True if a response is required
		
		Arguments:
			cmd	--	command to test
		"""
		
		return self.__dispatch[MAP][cmd][1]
	
	def __lock(self, lookup, state):
		"""
		Toggle Lock on/off
		
		Arguments:
			lookup	--	ref to the command lookup
			state	--	True if Lock on
			
		"""
		
		if state:
			lock = lookup[COMMANDS][CAT_LOCK][1]
		else:
			lock = lookup[COMMANDS][CAT_LOCK][2]
		return True, bytearray([0x00, 0x00, 0x00, 0x00, lock])

	def __ptt(self, lookup, state):
		"""
		Toggle PTT on/off
		
		Arguments:
			lookup	--	ref to the command lookup
			state	--	True if PTT on
			
		"""
		
		if state:
			ptt = lookup[COMMANDS][CAT_PTT][1]
		else:
			ptt = lookup[COMMANDS][CAT_PTT][2]
		return True, bytearray([0x00, 0x00, 0x00, 0x00, ptt])
	
	def __mode_set(self, lookup, mode):
		"""
		Change mode
		
		Arguments:
			lookup	--	ref to the command lookup
			mode	--	Mode to set
			
		"""
		
		return True, bytearray([lookup[MODES][mode], 0x00, 0x00, 0x00, lookup[COMMANDS][SET_MODE]])
		
	def __freq_set(self, lookup, freq):
		"""
		Change frequency
		
		Arguments:
			lookup	--	ref to the command lookup
			freq	--	Frequency in MHz
			
		"""
		
		# Frequency is a float in MHz like 14.100000
		# Make a hex prefixed string using 5 significant digits
		fs = str(int(freq*100000))
		fs = fs.zfill(8)
		b=bytearray.fromhex(fs)
		return True, bytearray([b[0], b[1], b[2], b[3], lookup[COMMANDS][SET_FREQ]])
		
	def __freq_mode_get(self, lookup, dummy):
		"""
		Get the frequency and mode
		
		Arguments:
			
		"""
		
		return True, bytearray([0x00, 0x00, 0x00, 0x00, lookup[COMMANDS][FREQ_MODE_GET]])

"""

Implements the IC7100 CAT protocol

"""
class ICOM:
	
	"""
	The serial format is 1 start bit, 8 data, parity and stop bits
	are defined in the command set. COM port and baud rate are defined
	in the configuration. If UDP the same command format applies.
	
	Commands are variable length as the data area changes by command type.
	See comments in-line for the data area for supported commands.
	
	Controller to IC7100
	--------------------
	FEFE | 88 | E0 | Cn | Sc | DataArea | FD
	
	Where:
		FEFE 	- 	preamble
		88		-	default tranceiver address
		E0		-	default controller address
		Cn		-	command number
		Sc		-	sub-command number, may be absent or multi-byte
		DataArea-	depends on command, absent or may be multi-byte
		FD		-	EOM
		
	IC7100 to Controller
	--------------------
	
	Identical except the addresses are transposed.
	
	OK Message to Controller
	------------------------
	
	FEFE | E0 | 88 | FB | FD	(see above)
	
	NG Message to Controller
	------------------------
	
	FEFE | E0 | 88 | FA | FD	(see above)
	
	
	"""
	
	def __init__(self, command_set):
		"""
		Constructor
		
		Arguments:
			command_set	--	command set for the FT-817ND
			
		"""
		
		self.__command_set = command_set
		
		# Create the dispatch table
		commands = command_set[COMMANDS]
		self.__dispatch = {
			REFERENCE: CAT_COMMAND_SETS[IC7100],
			MAP: {
				CAT_LOCK: [self.__lock, False],
				CAT_PTT: [self.__ptt, False],
				CAT_FREQ_SET: [self.__freq_set, False],
				CAT_MODE_SET: [self.__mode_set, False],
				CAT_FREQ_GET: [self.__freq_get, True],
				CAT_MODE_GET: [self.__mode_get, True]
			}
		}
		
	def format_cat_cmd(self, cat_cmd, param):
		"""
		Format and return the command bytes
		
		Arguments:
			cat_cmd	-- command type
			param	--	command parameters
			
		"""
		
		if not cat_cmd in self.__dispatch[MAP]:
			return False, None
		
		# Format command
		return self.__dispatch[MAP][cat_cmd][0](self.__dispatch[REFERENCE], param)
	
	def decode_cat_resp(self, lookup, cat_cmd, data):
		"""
		Decode and return a tuple according to command type
		
		Arguments:
			cat_cmd	-- command type
			data	--	the response bytes
			
		"""
		
		# Offsets to data
		RESPONSE_CODE = 4
		DATA_START = 5
		DATA_END = 9
		if data[RESPONSE_CODE] == lookup[RESPONSES][NAK]:
			return False, None
		if cat_cmd == CAT_FREQ_GET:
			# The data is in BCD format in 10 fields (0-9) - 5 bytes
			# Byte 	Nibble 	Digit
			# 0		0		1Hz
			# 0		1		10Hz
			# 1		0		100 Hz
			# 1		1		1KHz
			# 2		0		10KHz
			# 2		1		100KHz
			# 3		0		1MHz
			# 3		1		10MHZ
			# 4		0		100MHz
			# 4		1		1000MHz (always zero)
			
			MHz_1000 = ((data[DATA_END - 0] & 0xF0) >> 4) * 1000000000
			MHz_100 = (data[DATA_END - 0] & 0x0F) * 100000000
			MHz_10 = ((data[DATA_END - 1] & 0xF0) >> 4) * 10000000
			MHz_1 = (data[DATA_END - 1] & 0x0F) * 1000000
			KHz_100 = ((data[DATA_END - 2] & 0xF0) >> 4) * 100000
			KHz_10 = (data[DATA_END - 2] & 0x0F) * 10000
			KHz_1 = ((data[DATA_END - 3] & 0xF0) >> 4) * 1000
			Hz_100 = (data[DATA_END - 3] & 0x0F) * 100
			Hz_10 = ((data[DATA_END - 4] & 0x0F) >> 4) * 10
			Hz_1 = data[DATA_END - 4] & 0xF0
			Hz = MHz_1000 + MHz_100 + MHz_10 + MHz_1 + KHz_100 + KHz_10 + KHz_1 + Hz_100 + Hz_10 + Hz_1
			return True, Hz
		elif cat_cmd == CAT_MODE_GET:
			# Data byte 0 - mode
			# Data byte 1 - filter
			mode_id = data[DATA_START]
			mode_str = ''
			for key, value in lookup[MODES].items():
				if value == mode_id:
					mode_str = key
					break
			return True, mode_str
		else:
			return False, None

	def ack_nak(self, lookup, data):
		"""
		Decode and return any ack/nak response
		
		Arguments:
			data	--	the response bytes
			
		"""
		
		if len(data) > 0:
			if len(data) == 6:
				if data[4] == lookup[RESPONSES][ACK]:
					return True, None
				else:
					return False, None
			else:
				# Probably reflected the command
				return True, None
		else:
			return False, None
		
	def is_response(self, cmd):
		"""
		True if a response is required
		
		Arguments:
			cmd	--	command to test
		"""
		
		return self.__dispatch[MAP][cmd][1]
	
	def __lock(self, lookup, state):
		"""
		Toggle Lock on/off
		
		Arguments:
			lookup	--	ref to the command lookup
			state	--	True if Lock on
			
		"""
		
		cmd = lookup[COMMANDS][LOCK_CMD]
		sub_cmd = lookup[COMMANDS][LOCK_SUB]
		if state:
			# Set lock on
			data = lookup[COMMANDS][LOCK_ON]
		else:
			data = lookup[COMMANDS][LOCK_OFF]
			
		return self.__complete_build(cmd, sub_cmd, data)
		
	def __ptt(self, lookup, state):
		"""
		Toggle PTT on/off
		
		Arguments:
			lookup	--	ref to the command lookup
			state	--	True if PTT on
			
		"""
		
		cmd = lookup[COMMANDS][MULTIFUNC_CMD]
		sub_cmd = lookup[COMMANDS][MULTIFUNC_SUB]
		if state:
			# Set PTT on
			data = lookup[COMMANDS][PTT_ON]
		else:
			data = lookup[COMMANDS][PTT_OFF]
			
		return self.__complete_build(cmd, sub_cmd, data)
	
	def __mode_set(self, lookup, mode):
		"""
		Change mode
		
		Arguments:
			lookup	--	ref to the command lookup
			mode	--	Mode to set
			
		"""
		
		cmd = lookup[COMMANDS][SET_MODE_CMD]
		sub_cmd = lookup[COMMANDS][SET_MODE_SUB]
		data = lookup[MODES][mode]
		
		return self.__complete_build(cmd, sub_cmd, data)
		
	def __freq_set(self, lookup, freq):
		"""
		Change frequency
		
		Arguments:
			lookup	--	ref to the command lookup
			freq	--	Frequency in MHz
			
		"""
		
		cmd = lookup[COMMANDS][SET_FREQ_CMD]
		sub_cmd = lookup[COMMANDS][SET_FREQ_SUB]			
		# Frequency is a float in MHz like 14.100000
		# The data is required in BCD format in 10 fields (0-9) - 5 bytes
		# Byte 	Nibble 	Digit
		# 0		0		1Hz
		# 0		1		10Hz
		# 1		0		100 Hz
		# 1		1		1KHz
		# 2		0		10KHz
		# 2		1		100KHz
		# 3		0		1MHz
		# 3		1		10MHZ
		# 4		0		100MHz
		# 4		1		1000MHz (always zero)
		
		# Make a string of the frequency in Hz
		fs = str(int(freq*1000000))
		fs = fs.zfill(10)
		# Make an array to store the result
		data = bytearray(5)
		# Iterate through the string
		byte = 4
		nibble = 0
		for c in fs:
			if nibble == 0:
				data[byte] = ((data[byte] | int(c)) << 4) & 0xF0
				nibble = 1
			else:
				data[byte] = data[byte] | (int(c) & 0x0F)
				nibble = 0
				byte -= 1
		return self.__complete_build(cmd, sub_cmd, data)
		
	def __freq_get(self, lookup, dummy):
		"""
		Get the current frequency
		
		Arguments:
			lookup	--	ref to the command lookup
			dummy	--	
			
		"""
		
		cmd = lookup[COMMANDS][GET_FREQ_CMD]
		sub_cmd = lookup[COMMANDS][GET_FREQ_SUB]
		data = bytearray([])
		
		return self.__complete_build(cmd, sub_cmd, data)
	
	def __mode_get(self, lookup, dummy):
		"""
		Get the current mode
		
		Arguments:
			lookup	--	ref to the command lookup
			dummy	--	
			
		"""
		
		cmd = lookup[COMMANDS][GET_MODE_CMD]
		sub_cmd = lookup[COMMANDS][GET_MODE_SUB]
		data = bytearray([])
		
		return self.__complete_build(cmd, sub_cmd, data)
	
	def __complete_build(self, cmd, sub_cmd, data):
		"""
		Finish building command
		
		Arguments:
			cmd			--	command field
			sub_cmd		--	sub-command field
			data		--	data field
			
		"""
		
		# Do header
		b = bytearray([0xFE, 0xFE, 0x88, 0xE0])
		# Add the byte arrays for the data
		b += cmd[:]
		b += sub_cmd[:]
		b += data[:]
		b += bytearray([0xFD, ])
			
		return True, b
				
# ============================================================================
# Command sets
CAT_COMMAND_SETS = {
	FT_817ND: {
		CLASS: YAESU,
		SERIAL: {
			PARITY: serial.PARITY_NONE,
			STOP_BITS: serial.STOPBITS_ONE,
			TIMEOUT: 2,
			READ_SZ: 5
		},
		COMMANDS: {
			LOCK_ON: 0x00,
			LOCK_OFF: 0x80,
			PTT_ON: 0x08,
			PTT_OFF: 0x88,			
			SET_FREQ: 0x01,
			SET_MODE: 0x07,
			FREQ_MODE_GET: 0x03,
		},
		MODES: {
			MODE_LSB: 0x00,
			MODE_USB: 0x01,
			MODE_CW: 0x02,
			MODE_CWR: 0x03,
			MODE_AM: 0x04,
			MODE_FM: 0x08,
			MODE_DIG: 0x0A,
			MODE_PKT: 0x0C,
		}
	},
	IC7100: {
		CLASS: ICOM,
		SERIAL: {
			PARITY: serial.PARITY_NONE,
			STOP_BITS: serial.STOPBITS_ONE,
			TIMEOUT: 5,
			READ_SZ: 17
		},
		COMMANDS: {
			LOCK_CMD: bytearray([0x1A, ]),
			LOCK_SUB: bytearray([0x05, 0x00, 0x14]),
			LOCK_ON: bytearray([0x01, ]),
			LOCK_OFF: bytearray([0x00, ]),
			MULTIFUNC_CMD: bytearray([0x1A, ]),
			MULTIFUNC_SUB: bytearray([0x05, 0x00, 0x37]),
			PTT_ON: bytearray([0x22, ]),
			PTT_OFF: bytearray([0x00, ]),			
			SET_FREQ_CMD: bytearray([0x00, ]),
			SET_FREQ_SUB: bytearray([]),
			SET_MODE_CMD: bytearray([0x01, ]),
			SET_MODE_SUB:  bytearray([]),
			GET_FREQ_CMD: bytearray([0x03, ]),
			GET_FREQ_SUB: bytearray([]),
			GET_MODE_CMD: bytearray([0x04, ]),
			GET_MODE_SUB: bytearray([])
		},
		RESPONSES: {
			ACK: 0xFB,
			NAK: 0xFA
		},
		MODES: {
			MODE_LSB: bytearray([0x00, ]),
			MODE_USB: bytearray([0x01, ]),
			MODE_AM: bytearray([0x02, ]),
			MODE_CW: bytearray([0x03, ]),
			MODE_RTTY: bytearray([0x04, ]),
			MODE_FM: bytearray([0x05, ]),
			MODE_WFM: bytearray([0x06, ]),
			MODE_CWR: bytearray([0x07, ]),
			MODE_RTTYR: bytearray([0x08, ]),
			MODE_DV: bytearray([0x17 ])
		}
	}
}

#======================================================================================================================
# Testing code

settings = {
	CAT_SETTINGS: {
		VARIANT: CAT_VARIANTS[0],
		NETWORK: [
			# ip, port
			None, None
		],
		SERIAL: [
			#com port, baud rate
			'COM9', 4800
		],
		SELECT: CAT_SERIAL #CAT_UDP | CAT_SERIAL
	}
}
	
def callback(msg):
	
	print ('Msg ',msg)
	
def main():
	
	try:
		# Create instance
		cat = CAT(FT_817ND, settings)
		cat.set_callback(callback)
		cat.start_thrd()
		cat.do_command(CAT_FREQ_SET, 3.7)
		sleep(1)
		cat.do_command(CAT_FREQ_GET)
		sleep(1)
		cat.do_command(CAT_MODE_SET, MODE_AM)
		sleep(1)
		cat.do_command(CAT_MODE_GET)
		sleep(1)
		#cat.do_command(CAT_LOCK, False)
		#sleep(1)
		#cat.do_command(CAT_PTT, True)
		#sleep(1)
		#cat.do_command(CAT_PTT, False)
		#sleep(1)
		#cat.do_command(CAT_LOCK, True)
		cat.terminate()
		
	except Exception as e:
		print ('Exception','Exception [%s][%s]' % (str(e), traceback.format_exc()))

# Entry point       
if __name__ == '__main__':
	main()