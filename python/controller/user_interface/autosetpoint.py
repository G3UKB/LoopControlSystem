#!/usr/bin/env python
#
# autosetpoint.py
#
# Auto-configure the setpoints for the Mag Loop application

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

# Library imports
from PyQt4 import QtCore, QtGui

sys.path.append(os.path.join('..', '..'))
sys.path.append(os.path.join('..','..','..','..','..','Common','trunk','python'))
# Application imports
from common.defs import *

# Common files
#from common import cat
import cat

"""
Configuration dialog
"""
class AutoSetpoint(threading.Thread):

    def __init__(self, cat_inst, lower_freq, upper_freq, step, callback):
        """
        Constructor
        
        
        Arguments:
            cat_inst    --  CAT class instance
            lower_freq  --  lower antenna frequency in KHz
            upper_freq  --  upper antenna frequency in KHz
            step        --  step size in KHz   
            callback    --  callback here when ready for each tune cycle
            
        """
    
        super(AutoSetpoint, self).__init__()
        
        self.__cat = cat_inst
        self.__lower_freq = lower_freq
        self.__upper_freq = upper_freq
        self.__step = step
        self.__callback = callback
        
        self.__do_cycle = False
        self.__terminate = False
    
    def do_cycle(self):
        
        self.__do_cycle = True
    
    def terminate(self):
        
        self.__terminate = True
        
    def run(self):
        
        # Step through the frequency range
        for freq in range(self.__lower_freq, self.__upper_freq, self.__step):
            # Ensure we are within a band
            if len([f for f in BAND_PLAN if freq >= f[0] and freq <= f[1]]) > 0:
                while not self.__do_cycle:
                    # Waiting for the go
                    if self.__terminate: break
                    sleep(1)
                self.__do_cycle = False
                # Set mode to RTTY (best mode to get a carrier)
                self.__cat.do_command(CAT_MODE_SET, MODE_RTTY)
                # Set the first/next rig frequency
                self.__cat.do_command(CAT_FREQ_SET, float(freq/1000))
                # We could invoke PTT here but don't for two reasons.
                #   1. Most rigs will only allow PTT via CAT under certain conditions which we may not want or have
                #   2. The decision to TX on every step frequency in a band should be taken by a human and
                #   in any case could violate some licensing condition if done automatically.
                # Ask the user if they want to continue
                reply = self.__callback(AUTO_PROMPT_USER, freq)
                if reply == AUTO_CONTINUE:
                    # Yes so tell caller to execute the setpoint
                    self.__callback(AUTO_NEXT, freq)
                elif reply == AUTO_SKIP:
                    # Cycle was skipped so do another cycle
                    self.__do_cycle = True
                else:
                    # Operation aborted
                    break
                                
        # All done
        self.__callback(AUTO_COMPLETE, None)
