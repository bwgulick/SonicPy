
import os.path, sys
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal

from um.models.pv_model import pvModel
from um.models.pvServer import pvServer
from um.models.sbu_waveforms import (sbu_waveform, pulse_length,
                                     SBU_DEFAULT_SAMPLE_RATE,
                                     SBU_DEFAULT_RECORD_LENGTH,
                                     SBU_DEFAULT_PULSE_OFFSET,
                                     AFG3251_MAX_POINTS)


class SBUWaveformModel(pvModel):
    '''
    The SBU Standard's waveform source: a fixed broadband impulse in a long record.

    Nothing here recomputes on its own - unlike the HPCAT generator chain, the waveform
    only reaches the AFG when 'upload' is pressed.
    '''

    model_value_changed_signal = pyqtSignal(dict)

    def __init__(self, parent):
        pvModel.__init__(self, parent)
        self.pv_server = pvServer()

        self.instrument = 'SBUWave'
        self.settings_file_tag = 'SBUWaveform'
        self.offline = True

        self.tasks = {
                'sample_rate':
                        {'desc': 'Sample rate', 'unit': 'MS/s',
                         'val': SBU_DEFAULT_SAMPLE_RATE, 'val_scale': 1e6,
                         'min': 1e3, 'max': 2e9, 'increment': 1,
                         'param': {'type': 'f'}},
                'record_length':
                        {'desc': 'Record length', 'unit': 'pts',
                         'val': SBU_DEFAULT_RECORD_LENGTH,
                         'min': pulse_length(), 'max': AFG3251_MAX_POINTS,
                         'param': {'type': 'i'}},
                'pulse_offset':
                        {'desc': 'Pulse position', 'unit': 'pts',
                         'val': SBU_DEFAULT_PULSE_OFFSET,
                         'min': 0, 'max': AFG3251_MAX_POINTS,
                         'param': {'type': 'i'}},
                'afg_frequency':
                        {'desc': 'AFG frequency', 'unit': 'Hz',
                         'val': 2500.0, 'min': 0, 'max': 1000e6, 'increment': 1,
                         'methods': {'set': False, 'get': True},
                         'param': {'type': 'f'}},
                'rep_period':
                        {'desc': 'Repetition period', 'unit': 'us',
                         'val': 400.0, 'min': 0, 'max': 1e9, 'increment': 1,
                         'methods': {'set': False, 'get': True},
                         'param': {'type': 'f'}},
                'upload':
                        {'desc': 'Upload pulse;Go', 'val': False,
                         'param': {'type': 'b'}},
                'waveform':
                        {'desc': 'Waveform', 'val': {},
                         'param': {'type': 'dict'}},
                'output_channel':
                        {'desc': 'Output channel', 'val': 'AFG3251:user1_waveform',
                         'param': {'type': 's'}},
                'latest_event':
                        {'desc': 'Status', 'val': '',
                         'methods': {'set': False, 'get': True},
                         'param': {'type': 's'}},
        }

        self.create_pvs(self.tasks)
        self._refresh_derived()

    #####################################################################
    #  Private set/get functions. Should not be used by external calls  #
    #####################################################################

    def _exit_task(self):
        pass

    def _derived(self):
        rate = float(self.pvs['sample_rate']._val)
        points = int(self.pvs['record_length']._val)
        points = max(pulse_length(), min(points, AFG3251_MAX_POINTS))
        freq = rate / points
        period_us = points / rate * 1e6
        return rate, points, freq, period_us

    def _refresh_derived(self):
        rate, points, freq, period_us = self._derived()
        self.pvs['afg_frequency'].set(round(freq, 3))
        self.pvs['rep_period'].set(round(period_us, 4))

    def _set_sample_rate(self, val):
        self.pvs['sample_rate']._val = float(val)
        self._refresh_derived()

    def _set_record_length(self, val):
        val = int(val)
        if val > AFG3251_MAX_POINTS:
            val = AFG3251_MAX_POINTS
            self.pvs['latest_event'].set(
                'Record length clamped to %d points (AFG arb memory)' % AFG3251_MAX_POINTS)
        if val < pulse_length():
            val = pulse_length()
        self.pvs['record_length']._val = val
        self._refresh_derived()

    def _set_pulse_offset(self, val):
        self.pvs['pulse_offset']._val = int(val)

    def build_waveform(self):
        rate, points, freq, period_us = self._derived()
        params = {'sample_rate': rate,
                  'record_length': points,
                  'pulse_offset': self.pvs['pulse_offset']._val}
        return sbu_waveform(params), freq

    def _set_upload(self, val):
        self.pvs['upload']._val = val
        if not val:
            return
        try:
            waveform, freq = self.build_waveform()
            self.pvs['waveform'].set(waveform)

            afg_freq = self.pv_server.get_pv('AFG3251:upload_frequency_override')
            afg_wave = self.pv_server.get_pv(self.pvs['output_channel']._val)
            afg_upload = self.pv_server.get_pv('AFG3251:upload_user1_waveform')

            # pin the record frequency explicitly: the generic upload path derives it from
            # the time axis and is off by one sample interval
            afg_freq.set(float(round(freq, 3)))
            afg_wave.set(waveform)
            afg_upload.set(True)

            self.pvs['latest_event'].set(
                'Uploaded %d pts @ %.4g MS/s (%.4g Hz)' % (
                    waveform['points'], waveform['clock'] / 1e6, freq))
        except Exception as e:
            self.pvs['latest_event'].set('Upload failed: ' + str(e))
        self.pvs['upload'].set(False)
