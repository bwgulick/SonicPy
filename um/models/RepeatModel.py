
import os.path, sys

from PyQt5.QtCore import QThread, pyqtSignal

from um.models.pv_model import pvModel
from um.models.pvServer import pvServer


class RepeatModel(pvModel):
    '''
    Back-to-back repeat collection.

    Same handshake idiom as setpointSweep in sweep_model.py, with the positioner leg
    removed: there is nothing to move between collections, so as soon as one acquisition
    has reached its averaging preset and been saved the next one starts immediately.

        run_state True -> (clear waterfall) -> do_collection
        do_collection  -> subscribe scope run_state -> acquire -> scope erase_start True
        scope run_state emits False (num_acq >= num_av)
                       -> detector_done -> subscribe SaveData:save -> SaveData:save True
        SaveData:save emits False (SaveDataModel self-resets)
                       -> save_data_done -> advance
        advance        -> next collection, or run_state False when the count is reached

    n_collections of 0 means keep going until the user presses Stop.
    '''

    model_value_changed_signal = pyqtSignal(dict)

    def __init__(self, parent):
        pvModel.__init__(self, parent)
        self.pv_server = pvServer()

        self.instrument = 'Repeat'
        self.settings_file_tag = 'Repeat'
        self.offline = True

        self.tasks = {
                'n_collections':
                        {'desc': 'Collections', 'val': 10, 'min': 0, 'max': 1000000,
                         'param': {'type': 'i'}},
                'current_collection':
                        {'desc': 'Collected', 'val': 0, 'min': 0, 'max': 1000000,
                         'methods': {'set': False, 'get': True},
                         'param': {'type': 'i'}},
                'run_state':
                        {'desc': 'Repeat;Go/Stop', 'val': False,
                         'param': {'type': 'b'}},
                'clear_waterfall_on_start':
                        {'desc': 'Clear scan view;ON/OFF', 'val': True,
                         'param': {'type': 'b'}},
                'latest_event':
                        {'desc': 'Status', 'val': '',
                         'methods': {'set': False, 'get': True},
                         'param': {'type': 's'}},

                # internal handshake steps
                'do_collection':
                        {'desc': '', 'val': False, 'param': {'type': 'b'}},
                'acquire':
                        {'desc': '', 'val': False, 'param': {'type': 'b'}},
                'detector_done':
                        {'desc': '', 'val': False, 'param': {'type': 'b'}},
                'save_data_set_trigger':
                        {'desc': '', 'val': False, 'param': {'type': 'b'}},
                'save_data':
                        {'desc': '', 'val': False, 'param': {'type': 'b'}},
                'save_data_done':
                        {'desc': '', 'val': False, 'param': {'type': 'b'}},
                'advance_to_next':
                        {'desc': '', 'val': False, 'param': {'type': 'b'}},

                # channel names, matching the conventions in sweep_model.py
                # (MSO54 also reports instrument 'DPO5104', so these work for both scopes)
                'det_trigger_channel':
                        {'desc': 'Detector set', 'val': 'DPO5104:erase_start',
                         'param': {'type': 's'}},
                'det_run_state_channel':
                        {'desc': 'Detector read', 'val': 'DPO5104:run_state',
                         'param': {'type': 's'}},
                'save_data_set_channel':
                        {'desc': 'Save data set', 'val': 'SaveData:save',
                         'param': {'type': 's'}},
                'save_data_read_channel':
                        {'desc': 'Save data read', 'val': 'SaveData:save',
                         'param': {'type': 's'}},
        }

        self.create_pvs(self.tasks)

    #####################################################################
    #  Private set/get functions. Should not be used by external calls  #
    #####################################################################

    def _exit_task(self):
        self._detach_all()

    def _detach_all(self):
        '''Drop any handshake subscriptions left over from an interrupted run.'''
        for channel, handler in ((self.pvs['det_run_state_channel']._val,
                                  self.wait_for_detector_done),
                                 (self.pvs['save_data_read_channel']._val,
                                  self.wait_for_save_data_done)):
            try:
                self.pv_server.get_pv(channel).value_changed_signal.disconnect(handler)
            except (KeyError, TypeError):
                pass

    ### start / stop

    def _set_run_state(self, param):
        currently_running = self.pvs['run_state']._val
        self.pvs['run_state']._val = param
        if param:
            if currently_running:
                return
            if not self._preflight():
                self.pvs['run_state'].set(False)
                return
            if self.pvs['clear_waterfall_on_start']._val:
                try:
                    self.pv_server.get_pv('Waterfall:clear').set(True)
                except KeyError:
                    pass
            self.pvs['current_collection'].set(0)
            self.pvs['latest_event'].set('Collecting...')
            self.pvs['do_collection'].set(True)
        else:
            self._detach_all()
            done = self.pvs['current_collection']._val
            n = self.pvs['n_collections']._val
            if n and done >= n:
                self.pvs['latest_event'].set('Done: %d collection(s)' % done)
            else:
                self.pvs['latest_event'].set('Stopped after %d collection(s)' % done)

    def _preflight(self):
        '''Refuse to start into a state that would deadlock or fight the frequency scan.'''
        try:
            scanning = self.pv_server.get_pv('ScanModel:scan_go')._val
        except KeyError:
            scanning = False
        if scanning:
            self.pvs['latest_event'].set('Cannot repeat while a scan is running')
            return False

        # without the averaging auto-stop the scope never reports done and the loop hangs
        try:
            auto_stop_pv = self.pv_server.get_pv('DPO5104:stop_after_num_av_preset')
            if not auto_stop_pv._val:
                auto_stop_pv.set(True)
                self.pvs['latest_event'].set('Scope auto-stop turned on for repeat')
        except KeyError:
            pass
        return True

    ### one collection

    def _set_do_collection(self, param):
        if not self.pvs['run_state']._val:
            return
        detector_pv = self.pv_server.get_pv(self.pvs['det_run_state_channel']._val)
        detector_pv.value_changed_signal.connect(self.wait_for_detector_done)
        self.pvs['acquire'].set(True)

    def _set_acquire(self, param):
        if param:
            detector_pv = self.pv_server.get_pv(self.pvs['det_trigger_channel']._val)
            detector_pv.set(True)

    def wait_for_detector_done(self, pv, param):
        param = param[0]
        if not param:
            detector_pv = self.pv_server.get_pv(self.pvs['det_run_state_channel']._val)
            try:
                detector_pv.value_changed_signal.disconnect(self.wait_for_detector_done)
            except TypeError:
                pass
            self.pvs['detector_done'].set(True)

    def _set_detector_done(self, param):
        if self.pvs['run_state']._val:
            self.pvs['save_data_set_trigger'].set(True)

    ### save

    def _set_save_data_set_trigger(self, param):
        save_data_pv = self.pv_server.get_pv(self.pvs['save_data_read_channel']._val)
        save_data_pv.value_changed_signal.connect(self.wait_for_save_data_done)
        self.pvs['save_data'].set(True)

    def _set_save_data(self, param):
        if param:
            save_data_pv = self.pv_server.get_pv(self.pvs['save_data_set_channel']._val)
            save_data_pv.set(True)

    def wait_for_save_data_done(self, pv, param):
        param = param[0]
        if not param:
            save_data_pv = self.pv_server.get_pv(self.pvs['save_data_read_channel']._val)
            try:
                save_data_pv.value_changed_signal.disconnect(self.wait_for_save_data_done)
            except TypeError:
                pass
            self.pvs['save_data_done'].set(True)

    def _set_save_data_done(self, param):
        if self.pvs['run_state']._val:
            self.pvs['advance_to_next'].set(True)

    ### advance or finish

    def _set_advance_to_next(self, param):
        done = self.pvs['current_collection']._val + 1
        self.pvs['current_collection'].set(done)

        n = self.pvs['n_collections']._val
        if n == 0 or done < n:
            self.pvs['latest_event'].set('Collected %d' % done)
            self.pvs['do_collection'].set(True)
        else:
            self.pvs['run_state'].set(False)
