#!/usr/bin/env python
#
# dispatcher.py
#
# Threaded command dispatcher and tuning assistant
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
from time import sleep
import queue
import threading
import traceback

sys.path.append('..')

# Application imports
from common.defs import *

# Command execute thread ===================================================================    
# Dispatches commands from the main thread such that it remains responsive to events.

class CommandExecutionThrd(threading.Thread):
    
    def __init__(self, q, callback):
        """
        Constructor
        
        Arguments:
            q           --  queue to accept commands on
            callback    --  on status or error
        
        """
        
        super(CommandExecutionThrd, self).__init__()
        
        self.__q = q
        self.__callback = callback
        self.__originalCallback = callback
        
        self.__terminate = False
    
    def terminate(self):
        """ Thread terminating """
        
        self.__terminate = True
    
    def stealCallback( self, callback) :
        """ Steal the dispatcher callback """
        
        self.__callback = callback
    
    def restoreCallback( self) :
        """ Restore the dispatcher callback """
        
        self.__callback = self.__originalCallback    
        
    def run(self):
        """ Thread entry point """
        
        while not self.__terminate:
            try:
                if self.__q.qsize() > 0:
                    self.__callback('beginbatch')
                    while self.__q.qsize() > 0:
                        __callable, name, args = self.__q.get()
                        # By default this is synchronous so will wait for the response
                        # Response goes to main code callback, we don't care here
                        __callable(args)
                        self.__q.task_done()
                        self.__callback('executed:%s' % name)
                    self.__callback('endbatch')
                else:
                    sleep(0.02)
            except Exception as e:
                # Something went wrong
                print(str(e))
                self.__callback('fatal: {0}'.format(e))
                break 
 
# Command priority thread ===================================================================    
# Dispatches priority commands from the main thread such that it remains responsive to events.
# These are one way commands, usually to interrupt processing e.g. a stop command. We do not
# expect a response to these commands.

class CommandPriorityThrd(threading.Thread):
    
    def __init__(self, q):
        """
        Constructor
        
        Arguments:
            q           --  queue to accept commands on
        
        """
        
        super(CommandPriorityThrd, self).__init__()
        
        self.__q = q
        
        self.__terminate = False
    
    def terminate(self):
        """ Thread terminating """
        
        self.__terminate = True
        
    def run(self):
        """ Thread entry point """
        
        while not self.__terminate:
            try:
                if self.__q.qsize() > 0:
                    while self.__q.qsize() > 0:
                        __callable, name, args = self.__q.get()
                        # By default this is synchronous
                        # No response will be send so we don't need any status to the main thread
                        # Call with async and no response
                        __callable(args, False, False)
                        self.__q.task_done()
                else:
                    sleep(0.02)
            except Exception as e:
                # Something went wrong, we just have to ignore it
                pass
 