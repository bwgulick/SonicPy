

from PyQt5.QtCore import pyqtSignal

from um.models.SBUWaveformModel import SBUWaveformModel
from um.controllers.pv_controller import pvController


class SBUWaveformController(pvController):
    '''
    Panel for the SBU Standard's fixed broadband pulse. The band comes from the sample
    rate and the echo window from the record length; no carrier frequency is chosen here.
    '''

    def __init__(self, parent, isMain=False):

        model = SBUWaveformModel(parent)
        super().__init__(parent, model, isMain)

        self.panel_items = ['sample_rate',
                            'record_length',
                            'pulse_offset',
                            '_divider',
                            'afg_frequency',
                            'rep_period',
                            'latest_event',
                            'upload']

        self.init_panel("SBU broadband pulse", self.panel_items)

        if isMain:
            self.show_widget()

    def show_widget(self):
        self.panel.raise_widget()
