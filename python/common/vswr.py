# vswr.py
#
# VSWR calculations for the Mag Loop application
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

def getVSWR(forward, reflected):
    """
    Return an approximate VSWR from the relative forward and reverse power
    
    Arguments:
        forward     --  relative forward power
        reflected   --  relative reflected power
        
    """
    
    if forward > 0.0:
        # RF present
        if forward - reflected > 0:
            return (forward + reflected)/(forward - reflected)
        else:
            return None
    else:
        return None