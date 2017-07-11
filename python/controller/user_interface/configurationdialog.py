#!/usr/bin/env python
#
# configurationdialog.py
#
# Configuration for the Loop Controller application

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
import glob
import copy
from PyQt4 import QtCore, QtGui
import math
import queue
from time import sleep
import traceback

# Library imports
import serial

sys.path.append(os.path.join('..', '..'))
sys.path.append(os.path.join('..','..','..','Common','trunk','python'))
# Application imports
from common.defs import *
import autosetpoint
from controller.hw_interface import dispatcher
from common import vswr

# Common files
#from common import cat
import cat

"""
Configuration dialog
"""
class ConfigurationDialog(QtGui.QDialog):
    
    def __init__(self, cat_inst, dispatcher_inst, api_inst, main_q, priority_q, settings, current_loop, callback, parent = None):
        """
        Constructor
        
        Arguments:
            cat_inst        --  CAT class instance
            dispatcher_inst --  Dispatcher instance
            api_inst        --  Controller API instance
            main_q          --  Main dispatcher queue
            priority_q      --  Priority dispatcher queue
            settings        --  see common.py DEFAULT_SETTINGS for structure
            current_loop    --  selected loop
            callback        --  callback here with status messages
            parent          --  parent window
        """
        
        super(ConfigurationDialog, self).__init__(parent)
        
        # Make a full copy of the settings
        self.__settings = copy.deepcopy(settings)
        # Retain original settings incase we cancel
        self.__orig_settings = copy.deepcopy(settings)
        self.__current_loop = current_loop
        self.__statusCallback = callback
        # Get the instances
        self.__cat = cat_inst
        self.__api = api_inst
        # Redirect the response and event callbacks to us
        self.__api.stealRespCallback(self.__respCallback)
        self.__api.stealEvntCallback(self.__evntCallback)
        # Forward some event messages
        self.__evntForwardCallback = self.__api.originalEvntCallback()
        # Get the dispatcher queues and redirect the execution callback
        self.__q = main_q
        self.__p_q = priority_q
        dispatcher_inst.stealCallback(self.__executionCallback)
        
        # Create the UI interface elements
        self.__initUI()
        
        # Class vars
        self.__running = False              # True when motor running
        self.__progress = 0                 # %progress when activity running
        self.__spTuneInProgress = False     # if true setpoint tuning
        self.__lfTuneInProgress = False     # if true low band edge setpoint tuning
        self.__hfTuneInProgress = False     # if true high band edge setpoint tuning
        self.__vswr = (0.0,0.0)             # Set after a tune as final SWR
        self.__addSetpoint = [False, None]  # [True|False, None|freq] 
        self.__prompt_user = False          # Auto-config prompt
        self.__ready_to_go = AUTO_NONE      # Auto-config prompt result
        self.__extension = 0                # Extension % absolute
        self.__realExtension = None         # Extension in analog voltage
        
        # Start the idle timer
        QtCore.QTimer.singleShot(100, self.__idleProcessing)

    # ========================================================================================
    # UI initialisation
    def __initUI(self):
        """ Configure the GUI interface """
        
        # Set the back colour
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Background,QtGui.QColor(74,108,117,255))
        self.setPalette(palette)

        self.setWindowTitle('Configuration')
        
        # Set up the tabs
        self.top_tab_widget = QtGui.QTabWidget()
        arduinotab = QtGui.QWidget()
        looptab = QtGui.QWidget()
        pottab = QtGui.QWidget()
        sertpointtab = QtGui.QWidget()
        cattab = QtGui.QWidget()
        
        self.top_tab_widget.addTab(arduinotab, "Arduino")
        self.top_tab_widget.addTab(looptab, "Loop")
        self.top_tab_widget.addTab(pottab, "Potentiometer")
        self.top_tab_widget.addTab(sertpointtab, "Setpoints")
        self.top_tab_widget.addTab(cattab, "CAT")
        self.top_tab_widget.currentChanged.connect(self.onTab)        
        
        # Add the top layout to the dialog
        top_layout = QtGui.QGridLayout(self)
        top_layout.addWidget(self.top_tab_widget, 0, 0)
        self.setLayout(top_layout)

        # Set layouts for top tab
        arduinogrid = QtGui.QGridLayout()
        arduinotab.setLayout(arduinogrid)        
        loopgrid = QtGui.QGridLayout()
        looptab.setLayout(loopgrid)
        potgrid = QtGui.QGridLayout()
        pottab.setLayout(potgrid)
        setpointgrid = QtGui.QGridLayout()         
        sertpointtab.setLayout(setpointgrid)
        catgrid = QtGui.QGridLayout()         
        cattab.setLayout(catgrid)
        
        # Add the arduino layout to the dialog
        self.__populateArduino(arduinogrid)
        
        # Add the loop layout to the dialog
        self.__populateLoops(loopgrid)
        
        # Add the pot layout to the dialog
        self.__populatePot(potgrid)
        
        # Add the set-point layout to the dialog
        self.__populateSetpoints(setpointgrid)
        
        # Add the CAT layout to the dialog
        self.__populateCAT(catgrid)
        
        # Add common buttons
        self.__populateCommon(top_layout, 1, 0, 1, 1)
 
    def __populateArduino(self, grid):
        """
        Populate the Arduino parameters tab
        
        Arguments
            grid    --  grid to populate
            
        """
        
        # Add instructions
        usagelabel = QtGui.QLabel('Usage:')
        usagelabel.setStyleSheet("QLabel {color: rgb(0,64,128); font: 11px}")
        grid.addWidget(usagelabel, 0, 0)
        instlabel = QtGui.QLabel()
        instructions = """
 - Set the IP address and port to the listening IP/port of the Arduino.
 
 - If using an external analog reference voltage attached to the AREF
pin then check EXTERNAL.
        """
        instlabel.setText(instructions)
        instlabel.setStyleSheet("QLabel {color: rgb(0,64,128); font: 11px}")
        grid.addWidget(instlabel, 1, 0, 1, 3)
        
        # Add control items
        # IP selection
        iplabel = QtGui.QLabel('Arduino IP')
        grid.addWidget(iplabel, 2, 0)
        self.iptxt = QtGui.QLineEdit()
        self.iptxt.setToolTip('Listening IP of Arduino')
        self.iptxt.setInputMask('000.000.000.000;_')
        self.iptxt.setMaximumWidth(100)
        grid.addWidget(self.iptxt, 2, 1)
        self.iptxt.editingFinished.connect(self.ipChanged)
        if len(self.__settings[ARDUINO_SETTINGS][NETWORK]) > 0:
            self.iptxt.setText(self.__settings[ARDUINO_SETTINGS][NETWORK][IP])
        
        # Port selection
        portlabel = QtGui.QLabel('Arduino Port')
        grid.addWidget(portlabel, 3, 0)
        self.porttxt = QtGui.QLineEdit()
        self.porttxt.setToolTip('Listening port of Arduino')
        self.porttxt.setInputMask('00000;_')
        self.porttxt.setMaximumWidth(100)
        grid.addWidget(self.porttxt, 3, 1)
        self.porttxt.editingFinished.connect(self.portChanged)
        if len(self.__settings[ARDUINO_SETTINGS][NETWORK]) > 0:
            self.porttxt.setText(self.__settings[ARDUINO_SETTINGS][NETWORK][PORT])
        
        # Analog reference
        reflabel = QtGui.QLabel('Analog reference')
        grid.addWidget(reflabel, 4, 0)
        self.refcb = QtGui.QCheckBox('EXTERNAL')
        self.refcb.stateChanged.connect(self.refChanged)
        grid.addWidget(self.refcb, 4, 1)
        if self.__settings[ARDUINO_SETTINGS][ANALOG_REF] == EXTERNAL:
            self.refcb.setChecked(True)
        else:
            self.refcb.setChecked(False)
        
        # Push everything to the top
        nulllabel = QtGui.QLabel('')
        grid.addWidget(nulllabel, 5, 0, 1, 2)
        nulllabel1 = QtGui.QLabel('')
        grid.addWidget(nulllabel1, 0, 2)
        grid.setRowStretch(5, 1)
        grid.setColumnStretch(2, 1)
        
    def __populateLoops(self, grid):
        """
        Populate the loop parameters tab
        
        Arguments
            grid    --  grid to populate
            
        """
        
        # Add instructions
        usagelabel = QtGui.QLabel('Usage:')
        usagelabel.setStyleSheet("QLabel {color: rgb(0,64,128); font: 11px}")
        grid.addWidget(usagelabel, 0, 0)
        instlabel = QtGui.QLabel()
        instructions = """
Configure each loop:
  1. Unique loop name.
  2. The lower and upper frequency of the band covered
     (treat each span as a separate loop if the same physical loop).
  3. Relays to be energised to select the loop (if required).
  4. Motor speeds (depends on motor, keep reasonable).
  5. Set the span for the loop in extension % by tuning at band edges.
        """
        instlabel.setText(instructions)
        instlabel.setStyleSheet("QLabel {color: rgb(0,64,128); font: 11px}")
        grid.addWidget(instlabel, 1, 0, 1, 5)
        
        # Add control items
        # Loop selection
        looplabel = QtGui.QLabel('Loop')
        grid.addWidget(looplabel, 2, 0)
        self.loopcombo = QtGui.QComboBox()
        for key in sorted(self.__settings[LOOP_SETTINGS].keys()):
            self.loopcombo.addItem(str(key))
        grid.addWidget(self.loopcombo, 2, 1, 1, 2)
        self.loopcombo.activated.connect(self.onLoopLoop)
        if self.__current_loop != None:
            self.loopcombo.setCurrentIndex(self.loopcombo.findText(self.__current_loop))

        # Loop name
        namelabel = QtGui.QLabel('Name')
        grid.addWidget(namelabel, 3, 0)
        self.loopnametxt = QtGui.QLineEdit()
        self.loopnametxt.setToolTip('Name this loop')
        grid.addWidget(self.loopnametxt, 3, 1, 1, 2)
        
        # Lower freq limit of loop
        lowerfreqlabel = QtGui.QLabel('Lower freq')
        mhzlabel1 = QtGui.QLabel('MHz')
        grid.addWidget(lowerfreqlabel, 4, 0)
        self.freqlowertxt = QtGui.QLineEdit()
        self.freqlowertxt.setValidator(FreqValidator(self, 0.1, 148.0))
        self.freqlowertxt.resize(self.freqlowertxt.sizeHint())
        self.freqlowertxt.setMaximumWidth(60)
        self.freqlowertxt.setToolTip('Lower freq extent of loop')
        grid.addWidget(self.freqlowertxt, 4, 1)
        grid.addWidget(mhzlabel1, 4, 2)       
        
        # Upper freq limit of loop
        upperfreqlabel = QtGui.QLabel('Upper freq')
        mhzlabel2 = QtGui.QLabel('MHz')
        grid.addWidget(upperfreqlabel, 5, 0)
        self.frequppertxt = QtGui.QLineEdit()
        self.frequppertxt.setValidator(FreqValidator(self, 0.1, 148.0))
        self.frequppertxt.resize(self.frequppertxt.sizeHint())
        self.frequppertxt.setMaximumWidth(60)
        self.frequppertxt.setToolTip('Upper freq extent of loop')
        grid.addWidget(self.frequppertxt, 5, 1)
        grid.addWidget(mhzlabel2, 5, 2)
        
        # Select relays for antenna switching
        antennalabel = QtGui.QLabel('Relays to be energised :-')
        grid.addWidget(antennalabel, 6, 0, 1, 3)
        self.relay1cb = QtGui.QCheckBox('1')
        self.relay2cb = QtGui.QCheckBox('2')
        self.relay3cb = QtGui.QCheckBox('3')
        self.relay4cb = QtGui.QCheckBox('4')
        self.relay_groupbox = QtGui.QGroupBox('')
        relay_hbox = QtGui.QHBoxLayout()
        relay_hbox.addWidget(self.relay1cb)
        relay_hbox.addWidget(self.relay2cb)
        relay_hbox.addWidget(self.relay3cb)
        relay_hbox.addWidget(self.relay4cb)
        self.relay_groupbox.setLayout(relay_hbox)
        grid.addWidget(self.relay_groupbox, 7, 0, 1, 3)
        
        #Initialise relays
        loopName = self.loopcombo.currentText()
        if len(loopName) > 0:
            self.relay1cb.setChecked(self.__settings[LOOP_SETTINGS][loopName][I_RELAYS][0])
            self.relay2cb.setChecked(self.__settings[LOOP_SETTINGS][loopName][I_RELAYS][1])
            self.relay3cb.setChecked(self.__settings[LOOP_SETTINGS][loopName][I_RELAYS][2])
            self.relay4cb.setChecked(self.__settings[LOOP_SETTINGS][loopName][I_RELAYS][3])
        
        # Motor used on this loop
        motorlabel = QtGui.QLabel('Motor Settings (max speed = 400)')
        grid.addWidget(motorlabel, 4, 3, 1, 2)
        # Slow
        slowlabel = QtGui.QLabel('Slow (50-200)')
        grid.addWidget(slowlabel, 5, 3)
        self.slowsb = QtGui.QSpinBox(self)
        self.slowsb.setRange(50, 200)
        self.slowsb.setValue(MOTOR_SLOW)
        grid.addWidget(self.slowsb, 5, 4)
        # Medium
        medlabel = QtGui.QLabel('Medium (100-300)')
        grid.addWidget(medlabel, 6, 3)
        self.medsb = QtGui.QSpinBox(self)
        self.medsb.setRange(100,300)
        self.medsb.setValue(MOTOR_MEDIUM)
        grid.addWidget(self.medsb, 6, 4)
        # Fast
        fastlabel = QtGui.QLabel('Fast (100-400)')
        grid.addWidget(fastlabel, 7, 3)
        self.fastsb = QtGui.QSpinBox(self)
        self.fastsb.setRange(100, 400)
        self.fastsb.setValue(MOTOR_FAST)
        grid.addWidget(self.fastsb, 7, 4)
        # Nudge
        nudgelabel = QtGui.QLabel('Nudge (0.1 - 5.0 % extension)')
        grid.addWidget(nudgelabel, 8, 3)
        self.nudgesb = QtGui.QDoubleSpinBox(self)
        self.nudgesb.setRange(0.1, 5.0)
        self.nudgesb.setDecimals(1)
        self.nudgesb.setSingleStep(0.1)
        self.nudgesb.setValue(0.2)
        grid.addWidget(self.nudgesb, 8, 4)
        
        # Update loop parameters
        if len(loopName) > 0:
            self.loopnametxt.setText(loopName) 
            self.freqlowertxt.setText(self.__settings[LOOP_SETTINGS][loopName][I_FREQ][I_LOWER])
            self.frequppertxt.setText(self.__settings[LOOP_SETTINGS][loopName][I_FREQ][I_UPPER])
            self.slowsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_PARAMS][I_SLOW])
            self.medsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_PARAMS][I_MEDIUM])
            self.fastsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_PARAMS][I_FAST])
            self.nudgesb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_PARAMS][I_NUDGE]) 
               
        # Low/ high frequency setpoints
        loopLimitsGrid = QtGui.QGridLayout()
        widget = QtGui.QWidget()
        widget.setLayout(loopLimitsGrid)
        grid.addWidget(widget, 9, 0, 1, 5)
        
        # High freq
        hflabel = QtGui.QLabel('High Freq')
        loopLimitsGrid.addWidget(hflabel, 0, 0)
        
        self.hfextsb = QtGui.QSpinBox(self)
        self.hfextsb.setRange(0, 100)
        self.hfextsb.setValue(0)
        if len(loopName) > 0:
            if self.__settings[LOOP_SETTINGS][loopName][I_OFFSETS][I_HIGH_FREQ] != None:
                self.hfextsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_OFFSETS][I_HIGH_FREQ])
                
        loopLimitsGrid.addWidget(self.hfextsb, 0, 1)
        hfextlabel = QtGui.QLabel('%')
        loopLimitsGrid.addWidget(hfextlabel, 0, 2)
        
        self.hftunebtn = QtGui.QPushButton('Tune', self)
        self.hftunebtn.setToolTip('Tune to the high frequency setting')
        self.hftunebtn.resize(self.hftunebtn.sizeHint())
        self.hftunebtn.setMinimumHeight(20)
        self.hftunebtn.setMinimumWidth(50)
        self.hftunebtn.setEnabled(True)
        self.hftunebtn.clicked.connect(self.__hfTune)
        loopLimitsGrid.addWidget(self.hftunebtn, 0, 3)
        self.hfabortbtn = QtGui.QPushButton('Abort', self)
        self.hfabortbtn.setToolTip('Abort tuning')
        self.hfabortbtn.resize(self.hfabortbtn.sizeHint())
        self.hfabortbtn.setMinimumHeight(20)
        self.hfabortbtn.setMinimumWidth(50)
        self.hfabortbtn.setEnabled(True)
        self.hfabortbtn.clicked.connect(self.__hfAbortTune)
        loopLimitsGrid.addWidget(self.hfabortbtn, 0, 4)
        
        self.hfvswrlabel = QtGui.QLabel('VSWR')
        loopLimitsGrid.addWidget(self.hfvswrlabel, 0, 5)
        self.hfvswrvalue = QtGui.QLabel('__:__')
        loopLimitsGrid.addWidget(self.hfvswrvalue, 0, 6)
        
        # Low freq
        lflabel = QtGui.QLabel('Low Freq')
        loopLimitsGrid.addWidget(lflabel, 1, 0)
        
        self.lfextsb = QtGui.QSpinBox(self)
        self.lfextsb.setRange(0, 100)
        self.lfextsb.setValue(100)
        if len(loopName) > 0:
            if self.__settings[LOOP_SETTINGS][loopName][I_OFFSETS][I_LOW_FREQ] != None:
                self.lfextsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_OFFSETS][I_LOW_FREQ])
        
        loopLimitsGrid.addWidget(self.lfextsb, 1, 1)
        lfextlabel = QtGui.QLabel('%')
        loopLimitsGrid.addWidget(lfextlabel, 1, 2)
        
        self.lftunebtn = QtGui.QPushButton('Tune', self)
        self.lftunebtn.setToolTip('Tune to the low frequency setting')
        self.lftunebtn.resize(self.lftunebtn.sizeHint())
        self.lftunebtn.setMinimumHeight(20)
        self.lftunebtn.setMinimumWidth(50)
        self.lftunebtn.setEnabled(True)
        self.lftunebtn.clicked.connect(self.__lfTune)
        loopLimitsGrid.addWidget(self.lftunebtn, 1, 3)
        self.lfabortbtn = QtGui.QPushButton('Abort', self)
        self.lfabortbtn.setToolTip('Abort tuning')
        self.lfabortbtn.resize(self.lfabortbtn.sizeHint())
        self.lfabortbtn.setMinimumHeight(20)
        self.lfabortbtn.setMinimumWidth(50)
        self.lfabortbtn.setEnabled(True)
        self.lfabortbtn.clicked.connect(self.__lfAbortTune)
        loopLimitsGrid.addWidget(self.lfabortbtn, 1, 4)

        lfvswrlabel = QtGui.QLabel('VSWR')
        loopLimitsGrid.addWidget(lfvswrlabel, 1, 5)
        self.lfvswrvalue = QtGui.QLabel('__:__')
        loopLimitsGrid.addWidget(self.lfvswrvalue, 1, 6)
                
        # Buttons
        line = QtGui.QFrame()
        line.setFrameShape(QtGui.QFrame.HLine)
        line.setFrameShadow(QtGui.QFrame.Sunken)
        line.setStyleSheet("QFrame {background-color: rgb(126,126,126)}")
        grid.addWidget(line, 10, 0, 1, 6)
        
        buttonHbox = QtGui.QHBoxLayout()
        widget = QtGui.QWidget()
        widget.setLayout(buttonHbox)
        grid.addWidget(widget, 11, 0, 1, 6)
        
        self.loopeditbtn = QtGui.QPushButton('Add/Update', self)
        self.loopeditbtn.setToolTip('Add or update the current details')
        self.loopeditbtn.resize(self.loopeditbtn.sizeHint())
        self.loopeditbtn.setMinimumHeight(20)
        self.loopeditbtn.setMinimumWidth(120)
        self.loopeditbtn.setEnabled(True)
        buttonHbox.addWidget(self.loopeditbtn)
        self.loopeditbtn.clicked.connect(self.editLoop)
        self.loopremovebtn = QtGui.QPushButton('Remove', self)
        self.loopremovebtn.setToolTip('Remove the selected loop')
        self.loopremovebtn.resize(self.loopremovebtn.sizeHint())
        self.loopremovebtn.setMinimumHeight(20)
        self.loopremovebtn.setMinimumWidth(120)
        self.loopremovebtn.setEnabled(True)
        buttonHbox.addWidget(self.loopremovebtn)
        self.loopremovebtn.clicked.connect(self.removeLoop)       
    
        # Push everything up to the top
        nulllabel = QtGui.QLabel('')
        grid.addWidget(nulllabel, 12, 0, 1, 6)
        nulllabel1 = QtGui.QLabel('')
        grid.setRowStretch(12, 1)
        
    def __populatePot(self, grid):
        """
        Populate the potentiometer parameters tab
        
        Arguments
            grid    --  grid to populate
            
        """
        
        # Add instructions
        usagelabel = QtGui.QLabel('Usage:')
        usagelabel.setStyleSheet("QLabel {color: rgb(0,64,128); font: 11px}")
        grid.addWidget(usagelabel, 0, 0)
        instlabel = QtGui.QLabel()
        instructions = """
Manually set the extremes of linear motion for minimum and
maximum capacitance by moving the actuator to each extreme.
Note: The analog raw value is 0-1023 and could be different
with an external analog reference. The internal pot may not
quite reach min/max values.
The values are per loop as these will change for different
mechanical/motor arrangements.
        """
        
        instlabel.setText(instructions)
        instlabel.setStyleSheet("QLabel {color: rgb(0,64,128); font: 11px}")
        grid.addWidget(instlabel, 1, 0, 1, 5)
        
        # Loop selection (pot settings are per loop as they can be different control settings)
        loopName = self.loopcombo.currentText()
        looplabel = QtGui.QLabel('Loop')
        grid.addWidget(looplabel, 2, 0)
        self.potloopcombo = QtGui.QComboBox()
        for key in sorted(self.__settings[LOOP_SETTINGS].keys()):
            self.potloopcombo.addItem(str(key))
        grid.addWidget(self.potloopcombo, 2, 1, 1, 2)
        self.potloopcombo.activated.connect(self.onPotLoop)
        if self.__current_loop != None:
            self.potloopcombo.setCurrentIndex(self.loopcombo.findText(self.__current_loop))
            
        # Fully unmeshed (min cap)
        # Minimum extension
        mincaplabel = QtGui.QLabel('Min Capacitance')
        grid.addWidget(mincaplabel, 4, 0)
        self.mincapsb = QtGui.QSpinBox(self)
        self.mincapsb.setRange(0, 700)
        self.mincapsb.setValue(0)
        if len(loopName) > 0:
            if self.__settings[LOOP_SETTINGS][loopName][I_POT][I_MINCAP] != None:
                self.mincapsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_POT][I_MINCAP])
        self.mincapsb.valueChanged.connect(self.__minCapChanged)
        grid.addWidget(self.mincapsb, 4, 1)
        mincapextlabel = QtGui.QLabel('(0 to 700) analog value')
        grid.addWidget(mincapextlabel, 4, 2)
        
        # Fully meshed (max cap)
        # Maximum extension
        maxcaplabel = QtGui.QLabel('Max Capacitance')
        grid.addWidget(maxcaplabel, 5, 0)        
        self.maxcapsb = QtGui.QSpinBox(self)
        self.maxcapsb.setRange(500, 1023)
        self.maxcapsb.setValue(1023)
        if len(loopName) > 0:
            if self.__settings[LOOP_SETTINGS][loopName][I_POT][I_MAXCAP] != None:
                self.maxcapsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_POT][I_MAXCAP])
        self.maxcapsb.valueChanged.connect(self.__maxCapChanged)        
        grid.addWidget(self.maxcapsb, 5, 1)        
        maxcapextlabel = QtGui.QLabel('(500 to 1023) analog value')
        grid.addWidget(maxcapextlabel, 5, 2)        
        
        # Push everything up to the top
        nulllabel = QtGui.QLabel('')
        grid.addWidget(nulllabel, 6, 0, 1, 4)
        nulllabel1 = QtGui.QLabel('')
        grid.setRowStretch(6, 1)
        
    def __populateSetpoints(self, grid):
        """
        Populate the loop set-points tab
        
        Arguments
            grid    --  grid to populate
            
        """
        
        # Add instructions
        usagelabel = QtGui.QLabel('Usage:')
        usagelabel.setStyleSheet("QLabel {color: rgb(0,64,128); font: 11px}")
        grid.addWidget(usagelabel, 0, 0)
        instlabel = QtGui.QLabel()
        instructions = """
(1) Select a frequency to remove or edit entries.
(2) To add a frequency:
    1. Enter the required frequency.
    2. Set the transmitter to the same frequency.
    3. Transmit 5-10 watts of carrier.
    4. Click 'Tune' and when complete, 'Add'.
    5. Or enter the freq/extension % if known and click 'Add'.
    6. Or if CAT is active set step size and click 'Auto'.
        """
        
        instlabel.setText(instructions)
        instlabel.setStyleSheet("QLabel {color: rgb(0,64,128); font: 11px}")
        grid.addWidget(instlabel, 1, 0, 1, 6)
        
        self.contextlabel = QtGui.QLabel()
        context = "Loop: %s   [Low: %sMHz, High: %sMHz]" % (self.loopnametxt.text(), self.freqlowertxt.text(), self.frequppertxt.text())
        self.contextlabel.setText(context)
        self.contextlabel.setStyleSheet("QLabel {color: rgb(234,77,0); font: 12px}")
        grid.addWidget(self.contextlabel, 2, 1, 1, 5)
        
        # Step size
        stepszlabel = QtGui.QLabel('Step size')
        grid.addWidget(stepszlabel, 3, 0)
        self.stepsb = QtGui.QSpinBox(self)
        self.stepsb.setRange(1, 100)
        self.stepsb.setValue(20)
        grid.addWidget(self.stepsb, 3, 1)
        khzszlabel = QtGui.QLabel('1 - 100KHz')
        grid.addWidget(khzszlabel, 3, 2)
        
        # Auto button
        self.autobtn = QtGui.QPushButton('Auto', self)
        self.autobtn.setToolTip('Auto configure setpoints')
        self.autobtn.resize(self.autobtn.sizeHint())
        self.autobtn.setMinimumHeight(20)
        self.autobtn.setEnabled(True)
        grid.addWidget(self.autobtn, 3, 4)
        self.autobtn.clicked.connect(self.autoSetpoint)
        
        # Add control items
        # Freq selection
        freqlabel = QtGui.QLabel('Freq sel')
        grid.addWidget(freqlabel, 4, 0)
        self.freqcombo = QtGui.QComboBox()
        if len(self.__settings[LOOP_SETTINGS]) > 0:
            for key in sorted(self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_SETPOINTS].keys()):
                self.freqcombo.addItem(str(key)) 
        grid.addWidget(self.freqcombo, 4, 1)
        self.freqcombo.activated.connect(self.onFreqSetpoint)
        mhzlabel = QtGui.QLabel('MHz')
        grid.addWidget(mhzlabel, 4, 2)
        
        # New freq
        freqlabel1 = QtGui.QLabel('Freq')
        grid.addWidget(freqlabel1, 5, 0)
        # Freq entry
        self.freqtxt = QtGui.QLineEdit()
        self.freqtxt.resize(self.freqtxt.sizeHint())
        self.freqtxt.setMaximumWidth(50)
        grid.addWidget(self.freqtxt, 5, 1)
        self.freqtxt.setText(self.freqcombo.currentText())
        
        # Offset extension
        offsetlabel = QtGui.QLabel('% Ext')
        grid.addWidget(offsetlabel, 5, 2)        
        self.spextvalue = QtGui.QSpinBox(self)       
        grid.addWidget(self.spextvalue, 5, 3)
        
        # Set extension % range and value
        self.__setExtensions()
        
        # Tune button
        self.tunebtn = QtGui.QPushButton('Tune', self)
        self.tunebtn.setToolTip('Tune to freq')
        self.tunebtn.resize(self.tunebtn.sizeHint())
        self.tunebtn.setMinimumHeight(20)
        self.tunebtn.setEnabled(True)
        grid.addWidget(self.tunebtn, 5, 4)
        self.tunebtn.clicked.connect(self.tuneSetpoint)
        
        # Progress bar
        progresslabel = QtGui.QLabel('Progress')
        grid.addWidget(progresslabel, 6, 0)
        self.progressbar = QtGui.QProgressBar(self)
        self.progressbar.setToolTip('Motor progress')
        self.progressbar.setMinimum(0)
        self.progressbar.setMaximum(100)
        self.progressbar.setEnabled(True)
        grid.addWidget(self.progressbar, 6, 1, 1, 2)
        
        # VSWR
        vswrlabel = QtGui.QLabel('VSWR')
        vswrlabel.setStyleSheet("QLabel {color: orange; font: 10px}")
        grid.addWidget(vswrlabel, 6, 3)
        self.spvswrvalue = QtGui.QLabel('-RX-')
        self.spvswrvalue.setStyleSheet("QLabel {color: rgb(255,128,64); font: 14px}")
        self.spvswrvalue.setVisible(True)
        grid.addWidget(self.spvswrvalue, 6, 4)

        # Buttons
        line = QtGui.QFrame()
        line.setFrameShape(QtGui.QFrame.HLine)
        line.setFrameShadow(QtGui.QFrame.Sunken)
        line.setStyleSheet("QFrame {background-color: rgb(126,126,126)}")
        grid.addWidget(line, 7, 0, 1, 5)
        
        buttonHbox = QtGui.QHBoxLayout()
        widget = QtGui.QWidget()
        widget.setLayout(buttonHbox)
        grid.addWidget(widget, 8, 0, 1, 5)
        
        # Edit/Add button
        self.addbtn = QtGui.QPushButton('Add/Update', self)
        self.addbtn.setToolTip('Add/Update to list')
        self.addbtn.resize(self.addbtn.sizeHint())
        self.addbtn.setMinimumHeight(20)
        self.addbtn.setMinimumWidth(100)
        self.addbtn.setEnabled(True)
        buttonHbox.addWidget(self.addbtn)
        self.addbtn.clicked.connect(self.editaddSetpoint)
    
        # Remove button
        self.removebtn = QtGui.QPushButton('Remove', self)
        self.removebtn.setToolTip('Remove selected allocation')
        self.removebtn.resize(self.removebtn.sizeHint())
        self.removebtn.setMinimumHeight(20)
        self.removebtn.setMinimumWidth(100)
        self.removebtn.setEnabled(True)
        buttonHbox.addWidget(self.removebtn)
        self.removebtn.clicked.connect(self.removeSetpoint)
        
        # Push everything up to the top
        nulllabel = QtGui.QLabel('')
        grid.addWidget(nulllabel, 9, 0, 1, 5)
        nulllabel1 = QtGui.QLabel('')
        grid.setRowStretch(9, 1)
        
    def __populateCAT(self, grid):
        """
        Populate the CAT tab
        
        Arguments
            grid    --  grid to populate
            
        """

        # Add instructions
        usagelabel1 = QtGui.QLabel('Usage:')
        usagelabel1.setStyleSheet("QLabel {color: rgb(0,64,128); font: 11px}")
        grid.addWidget(usagelabel1, 0, 0)
        instlabel1 = QtGui.QLabel()
        instructions1 = """
Tranceiver integration:
Set the IP address and port to the rig IP/port for UDP or
Set the COM port and baud rate for serial communication. 
        """
        instlabel1.setText(instructions1)
        instlabel1.setStyleSheet("QLabel {color: rgb(0,64,128); font: 11px}")
        grid.addWidget(instlabel1, 1, 0, 1, 4)
        
        # CAT variants
        catvariantlabel = QtGui.QLabel('Rig')
        grid.addWidget(catvariantlabel, 2, 0)
        self.variantcombo = QtGui.QComboBox()
        self.variantcombo.setMaximumWidth(150)
        for variant in CAT_VARIANTS:
            self.variantcombo.addItem(variant)
        grid.addWidget(self.variantcombo, 2, 1)
        self.variantcombo.activated.connect(self.onVariant)
        self.variantcombo.setCurrentIndex(self.variantcombo.findText(self.__settings[CAT_SETTINGS][VARIANT]))
                
        # Add external IP data
        # IP selection
        extiplabel = QtGui.QLabel('External IP')
        grid.addWidget(extiplabel, 3, 0)
        self.extiptxt = QtGui.QLineEdit()
        self.extiptxt.setToolTip('Sending External IP')
        self.extiptxt.setInputMask('000.000.000.000;_')
        self.extiptxt.setMaximumWidth(100)
        grid.addWidget(self.extiptxt, 3, 1)
        self.extiptxt.editingFinished.connect(self.extipChanged)
        if len(self.__settings[CAT_SETTINGS][NETWORK]) > 0:
            self.extiptxt.setText(self.__settings[CAT_SETTINGS][NETWORK][IP])
        
        # Port selection
        extportlabel = QtGui.QLabel('ExternalPort')
        grid.addWidget(extportlabel, 4, 0)
        self.extporttxt = QtGui.QLineEdit()
        self.extporttxt.setToolTip('Sending Externaal port')
        self.extporttxt.setInputMask('00000;_')
        self.extporttxt.setMaximumWidth(100)
        grid.addWidget(self.extporttxt, 4, 1)
        self.extporttxt.editingFinished.connect(self.extportChanged)
        if len(self.__settings[CAT_SETTINGS][NETWORK]) > 0:
            self.extporttxt.setText(self.__settings[CAT_SETTINGS][NETWORK][PORT])
        
        # Add external CAT data
        # COM Port
        catcomlabel = QtGui.QLabel('COM Port')
        grid.addWidget(catcomlabel, 5, 0)
        self.catcomcombo = QtGui.QComboBox()
        self.catcomcombo.setMaximumWidth(150)
        for port in self.__cat.get_serial_ports():
            self.catcomcombo.addItem(port)
        grid.addWidget(self.catcomcombo, 5, 1)
        self.catcomcombo.activated.connect(self.onCatCom)
        if len(self.__settings[CAT_SETTINGS][SERIAL]) > 0:
            self.catcomcombo.setCurrentIndex(self.catcomcombo.findText(self.__settings[CAT_SETTINGS][SERIAL][COM_PORT]))
        
        # Baud Rate    
        catbaudlabel = QtGui.QLabel('Baud Rate')
        grid.addWidget(catbaudlabel, 6, 0)
        self.catbaudcombo = QtGui.QComboBox()
        for baud in ('1200', '2400', '4800', '9600', '19200','38400'):
            self.catbaudcombo.addItem(baud)
        grid.addWidget(self.catbaudcombo, 6, 1)
        self.catbaudcombo.activated.connect(self.onCatBaud)
        if len(self.__settings[CAT_SETTINGS][SERIAL]) > 0:
            self.catbaudcombo.setCurrentIndex(self.catbaudcombo.findText(self.__settings[CAT_SETTINGS][SERIAL][BAUD_RATE]))
        
        # UDP/ serial select
        catbaudlabel = QtGui.QLabel('Transport')
        grid.addWidget(catbaudlabel, 7, 0)
        self.rbgroup = QtGui.QButtonGroup()
        self.extudprb = QtGui.QRadioButton('Use UDP')
        self.extudprb.setToolTip('CAT via UDP')
        self.extserialrb = QtGui.QRadioButton('Use Serial')
        self.extserialrb.setToolTip('CAT via Serial')
        self.rbgroup.addButton(self.extudprb)
        self.rbgroup.addButton(self.extserialrb)
        grid.addWidget(self.extudprb, 7, 1)
        grid.addWidget(self.extserialrb, 7, 2)
        if self.__settings[CAT_SETTINGS][SELECT] == CAT_UDP:
            self.extudprb.setChecked(True)
        else:
            self.extserialrb.setChecked(True)
        self.rbgroup.buttonClicked.connect(self.onTransport)
    
        # Fill space
        nulllabel = QtGui.QLabel('')
        grid.addWidget(nulllabel, 8, 0, 1, 3)
        nulllabel1 = QtGui.QLabel('')
        grid.addWidget(nulllabel1, 0, 3)
        grid.setRowStretch(8, 1)
        grid.setColumnStretch(3, 1)
        
    def __populateCommon(self, grid, x, y, cols, rows):
    
        """
        Populate the common buttons
        
        Arguments
            grid    --  grid to populate
            x       --  grid x
            y       --  grid y
            cols    --  no of cols to occupy
            rows    --  no of rows to occupy
            
        """
        
        # OK and Cancel buttons in a buttonbox
        self.buttonbox = QtGui.QDialogButtonBox(
            QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal, self)
        grid.addWidget(self.buttonbox, x, y, cols, rows)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)
    
    # ========================================================================================
    # Dialog Management
    # A static method which is called to create and execute the dialog
    # A response constructor
    @staticmethod
    def getConfig(cat_inst, dispatcher_inst, api_inst, main_q, settings, current_loop, callback, parent = None):
        """
        Start a new dialog session
        
        Arguments:
            cat_inst        --  CAT class instance
            dispatcher_inst --  Dispatcher instance
            main_q          --  Main dispatcher queue
            priority_q      --  Priority dispatcher queue
            settings        --  current settings list
            current-loop    --  selected loop
            callback        -- callback here with status messages
            parent          --  parent window
        
        """
        
        # Do dialog
        dialog = ConfigurationDialog(cat_inst, dispatcher_inst, api_inst, main_q, settings, current_loop, callback, parent)
        result = dialog.exec_()
        response = dialog.response(result == QtGui.QDialog.Accepted)
        dialog.cleanup()    
        return response, result == QtGui.QDialog.Accepted
    
    def response(self, result):
        """
        Construct the response to the dialog call
        
        Arguments:
            result  --  True if user clicked OK
            
        """
        
        if result:
            # OK
            # Return new settings
            return self.__settings
        else:
            # Cancel
            # Reinstate the original settings
            self.__settings = self.__orig_settings
            return self.__orig_settings
    
    def cleanup(self):
        """ Cleanup threads """
        
        pass
    
    # ========================================================================================        
    # Event handlers
    
    # ========================================================================================
    # Tab event handler
    def onTab(self, tab):
        """
        User changed tabs
        
        Arguments:
            tab --  new tab index
            
        """
        
        if tab == I_TAB_SETPOINTS:
            # Switched to Setpoints
            # Rejig the interface
            context = "Loop: %s   [Low: %sMHz, High: %sMHz]" % (self.loopnametxt.text(), self.freqlowertxt.text(), self.frequppertxt.text())
            self.contextlabel.setText(context)
            # Set frequency list
            self.freqcombo.clear()
            if len(self.__settings[LOOP_SETTINGS]) > 0:
                for key in sorted(self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_SETPOINTS].keys()):
                    self.freqcombo.addItem(str(key))
            self.freqtxt.setText(self.freqcombo.currentText())
            # Set extension value
            self.__setExtensions()
        elif tab == I_TAB_POT:
            # Reload the loop selection
            self.potloopcombo.clear()
            for key in sorted(self.__settings[LOOP_SETTINGS].keys()):
                self.potloopcombo.addItem(str(key))
            if self.__current_loop != None:
                self.potloopcombo.setCurrentIndex(self.loopcombo.findText(self.__current_loop))
            
    # Arduino event handlers
    def ipChanged(self, ):
        """ User edited IP address """
        
        self.__settings[ARDUINO_SETTINGS][NETWORK][IP] = self.iptxt.text()
        
    def portChanged(self, ):
        """ User edited port address """
        
        self.__settings[ARDUINO_SETTINGS][NETWORK][PORT] = self.porttxt.text()
        
    def refChanged(self):
        """ Set the analog reference """
        
        if self.refcb.isChecked():
            self.__settings[ARDUINO_SETTINGS][ANALOG_REF] = EXTERNAL
        else:
            self.__settings[ARDUINO_SETTINGS][ANALOG_REF] = INTERNAL
        
        self.__q.put((self.__api.setAnalogRef, 'analogref', (self.__settings[ARDUINO_SETTINGS][ANALOG_REF])))
    
    # ========================================================================================
    # Loop event handlers
    def onLoopLoop(self, ):
        """ User selected a new loop """
    
        # Update the UI
        loopName = self.loopcombo.currentText()
        self.potloopcombo.setCurrentIndex(self.loopcombo.findText(loopName))
        self.loopnametxt.setText(loopName) 
        self.freqlowertxt.setText(self.__settings[LOOP_SETTINGS][loopName][I_FREQ][I_LOWER])
        self.frequppertxt.setText(self.__settings[LOOP_SETTINGS][loopName][I_FREQ][I_UPPER])
        self.relay1cb.setChecked(self.__settings[LOOP_SETTINGS][loopName][I_RELAYS][0])
        self.relay2cb.setChecked(self.__settings[LOOP_SETTINGS][loopName][I_RELAYS][1])
        self.relay3cb.setChecked(self.__settings[LOOP_SETTINGS][loopName][I_RELAYS][2])
        self.relay4cb.setChecked(self.__settings[LOOP_SETTINGS][loopName][I_RELAYS][3])
        self.slowsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_PARAMS][I_SLOW])
        self.medsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_PARAMS][I_MEDIUM])
        self.fastsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_PARAMS][I_FAST])
        self.nudgesb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_PARAMS][I_NUDGE])
        if self.__settings[LOOP_SETTINGS][loopName][I_OFFSETS][I_LOW_FREQ] != None:
            self.lfextsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_OFFSETS][I_LOW_FREQ])
        else:
            self.lfextsb.setValue(100)
        if self.__settings[LOOP_SETTINGS][loopName][I_OFFSETS][I_HIGH_FREQ] != None:
            self.hfextsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_OFFSETS][I_HIGH_FREQ])
        else:            
            self.hfextsb.setValue(0)
            
        # Set the validator for these loop parameters
        self.freqtxt.setValidator(FreqValidator(self, self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_FREQ][I_LOWER], self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_FREQ][I_UPPER]))        
        
    def editLoop(self, ):
        """ Add new loop parameters to the configuration """
        
        if self.loopnametxt.text() not in self.__settings[LOOP_SETTINGS]:
            self.__settings[LOOP_SETTINGS][self.loopnametxt.text()] = [[], [], [], [], {}, []]
        
        self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_POT] =  [self.mincapsb.value(), self.maxcapsb.value()]
        self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_FREQ] =  [self.freqlowertxt.text(), self.frequppertxt.text()]
        self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_RELAYS] =  [self.relay1cb.isChecked(), self.relay2cb.isChecked(), self.relay3cb.isChecked(), self.relay4cb.isChecked()]
        self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_SETPOINTS] = {}
        self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_PARAMS] = [self.slowsb.value(), self.medsb.value(), self.fastsb.value(), self.nudgesb.value()]
        self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_OFFSETS] = [int(self.lfextsb.value()) ,int(self.hfextsb.value())]
                                
        self.loopcombo.clear()
        for key in sorted(self.__settings[LOOP_SETTINGS].keys()):
            self.loopcombo.addItem(str(key))
        self.loopcombo.setCurrentIndex(self.loopcombo.findText(self.loopnametxt.text()))
           
    def removeLoop(self, ):
        """ Remove the selected loop """
        
        del self.__settings[LOOP_SETTINGS][self.loopnametxt.text()]
        thisloop = self.loopcombo.currentIndex()
        self.loopcombo.removeItem(thisloop)
        self.potloopcombo.removeItem(thisloop)
        loopName = self.loopcombo.currentText()
        if len(loopName) > 0:
            self.loopnametxt.setText(loopName) 
            self.freqlowertxt.setText(self.__settings[LOOP_SETTINGS][loopName][I_PARAMS][I_LOWER])
            self.frequppertxt.setText(self.__settings[LOOP_SETTINGS][loopName][I_PARAMS] [I_UPPER])
            self.relay1cb.setChecked(self.__settings[LOOP_SETTINGS][loopName][I_RELAYS][0])
            self.relay2cb.setChecked(self.__settings[LOOP_SETTINGS][loopName][I_RELAYS][1])
            self.relay3cb.setChecked(self.__settings[LOOP_SETTINGS][loopName][I_RELAYS][2])
            self.relay4cb.setChecked(self.__settings[LOOP_SETTINGS][loopName][I_RELAYS][3])
            self.slowsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_PARAMS][I_SLOW])
            self.medsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_PARAMS][I_MEDIUM])
            self.fastsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_PARAMS][I_FAST])
            self.nudgesb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_PARAMS][I_NUDGE])
            if self.__settings[LOOP_SETTINGS][loopName][I_OFFSETS][I_LOW_FREQ] != None:
                self.lfextsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_OFFSETS][I_LOW_FREQ])
            else:
                self.lfextsb.setValue(0)
            if self.__settings[LOOP_SETTINGS][loopName][I_OFFSETS][I_HIGH_FREQ] != None:
                self.hfextsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_OFFSETS][I_HIGH_FREQ])
            else:
                self.hfextsb.setValue(100)
            if self.__settings[LOOP_SETTINGS][loopName][I_POT][I_MINCAP] != None:
                self.mincapsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_POT][I_MINCAP])
            else:
                self.mincapsb.setValue(0)
            if self.__settings[LOOP_SETTINGS][loopName][I_POT][I_MAXCAP] != None:
                self.maxcapsb.setValue(self.__settings[LOOP_SETTINGS][loopName][I_POT][I_MAXCAP])
            else:
                self.maxcapsb.setValue(1023)
        else:
            # Set defaults
            self.mincapsb.setValue(0)
            self.maxcapsb.setValue(1023)
            self.loopnametxt.setText('') 
            self.freqlowertxt.setText('')
            self.frequppertxt.setText('')
            self.macrosb.setValue(1)
            self.slowsb.setValue(MOTOR_SLOW)
            self.mediumsb.setValue(MOTOR_MEDIUM)
            self.fastsb.setValue(MOTOR_FAST)
            self.nudgesb.setValue(MOTOR_NUDGE)
            self.lfextsb.setValue(0)
            self.hfextsb.setValue(100)
    
    def onPotLoop(self):
        """ Update the min and max cap settings for the selected loop """
        
        thisloop = self.potloopcombo.currentText()
        if self.__settings[LOOP_SETTINGS][thisloop][I_POT][I_MINCAP] != None:
            self.mincapsb.setValue(self.__settings[LOOP_SETTINGS][thisloop][I_POT][I_MINCAP])
        else:
            self.mincapsb.setValue(0)
        if self.__settings[LOOP_SETTINGS][thisloop][I_POT][I_MAXCAP] != None:
            self.maxcapsb.setValue(self.__settings[LOOP_SETTINGS][thisloop][I_POT][I_MAXCAP])
        else:
            self.maxcapsb.setValue(1023)
        
    def __lfTune(self, ):
        """ Find the extension % for the lower band edge """
        
        reply = QtGui.QMessageBox.question( None, 'Band Setpoints',
                                            "TX(5-10 watts) near the lower band edge... Continue?",
                                            QtGui.QMessageBox.Yes | 
                                            QtGui.QMessageBox.No,
                                            QtGui.QMessageBox.No)
    
        if reply == QtGui.QMessageBox.Yes:            
            if self.__vswr[0] > 0:
                self.__lfTuneInProgress = True
                self.__spTuneInProgress = False
                self.__hfTuneInProgress = False
                self.__q.put((self.__api.setHighSetpoint, 'sethighsetpoint', (0)))
                self.__q.put((self.__api.setLowSetpoint, 'setlowsetpoint', (100)))
                self.__q.put((self.__api.tune, 'tune', ()))
            else:
                # No forward power
                QtGui.QMessageBox.information(self, 'Band Setpoints', 'No RF power detected, please try again.', QtGui.QMessageBox.Ok)
    
    def __lfAbortTune(self):
        """ Abort tuning """
        
        self.__p_q.put((self.__api.stop, 'stop', ()))
        
    def __hfTune(self, ):
        """ Find the extension % for the upper band edge """
            
        reply = QtGui.QMessageBox.question( None, 'Band Setpoints',
                                            "TX(5-10 watts) near the upper band edge... Continue?",
                                            QtGui.QMessageBox.Yes | 
                                            QtGui.QMessageBox.No,
                                            QtGui.QMessageBox.No)
    
        if reply == QtGui.QMessageBox.Yes:
            if self.__vswr[0] > 0:
                self.__hfTuneInProgress = True
                self.__spTuneInProgress = False
                self.__lfTuneInProgress = False
                self.__q.put((self.__api.setHighSetpoint, 'sethighsetpoint', (0)))
                self.__q.put((self.__api.setLowSetpoint, 'setlowsetpoint', (100)))
                self.__q.put((self.__api.tune, 'tune', ()))
            else:
                # No forward power
                QtGui.QMessageBox.information(self, 'Band Setpoints', 'No RF power detected, please try again.', QtGui.QMessageBox.Ok)    
    
    def __hfAbortTune(self):
        """ Abort tuning """
        
        self.__p_q.put((self.__api.stop, 'stop', ()))

    # ========================================================================================
    # Pot event handlers
    def __maxCapChanged(self, value):
        """ Value changed for max capacity limit """
        
        self.__settings[LOOP_SETTINGS][self.potloopcombo.currentText()][I_POT][I_MAXCAP] = value
    
    def __minCapChanged(self, value):
        """ Value changed for min capacity limit """
        
        self.__settings[LOOP_SETTINGS][self.potloopcombo.currentText()][I_POT][I_MINCAP] = value
        
    # ========================================================================================   
    # Setpoint event handlers
    def onFreqSetpoint(self, sel): 
        """
        User selected an existing frequency
        
        Arguments:
            sel --  selected offset
        
        """
        
        # Update the steps associated with the frequency
        self.freqtxt.setText(self.freqcombo.currentText())
        offset = self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_SETPOINTS][self.freqcombo.currentText()]
        self.spextvalue.setValue(offset)
        self.__extension = 0
    
    def removeSetpoint(self):
        """ Remove the currently selected frequency """
        
        del self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_SETPOINTS][self.freqcombo.currentText()]
        self.freqcombo.removeItem(self.freqcombo.currentIndex())
        # Set the new frequency list
        if len(self.freqcombo.currentText()) > 0:
            self.freqtxt.setText(self.freqcombo.currentText())
        else:
            self.freqtxt.setText('')
        # Set the extension range and value
        self.__setExtensions()
            
    def tuneSetpoint(self):
        """ Tune for lowest VSWR for the frequency """
        
        self.__spTuneInProgress = True
        self.__lfTuneInProgress = False
        self.__hfTuneInProgress = False
        if self.__vswr[0] > 0:
            self.__q.put((self.__api.tune, 'tune', ()))
        else:
            # No forward power
            self.__statusCallback ('Please key TX!')
            
    def editaddSetpoint(self):
        """ Edit or Add the current setpoint params """
        
        self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_SETPOINTS][self.freqtxt.text()] = self.spextvalue.value()
        self.freqcombo.clear()
        for key in sorted(self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_SETPOINTS].keys()):
            self.freqcombo.addItem(str(key))
        self.freqcombo.setCurrentIndex(self.freqcombo.findText(self.freqtxt.text()))        
    
    def autoSetpoint(self, ):
        """
        Perform a automatic tune from low to high antenna frequency span
        with the given KHz step size. For each step populate a setpoint.
        Note: this requires CAT to be operational and the rig to be TX
        ready. This will transmit so use low power 2-5 watts and do this
        when the band is quiet.
        """
        
        reply = QtGui.QMessageBox.question( None, 'Auto-Configure',
                                            "This will remove all existing setpoints. Continue?",
                                            QtGui.QMessageBox.Yes | 
                                            QtGui.QMessageBox.No,
                                            QtGui.QMessageBox.No)
    
        if reply == QtGui.QMessageBox.Yes:
            # Use says yes, so cleardown everything
            self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_SETPOINTS] = {}
            self.freqcombo.clear()
            self.freqtxt.setText('')
            self.__setExtensions()
            # Get the frequency limits in KHz
            lower_freq = int(float(self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_FREQ][I_LOWER])*1000.0)
            upper_freq = int(float(self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_FREQ][I_UPPER])*1000.0)
            
            # Create the setpoint instance, lives for duration only
            # Runs on its own thread and will callback to self.__setpoint_callback when ready to tune.
            self.__auto_setpoint = autosetpoint.AutoSetpoint(self.__cat, lower_freq, upper_freq, self.stepsb.value(), self.__setpoint_callback)
            self.__auto_setpoint.start()
            self.__auto_setpoint.do_cycle()
    
    # ========================================================================================
    # CAT event handlers
    def onVariant(self, ):
        """ User selected a variant """
        
        self.__settings[CAT_SETTINGS][VARIANT] = CAT_VARIANTS[self.variantcombo.currentIndex()]
    
    def extipChanged(self, ):
        """ User edited CAT IP address """
        
        self.__settings[CAT_SETTINGS][NETWORK][IP]  = self.extiptxt.text()
        
    def extportChanged(self, ):
        """ User edited CAT port address """
        
        self.__settings[CAT_SETTINGS][NETWORK][PORT] = self.extporttxt.text()

    def onCatCom(self, ):
        """ User edited CAT COM port """
        
        self.__settings[CAT_SETTINGS][SERIAL][COM_PORT]  = self.catcomcombo.currentText()
    
    def onCatBaud(self, ):
        """ User edited CAT baud rate """
        
        self.__settings[CAT_SETTINGS][SERIAL][BAUD_RATE]  = self.catbaudcombo.currentText()
    
    def onTransport(self, ):
        """ User changed transport """
        
        if self.extudprb.isChecked():
            self.__settings[CAT_SETTINGS][SELECT] = CAT_UDP
        else:
            self.__settings[CAT_SETTINGS][SELECT] = CAT_SERIAL
    
    # ========================================================================================       
    # Callback handlers
    def __respCallback(self, message):
        
        """
        Callback from status messages. Note that this is not called
        from the main thread and therefore we just set a status which
        is picked up in the idle loop for display.
        
        Arguments:
            message --  text to drive the status messages
            
        """
        
        try:
            if 'success' in message:
                pass 
            elif 'failure' in message:
                # Error, so reset
                _, reason = message.split(':')
                self.__statusCallback('Failed : %s' % (reason))
                self.__spTuneInProgress = False
                self.__lfTuneInProgress = False
                self.__hfTuneInProgress = False
            elif 'offline' in message:
                self.__spTuneInProgress = False
                self.__lfTuneInProgress = False
                self.__hfTuneInProgress = False
                self.__statusCallback('Failed: Controller is offline!!')
            elif 'tx' in message:
                # TX status request
                _, status = message.split(':')
                if status == 'on':
                    self.__isTX = True
                elif status == 'off':
                    self.__isTX = False
        except Exception as e:
            self.__statusCallback('**Fatal: %s**' % (str(e)))    

    def __executionCallback(self, message):
        
        """
        Callback from status messages. Note that this is not called
        from the main thread and therefore we just set a status which
        is picked up in the idle loop for display.
        
        Arguments:
            message --  text to drive the status messages
            
        """
        
        try:
            # This comes from the command execution thread and is batch related
            if 'beginbatch' in message:
                # When we start executing commands from the q
                self.__running = True
            elif 'endbatch' in message:
                # When we finish executing all commands from the q
                self.__running = False
            elif 'tuned' in message:
                if self.__lfTuneInProgress:
                    self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_OFFSETS][0] = self.__extension
                if self.__hfTuneInProgress:
                    self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_OFFSETS][1] = self.__extension
            elif 'fatal' in message:
                # Oops
                _, reason = message.split(':')
                self.__statusCallback('**Fatal: %s**' % (reason))
                raise RuntimeError(reason)
        except Exception as e:
            self.__statusCallback('**Fatal: %s**' % (str(e)))
            
    def __evntCallback(self, message):
        
        """
        Callback for event messages. Note that this is not called
        from the main thread and therefore we just set a status which
        is picked up in the idle loop for display.
        Qt calls MUST be made from the main thread.
        
        Arguments:
            message --  text to drive the event messages
            
        """
            
        try:
            if 'progress' in message:
                # Progress messages
                _, progress = message.split(':')
                self.__progress = (100 - int(progress))
            elif 'vswr' in message:
                _, forward, reverse = message.split(':')
                self.__vswr = (float(forward), float(reverse))
                self.__evntForwardCallback(message)
            elif 'pot' in message:
                _, self.__realExtension, self.__extension = message.split(':')
                self.__extension = int(self.__extension)
        except Exception as e:
            self.__statusMessage = 'Exception getting event status!'
    
    def __setpoint_callback(self, state, freq):
        
        """
        Callback from auto setpoint when each setpoint sequence
        is ready for tuning.
        
        Arguments:
            state   --  AUTO_NEXT | AUTO_COMPLETE
            freq    --  Frequency of this setpoint
            
        """
        
        if state == AUTO_PROMPT_USER:
            self.__ready_to_go = AUTO_NONE
            self.__prompt_user = True
            while self.__ready_to_go == AUTO_NONE:
                sleep(1)
            return self.__ready_to_go
        elif state == AUTO_NEXT:
            # Not finished yet
            # Tell idle to add a setpoint
            self.__addSetpoint = [True, freq]
            # Wait for this setpoint to complete
            while self.__addSetpoint[0]: sleep(1)
            # Do another auto cycle
            sleep(2)    # Let the user see the SWR
            self.__auto_setpoint.do_cycle()
    
    # ========================================================================================                
    # Idle time processing
    def __idleProcessing(self):
        
        """
        Idle processing.
        Called every 100ms single shot
        
        """
        
        # Tuning for a setpoint
        if self.__running:
            if self.__spTuneInProgress or self.__lfTuneInProgress or self.__hfTuneInProgress:
                self.progressbar.setValue(self.__progress)
                self.__showVSWR()
                self.__showExtension()
        else:
            self.progressbar.reset()
            self.__showVSWR()
            self.__showExtension()
        
        # Adding a setpoint
        if self.__addSetpoint[0]:
            if self.__vswr[0] > 0:
                self.freqtxt.setText(str(float(self.__addSetpoint[1])/1000.0))
                # Tune the loop
                self.tuneSetpoint()
                # When complete add a setpoint
                while self.__spTuneInProgress:
                    self.progressbar.setValue(self.__progress)
                    sleep(0.1)
                self.editaddSetpoint()
                self.__showVSWR()
                self.__showExtension()
            else:
                # No forward power
                self.__statusCallback ('Please key TX!')
                QtGui.QMessageBox.information(self, 'No RF!', 'Please restart auto-configure and key the TX when requested.', QtGui.QMessageBox.Ok)
            self.__addSetpoint[0] = False
            self.__addSetpoint[1] = None
         
        # Prompt user
        if self.__prompt_user:
            self.__prompt_user = False
            msgBox = QtGui.QMessageBox(None)
            msgBox.setWindowTitle('Auto-Configure')
            msgBox.setText("Key transmitter and press 'Continue' or\npress 'Skip' to skip this setpoint.\nPress 'Finish' to exit auto-config.")
            msgBox.addButton(QtGui.QPushButton('Continue'), QtGui.QMessageBox.AcceptRole)
            msgBox.addButton(QtGui.QPushButton('Skip'), QtGui.QMessageBox.RejectRole)
            msgBox.addButton(QtGui.QPushButton('Finish'), QtGui.QMessageBox.ResetRole)
            msgBox.exec_()
            role = msgBox.buttonRole(msgBox.clickedButton())
            if role == QtGui.QMessageBox.AcceptRole:
                self.__ready_to_go = AUTO_CONTINUE
            elif role == QtGui.QMessageBox.RejectRole:
                self.__ready_to_go = AUTO_SKIP
            else:
                self.__ready_to_go = AUTO_ABORT
                    
        # Adjust loop buttons
        if len(self.__settings[LOOP_SETTINGS]) > 0:
            self.loopremovebtn.setEnabled(True)
        else:
            self.loopremovebtn.setEnabled(False)
        if  len(self.loopnametxt.text()) > 0 and \
            len(self.freqlowertxt.text()) > 1 and \
            len(self.frequppertxt.text()) > 1 and \
            self.slowsb.value() > 0 and \
            self.medsb.value() > 0 and \
            self.fastsb.value() > 0 and \
            self.nudgesb.value() > 0:
            self.loopeditbtn.setEnabled(True)
        else:
            self.loopeditbtn.setEnabled(False)
        
        # Adjust setpoint buttons
        if self.freqcombo.count() > 0:
            self.removebtn.setEnabled(True)
        else:
            self.removebtn.setEnabled(False)
        if len(self.freqtxt.text()) > 1:
            self.tunebtn.setEnabled(True)
            if self.spextvalue.value() > 0:
                self.addbtn.setEnabled(True)
            else:
                self.addbtn.setEnabled(False)
        else:
            self.tunebtn.setEnabled(False)
            self.addbtn.setEnabled(False)
        
        QtCore.QTimer.singleShot(100, self.__idleProcessing)
    
    # ========================================================================================
    # Helpers
    def __showVSWR(self):
        """ Calculate and show the VSWR reading """
        
        vswrtxt = ""
        
        if self.__vswr[0] == 0.0:
            # No forward power
            vswrtxt = "-RX-"
        else:
            # Do an approximate lookup to get the VSWR
            ratio = vswr.getVSWR(self.__vswr[0], self.__vswr[1])           
            if ratio != None:
                vswrtxt = "%.1f:1" % ratio
            else:
                vswrtxt = "infinity"
        
        # Set the appropriate field
        if self.__spTuneInProgress:
            self.spvswrvalue.setText(vswrtxt)            
        elif self.__lfTuneInProgress:
            self.lfvswrvalue.setText(vswrtxt)
        elif self.__hfTuneInProgress:        
            self.hfvswrvalue.setText(vswrtxt)
    
    def __showExtension(self):
        """ Show extension reading as appropriate """
        
        if self.__spTuneInProgress:
            self.spextvalue.setValue(self.__extension)
        elif self.__lfTuneInProgress:
            self.lfextsb.setValue(self.__extension)
        elif self.__hfTuneInProgress:
            self.hfextsb.setValue(self.__extension)
            
    def __serial_ports(self):
        """ Lists serial port names """
        
        result = []
        ports = []
        if sys.platform.startswith('win'):
            ports = ['COM%s' % (i + 1) for i in range(4,5)]
        elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
            # this excludes your current terminal "/dev/tty"
            ports = glob.glob('/dev/tty[A-Za-z]*')
        elif sys.platform.startswith('darwin'):
            ports = glob.glob('/dev/tty.*')
    
        for port in ports:
            try:
                s = serial.Serial(port)
                s.close()
                result.append(port)
            except (OSError, serial.SerialException):
                pass
        return result

    def __isInt(self, value):
        """ Test for integer """
        
        try:
            ivalue = int(value)
            return True
        except Exception as e:
            return False
    
    def __setExtensions(self):
        """ Set the setpoint extension range and value """
        
        self.spextvalue.setRange(0, 100)
        self.spextvalue.setValue(0)  
        if len(self.__settings[LOOP_SETTINGS]) > 0:
            if  self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_OFFSETS][I_LOW_FREQ] != None and\
                self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_OFFSETS][I_HIGH_FREQ] != None:
                # We have valid settings for the extension range on this band
                self.spextvalue.setRange(self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_OFFSETS][I_HIGH_FREQ], self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_OFFSETS][I_LOW_FREQ])
                if len(self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_SETPOINTS]) > 0:
                    # We have a valid setting for the extension value
                    self.spextvalue.setValue(self.__settings[LOOP_SETTINGS][self.loopnametxt.text()][I_SETPOINTS][self.freqcombo.currentText()])
            
# ========================================================================================
# Validator classes
# Frequency entry validator
class FreqValidator(QtGui.QDoubleValidator):
    
    def __init__(self, parent, lowFreq, highFreq):
        """ Constructor """
        
        super(FreqValidator, self).__init__(parent)
        # Frequencies are floats
        self.__lowMHz = float(lowFreq)
        self.__highMHz = float(highFreq)
        
    def validate(self, text, position):
        """
        Validate override
        
        Arguments:
            text        --  current text in control
            position    --  character position of last entered character
            
        """
        
        try:
            # Do the easy checks
            if len(text) == 0:
                # User deleted everything which has to be a valid entry
                return (QtGui.QValidator.Intermediate, text, position)
            if '.' in text:
                # Entry is a float value
                n,m = text.split('.')
                # Only allow 3 significant digits
                if len(m) > 3:
                    # > 3 significant digits
                    return (QtGui.QValidator.Invalid, text, position)
                # Get the float
                value = float(text)
            else:
                # Must be an integer value, so convert to a float
                #text = text + '.0'
                value = float(int(text))
            # Are we within the valid range
            if value >= self.__lowMHz and value <= self.__highMHz:
                # Yes so fully valid
                return (QtGui.QValidator.Acceptable, text, position)
            elif value > self.__highMHz:
                return (QtGui.Qalidator.Invalid, text, position)
            
            # Now the partial entry checks
            # We need to check for valid values that are less than the low value
            # e.g.
            #   if low is 1.8 then 1 is interim,
            #   1.7 is invalid because it can only ever be 1.799
            #   if low id 14.0 then 
            decEnt, intEnt = math.modf(value)
            decLow, intLow = math.modf(self.__lowMHz)
            if intEnt <= intLow and decEnt == 0.0:
                return (QtGui.QValidator.Intermediate, text, position)
        except Exception as e:
            #print(str(e), traceback.print_exc())
            return (QtGui.QValidator.Invalid, text, position)
        
        return (QtGui.QValidator.Invalid, text, position)
                    
# Degree offset limits validator
class LimitsValidator(QtGui.QIntValidator):
    
    def __init__(self, parent, lowOffset, highOffset):
        """ Constructor """
        
        super(LimitsValidator, self).__init__(parent)
        # Offsets are ints
        self.__low = int(lowOffset)
        self.__high = int(highOffset)
        
    def validate(self, text, position):
        """
        Validate override
        
        Arguments:
            text        --  current text in control
            position    --  character position of last entered character
            
        """
        
        try:
            if len(text) == 0:
                # User deleted everything which has to be a valid entry
                return (QtGui.QValidator.Intermediate, text, position)   
            else:
                value = int(text)
                if value >= self.__low and value <= self.__high:
                    return (QtGui.QValidator.Acceptable, text, position)
                elif value < self.__low:
                    return (QtGui.QValidator.Intermediate, text, position)
                else:
                    return (QtGui.QValidator.Invalid, text, position)
        except Exception as e:
            return (QtGui.QValidator.Invalid, text, position)
        
        return (QtGui.QValidator.Invalid, text, position)
    