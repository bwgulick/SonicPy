#-------------------------------------------------------------------------------
# Name:        AFG3000C - Passing a Waveform File into Internal Memory
# Purpose: This code is an example of how to send a AFG TFW file to editable memory on a AFG3000 generator
#
# Created using Python version 2.7
# Using Tekvisa v1.8
# Using Windows 7, Tekvisa version v4.1.0 or newer
# Created:     5/10/2016
# Copyright:   (c) Tektronix 2016
#-------------------------------------------------------------------------------

import pyvisa as visa
import time, logging, os, struct, sys, copy, os.path

import pyqtgraph as pg
from pyqtgraph.Qt import QtGui, QtCore
from um.models.AFGModel import Afg
from PyQt5.QtCore import QThread, pyqtSignal

import queue 
from functools import partial
from um.models.tek_fileIO import read_file_TEKAFG3000, waveform_to_AFG3251_binary, read_afg_waveform_file
import json
from um.models.pv_model import pvModel


class AFG_AFG3251(Afg, pvModel):

    model_value_changed_signal = pyqtSignal(dict)

    def __init__(self, parent, visa_hostname='202', offline = False):
        pvModel.__init__(self, parent)
        Afg.__init__(self)

        ## device speficic:
        self.instrument = 'AFG3251'
        self.settings_file_tag ='Waveform'

        self.duration = 50

        self.visa_hostname = visa_hostname
        self.connected = False
        if not offline:
            self.connected = self.connect(self.visa_hostname)
        if self.connected:
            #print('connected')
            pass
        
        
        self.function_shapes = ['sinusoid', 'square', 'pulse', 'ramp', 'prnoise', 'dc', 'sinc', 
                                'gaussian', 'lorentz', 'erise', 'edecay', 'haversine', 'user1', 
                                'user2', 'user3', 'user4', 'ememory', 'efile']
        self.operating_modes = ['continuous','burst n-cycles']
        self.memory_slots = ['user1', 'user2', 'user3', 'user4', 'ememory']
        
        # Task description markup. Aarbitrary default values ('val') are for type recognition in panel widget constructor
        # supported types are float, int, bool, string, and list of strings
        self.tasks = {  'amplitude': 
                                {'desc': 'Amplitude', 'unit':u'V<sub>p-p</sub>', 'val':1.0,'min':0.05,'max':9,'increment':0.05, 
                                'param':{'type':'f'}},
                        'frequency': 
                                {'desc': 'Frequency', 'unit':'MHz','val':30000000.0,'val_scale':1e6, 'min':0, 'max':1000e6,'increment':.5, 
                                'param':{'type':'f'}},
                        'output_state':     
                                {'desc': 'Output;ON/OFF','val':False, 
                                'param':{'type':'b'}},
                        'n_cycles':  
                                {'desc': 'N-cycles', 'val':3,'min':1 ,'max':100000, 
                                'param':{'type':'i'}},
                        'instrument':
                                {'desc': 'Instrument', 'val':'not connected', 
                                'methods':{'set':False, 'get':True}, 
                                'param':{'type':'s'}},
                        'operating_mode':
                                {'desc': 'Operating mode', 'val':self.operating_modes[0],'list':self.operating_modes, 
                                'param':{'type':'l'}},
                        'function_shape':
                                {'desc': 'Function shape', 'val':self.function_shapes[0],'list':self.function_shapes, 
                                'param':{'type':'l'}},
                        'user1_waveform':
                                {'desc': 'User waveform 1', 'val':{}, 
                                'param':{'type':'dict'}},
                        'user1_waveform_from_file':
                                {'desc': 'Waveform file', 'val':'',
                                'param':{'type':'s'}},
                        'user1_waveform_sample_rate':
                                {'desc': 'File sample rate', 'unit':'MS/s', 'val':250e6,
                                'val_scale':1e6, 'min':1e3, 'max':2e9, 'increment':1,
                                'param':{'type':'f'}},
                        'upload_slot':
                                {'desc': 'Upload to', 'val':self.memory_slots[0],
                                'list':self.memory_slots,
                                'param':{'type':'l'}},
                        'upload_frequency_override':
                                # 0 keeps the historical behaviour of deriving the record
                                # frequency from the waveform's own time axis
                                {'desc': 'Upload freq override', 'unit':'Hz', 'val':0.0,
                                'min':0, 'max':1000e6, 'increment':1,
                                'param':{'type':'f'}},
                        'upload_user1_waveform':     
                                {'desc': 'Upload waveform;Go','val':False, 
                                'param':{'type':'b'}},
                        'auto_upload_user1_waveform':     
                                {'desc': 'Autoload;ON/OFF','val':True, 
                                'param':{'type':'b'}},
                      }       

        self.create_pvs(self.tasks)
        

    ###############################################################################
    #  Private device specific functions. Should not be used by external callers  #
    ###############################################################################    

    def _exit_task(self):
        self.disconnect()

    def ask(self, command):
        #print(command)
        if self.connected:
            ans = self.AFG3000.query(command)
            return ans
        else: return None

    def write(self, command):
        #print(command)
        if self.connected:
            self.AFG3000.write(command)
    
    def write_binary_values(self, command, binary_waveform):
        #print (command)
        if self.connected:
            self.AFG3000.write_binary_values(command, binary_waveform, datatype='h', is_big_endian=True)

        
    def _get_instrument(self):
        
        ID = self.ask('*IDN?')
        if ID is not None:
            if len(ID):
                tokens = ID.split(',')
                ID = tokens[1]
        return ID

    def _set_upload_user1_waveform(self, param):
        self.pvs['upload_user1_waveform']._val = param
        if param:
            waveform = self.pvs['user1_waveform']._val

            if waveform is not None and len(waveform):
                if not ('t' in waveform and 'waveform' in waveform):
                    # a malformed waveform dict used to raise here and kill this thread
                    print('AFG upload skipped: waveform dict has no "t"/"waveform" keys')
                    self.pvs['upload_user1_waveform'].set(False)
                    return

                t = waveform['t']

                y = waveform['waveform']

                freq, binary_waveform = waveform_to_AFG3251_binary(t, y)

                override = self.pvs['upload_frequency_override']._val
                if override:
                    freq = override

                slot = self.pvs['upload_slot']._val

                if self.connected:
                    #We can write the waveform data to the AFG after making sure its in big endian format
                    self.write_binary_values('TRACE:DATA EMEMory,', binary_waveform)
                    if slot != 'ememory':
                        #'copies' the Editable Memory to the target user memory location
                        self.write('data:copy ' +slot+', ememory')

                self.pvs['function_shape'].set(slot)
                #print('set function_shape to ' + slot)
                self.pvs['frequency'].set(float(freq))

            self.pvs['upload_user1_waveform'].set(False)

                #self.write('source1:function '+slot) #sets the AFG source to user1 memory

        


    def _set_user1_waveform(self, waveform):

        self.pvs['user1_waveform']._val = waveform
        autoupload = self.pvs['auto_upload_user1_waveform']._val
        if autoupload:
            if waveform is not None and len(waveform):
                self.pvs['upload_user1_waveform'].set(True)

        #print('_set_user1_waveform')
    
    def _set_user1_waveform_from_file(self, filename):
        self.pvs['user1_waveform_from_file']._val = filename
        if len(filename) and os.path.exists(filename):
            waveform = self.read_file(filename)
            if waveform is not None:
                self._set_user1_waveform(waveform)

    def _get_user1_waveform_from_file(self):
        return self.pvs['user1_waveform_from_file']._val

    def read_file(self, filename='3pulse.tfw'):
        # .tfw (TEKAFG3000) and ArbExpress .wfm; .tfw carries no clock, so the
        # sample rate pv supplies it
        sample_rate = self.pvs['user1_waveform_sample_rate']._val
        return read_afg_waveform_file(filename, sample_rate)

    def _set_frequency(self, freq):
        #time.sleep(.2)
        freq_str = str(freq )
        command = 'source1:Frequency '+freq_str
        self.write(command) #set frequency 

    def _get_frequency(self):
        
        command = 'source1:Frequency?'
        ans = self.ask(command) # get frequency 
        ans = float(ans)
        return ans

    def _set_duration(self, duration):
        
        self.duration = duration

    def _get_duration(self):
        
        ans = self.duration
        return ans
    
    def _set_amplitude(self, amplitude):
        
        a_str='%0.3f'%(amplitude)
        command = 'source1:voltage:amplitude '+a_str
        self.write(command) # sets voltage 

    def _get_amplitude(self):
        
        command = 'source1:voltage:amplitude?'
        ans = self.ask(command) #gets voltage Vpp
        ans = float(ans)
        return ans

    def _set_output_state(self, state):
        
        if state:
            state_str = 'ON'
        else:
            state_str = 'OFF'
        self.write('output1:state ' +state_str) # turns on/off output 1

    def _get_output_state(self):
        
        ans = self.ask('output1:state?') # gets output state
        ans = int(ans)
        return ans

    def _set_n_cycles(self, N):
        
        N_str='%d'%(N)
        command = 'SOURce1:BURSt:NCYCles ' + N_str
        self.write(command) #sets N cycles in burst mode 

    def _get_n_cycles(self):
        
        command = 'SOURce1:BURSt:NCYCles?'
        ans = self.ask(command) #gets N cycles in burst mode 
        ans = int(float(ans))
        return ans

    def _set_function_shape(self, shape):
        
        if type(shape) is str:
            if shape.lower() in self.function_shapes:
                command = 'SOURce1:FUNCtion:SHAPe ' + shape
                self.write(command) #sets shape

    def _get_function_shape(self):
        
        command = 'SOURce1:FUNCtion:SHAPe?'
        ans = self.ask(command) #gets shape
        ans = ans[:-1].lower()
        chars = len(ans)
        shapes = self.function_shapes
        for s in shapes:
            if ans == s[:chars].lower():
                return s
        return 'other'

    def _set_operating_mode(self, mode):
        if 'cont' in mode.lower() or 'cw' in mode.lower():
            command = 'Source1:Freq:Mode CW'
            self.write(command) #sets shape
        if mode.lower() in 'burst n-cycles'.lower():
            command = ':Source1:BURST:STAT ON;:Source1:BURSt:MODE TRIG'
            self.write(command) #sets shape
    
    def _get_operating_mode(self):
        command = 'Source1:Freq:Mode?'
        ans1 = self.ask(command)
        command = 'Source1:BURST:STAT?'
        ans2 = self.ask(command)
        command = 'Source1:BURSt:MODE?'
        ans3 = self.ask(command)
        command = 'SOURce1:BURSt:NCYCles?'
        ans4 = self.ask(command)
        if 'cw' in ans1.lower() and '0' in ans2:
            return 'continuous'
        if '1' in ans2 and 'trig' in ans3.lower():
            return 'burst n-cycles'
        return 'other'
            
    
    def connect(self, hostname):
        self.AFG3000 = None
        self.disconnect()
        rm = visa.ResourceManager()
        resources = rm.list_resources()
        res = None
        for r in resources:
            if hostname in r:
                res = r
                break
        if res is not None:
            # pyvisa code:
            AFG3000 = rm.open_resource(r)
            AFG3000.clear()
            ID = AFG3000.query('*IDN?')
            if ID is not None:
                if len(ID):
                    tokens = ID.split(',')
                    ID = tokens[1]
            #print(ID)
            self.instrument = ID
            #AFG3000.write('*RST') #reset AFG
            self.AFG3000 = AFG3000
            return True
        else:
            return False
      
    

    def disconnect(self):
        if self.connected:
            try:
                if self.AFG3000 is not None:
                    self.AFG3000.clear()
                    self.AFG3000.close()
                    self.AFG3000 = None
                    self.connected = False
                    #print('disconnected')
            except:
                self.AFG3000 = None
                self.connected = False
            
    
