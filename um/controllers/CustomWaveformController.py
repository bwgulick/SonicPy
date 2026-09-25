

import os.path

from PyQt5.QtCore import pyqtSignal

from um.models.CustomWaveformModel import CustomWaveformModel
from um.controllers.pv_controller import pvController
from um.widgets.UtilityWidgets import open_file_dialog


class CustomWaveformController(pvController):
    '''
    Panel for the Custom Standard: browse for a waveform file, pick the AFG memory slot,
    upload on demand. The file dialog has to run on the GUI thread, so it lives here
    rather than in the model.
    '''

    def __init__(self, parent, isMain=False):

        model = CustomWaveformModel(parent)
        super().__init__(parent, model, isMain)

        self.panel_items = ['browse',
                            'waveform_file',
                            'use_file_clock',
                            'sample_rate',
                            'slot',
                            '_divider',
                            'points',
                            'afg_frequency',
                            'rep_period',
                            'latest_event',
                            'upload']

        self.init_panel("Custom waveform", self.panel_items)
        self.make_connections()

        if isMain:
            self.show_widget()

    def make_connections(self):
        self.model.pvs['browse'].value_changed_signal.connect(self.browse_callback)

    def browse_callback(self, pv_name, data):
        if not data[0]:
            return
        current = self.model.pvs['waveform_file']._val
        folder = os.path.dirname(current) if current else None
        filename = open_file_dialog(
            self.panel, "Load AFG waveform", directory=folder,
            filter="AFG waveforms (*.tfw *.wfm *.WFM);;All files (*)")
        # open_file_dialog normpaths an empty selection into '.'
        if filename and filename != '.' and os.path.isfile(filename):
            self.model.pvs['waveform_file'].set(filename)
        self.model.pvs['browse'].set(False)

    def show_widget(self):
        self.panel.raise_widget()
