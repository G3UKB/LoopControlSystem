#!/usr/bin/env python
#
# defs.py
#
# Common definitions for Mag Loop application
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
import os,sys

# Application imports

# ============================================================================
# CAT

# CAT variants
FT_817ND = 'FT-817ND'
IC7100 = 'IC7100'
CAT_VARIANTS = [FT_817ND, IC7100]
YAESU = 'YAESU'
ICOM = 'ICOM'

# ============================================================================
# Constants used in command sets
REFERENCE = 'reference'
MAP = 'map'
CLASS = 'rigclass'
SERIAL = 'serial'
COMMANDS = 'commands'
MODES = 'modes'
PARITY = 'parity'
STOP_BITS = 'stopbits'
TIMEOUT = 'timeout'
READ_SZ = 'readsz'
LOCK_CMD = 'lockcmd'
LOCK_SUB = 'locksub'
LOCK_ON = 'lockon'
LOCK_OFF = 'lockoff'
MULTIFUNC_CMD = 'multifunccmd'
MULTIFUNC_SUB = 'multifuncsub'
PTT_ON = 'ptton'
PTT_OFF = 'pttoff'
SET_FREQ_CMD = 'setfreqcmd'
SET_FREQ_SUB = 'setfreqsub'
SET_FREQ = 'setfreq'
SET_MODE_CMD = 'setmodecmd'
SET_MODE_SUB = 'setmodesub'
SET_MODE = 'setmode'
GET_FREQ_CMD = 'getfreqcmd'
GET_FREQ_SUB = 'getfreqsub'
GET_MODE_CMD = 'getmodecmd'
GET_MODE_SUB = 'getmodesub'
FREQ_MODE_GET = 'freqmodeget'
RESPONSES = 'responses'
ACK = 'ack'
NAK = 'nak'

FROM_HOME = 'fromhome'
FROM_CURRENT = 'fromcurrent'

# ============================================================================
# Constants used in command sets and to be used by callers for mode changes
MODE_LSB = 'lsb'
MODE_USB = 'usb'
MODE_CW = 'cw'
MODE_CWR = 'cwr'
MODE_AM = 'am'
MODE_FM = 'fm'
MODE_DIG = 'dig'
MODE_PKT = 'pkt'
MODE_RTTY = 'rtty'
MODE_RTTYR = 'rttyr'
MODE_WFM = 'wfm'
MODE_DV = 'dv'

# ============================================================================
# CAT command set to be used by callers
CAT_LOCK = 'catlock'
CAT_PTT = 'catptt'
CAT_FREQ_SET = 'catfreqset'
CAT_MODE_SET = 'catmodeset'
CAT_FREQ_GET = 'catfreqget'
CAT_MODE_GET = 'catmodeget'

# ======================================================================================
# SETTINGS and STATE

# Paths to state and configuration files
SETTINGS_PATH = os.path.join('..', '..', 'settings', 'magcontrol.cfg')
STATE_PATH = os.path.join('..', '..', 'settings', 'state.cfg')
WMM_COF_PATH = os.path.join('..', '..', 'settings', 'WMM.COF')

# Constants for settings
ARDUINO_SETTINGS = 'arduinosettings'
LOOP_SETTINGS = 'loopsettings'
CAT_SETTINGS = 'catsettings'
NETWORK = 'network'
ANALOG_REF = 'analogref'
INTERNAL = 'internal'
EXTERNAL = 'external'
SERIAL = 'serial'
SELECT = 'select'
VARIANT = 'variant'
CAT_UDP = 'catudp'
CAT_SERIAL = 'catserial'
SELECTED_LOOP = 'selectedloop'
LOOP_PARAMS = 'loopparams'
LOCATION = 'location'
LIMITS = 'limits'
WINDOW = 'window'
X_POS = 'xpos'
Y_POS = 'ypos'

# Index into settings list
I_POT = 0
I_MINCAP = 0
I_MAXCAP = 1
I_FREQ = 1
I_LOWER = 0
I_UPPER = 1

I_RELAYS = 2

I_SETPOINTS = 3
I_PARAMS = 4
I_SLOW = 0
I_MEDIUM = 1
I_FAST = 2
I_NUDGE = 3

I_OFFSETS = 5
I_LOW_FREQ = 0
I_HIGH_FREQ = 1

# Index into comms parameters
IP = 0
PORT = 1
COM_PORT = 0
BAUD_RATE = 1

# ======================================================================================
# ARDUINO
# Default arduino parameters
ARDUINO_IP = '192.168.1.177'
ARDUINO_PORT = '8888'

# Default motor parameters
FORWARD = 'forward'
REVERSE = 'reverse'
# Speed range is 0 - 400 (negative if reverse)
MOTOR_SLOW = 35
MOTOR_MEDIUM = 50
MOTOR_FAST = 80
MOTOR_TUNE_FAST = 50
MOTOR_TUNE_SLOW = 25

# Nudge forward or reverse 5 degrees
MOTOR_NUDGE = 5
# Buffer size
RECEIVE_BUFFER = 512
# Timeout for responses and events
CONTROLLER_TIMEOUT = 1

# Arduino event port on which we listen
EVENT_PORT = 8889

# ======================================================================================
# DEFAULT STRUCTURES
DEFAULT_SETTINGS = {
    ARDUINO_SETTINGS: {
        NETWORK: [
            # ip, port
            ARDUINO_IP, ARDUINO_PORT,
        ],
        ANALOG_REF: INTERNAL,
    },
        
    LOOP_SETTINGS: {
    # Loop name - Lower and upper frequency of loop, setpoints
    # name: [
    #           -- Pot settings
    #           [mincap, maxcap],
    #           -- Lower and upper frequency of loop --
    #           [lower, upper],
    #           -- Relay state for antenna switch
    #           [0|1, 0|1, 0|1, 0|1],
    #           -- Setpoints as degrees from home --
    #           {1.9 : 100, 2.0 : 200, ...},
    #           -- Motor Parameters --
    #           -- Range 0 - 400 : Slow, Medium, Fast, Degrees to Nudge
    #           [slow, medium, fast, nudge],
    #           -- Loop range --
    #           -- Min freq extension %, max freq extension %
    #           [min cap extension %, max cap extension %]
    #          ],
    #   name: [...],
    #    
    },
    
    CAT_SETTINGS: {
        VARIANT: CAT_VARIANTS[0],
        NETWORK: [
            # ip, port
            None, None
        ],
        SERIAL: [
            #com port, baud rate
            '', '9600'
        ],
        SELECT: CAT_SERIAL #CAT_UDP | CAT_SERIAL
    }        
}

DEFAULT_STATE  = {
    WINDOW: {X_POS: 100, Y_POS: 100},
    SELECTED_LOOP: None,
}

# ======================================================================================
# GUI

# Index for tabs
I_TAB_ARDUINO = 0
I_TAB_LOOPS = 1
I_TAB_POT = 2
I_TAB_SETPOINTS = 3
I_TAB_CAT = 4

# Status messsages
TICKS_TO_CLEAR = 30

# Idle ticker
IDLE_TICKER = 100 # ms

# Frequency to try and start CAT
CAT_TIMER = 50 # 5s timer

# Status messages time
STATUS_TIMER = 4000 # 4s timer

# Connected poll
POLL_TICKS = 50

# Relay state
ENERGISE = 'energise'
DE_ENERGISE = 'deenergise'

# Source
PI_WSPR = 'piwspr'
MAIN_RADIO = 'mainradio'

# Indexes to vswr array
VSWR_FWD = 0
VSWR_REF = 1

# Indexes to motor status array
MOTOR_REL_STEPS = 0
MOTOR_STEPS_FROM_HOME = 1
MOTOR_DEG_FROM_HOME = 2

# ======================================================================================
# TRACKING

# Tracking message types
TRACKING_TO_DEGS = 'trackingtodegs'
TRACKING_ERROR = 'trackingerror'
TRACKING_UPDATE = 'trackingupdate'

# ======================================================================================
# AUTO-CONFIGURE

AUTO_NEXT = 'autonext'
AUTO_COMPLETE = 'autocomplete'
AUTO_PROMPT_USER = 'promptuser'
AUTO_CONTINUE = 'continue'
AUTO_SKIP = 'skip'
AUTO_ABORT = 'abort'
AUTO_NONE = 'none'

# ======================================================================================
# BAND_PLAN

BAND_PLAN = (
    (1810, 2000),
    (3500, 3800),
    (7000, 7200),
    (10100, 10150),
    (14000, 14350),
    (18068, 18168),
    (21000, 21450),
    (24890, 24990),
    (24890, 24990),
    (28000, 29700),    
)