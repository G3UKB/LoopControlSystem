#!/usr/bin/env python
#
# magui.py
#
# UI for the Mag Loop application
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
import string
from time import sleep
import socket
import queue
import math
import threading
import traceback
from PyQt4 import QtCore, QtGui

sys.path.append(os.path.join('..', '..'))
sys.path.append(os.path.join('..','..','..','Common','trunk','python'))

# Application imports
from common.defs import *
#from controller.hw_interface import control_if
import tracking
import configurationdialog
from controller.hw_interface import dispatcher
from common import vswr
from common import persist
#from common import cat
# Common files
import cat
import loop_control_if

"""
GUI UI for loop controller
"""
class LoopUI(QtGui.QMainWindow):
    
    def __init__(self, qt_app):
        """
        Constructor
        
        Arguments:
            qt_app  --  the Qt appplication object
            
        """
        
        super(LoopUI, self).__init__()
        
        self.__qt_app = qt_app
        
        # Set the back colour
        palette = QtGui.QPalette()
        #palette.setColor(QtGui.QPalette.Background,QtGui.QColor(74,108,117,255))
        palette.setColor(QtGui.QPalette.Background,QtGui.QColor(195,195,195,255))
        self.setPalette(palette)
        
        # Class variables
        self.__settings = {}                # See common.py DEFAULT_SETTINGS for structure
        self.__running = False              # True when commands executing
        self.__progress = 0                 # %complete
        self.__vswr = [0.0,0.0]             # Relative VSWR reading
        self.__realExtension = 0            # Pot real analog value (0 - 1023)
        self.__virtualExtension = 0         # Normalised analog value (0-100%)
        self.__statusMessage = ''           # Status bar message
        self.__startup = False              # True if startup active
        self.__enable_tracking = False      # True if RX frequency tracking enabled
        self.__direction = FORWARD          # Requested direction
        self.__speed = None                 # Current speed
        self.__absoluteExtension = None     # Tracking info
        self.__currentFreq = None           # ditto
        self.__cat_timer = CAT_TIMER        # to start CAT if not running
        self.__tickcount = 0                # Counter to clear status messages in idle time
        self.__lastStatus = ''              # Holds last status message, used to clear status
        self.__currentDirection = FORWARD   # Current direction, can be different from requested direction
        self.__pollcount = 0                # Connected poll counter
        self.__connected = False            # True if connected to the business end
        self.__relays_set = False           # True when initial relay state set
        self.__isTX = False                 # True if TX
        self.__autoTuneState = False        # Auto-tune off
       
        # Retrieve settings and state ( see common.py DEFAULTS for strcture)
        self.__settings = persist.getSavedCfg(SETTINGS_PATH)
        if self.__settings == None: self.__settings = DEFAULT_SETTINGS
        self.__state = persist.getSavedCfg(STATE_PATH)
        if self.__state == None: self.__state = DEFAULT_STATE
        
        # Create the Loop API
        self.__api = loop_control_if.ControllerAPI(self.__settings[ARDUINO_SETTINGS][NETWORK], self.__respCallback, self.__evntCallback)
        
        # Create the command execution thread
        # A command queue with max 20 items
        self.__q = queue.Queue(20)
        # Create and start the thread
        self.__executeThrd = dispatcher.CommandExecutionThrd(self.__q, self.__executeCallback)
        self.__executeThrd.start()
        # and the priority thread
        self.__p_q = queue.Queue(20)
        self.__priorityThrd = dispatcher.CommandPriorityThrd(self.__p_q)
        self.__priorityThrd.start()
        
        # Create the CAT interface
        self.__cat_running = False
        self.__cat = cat.CAT(self.__settings[CAT_SETTINGS][VARIANT], self.__settings[CAT_SETTINGS])
        if self.__cat.start_thrd():
            self.__cat_running = True
                
        # Get the current loop
        self.__loop = None
        if self.__state[SELECTED_LOOP] != None:
            # Use the last selected loop
            self.__loop = self.__state[SELECTED_LOOP]
        elif len(self.__settings[LOOP_SETTINGS]) > 0:
            # Use the first loop
            self.__loop = sorted(self.__settings[LOOP_SETTINGS].keys())[0]
            
        # Create the Tracking instance
        self.__tracking = tracking.Tracking(self.__cat, self.__settings[CAT_SETTINGS][VARIANT], self.__settings, self.__loop, self.__track_callback)
        self.__tracking.start()
            
        # Initialise the GUI
        self.initUI()
        
        # Show the GUI
        self.show()
        self.repaint()
        
        # Startup active
        self.__startup = True
        
        # Start idle processing
        QtCore.QTimer.singleShot(IDLE_TICKER, self.__idleProcessing)
    
    def run(self, ):
        """ Run the application """
        
        # Check if we need configuring
        if len(self.__settings[LOOP_SETTINGS]) > 0:
            
            # Wait until on-line or timeout
            timeout = 10
            self.__connected = False
            while (True):
                if self.__api.is_online():
                    self.__connected = True
                    break
                else:
                    sleep(1)
                    timeout -= 1
                    if timeout <= 0:
                        # Problem with the controller
                        print('Timeout waiting for controller to come on line!')
                        break
            
            if self.__connected:
                # Set the analog reference
                self.__q.put((self.__api.setAnalogRef, 'analogref', (self.__settings[ARDUINO_SETTINGS][ANALOG_REF])))
                
                # Set the Capacitor limits
                if self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_POT][I_MAXCAP] != None and self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_POT][I_MINCAP] != None:
                    self.__q.put((self.__api.setCapMaxSetpoint, 'capmaxsetpoint', (self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_POT][I_MAXCAP])))
                    self.__q.put((self.__api.setCapMinSetpoint, 'capminsetpoint', (self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_POT][I_MINCAP])))
                    
                # Set the loop limits
                try:
                    lowSetpoint = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_OFFSETS][I_LOW_FREQ]
                    if lowSetpoint != None: self.__q.put((self.__api.setLowSetpoint, 'setlowsetpoint', (lowSetpoint)))
                except:
                    pass
                try:
                    highSetpoint = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_OFFSETS][I_HIGH_FREQ]
                    if highSetpoint != None: self.__q.put((self.__api.setHighSetpoint, 'sethighsetpoint', (highSetpoint)))
                except:
                    pass
                
                # Set speed
                try:
                    if self.speedslow.isChecked():
                        speed = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_PARAMS][I_SLOW]
                    elif self.speedmed.isChecked():
                        speed = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_PARAMS][I_MED]
                    elif self.speedfast.isChecked():
                        speed = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_PARAMS][I_FAST]
                    self.__q.put((self.__api.speed, 'speed', (speed)))
                except:
                    pass
                
        # Returns when application exists
        r = self.__qt_app.exec_()
        
        # Terminate threads
        self.__cat.terminate()
        self.__tracking.terminate()
        self.__tracking.join()
        self.__api.terminate()
        if self.__executeThrd.isAlive():
            self.__executeThrd.terminate()
            self.__executeThrd.join()
        if self.__priorityThrd.isAlive():
            self.__priorityThrd.terminate()
            self.__priorityThrd.join()        
        
        return r
    
    #==========================================================================================       
    # UI initialisation and window event handlers
    def initUI(self):
        """ Configure the GUI interface """
        
        #======================================================================================
        # Configure the status bar
        self.statusBar = QtGui.QStatusBar()
        self.setStatusBar(self.statusBar)
        # Right align a permanent status indicator
        self.statusIndLbl = QtGui.QLabel()
        self.statusIndLbl.setText('')       
        self.statusBar.addPermanentWidget(self.statusIndLbl)
        # Set the style sheets
        self.statusIndLbl.setStyleSheet("QLabel {color: rgb(232,75,0); font: 14px}")
        self.statusBar.setStyleSheet("QStatusBar::item{border: none;}")       
        
        #======================================================================================
        # Arrange window
        self.move(self.__state[WINDOW][X_POS], self.__state[WINDOW][Y_POS])
        self.setWindowTitle('Loop Controller')
        QtGui.QToolTip.setFont(QtGui.QFont('SansSerif', 10))
        
        #======================================================================================
        # Configure the menu bar
        aboutAction = QtGui.QAction(QtGui.QIcon('about.png'), '&About', self)        
        aboutAction.setShortcut('Ctrl+A')
        aboutAction.setStatusTip('About')
        aboutAction.triggered.connect(self.about)
        exitAction = QtGui.QAction(QtGui.QIcon('exit.png'), '&Exit', self)        
        exitAction.setShortcut('Ctrl+Q')
        exitAction.setStatusTip('Quit application')
        exitAction.triggered.connect(self.quit)
        configAction = QtGui.QAction(QtGui.QIcon('config.png'), '&Configuration', self)        
        configAction.setShortcut('Ctrl+C')
        configAction.setStatusTip('Configure controller')
        configAction.triggered.connect(self.__configEvnt)
        
        menubar = self.menuBar()
        fileMenu = menubar.addMenu('&File')
        fileMenu.addAction(exitAction)
        configMenu = menubar.addMenu('&Edit')
        configMenu.addAction(configAction)
        helpMenu = menubar.addMenu('&Help')
        helpMenu.addAction(aboutAction)
        
        #======================================================================================
        # Set overall layout
        w = QtGui.QWidget()
        self.setCentralWidget(w)
        grid = QtGui.QGridLayout()
        w.setLayout(grid)
        
        #======================================================================================     
        # Loop selection
        looplabel = QtGui.QLabel('Select Loop')
        grid.addWidget(looplabel, 1, 0)
        self.loopcombo = QtGui.QComboBox()
        for key in sorted(self.__settings[LOOP_SETTINGS].keys()):
            self.loopcombo.addItem(str(key))
        self.loopcombo.setCurrentIndex(self.loopcombo.findText(self.__loop))
        grid.addWidget(self.loopcombo, 1, 1, 1, 3)
        self.loopcombo.setToolTip("Select working loop")
        self.loopcombo.activated.connect(self.__onLoop)
        
        #======================================================================================     
        # Action buttons
        # Configure button group
        self.buttongroupbox = QtGui.QGroupBox('Action')
        buttonvbox = QtGui.QVBoxLayout()
        buttonvbox.setAlignment(QtCore.Qt.AlignTop)
        # Configure nudge buttons
        # Forward
        self.nudgefwdbtn = QtGui.QPushButton('Nudge Fwd', self)
        self.nudgefwdbtn.setToolTip('Move fwd nudge %')
        self.nudgefwdbtn.resize(self.nudgefwdbtn.sizeHint())
        self.nudgefwdbtn.setMinimumHeight(20)
        self.nudgefwdbtn.setEnabled(True)
        buttonvbox.addWidget(self.nudgefwdbtn)
        self.nudgefwdbtn.clicked.connect(self.__nudgeFwd)
        # Reverse
        self.nudgerevbtn = QtGui.QPushButton('Nudge Rev', self)
        self.nudgerevbtn.setToolTip('Move rev nudge %')
        self.nudgerevbtn.resize(self.nudgerevbtn.sizeHint())
        self.nudgerevbtn.setMinimumHeight(20)
        self.nudgerevbtn.setEnabled(True)
        buttonvbox.addWidget(self.nudgerevbtn)
        self.nudgerevbtn.clicked.connect(self.__nudgeRev)
        # Configure goto button
        self.gotobtn = QtGui.QPushButton('GoTo', self)
        self.gotobtn.setToolTip('GoTo freq or % extension')
        self.gotobtn.resize(self.gotobtn.sizeHint())
        self.gotobtn.setMinimumHeight(20)
        self.gotobtn.setEnabled(True)
        buttonvbox.addWidget(self.gotobtn)
        self.gotobtn.clicked.connect(self.__goto)
        # Configure stop button
        self.stopbtn = QtGui.QPushButton('Stop', self)
        self.stopbtn.setToolTip('Stop motor')
        self.stopbtn.resize(self.stopbtn.sizeHint())
        self.stopbtn.setMinimumHeight(40)
        self.stopbtn.setEnabled(True)
        buttonvbox.addWidget(self.stopbtn)
        self.stopbtn.clicked.connect(self.__stop)        
        self.buttongroupbox.setLayout(buttonvbox)
        grid.addWidget(self.buttongroupbox, 2, 0, 3, 1)
        # Configure tune button
        self.tunebtn = QtGui.QPushButton('Tune', self)
        self.tunebtn.setToolTip('Tune for lowest SWR')
        self.tunebtn.resize(self.tunebtn.sizeHint())
        self.tunebtn.setMinimumHeight(20)
        self.tunebtn.setEnabled(True)
        buttonvbox.addWidget(self.tunebtn)
        self.tunebtn.clicked.connect(self.__tune)
        # Configure auto-tune button
        self.autotunebtn = QtGui.QPushButton('Auto-Tune', self)
        self.autotunebtn.setToolTip('Tune when TX')
        self.autotunebtn.resize(self.autotunebtn.sizeHint())
        self.autotunebtn.setMinimumHeight(20)
        self.autotunebtn.setEnabled(True)
        # Make it a latching button
        self.autotunebtn.setCheckable(True)
        buttonvbox.addWidget(self.autotunebtn)
        self.autotunebtn.clicked.connect(self.__autotune)
        # Configure rx tracking button
        self.trackingbtn = QtGui.QPushButton('RX-Tracking', self)
        self.trackingbtn.setToolTip('Track RX frequency')
        self.trackingbtn.resize(self.trackingbtn.sizeHint())
        self.trackingbtn.setMinimumHeight(20)
        self.trackingbtn.setEnabled(True)
        # Make it a latching button
        self.trackingbtn.setCheckable(True)
        buttonvbox.addWidget(self.trackingbtn)
        self.trackingbtn.clicked.connect(self.__rxtracking)               
        
        #======================================================================================
        # Motor speed
        self.speedgroupbox = QtGui.QGroupBox('Speed (Advisory)')
        self.speedgroupbox.setToolTip("Speed, but action may override")
        speedhbox = QtGui.QHBoxLayout()
        self.speedgroup = QtGui.QButtonGroup(self)
        self.speedslow = QtGui.QRadioButton ("Slow")
        self.speedmed = QtGui.QRadioButton ("Medium")
        self.speedfast = QtGui.QRadioButton ("Fast")
        self.speedgroup.addButton(self.speedslow)
        self.speedgroup.setId(self.speedslow, 1)
        self.speedgroup.addButton(self.speedmed)
        self.speedgroup.setId(self.speedmed, 2)
        self.speedgroup.addButton(self.speedfast)
        self.speedgroup.setId(self.speedfast, 3)
        speedhbox.addWidget(self.speedslow)
        speedhbox.addWidget(self.speedmed)
        speedhbox.addWidget(self.speedfast)
        self.speedmed.setChecked(True)
        self.speedgroupbox.setLayout(speedhbox)
        grid.addWidget(self.speedgroupbox, 2, 1, 1, 3)
        self.connect(self.speedgroup, QtCore.SIGNAL("buttonClicked(int)"), self.__setSpeed)
        
        #======================================================================================
        # GoTo Parameters
        self.gotogroupbox = QtGui.QGroupBox('GoTo Options')
        self.gotogroupbox.setToolTip("GoTo % extension or frequency setpoint")
        gotogrid = QtGui.QGridLayout()
        # to the extension setting
        self.exttosb = QtGui.QSpinBox(self) 
        self.exttosb.setRange(0, 100)
        self.exttosb.setValue(0)
        self.exttosb.setToolTip("Goto extension setting")
        gotogrid.addWidget(self.exttosb, 0, 0)
        # to the frequency setpoint
        self.freqcombo = QtGui.QComboBox()
        if len(self.__settings[LOOP_SETTINGS]) > 0:
            for key in sorted(self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_SETPOINTS].keys()):
                self.freqcombo.addItem(str(key))
        gotogrid.addWidget(self.freqcombo, 0, 2)
        self.freqcombo.setToolTip("Select setpoint frequency")       
        self.gotoradiogroup = QtGui.QButtonGroup(self)
        self.selExtension = QtGui.QRadioButton ("%")
        self.selAnalog = QtGui.QRadioButton ("Value")
        self.selFreq = QtGui.QRadioButton ("Freq")        
        self.gotoradiogroup.addButton(self.selExtension)
        self.gotoradiogroup.setId(self.selExtension, 1)
        self.gotoradiogroup.addButton(self.selAnalog)
        self.gotoradiogroup.setId(self.selAnalog, 2)
        self.gotoradiogroup.addButton(self.selFreq)
        self.gotoradiogroup.setId(self.selFreq, 3)       
        gotogrid.addWidget(self.selExtension, 1, 0)
        gotogrid.addWidget(self.selAnalog, 1, 1)
        gotogrid.addWidget(self.selFreq, 1, 2)
        self.selFreq.setChecked(True)
        self.gotogroupbox.setLayout(gotogrid)
        grid.addWidget(self.gotogroupbox, 3, 1, 1, 3)

        #======================================================================================
        # Status Indicators
        # Status containers
        statusgroupbox = QtGui.QGroupBox('Status')
        statusgrid = QtGui.QGridLayout()
        # Configure VSWR indicators
        self.vswrlabel = QtGui.QLabel(self)
        self.vswrlabel.setText("VSWR")
        self.vswrlabel.setStyleSheet("QLabel {color: rgb(78,78,78); font: 10px}")
        statusgrid.addWidget(self.vswrlabel, 0, 0)
        self.vswrle = QtGui.QLabel(self)
        self.vswrle.setText("-RX-")
        self.vswrle.setStyleSheet("QLabel {color: rgb(232,75,0); font: 14px}")
        statusgrid.addWidget(self.vswrle, 0, 1)
        
        self.fwdlabel = QtGui.QLabel(self)
        self.fwdlabel.setText('Fwd')
        self.fwdlabel.setStyleSheet("QLabel {color: rgb(78,78,78); font: 10px}")
        statusgrid.addWidget(self.fwdlabel, 1, 1)
        self.fwdvalue = QtGui.QLabel(self)
        self.fwdvalue.setText('_')
        self.fwdvalue.setStyleSheet("QLabel {color: rgb(78,78,78); font: 10px}")
        statusgrid.addWidget(self.fwdvalue, 1, 2)
        
        self.reflabel = QtGui.QLabel(self)
        self.reflabel.setText('Ref')
        self.reflabel.setStyleSheet("QLabel {color: rgb(78,78,78); font: 10px}")
        statusgrid.addWidget(self.reflabel, 1, 3)
        self.refvalue = QtGui.QLabel(self)
        self.refvalue.setText('_')
        self.refvalue.setStyleSheet("QLabel {color: rgb(78,78,78); font: 10px}")
        statusgrid.addWidget(self.refvalue, 1, 4)
        
        # Configure CAT frequency
        self.freqlabel = QtGui.QLabel(self)
        self.freqlabel.setText("RX Freq")
        self.freqlabel.setStyleSheet("QLabel {color: rgb(78,78,78); font: 10px}")
        statusgrid.addWidget(self.freqlabel, 2, 0)
        self.freqvalue = QtGui.QLabel(self)
        self.freqvalue.setText("_._ ")
        self.freqvalue.setStyleSheet("QLabel {color: rgb(232,75,0); font: 14px}")
        statusgrid.addWidget(self.freqvalue, 2, 1, 1, 2)
        self.mhzlabel = QtGui.QLabel(self)
        self.mhzlabel.setText("MHz")
        self.mhzlabel.setStyleSheet("QLabel {color: rgb(78,78,78); font: 10px}")
        statusgrid.addWidget(self.mhzlabel, 2, 3)
        
        # Configure extension % offset
        self.headinglabel = QtGui.QLabel(self)
        self.headinglabel.setText("Position")
        self.headinglabel.setStyleSheet("QLabel {color: rgb(78,78,78); font: 10px}")
        statusgrid.addWidget(self.headinglabel, 3, 0)
        self.virtualextvalue = QtGui.QLabel(self)
        self.virtualextvalue.setText("__")
        self.virtualextvalue.setStyleSheet("QLabel {color: rgb(232,75,0); font: 14px}")
        statusgrid.addWidget(self.virtualextvalue, 3, 1)
        self.realextvalue = QtGui.QLabel(self)
        self.realextvalue.setText("(__)")
        self.realextvalue.setStyleSheet("QLabel {color: rgb(232,75,0); font: 14px}")
        statusgrid.addWidget(self.realextvalue, 3, 2)
        
        self.extlabel = QtGui.QLabel(self)
        self.extlabel.setText("% ext (raw)")
        self.extlabel.setStyleSheet("QLabel {color: rgb(78,78,78); font: 10px}")
        statusgrid.addWidget(self.extlabel, 3, 3)
        
        # Set layout
        statusgrid.setColumnStretch(1, 1)
        statusgroupbox.setLayout(statusgrid)
        grid.addWidget(statusgroupbox, 4, 1, 1, 3)
        
        #======================================================================================
        # Progress bar
        self.progresslabel = QtGui.QLabel(self)
        self.progresslabel.setText("Progress")
        grid.addWidget(self.progresslabel, 5, 0)
        self.progressbar = QtGui.QProgressBar(self)
        self.progressbar.setToolTip('Motor progress')
        self.progressbar.setEnabled(True)
        self.progressbar.setMinimum(0)
        self.progressbar.setMaximum(100)
        grid.addWidget(self.progressbar, 5, 1, 1, 3)
        
        #======================================================================================
        # Draw line
        line = QtGui.QFrame()
        line.setFrameShape(QtGui.QFrame.HLine)
        line.setFrameShadow(QtGui.QFrame.Sunken)
        line.setStyleSheet("QFrame {background-color: rgb(126,126,126)}")
        grid.addWidget(line, 6, 0, 1, 4)
        
        #======================================================================================
        # Busy indicator
        self.busyIndicator = QtGui.QLabel(self)
        self.busyIndicator.setText("")
        grid.addWidget(self.busyIndicator, 7, 0)
        
        #======================================================================================
        # Configure Quit        
        self.quitbtn = QtGui.QPushButton('Quit', self)
        self.quitbtn.setToolTip('Quit program')
        self.quitbtn.resize(self.quitbtn.sizeHint())
        self.quitbtn.setMinimumHeight(20)
        self.quitbtn.setEnabled(True)
        grid.addWidget(self.quitbtn, 7, 3)
        self.quitbtn.clicked.connect(self.quit)
        
        #======================================================================================
        # Set final layout
        w.setLayout(grid)
    
    def about(self):
        """ User hit about """
        
        text = """
Loop Controller

    by Bob Cowdery (G3UKB)
    email:  bob@bobcowdery.plus.com
"""
        QtGui.QMessageBox.about(self, 'About', text)
               
    def quit(self):
        """ User hit quit """
        
        # Save the current settings
        persist.saveCfg(SETTINGS_PATH, self.__settings)
        self.__state[WINDOW][X_POS] = self.x()
        self.__state[WINDOW][Y_POS] = self.y()
        persist.saveCfg(STATE_PATH, self.__state)
        
        # Close
        QtCore.QCoreApplication.instance().quit()
    
    def closeEvent(self, event):
        """
        User hit x
        
        Arguments:
            event   -- ui event object
            
        """
        
        # Be polite, ask user
        reply = QtGui.QMessageBox.question(self, 'Quit?',
            "Quit application?", QtGui.QMessageBox.Yes | 
            QtGui.QMessageBox.No, QtGui.QMessageBox.No)
        if reply == QtGui.QMessageBox.Yes:
            self.quit()
        else:
            event.ignore()
    
    def __configEvnt(self, event):
        """
        Run the configurator
        
        Arguments:
            event   -- ui event object
            
        """
        
        self.__settings, r = configurationdialog.ConfigurationDialog.getConfig(self.__cat, self.__executeThrd, self.__api, self.__q, self.__p_q, self.__settings, self.loopcombo.currentText(), self.__statusCallback)
        # Restore the magcontrol callback in case it was nicked
        self.__api.restoreRespCallback()
        self.__api.restoreEvntCallback()
        self.__executeThrd.restoreCallback()
        # If Ok save the new config and update internally
        if r:
            # Settings
            persist.saveCfg(SETTINGS_PATH, self.__settings)
            # Update the UI
            self.loopcombo.clear()
            self.freqcombo.clear()
            if len(self.__settings[LOOP_SETTINGS]) > 0:
                for key in sorted(self.__settings[LOOP_SETTINGS].keys()):
                    self.loopcombo.addItem(str(key))
                if len(self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_SETPOINTS]) > 0:
                    for key in sorted(self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_SETPOINTS].keys()):
                        self.freqcombo.addItem(str(key))
            else:
                self.loopcombo.clear()
            # Network settings
            self.__api.resetNetworkParams(self.__settings[ARDUINO_SETTINGS][NETWORK][IP], self.__settings[ARDUINO_SETTINGS][NETWORK][PORT])
                
            # Pot limit settings
            if self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_POT][I_MAXCAP] != None and self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_POT][I_MINCAP] != None:
                self.__q.put((self.__api.setCapMaxSetpoint, 'capmaxsetpoint', (self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_POT][I_MAXCAP])))
                self.__q.put((self.__api.setCapMinSetpoint, 'capminsetpoint', (self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_POT][I_MINCAP])))
                
            # Band edge settings
            self.__q.put((self.__api.setLowSetpoint, 'freqpminsetpoint', (self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_OFFSETS][I_LOW_FREQ])))
            self.__q.put((self.__api.setHighSetpoint, 'freqmaxsetpoint', (self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_OFFSETS][I_HIGH_FREQ])))

    # ======================================================================================================
    # Main Event Handlers
    def __onLoop(self, ):
        """ Change loop selection """
        
        loop = self.loopcombo.currentText()
        # Reset the setpoint selection
        if len(self.__settings[LOOP_SETTINGS][loop][I_SETPOINTS]) > 0:
            self.freqcombo.clear()
            for key in sorted(self.__settings[LOOP_SETTINGS][loop][I_SETPOINTS].keys()):
                self.freqcombo.addItem(str(key))
        else:
            self.freqcombo.clear()
        
        # Adjust state
        self.__state[SELECTED_LOOP] = loop
        
        # Set the params
        self.__vswr = [0.0,0.0]
        
        # Select the correct relays for the loop
        relayArray = self.__settings[LOOP_SETTINGS][loop][I_RELAYS]
        if len(relayArray) == 4:
            for relay, state in enumerate(relayArray):
                self.__q.put((self.__api.setRelay, 'relay', (relay+1, int(state))))
                
        # Band edge settings
        self.__q.put((self.__api.setLowSetpoint, 'freqpminsetpoint', (self.__settings[LOOP_SETTINGS][loop][I_OFFSETS][I_LOW_FREQ])))
        self.__q.put((self.__api.setHighSetpoint, 'freqmaxsetpoint', (self.__settings[LOOP_SETTINGS][loop][I_OFFSETS][I_HIGH_FREQ])))
    
    def __setSpeed(self, id):
        
        """
        Set the motor speed
        
        Arguments:
            id  --  id of the widget that raised the event
            
        """
        
        if len(self.__settings[LOOP_SETTINGS]) > 0:
            if id == 1:
                speed = self.__setSlow()
            elif id == 2:
                speed = self.__setMedium()
            else:
                speed = self.__setFast()
            
            self.__speed = speed
    
    def __setSlow(self):
        
        speed = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_PARAMS][I_SLOW]
        self.__q.put((self.__api.speed, 'speed', (speed)))
        return speed
    
    def __setMedium(self):
        
        speed = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_PARAMS][I_MEDIUM]
        self.__q.put((self.__api.speed, 'speed', (speed)))
        return speed
    
    def __setFast(self):
        
        speed = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_PARAMS][I_FAST]
        self.__q.put((self.__api.speed, 'speed', (speed)))
        return speed
    
    def __nudgeFwd(self):
        """ Nudge forward from current position by the nudge % setting """
        
        nudgeExtension = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_PARAMS][I_NUDGE]
        analogMin = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_POT][I_MINCAP]
        analogMax = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_POT][I_MAXCAP]
        self.__q.put((self.__api.nudge, 'nudge', (FORWARD, nudgeExtension, analogMin, analogMax)))
            
    def __nudgeRev(self):
        """ Nudge reverse from current position by the nudge % setting """
        
        nudgeExtension = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_PARAMS][I_NUDGE]
        analogMin = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_POT][I_MINCAP]
        analogMax = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_POT][I_MAXCAP]
        self.__q.put((self.__api.nudge, 'nudge', (REVERSE, nudgeExtension, analogMin, analogMax)))
            
    def __tune(self):
        """ Tune for lowest VSWR """
        
        self.__q.put((self.__api.tune, 'tune', ()))
                     
    def __autotune(self):
        """ Set/reset auto tune """
        
        self.__autoTuneState = self.autotunebtn.isChecked()
        self.__q.put((self.__api.autoTune, 'autotune', (self.__autoTuneState)))
        
    def __goto(self):
        
        """ Either move to the frequency setpoint or the given extension """
       
        if self.selExtension.isChecked():
            # Move to extension setting
            self.__q.put((self.__api.move, 'move', (self.exttosb.value(), True)))
        elif self.selAnalog.isChecked():
            # Move to analog value setting
            self.__q.put((self.__api.move, 'move', (self.exttosb.value(), False)))
        elif self.selFreq.isChecked():
            # Move to the frequency setpoint
            setpoint = self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_SETPOINTS][self.freqcombo.currentText()]
            self.__q.put((self.__api.move, 'move', (setpoint, True)))
        
    def __stop(self):
        
        """ Stop the motor """
        
        if self.__running:
            # Must be an interrupt stop, make priority
            self.__p_q.put((self.__api.stop, 'stop', ()))
        else:
            self.__q.put((self.__api.stop, 'stop', ()))
    
    def __rxtracking(self):
        """ Change tracking state """
        
        state = self.trackingbtn.isChecked()
        if state == 0:
            # Disable tracking
            self.__enable_tracking = False
            self.__tracking.pause_tracker()
            self.__absoluteExtension = None
            self.__currentFreq = None
        else:
            # Enable tracking
            self.__enable_tracking = True
            self.__tracking.reset_tracker()
            self.__tracking.run_tracker()
        
    # Callback handlers ===============================================================================================
    def __respCallback(self, message):
        
        """
        Callback for response messages. Note that this is not called
        from the main thread and therefore we just set a status which
        is picked up in the idle loop for display.
        Qt calls MUST be made from the main thread.
        
        Arguments:
            message --  text to drive the response messages
            
        """
         
        try:
            # This set comes from command completions via magcontrol
            if 'success' in message:
                # Completed, so reset
                self.__statusMessage = 'Finished'
                self.__progress = 100
            elif 'failure' in message:
                # Error, so reset
                _, reason = message.split(':')
                self.__statusMessage = '**Failed - %s**' % (reason)
                self.__progress = 100
            elif 'offline' in message:
                self.__statusMessage = 'Controller is offline! - attempting reset'
                # Try a reset
                if self.__state[SELECTED_LOOP] != None:
                    self.__api.resetNetworkParams(self.__settings[ARDUINO_SETTINGS][NETWORK][IP], self.__settings[ARDUINO_SETTINGS][NETWORK][PORT])
            elif 'tx' in message:
                # TX status request
                _, status = message.split(':')
                if status == 'on':
                    self.__isTX = True
                elif status == 'off':
                    self.__isTX = False
        except Exception as e:
            self.__statusMessage = 'Exception getting response!'
            print('Exception %s' % (str(e)))

    def __executeCallback(self, message):
        
        """
        Callback for response messages. Note that this is not called
        from the main thread and therefore we just set a status which
        is picked up in the idle loop for display.
        Qt calls MUST be made from the main thread.
        
        Arguments:
            message --  text to drive the response messages
            
        """
        
        try:
            # This comes from the command execution thread and is batch related
            if 'beginbatch' in message:
                # When we start executing commands from the q
                self.__running = True
            elif 'endbatch' in message:
                # When we finish executing commands from the q
                self.__running = False
            elif 'name' in message:
                # When we finish executing a command from the q
                pass
            elif 'tuned' in message:
                # When we finish tuning
                self.__statusMessage = 'Tune complete'
            elif 'fatal' in message:
                # Oops
                _, reason = message.split(':')
                self.__statusMessage = '**Fatal - %s**' % (reason)
                raise RuntimeError(reason)            
        except Exception as e:
            self.__statusMessage = 'Exception getting response [%s]!' % (str(e))

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
                self.__vswr[0] = float(forward)
                self.__vswr[1] = float(reverse)
            elif 'pot' in message:
                _, self.__realExtension, self.__virtualExtension = message.split(':')
            elif 'tx' in message:
                # TX status request
                _, status = message.split(':')
                if status == 'on':
                    self.__isTX = True
                elif status == 'off':
                    self.__isTX = False
            elif 'alarm' in message:
                _, reason = message.split(':')
                if 'autotune' in reason:
                    self.__statusMessage = 'Autotune problem (excessive SWR?)!'
                    self.__autoTuneState = False
        except Exception as e:
            self.__statusMessage = 'Exception getting event status!'
        
    def __track_callback(self, form, freq, moveToExtension = None, message = ''):
        
        """
        Callback for external command messages. Note that this is
        not called from the main thread and therefore we just
        set a status which is picked up in the idle loop for display.
        Qt calls MUST be made from the main thread.
        
        Arguments:
            form            --  TRACKING_FREQ or TRACKING_ERROR or TRACKING_HOME_DEGS or TRACKING_DEGS
            freq            --  frequency to move to
            moveToExtension --  absolute extension to move to
            message         --  text to drive the status messages
        """    
        
        # Track
        if self.__enable_tracking:
            self.__tracking.pause_tracker() # Stop updates            
            if form == TRACKING_TO_DEGS:
                # Move to the given extension %
                self.__q.put((self.__api.move, 'move', (int(moveToExtension), True)))
            elif form == TRACKING_ERROR:
                # Oops, something went wrong.
                self.__statusMessage = 'Tracking problem! (%s)' % (message)
            elif form == TRACKING_UPDATE:
                # Just a display current frequency
                self.__currentFreq = freq
            self.__tracking.run_tracker() # Resume updates
        else:
            if form == TRACKING_UPDATE:
                # Just a display current frequency
                self.__currentFreq = freq
               
    def __statusCallback(self, message):
        """
        Callback for status messages from the configuration dialog.
        
        Arguments:
            message --  message text
            
        """
        
        self.__statusMessage = message
        
    # Idle time processing ============================================================================================        
    def __idleProcessing(self):
        
        """
        Idle processing.
        Called every 100ms single shot
        
        """
        # Check if we need to clear status message
        if (self.__lastStatus == self.__statusMessage) and len(self.__statusMessage) > 0:
            self.__tickcount += 1
            if self.__tickcount >= TICKS_TO_CLEAR:
                self.__tickcount = 0
                self.__statusMessage = ''
        else:
            self.__tickcount = 0
            self.__lastStatus = self.__statusMessage
        
        # Check online state
        if self.__state[SELECTED_LOOP] != None:
            self.__pollcount += 1
            if self.__pollcount >= POLL_TICKS:
                self.__pollcount = 0
                if self.__api.is_online():
                    if not self.__connected:
                        # We have now come on-line from being off-line
                        self.__connected = True
                else:
                    self.busyIndicator.setStyleSheet("QLabel {color: red; font: 14px}")
                    self.busyIndicator.setText('Disconnected')
                    
        # Main idle processing        
        if self.__startup:
            # Startup ====================================================
            self.__startup = False
            # Initialise state if required
            if len(self.__state) > 0:
                if len(self.__settings[LOOP_SETTINGS]) > 0:
                    self.__state[SELECTED_LOOP] = self.loopcombo.currentText()
                
            # Check startup conditions
            if self.__settings[ARDUINO_SETTINGS][NETWORK][IP] == None:
                # We have no Arduino settings so user must configure first
                QtGui.QMessageBox.information(self, 'Configuration Required', 'Please configure the Arduino network settings using the edit/network dialog', QtGui.QMessageBox.Ok)
            if len(self.__settings[LOOP_SETTINGS]) == 0:
                # We have no settings so user must configure first
                QtGui.QMessageBox.information(self, 'Configuration Required', 'Please configure a loop using the edit/loop dialog', QtGui.QMessageBox.Ok)
            elif  self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_POT][I_MAXCAP] == None or\
                self.__settings[LOOP_SETTINGS][self.loopcombo.currentText()][I_POT][I_MINCAP] == None:
                # We have no pot settings so user must configure first
                QtGui.QMessageBox.information(self, 'Configuration Required', 'Please configure the potentiometer band limit settings or operation will be compromised.', QtGui.QMessageBox.Ok)
                
            # Adjust the state
            if self.__state[SELECTED_LOOP] != None:
                self.loopcombo.setCurrentIndex(self.loopcombo.findText(self.__state[SELECTED_LOOP]))
            # Make sure the status gets cleared
            self.__tickcount = 50
        else:
            # Runtime ====================================================
            # Button state
            if len(self.__settings[LOOP_SETTINGS]) == 0:
                # No loops configured, disable all
                buttons = (self.speedgroupbox, self.gotogroupbox, self.buttongroupbox)
                self.__setButtonState(False, buttons)
            elif self.__running:
                # Motor running, only allow stop
                buttons = (self.speedgroupbox, self.gotogroupbox, self.nudgefwdbtn, self.nudgerevbtn, self.gotobtn, self.tunebtn, self.autotunebtn, self.trackingbtn)
                self.__setButtonState(False, buttons)
                self.__setButtonState(True, (self.buttongroupbox, self.stopbtn, ))
            elif self.__enable_tracking:
                # Tracking frequency, only allow tracking off
                buttons = (self.speedgroupbox, self.gotogroupbox, self.nudgefwdbtn, self.nudgerevbtn, self.gotobtn, self.tunebtn, self.autotunebtn, self.stopbtn)
                self.__setButtonState(False, buttons)
                self.__setButtonState(True, (self.buttongroupbox, self.trackingbtn))
            elif self.__autoTuneState:
                # Autotune, only allow autotune off
                buttons = (self.speedgroupbox, self.gotogroupbox, self.nudgefwdbtn, self.nudgerevbtn, self.gotobtn, self.tunebtn, self.trackingbtn, self.stopbtn)
                self.__setButtonState(False, buttons)
                self.__setButtonState(True, (self.buttongroupbox, self.autotunebtn))                
            else:
                # Normal operation, allow everything except stop which would be a noop
                buttons = (self.buttongroupbox, self.speedgroupbox, self.gotogroupbox, self.nudgefwdbtn, self.nudgerevbtn, self.gotobtn, self.tunebtn, self.autotunebtn, self.trackingbtn)
                self.__setButtonState(True, buttons)
                self.__setButtonState(False, (self.stopbtn, ))
                self.__progress = 0
                if self.selExtension.isChecked():
                    self.exttosb.setRange(0, 100)
                    self.__setButtonState(True, (self.exttosb, ))
                    self.__setButtonState(False, (self.freqcombo, ))
                elif self.selAnalog.isChecked():
                    self.exttosb.setRange(0, 1000)
                    self.__setButtonState(True, (self.exttosb, ))
                    self.__setButtonState(False, (self.freqcombo, ))
                else:
                    self.__setButtonState(False, (self.exttosb, ))
                    self.__setButtonState(True, (self.freqcombo, ))
            
            # Progress bar and status messages
            self.statusBar.showMessage(self.__statusMessage)
            if self.__connected:
                if self.__running:
                    self.progressbar.setValue(self.__progress)
                    self.busyIndicator.setStyleSheet("QLabel {color: rgb(232,75,0); font: 14px}")
                    self.busyIndicator.setText('BUSY')
                else:
                    self.progressbar.setValue(self.__progress)
                    self.__progress = 0
                    self.busyIndicator.setStyleSheet("QLabel {color: rgb(62,103,54); font: 14px}")
                    self.busyIndicator.setText('IDLE')
            
            # Get TX state
            # Not currently used but may be needed in the future 
            #if self.__connected:
            #    self.__q.put((self.__api.is_tx, 'istx', ()))
            
            # Display status
            self.__showVSWR()                               # Current fwd and ref and SWR if TXing
            self.virtualextvalue.setText('%s' % (str(self.__virtualExtension)))
            self.realextvalue.setText('(%s)' % (str(self.__realExtension)))
            if self.__currentFreq == None:          
                self.freqvalue.setText("_._")
            else:
                self.freqvalue.setText(str(self.__currentFreq))
            
            # Check if we need to start CAT
            if not self.__cat_running:
                if self.__cat_timer <= 0:
                    if self.__cat.start_thrd():
                        self.__cat_running = True
                        self.__cat_timer = CAT_TIMER
                else:
                    self.__cat_timer -= 1
            
            # Check if we need to set relays
            if not self.__relays_set and not self.__running:
                if self.__connected:
                    # Select the correct relays for the loop
                    relayArray = self.__settings[LOOP_SETTINGS][self.__state[SELECTED_LOOP]][I_RELAYS]
                    if len(relayArray) == 4:
                        for relay, state in enumerate(relayArray):
                            self.__q.put((self.__api.setRelay, 'relay', (relay+1, int(state))))
                    self.__relays_set = True                    
                
        # Set next idle time    
        QtCore.QTimer.singleShot(IDLE_TICKER, self.__idleProcessing)
    
    # Helpers =========================================================================================================
    def __setButtonState(self, enabled, widgets):
        """
        Set enabled/disabled state
        
        Arguments:
            enabled --  True if enabled state else disabled
            widgets --  list of widgets to set state
            
        """
        
        for widget in widgets:
            if enabled:
                widget.setEnabled(True)
            else:
                widget.setEnabled(False)
    
    def __showVSWR(self):
        """ Calculate and show the VSWR reading """
        
        if self.__isTX:
            # Do an approximate lookup to get the VSWR
            ratio = vswr.getVSWR(self.__vswr[0], self.__vswr[1])           
            if ratio != None:
                self.vswrle.setText("%.1f:1" % ratio)
            else:
                self.vswrle.setText("infinity")
            # Show actuals
            self.fwdvalue.setText('%d' % int(self.__vswr[0]))
            self.refvalue.setText('%d' % int(self.__vswr[1]))            
        else:
            # RX mode
            self.vswrle.setText("-RX-")
            self.fwdvalue.setText('_')
            self.refvalue.setText('_')
 
#======================================================================================================================
# Main code
def main():
    
    try:
        # The one and only QApplication 
        qt_app = QtGui.QApplication(sys.argv)
        # Cretae instance
        loop_ui = LoopUI(qt_app)
        sleep(0.2)
        # Run application loop
        sys.exit(loop_ui.run())
        
    except Exception as e:
        print ('Exception','Exception [%s][%s]' % (str(e), traceback.format_exc()))
 
# Entry point       
if __name__ == '__main__':
    main()