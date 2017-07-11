#!/usr/bin/env python
#
# tracking.py
#
# RX frequency tracking for the Mag Loop application
# 
# Copyright (C) 2016 by G3UKB Bob Cowdery
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
import os, sys
import threading
from time import sleep
import traceback

sys.path.append(os.path.join('..','..','..','..','..','Common','trunk','python'))
# Application imports
from common.defs import *

# Common files
import cat

"""

Tracking follows the RX frequency, retuning the antenna as necessary. This means it
will always be optimal for RX as loops have a narrow bandwidth and 'should' present
a low SWR on TX without retuning.

This is a separate autonomous thread that performs a CAT exchange every TRACK_UPDATE
mseconds to get the current receiver frequency (if tracking is enabled). If the
frequency has changed by more than TRACK_FREQ Hz then a callback is made to move the
dc motor by an amount to bring the antenna back to resonance.

"""
class Tracking(threading.Thread):
	
	TRACK_UPDATE = 100 		# Get RX freq every n ms
	TRACK_FREQ = 10000 		# Track if the frequency changes by >n Hz
	
	def __init__(self, cat_inst, variant, settings, loopname, callback):
		"""
		Constructor
		
		Arguments:
			cat_inst	--	CAT class instance
			variant		--	CAT command set and format
			settings	--  see common.py DEFAULT_SETTINGS for structure
			loopname	--  current selected loop
			callback	--  callback here with async responses
		
		"""
		
		super(Tracking, self).__init__()

		self.__variant 	= variant
		self.__settings = settings
		self.__loopname = loopname
		self.__callback = callback
		
		# Get the CAT interface
		self.__cat = cat_inst
		self.__cat.set_callback(self.__cat_callback)
		
		# Class vars
		self.__last_freq = None
		self.__last_setpoint = None
		self.__terminate = False
		self.__run = False
		self.__degrees_moved = 0
	
	def terminate(self):
		""" Asked to terminate the thread """
		
		self.__terminate = True
		self.join()
		self.__cat.terminate()

	def run_tracker(self):
		""" Run the tracker """
		
		self.__run = True
	
	def pause_tracker(self):
		""" Pause the tracker """
		
		self.__run = False
	
	def reset_tracker(self):
		""" Reset the tracking state """
		
		self.__last_freq = None
		self.__last_setpoint = None
		self.__degrees_moved = 0
		
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
				# Send a freq request every TRACK_UPDATE ms
				self.__cat.do_command(CAT_FREQ_GET)
				sleep(Tracking.TRACK_UPDATE/1000.0)				
			except Exception as e:
				self.__callback(TRACKING_ERROR, None, None, None, 'CAT error [%s]' % (str(e)))

	def __cat_callback(self, data):
		"""
		Response from CAT GET_FREQ command
		
		Arguments:
			data	--	(True|False, current freq in Hz)
		
		"""
		
		# Algorithm to see if, and where, we need to move capacitor to
		(r, freq) = data
		if r:
			# Good response
			if self.__run:
				try:
					self.__callback(TRACKING_UPDATE, float(freq/1000000.0))
					tune = False
					if self.__last_freq == None:
						# Start or restart so force a tune
						tune = True
					else:
						# We don't want to be continuously nudging the tuning so,
						# tune only if we have moved in frequency more than TRACK_FREQ Hz since the last tune
						if abs(freq - self.__last_freq) >= Tracking.TRACK_FREQ:
							tune = True
					if tune:
						# Required to do a retune
						freqMHz = float(freq/1000000.0)
						freqKHz = int(freq/1000)
						# Do a sensibility check
						if freqMHz >= float(self.__settings[LOOP_SETTINGS][self.__loopname][I_FREQ][I_LOWER]) and freqMHz <= float(self.__settings[LOOP_SETTINGS][self.__loopname][I_FREQ][I_UPPER]):
							# Within the loop frequency range
							# We now need to find the closest before and after setpoints to the frequency
							# If between setpoints we interpolate between points
							# Get the setpoint list for this loop
							setpoints = self.__settings[LOOP_SETTINGS][self.__loopname][I_SETPOINTS]
							if len(setpoints) == 0:
								# Nothing we can do
								self.__callback(TRACKING_ERROR, None, None, 'There are no setpoints!')
								return
							#=========================================================================================
							# Main loop
							
							# Initial conditions
							diff = None				# Current difference in freq between current freq and current setpoint
							# We note the closest setpoint both below and above the current frequency (as present)
							#[[freq difference, setpoint freq, degrees], [freq difference, setpoint freq, degrees]]
							span = [None, None]
							
							# We work in KHz here as we don't need Hz granularity.
							# Iterate setpoints.
							for setpointfreq in setpoints:
								# Setpoints held as MHz strings in configuration
								setpointKHz = int(float(setpointfreq)*1000)
								# Get the difference between the setpoint and the actual Rx frequency in KHz
								diff = freqKHz-setpointKHz
								if diff < 0:
									# Below the current frequency
									if span[0] == None:
										# First time below
										span[0] = [diff, setpointfreq, setpoints[setpointfreq]]
									else:
										# Subsequent pass
										if abs(diff) < abs(span[0][0]):
											# Closer
											span[0] = [diff, setpointfreq, setpoints[setpointfreq]]									
								else:
									# Above or equal to the current frequency
									if span[1] == None:
										# First time above
										span[1] = [diff, setpointfreq, setpoints[setpointfreq]]
									else:
										# Subsequent pass
										if diff < span[1][0]:
											# Closer
											span[1] = [diff, setpointfreq, setpoints[setpointfreq]]
							
							# Move to the frequency
							if span[0] == None:
								# Only had a higher freq setpoint
								self.__callback(TRACKING_TO_DEGS, span[1][1], span[1][2], '')
							elif span[1] == None:
								# Only had a lower freq setpoint
								self.__callback(TRACKING_TO_DEGS, span[0][1], span[0][2], '')
							else:
								# We had an upper and lower setpoint
								# Interpolate between them to create a pseudo setpoint
								fracFreqRatio = float (abs (span[0][0]) ) /( float (abs(span[0][0]) ) + float (span[1][0]) )
								fracDegRatio = fracFreqRatio * float(span[1][2] - span[0][2])
								newHeading = fracDegRatio + span[0][2]
								self.__callback(TRACKING_TO_DEGS, freqKHz, newHeading, '')
								
							# Remember last freq we moved to
							self.__last_freq = freq
							# End main loop
							#============================================================================================
						
						else:
							# Not withing the loop range
							self.__callback(TRACKING_ERROR, None, None, 'Frequency %s out of range' % (freq))
							self.__callback(TRACKING_UPDATE, float(freq/1000000.0))
				except Exception as e:
					# Problem
					self.__callback(TRACKING_ERROR, None, None, 'Exception in tracking [%s][%s]' % (str(e), traceback.format_exc()))
			else:
				# Not tracking but give a frequency update anyway
				self.__callback(TRACKING_UPDATE, float(freq/1000000.0))
		else:
			# Bad response from CAT
			self.__callback(TRACKING_ERROR, None, None, 'Bad response from CAT, unknown error!')