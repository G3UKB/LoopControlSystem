#!/usr/bin/env python
#
# control_if.py
#
# Controller API for the Loop Controller application
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
import socket
import threading
import traceback
from time import sleep
import math

# Application imports
sys.path.append(os.path.join('..', '..'))
from common.defs import *

"""
Controller API
The one and only interface to the hardware
"""
class ControllerAPI:
    
    def __init__(self, networkParams, respCallback, evntCallback):
        """
        Constructor
        
        Arguments:
        
            networkParams   --  [ip, port] address of Arduino
            respCallback    --  command response callback
            evntCallback    --  event callbacks
        """
        
        # Check network parameters
        if len(networkParams) == 0 or networkParams[0]== None or networkParams[1]== None:
            # Not configured yet
            self.__ip = None
            self.__port = None
            self.__ready = False
        else:
            # Ready to roll
            self.__ip = networkParams[0]
            self.__port = int(networkParams[1])
            self.__ready = True
            
        # Callback parameters
        self.__originalRespCallback = respCallback
        self.__respCallback = respCallback
        self.__originalEvntCallback = evntCallback
        self.__evntCallback = evntCallback
        
        # Set online status
        self.__online = False
        if self.__ready:
            # Create UDP socket
            self.__sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Check connectivity
            if self.__ping():
                self.__online = True
                
        # Create and start the event thread
        self.__evntThrd = EventThread(self.__evntCallback)
        self.__evntThrd.start()
        if self.__online:
            # Allow it to run
            self.__evntThrd.online()

    def resetNetworkParams(self, ip, port):
        """
        Parameters (may) have changed
        
        Arguments:
        
            ip          --  IP address of Arduino
            port        --  port address for Arduino
        """
        
        self.__ip = ip
        self.__port = int(port)
        self.__ready = True
        
        if self.__sock != None:
           self.__sock.close()
        # Create UDP socket
        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Check connectivity
        if self.__ping():
            self.__online = True
            self.__evntThrd.online()
    
    def stealRespCallback(self, callback):
        """
        Temporarily steal the response callback
        
        Arguments:
        
            callback    --  new callback address
        """
        
        self.__respCallback = callback
        
    def restoreRespCallback(self):
        """ Restore original callback """
        
        self.__respCallback = self.__originalRespCallback
    
    def originalRespCallback(self):
        """ Get the main resp callback """
        
        return self.__originalRespCallback
    
    def stealEvntCallback(self, callback):
        """
        Temporarily steal the event callback
        
        Arguments:
        
            callback    --  new callback address
        """
        
        self.__evntCallback = callback
        self.__evntThrd.stealCallback(callback)
        
    def restoreEvntCallback(self):
        """ Restore original callback """
        
        self.__evntCallback = self.__originalEvntCallback
        self.__evntThrd.restoreCallback()
    
    def originalEvntCallback(self):
        """ Get the main evnt callback """
        
        return self.__originalEvntCallback
    
    def terminate(self):
        """ Closing, so terminate threads """
        
        self.__evntThrd.terminate()
        self.__evntThrd.join()
        
        
    # API =============================================================================================================
    def is_online(self):
        """ If offline try and get online, return online state """
        
        if self.__ready:
            if self.__online:
                return True
            else:
                if self.__ping():
                    self.__online = True
                    self.__evntThrd.online()
                    return True
                else:
                    return False        
        else:
            return False
    
    def setAnalogRef(self, args, sync=True, response=True):
        """ Set analog ref to INTERNAL or EXTERNAL """
        
        if not self.__online:
            self.__respCallback('offline!')
            return
        
        if args == EXTERNAL:
            self.__send('refexternal')
        else:
            self.__send('refdefault')
            
        if response:
            self.__doReceive(sync)        
        
    def is_tx(self, args, sync=True, response=True):
        """ If TX return True """
        
        if not self.__online:
            self.__respCallback('offline!')
            return
        self.__send('istx')
        if response:
            self.__doReceive(sync)

    def speed(self, value, sync=True, response=True):
        """
        Change speed
        
        Arguments:
            value   --  speed value
        """
        
        if not self.__online:
            self.__respCallback('offline!')
            return
        
        self.__send(str(value) + 's')
        if response:
            self.__doReceive(sync)
        
    def stop(self, args, sync=True, response=True):
        """ Stop motor """
        
        if not self.__online:
            self.__respCallback('offline!')
            return
        self.__send('stop')
        if response:
            self.__doReceive(sync)
    
    def move(self, args, sync=True, response=True):        
        """
        Move to the given extension value
        
        Arguments:
            args     --  (extension or raw value, True|False)
        """
       
        if not self.__online:
            self.__respCallback('offline!')
            return
        
        extensionOrRaw, extension = args
        if extension:
            self.__send(str(extensionOrRaw) + 'm')
        else:
            self.__send(str(extensionOrRaw) + 'n')
        if response:
            self.__doReceive(sync)
    
    def nudge(self, args, sync=True, response=True):        
        """
        Nudge in the given direction
        
        Arguments:
            args
                direction   --  FORWARD|REVERSE
                value       --  %.% to nudge
                min         --  min analog setting
                max         --  max analog setting
        """
        
        if not self.__online:
            self.__respCallback('offline!')
            return
        
        direction, value, minAnalog, maxAnalog = args
        # Convert the % to an analog value.
        analogValue = int(round(float(maxAnalog - minAnalog) * (value/100.0)))
        if analogValue == 0:
            self.__respCallback('nudge calculated analog value 0!')
            return
        
        if direction == FORWARD:
            self.__send(str(analogValue) + 'f')
        else:
            self.__send(str(analogValue) + 'r')
        if response:
            self.__doReceive(sync)

    def setLowSetpoint(self, extension, sync=True, response=True):
        """
        Set the low setpoint
        
        Arguments:
            extension     --  extension % to low frequency setpoint
        """
        
        if not self.__online:
            self.__respCallback('offline!')
            return
        
        self.__send(str(extension) + 'l')
        if response:
            self.__doReceive(sync)
    
    def setHighSetpoint(self, extension, sync=True, response=True):
        """
        Set the high setpoint
        
        Arguments:
            extension     --  extension % to high frequency setpoint
        """
        
        if not self.__online:
            self.__respCallback('offline!')
            return
        
        self.__send(str(extension) + 'h')
        if response:
            self.__doReceive(sync)
    
    def setCapMaxSetpoint(self, extension, sync=True, response=True):
        """
        Set the extension % for max capacitance
        
        Arguments:
            extension     --  extension % for maximum capacity
        """

        if not self.__online:
            self.__respCallback('offline!')
            return
        
        self.__send(str(extension) + 'x')
        if response:
            self.__doReceive(sync)
            
    def setCapMinSetpoint(self, extension, sync=True, response=True):
        """
        Set the extension % for min capacitance
        
        Arguments:
            extension     --  extension % for minimum capacity
        """
        
        if not self.__online:
            self.__respCallback('offline!')
            return
        
        self.__send(str(extension) + 'y')
        if response:
            self.__doReceive(sync)
            
    def tune(self, args, sync=True, response=True):
        """ Tune for lowest VSWR """
        
        if not self.__online:
            self.__respCallback('offline!')
            return
        
        self.__send('tune')
        if response:
            self.__doReceive(sync)
    
    def autoTune(self, state, sync=True, response=True):
        """ Set automatic tuning """
        
        if not self.__online:
            self.__respCallback('offline!')
            return
        if state:
            self.__send('autotuneon')
        else:
            self.__send('autotuneoff')
        if response:
            self.__doReceive(sync)
            
    def setRelay(self, args, sync=True, response=True):
        """
        Set the given relay to the given state
        
        Arguments:
            relay   --  Relay number (1-8)
            state   --  1 = energise
        """
        
        if not self.__online:
            self.__respCallback('offline!')
            return
        
        relay, state = args
        if state == 1:
            self.__send(str(relay) + 'e')
            if response:
                self.__doReceive(sync)
        else:
            self.__send(str(relay) + 'd')
            if response:
                self.__doReceive(sync)
            
    # Helpers =========================================================================================================    
    def __send(self, command):
        """
        Send data to the controller
        
        Arguments:
            command     --  command to send
            synchronous --  if True wait for a response 
        """
        
        if  self.__online:
            self.__sock.sendto(bytes(command, "utf-8"), (self.__ip, self.__port))
        
    def __doReceive(self, sync):
        """
        Initiate receiving a response from the controller
        
        Arguments:
            wait   --  True = wait for transient thread to terminate
        """
        
        if self.__online:
            # Run the transient receive thread
            t = threading.Thread(target=receive, args=(self.__sock, self.__respCallback, self.__online))
            t.start()
            if sync:
                t.join()
        else:
            self.__respCallback('offline: controller is not connected')
            return

    def __ping(self):
        """
        Check connectivity
        
        """
        
        if not self.__ready:
            return False
        
        try:
            self.__sock.sendto(bytes('ping', "utf-8"), (self.__ip, self.__port))
            self.__sock.settimeout(0.5)
            data, addr = self.__sock.recvfrom(RECEIVE_BUFFER)
            return True
        except socket.timeout:
            # Server didn't respond
            return False
        except Exception as e:
            # Something went wrong
            return False
        
# Response loop ========================================================================================================        
# Runs on separate thread as calls are from within a UI event proc so need to detach the long running part.
# Also allow the UI to continue to display status changes.
def receive(sock, callback, online):
    
    # Some commands are long running and we must not timeout too soon
    timeoutCount = 60   # Allow 60 * CONTROLLER_TIMEOUT
    data = ''
    
    sock.settimeout(CONTROLLER_TIMEOUT)
    while(1):
        try:
            data, addr = sock.recvfrom(RECEIVE_BUFFER)
            break
        except socket.timeout:
            # Wait for response
            timeoutCount -= 1
            if timeoutCount > 0:
                callback('status: waiting for response...')
                continue
            else:
                callback('failure: timeout on read!')
                break
        except Exception as e:
            # Something went wrong
            callback('failure: {0}'.format(e))
            break
        
    # Successful read
    if len(data) > 0:
        asciidata = data.decode(encoding='UTF-8')
        callback(asciidata)  
        
# Event loop ========================================================================================================        
# Runs on separate thread. Generates callbacks to the main program whenever an event arrives.

class EventThread(threading.Thread):
    
    def __init__(self, callback):
        """
        Constructor
        
        Arguments
            callback    --  callback here with event data
        
        """
        
        super(EventThread, self).__init__()
        
        self.__callback = callback
        self.__originalCallback = callback
        self.__release = False
        self.__terminate = False
        
        self.__sock = None
    
    def terminate(self):
        """ Thread terminating """
        
        self.__terminate = True
    
    def stealCallback(self, callback):
        """ Redirect callback """
        
        self.__callback = callback
        
    def restoreCallback(self):
        """ Restore callback """
        
        self.__callback = self.__originalCallback
        
    def online (self):
        """ Controller has come online """
        
        if self.__sock == None:
            # Create UDP socket
            self.__sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Bind for any IP to our event port
            self.__sock.bind(('', EVENT_PORT))
            # Set a reasonable timeout
            self.__sock.settimeout(CONTROLLER_TIMEOUT)
        # Release the thread
        self.__release = True
        
    def run(self):
        """ Thread entry point """
        
        while not self.__release:
            if self.__terminate:
                break
            sleep(0.2)
            
        while not self.__terminate:
            try:
                data, addr = self.__sock.recvfrom(RECEIVE_BUFFER)              
                asciidata = data.decode(encoding='UTF-8')
                self.__callback(asciidata)
            except socket.timeout:
                # No events
                continue
            except Exception as e:
                # Something went wrong
                self.__callback('failure: {0}'.format(e))
                break
            
#======================================================================================================================
# Testing code
def callback1(msg):
    print(msg)
    
def callback2(msg):
    print(msg)
    
def main():
    
    try:
        api = ControllerAPI(('192.168.1.177', 8888), callback1, callback2)
        if api.is_online():
            api.setLowSetpoint(50)
            sleep(1)
            api.setHighSetpoint(150)
            sleep(1)
            api.speed(30)
            sleep(1)
            api.move(100)
            sleep(5)
            api.move(1)
            #sleep(5)
            #api.tune()
            sleep(5)
            api.terminate()
        
    except Exception as e:
        print ('Exception','Exception [%s][%s]' % (str(e), traceback.format_exc()))
 
# Entry point       
if __name__ == '__main__':
    main()        
    