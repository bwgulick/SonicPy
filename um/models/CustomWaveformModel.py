
import os.path, sys
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal

from um.models.pv_model import pvModel
from um.models.pvServer import pvServer
from um.models.tek_fileIO import read_afg_waveform_file
from um.models.sbu_waveforms import AFG3251_MAX_POINTS


class CustomWaveformModel(pvModel):
    '''
    The Custom Standard's waveform source: load a file from disk and push it to a chosen
    AFG memory slot by hand. Nothing auto-regenerates and nothing uploads until asked.

    Supported: TEKAFG3000 .tfw (no stored clock, so the sample rate pv supplies it) and
    ArbExpress MAGIC 1000 .wfm (stored CLOCK is used unless use_file_clock is off).
    '''

    model_value_changed_signal = pyqtSignal(dict)

    def __init__(self, parent):
        pvModel.__init__(self, parent)
        self.pv_server = pvServer()

        self.instrument = 'CustomWave'
        self.settings_file_tag = 'CustomWaveform'
        self.offline = True

        self.slots = ['user1', 'user2', 'user3', 'user4', 'ememory']

        self.tasks = {
                'waveform_file':
                        {'desc': 'File', 'val': '',
                         'param': {'type': 's'}},
                'browse':
                        {'desc': 'Waveform file;Browse...', 'val': False,
                         'param': {'type': 'b'}},
                'use_file_clock':
                        {'desc': 'Use file clock;ON/OFF', 'val': True,
                         'param': {'type': 'b'}},
                'sample_rate':
                        {'desc': 'Sample rate', 'unit': 'MS/s',
                         'val': 250e6, 'val_scale': 1e6,
                         'min': 1e3, 'max': 2e9, 'increment': 1,
                         'param': {'type': 'f'}},
                'slot':
                        {'desc': 'Upload to', 'val': self.slots[0], 'list': self.slots,
                         'param': {'type': 'l'}},
                'points':
                        {'desc': 'Points', 'val': 0, 'min': 0, 'max': 1e9,
                         'methods': {'set': False, 'get': True},
                         'param': {'type': 'i'}},
                'afg_frequency':
                        {'desc': 'AFG frequency', 'unit': 'Hz',
                         'val': 0.0, 'min': 0, 'max': 1000e6, 'increment': 1,
                         'methods': {'set': False, 'get': True},
                         'param': {'type': 'f'}},
                'rep_period':
                        {'desc': 'Repetition period', 'unit': 'us',
                         'val': 0.0, 'min': 0, 'max': 1e9, 'increment': 1,
                         'methods': {'set': False, 'get': True},
                         'param': {'type': 'f'}},
                'upload':
                        {'desc': 'Upload waveform;Go', 'val': False,
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

    #####################################################################
    #  Private set/get functions. Should not be used by external calls  #
    #####################################################################

    def _exit_task(self):
        pass

    def _set_waveform_file(self, filename):
        self.pvs['waveform_file']._val = filename
        if filename:
            self.load()

    def _set_use_file_clock(self, val):
        self.pvs['use_file_clock']._val = val
        if self.pvs['waveform_file']._val:
            self.load()

    def _set_sample_rate(self, val):
        self.pvs['sample_rate']._val = float(val)
        if self.pvs['waveform_file']._val and not self.pvs['use_file_clock']._val:
            self.load()

    def load(self):
        '''Read the file into 'waveform' and update the derived readouts. No upload.'''
        filename = self.pvs['waveform_file']._val
        if not filename or not os.path.isfile(filename):
            self.pvs['latest_event'].set('File not found')
            return None

        rate = self.pvs['sample_rate']._val
        use_file_clock = self.pvs['use_file_clock']._val
        # .tfw stores no clock, so it always needs the pv value
        waveform = read_afg_waveform_file(filename, None if use_file_clock else rate)
        if waveform is None and use_file_clock:
            waveform = read_afg_waveform_file(filename, rate)

        if waveform is None:
            self.pvs['latest_event'].set('Could not read ' + os.path.split(filename)[-1])
            return None

        points = waveform['points']
        clock = waveform['clock']
        freq = clock / points

        self.pvs['waveform'].set(waveform)
        self.pvs['points'].set(int(points))
        self.pvs['afg_frequency'].set(round(freq, 3))
        self.pvs['rep_period'].set(round(points / clock * 1e6, 4))

        msg = 'Loaded %s: %d pts @ %.4g MS/s' % (
            os.path.split(filename)[-1], points, clock / 1e6)
        if points > AFG3251_MAX_POINTS:
            msg += ' - EXCEEDS %d pt AFG memory' % AFG3251_MAX_POINTS
        self.pvs['latest_event'].set(msg)
        return waveform

    def _set_upload(self, val):
        self.pvs['upload']._val = val
        if not val:
            return
        try:
            waveform = self.pvs['waveform']._val
            if not waveform:
                waveform = self.load()
            if not waveform:
                self.pvs['upload'].set(False)
                return

            points = waveform['points']
            if points > AFG3251_MAX_POINTS:
                self.pvs['latest_event'].set(
                    'Refused: %d pts exceeds the %d pt AFG arb memory' % (
                        points, AFG3251_MAX_POINTS))
                self.pvs['upload'].set(False)
                return

            freq = waveform['clock'] / points

            self.pv_server.get_pv('AFG3251:upload_slot').set(self.pvs['slot']._val)
            self.pv_server.get_pv('AFG3251:upload_frequency_override').set(
                float(round(freq, 3)))
            self.pv_server.get_pv(self.pvs['output_channel']._val).set(waveform)
            self.pv_server.get_pv('AFG3251:upload_user1_waveform').set(True)

            self.pvs['latest_event'].set(
                'Uploaded %d pts to %s (%.4g Hz)' % (points, self.pvs['slot']._val, freq))
        except Exception as e:
            self.pvs['latest_event'].set('Upload failed: ' + str(e))
        self.pvs['upload'].set(False)
