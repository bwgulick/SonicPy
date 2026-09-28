

import  time, logging, os, struct, sys, copy

from pyqtgraph.Qt import QtCore
from PyQt5.QtCore import QThread, pyqtSignal, QObject
import queue 
from functools import partial
import json
from um.models.pvServer import pvServer

# ── EPICS bridge (SonicPy ↔ Bluesky) ────────────────────────────────────────────
# Design A: SonicPy is a Channel-Access *client* of an external IOC (the sandbox
# soft IOC `sonicpy_sim_ioc.py`, or the beamline production IOC). Tasks carry
# `epics_PV_in` (an external PV SonicPy monitors → mirrors onto its internal PV) and
# `epics_PV_out` (SonicPy caputs its internal value out to an external PV) tags.
#
# This is INDEPENDENT of the scope/afg VISA-offline flags: the whole point is to let
# Bluesky drive SonicPy while the instruments run offline (noised anvil.csv). Toggle
# the bridge with env SONICPY_EPICS_BRIDGE=0 (defaults on when pyepics imports).
EPICS_BRIDGE_ENABLED = os.environ.get('SONICPY_EPICS_BRIDGE', '1') not in ('0', 'false', 'False', '')
epics_PV = None
if EPICS_BRIDGE_ENABLED:
    try:
        from epics import PV as epics_PV
    except Exception as _e:
        print('SonicPy EPICS bridge: pyepics unavailable (%s) - bridge disabled' % _e)
        EPICS_BRIDGE_ENABLED = False


def _value_changed(new, old):
    """Array-safe scalar `new != old` for the bridge-out change gate.

    A bare `new != old` raises "truth value of an array is ambiguous" when a PV
    carries a numpy array (waveforms: DPO5104:waveform, AFG3251:user1_waveform,
    …). Those PVs are never bridged (no epics_PV_out), but this stays robust if
    one ever is. Returns a plain bool; on any comparison failure assume changed.
    """
    try:
        import numpy as _np
        if isinstance(new, _np.ndarray) or isinstance(old, _np.ndarray):
            return not _np.array_equal(new, old)
    except Exception:
        pass
    try:
        return bool(new != old)
    except Exception:
        return True

class PV(QObject):
    
    value_changed_signal = pyqtSignal(str, list)
    def __init__(self, name='', settings=''):
        super().__init__()
        
        if name == '':
            return
        self._pv_name=name
        self.settings = settings

        if 'desc' in settings:
            self._description = settings['desc']
        if 'val' in settings:
            self._val = settings['val']
        if 'param' in settings:
            types ={'s':str, 'i':int, 'f':float, 'b':bool, 'l':list, 'dict':dict, 'pv':type(PV)}
            self._type = types[settings['param']['type']]
            if self._type == type(PV):
                pass
            if self._type == list:
                self._items = settings['list']
            if self._type == int or self._type == float:
                if 'val_scale' in settings:
                    self._val_scale = self._val_scale = settings['val_scale']
                else : self._val_scale = 1
        if 'methods' in settings:
            if 'get' in settings['methods']:
                self._get_enabled = settings['methods']['get']
            else:
                self._get_enabled = True
            if 'set' in settings['methods']:
                self._set_enabled = settings['methods']['set']
            else:
                self._set_enabled = True
        else:
            self._get_enabled = True
            self._set_enabled = True
        if 'increment' in settings:
            self._increment = settings['increment']
        if 'min' in settings:
            self._min = settings['min']
        if 'max' in settings:
            self._max = settings['max']    
        if 'format' in settings:
            self._format = settings['format']   
        else: self._format = ''
        if 'unit' in settings:
            self._unit = settings['unit']
        else: self._unit = ''

        
        self._epics_PV_out = None
        self._epics_PV_out_name = None
        self._epics_PV_in = None
        self._epics_PV_in_name = None
        self._epics_PV_in_monitor = None
        self._epics_monitor_on = False
        if EPICS_BRIDGE_ENABLED and 'epics_PV_out' in settings:
            try:
                self._epics_PV_out_name = settings['epics_PV_out']
                self._epics_PV_out = epics_PV(self._epics_PV_out_name)
            except Exception:
                self._epics_PV_out = None

    def __str__(self):
        return self._pv_name
    

    def connect_epics_monitor(self):
        # Arm a CA monitor on this PV's external `epics_PV_in`, if it has one, so an
        # external IOC writing that PV mirrors onto our internal PV. No-op otherwise.
        if not (EPICS_BRIDGE_ENABLED and isinstance(self.settings, dict)
                and 'epics_PV_in' in self.settings):
            return
        try:
            self._epics_PV_in_name = self.settings['epics_PV_in']
            self._epics_PV_in = epics_PV(self._epics_PV_in_name)
            self._epics_PV_in_monitor = epicsMonitor(
                self._epics_PV_in, self.handle_epics_pv_callback, autostart=True)
        except Exception:
            self._epics_PV_in_monitor = None

    def handle_epics_pv_callback(self, status):
        # External IOC wrote our epics_PV_in — mirror it onto the internal PV.
        # pyepics delivers char_value (a string); coerce command-style values and
        # then cast to this PV's declared type so validate_params accepts it.
        val = status
        if isinstance(val, str):
            if val in ('0', 'Done'):
                val = False
            elif val in ('1', 'Write'):
                val = True
            else:
                t = getattr(self, '_type', str)
                try:
                    if t is int:
                        val = int(float(val))
                    elif t is float:
                        val = float(val)
                    elif t is bool:
                        val = bool(float(val))
                    else:
                        val = t(val)
                except Exception:
                    return
        setter = getattr(self, 'set', None)
        if setter is not None:
            setter(val)

        

    
class epicsMonitor(QtCore.QObject):
    # Marshals a pyepics CA-thread callback onto the Qt event loop via a signal, so
    # the internal `.set()` (queue-based) is invoked from the Qt side, not the CA
    # thread. char_value is a string; the consumer casts it to the PV's type.
    callback_triggered = QtCore.pyqtSignal(str)

    def __init__(self, pv, callback, debounce_time=None, autostart=False):
        super().__init__()
        self.mcaPV = pv
        self.monitor_On = False
        self.emitted_timestamp = None
        self.callback_triggered.connect(callback)
        if autostart:
            self.SetPVmonitor()

    def SetPVmonitor(self):
        self.mcaPV.clear_callbacks()
        self.mcaPV.add_callback(self.onPVChange)
        self.monitor_On = True

    def unSetPVmonitor(self):
        self.mcaPV.clear_callbacks()
        self.monitor_On = False

    def onPVChange(self, pvname=None, char_value=None, **kws):
        self.callback_triggered.emit(char_value)

class pvModel(QThread):

    # TODO add autosave_settings file support. autosave file would list pvs that need saving.
    # those pvs would be saved when changed and loaded when running __init__

    model_value_changed_signal = pyqtSignal(dict)
    num_pvs = 0
    def __init__(self, parent):
        super().__init__(parent)
        self.my_queue = queue.Queue()
        self.pv_server = pvServer()

        # may use later for synchronous get:
        # self.get_queue = queue.Queue()
        self.instrument = ''
        self.settings_file_tag =''

        self.connected = False
        self.offline = False
        
        self.valid_types = [str, int, float, bool, dict]
        self.validators ={'s':str, 'i':int, 'f':float, 'b':bool, 'l':str, 'dict':dict}

        self.pvs = {}

        ## device speficic:
        
        
        # Task description markup. Aarbitrary default values ('val') are for type recognition in panel widget constructor
        # supported types are float, int, bool, string, and list of strings
        self.tasks = { }

        '''
        Example:
        self.tasks = {'start_freq': 
                                {'desc': 'Start (MHz)', 'val':5.0, 'increment':0.5,'min':1,'max':50 ,
                                'methods':{'set':True, 'get':True}, 
                                'param':{'type':'f'}},
                                ...
                     }
        '''
        

        '''
        child class needs to call:
        self.create_pvs(self.tasks)
        '''

        
        self.start()

        
        

    def clear_queue(self):
        q = self.my_queue
        with q.mutex:
            q.queue.clear()

    def get_tasks(self):
        return self.tasks


    def create_pvs(self, tasks):

        for tag in tasks:
            self.num_pvs = self.num_pvs + 1
            
            task = tasks[tag]
            self.create_pv(tag, task)
            self.pvs[tag].connect_epics_monitor()
   
    def create_pv(self, tag, task):
        pv_name = self.instrument + ':'+tag
        new_pv = PV(pv_name,task)
        
        for method in ['set', 'get']:
            #if task['methods'][method]:
            private_attr ='_'+method+'_'+ tag
            has_private = hasattr(self, private_attr)
            if not has_private:
                
                self._create_default_private_method(method, tag)
            has_private = hasattr(self, private_attr)
            if not has_private:
                print('failed to create "'+ private_attr+ '" method')
            if has_private:
                attr = method+'_task'
                func = self.__getattribute__(attr)
                params = task['param']
                public_method = partial(func, method, tag, params)
                setattr(new_pv,method,public_method)

        pv_name = self.instrument + ':'+tag
        if self.instrument != '':
            self.pv_server.set_pv(pv_name, new_pv)
        self.pvs[tag]=new_pv

    def _default_set_task(self,tag, val):
        self.pvs[tag]._val = val
        
        #print('set: '+ tag+ ' = ' + str(val))

    def _default_get_task(self, tag):
        val = self.pvs[tag]._val
        #print('set: '+ tag+ ' = ' + str(val))
        return val

    def _create_default_private_method(self, method, tag):
        attr = '_'+method+'_'+ tag
        if method == 'set':
            func = partial(self._default_set_task,tag)
        elif method == 'get':
            func = partial(self._default_get_task,tag)

        setattr(self, attr, func)
       
        #print('create private method: _' + method+ '_'+ tag + ' ('+self.instrument+')') 

    def get_task(self,  mode, task, get_params):
        
        task_str = mode+'_'+task
        self.my_queue.put({'task_name': task, 'mode': mode})
        
       

    def set_task(self,  mode, task, desc_params, param_in):
        pv = self.pvs[task]
        valid, params_out = self.validate_params(desc_params, param_in)
        # if parameters have been validated they should be safe to send to device
        if valid:
            task_str = mode+'_'+task
            queue_item = {'task_name': task, 'mode': mode, 'param':params_out}
            #print('put in queue: ' + str(params_out))
            self.my_queue.put(queue_item)
            #print (queue_item)

    def validate_params(self, desc_param, param_in):
        # here is the validator for the param_in
        #print('param_in: ' + str(param_in))
        valid = True
        param_out = None
        param_type = type(param_in)
        #print(param_type)
        valid_type = type(param_in) in self.valid_types
        
        param=desc_param
        if valid_type:
            #print ('valid_type')
            expected_type = self.validators[param['type']]
            param_out = param_in
            if (expected_type == int and type(param_in) == float):
                #print('expected_type')
                param_val = expected_type(param_in)
                param_type  = expected_type
            if (expected_type == bool and type(param_in) == str):
                if param_in == '0' or param_in == 'Done':
                    param_out = False
                    param_type  = expected_type
                if param_in == '1' or param_in == 'Write':
                    param_out = True
                    param_type  = expected_type
            if param_type != expected_type:
                '''print(expected_type)
                print('type invalid')
                print(type(param_in))'''
                valid = False
        #print( str(valid) + ', ' + str(param_out))
        return valid, param_out
            
    def exit(self):
        if self.isRunning():
            self.my_queue.put({'task_name': 'exit'})
        
    def run(self):
        self.go= True
        #epics_wait = 0.05
        # do stuff
        while self.go:
            task = self.my_queue.get()
            #print('task in queue: ' + str(task))
            
            if 'task_name' in task:
                task_name = task['task_name']
                if task_name == 'exit':
                    self._exit_task()
                    self.go = False
                else:
                    mode = task['mode']
                    attr = '_'+mode+'_'+task_name
                    
                    if hasattr(self, attr):
                        func = self.__getattribute__(attr)
                        pv = self.pvs[task_name]
                        if mode == 'set':
                            param = task['param']
                            
                            # param must be validated prior to here !
                            
                            old_val = getattr(pv, '_val', None)
                            try:
                                func(param)
                            except Exception as e:
                                # a raising set handler used to escape this loop and kill the
                                # model thread for good, leaving the panel silently dead
                                print('set failed: ' + self.instrument + ':' + task_name +
                                      ' (' + type(e).__name__ + ': ' + str(e) + ')')
                            pv._val = param

                            # Bridge OUT: mirror a genuine change to the external PV.
                            # Gating on change (not the original inverted `==`) breaks
                            # the echo loop for dual-tagged PVs like scan_go (in+out):
                            # a re-armed in-monitor seeing our own put finds the value
                            # unchanged and does not push again. The change test lives
                            # INSIDE this branch (bridged PVs are always scalar/string)
                            # so array-valued PVs never hit the ambiguous-truth compare.
                            if pv._epics_PV_out is not None and _value_changed(param, old_val):
                                try:
                                    e_param = int(param) if isinstance(param, bool) else param
                                    if pv._epics_PV_in_monitor is not None:
                                        pv._epics_PV_in_monitor.unSetPVmonitor()
                                    pv._epics_PV_out.put(e_param)
                                    if pv._epics_PV_in_monitor is not None:
                                        pv._epics_PV_in_monitor.SetPVmonitor()
                                except Exception:
                                    print('could not put epics pv ' + str(pv._epics_PV_out_name))

                            pv.value_changed_signal.emit(task_name,[param])
                            #print('emit '+ str(task_name) + ', '+ str(param))
                            
                        elif mode == 'get':
                            #print('get... try:  '+ str(task_name))
                            try:
                                ans = func()
                            except:
                                #print('get failed: '+task_name)
                                ans = None
                            #print('get succeeded')
                            # asynchronously send reply
                            if ans is not None:
                                if type(ans) is not dict:
                                    #print(ans)
                                    pass
                                old_ans = getattr(pv, '_val', None)
                                pv._val = ans
                                pv.value_changed_signal.emit(task_name,[ans])
                                # Bridge OUT: push readback changes to the external PV
                                # (for status PVs refreshed via get rather than set).
                                if pv._epics_PV_out is not None \
                                        and not isinstance(ans, dict) \
                                        and _value_changed(ans, old_ans):
                                    try:
                                        e_ans = int(ans) if isinstance(ans, bool) else ans
                                        pv._epics_PV_out.put(e_ans)
                                    except Exception:
                                        print('could not put epics pv ' + str(pv._epics_PV_out_name))
                                #self.get_queue.put(ans)
        #print('Exited thread')

    def save_settings(self, settings_list, filename):
        data_out = self.get_settings(settings_list)

        try:
            with open(filename) as f:
                openned_file = json.load(f)

                tag = self.settings_file_tag
                if tag in openned_file:
                    openned_file[tag] = data_out[tag]
                    data_out = openned_file
        except:
            pass
        
        try:
            with open(filename, 'w') as outfile:
                json.dump(data_out, outfile, sort_keys=True, indent=4)
                outfile.close()
                #print(data_out)
        except:
            pass

    def get_settings(self, settings_list):
        data = {}
        
        for setting in settings_list:
            pv = self.pvs[setting]
            val = pv._val
            
            t = pv._type
            
            data[setting] = val
        
        tag = self.settings_file_tag
        data_out = {tag:data}
        return data_out
        

    def load_settings(self, filename):
        try:
            with open(filename) as f:
                openned_file = json.load(f)

                tag = self.settings_file_tag
                if tag in openned_file:
                    settings = openned_file[tag]
                    return settings
        except:
            pass
        return None

    

    def _exit_task(self):
        pass