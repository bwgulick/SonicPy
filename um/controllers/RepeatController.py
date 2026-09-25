

from PyQt5.QtCore import pyqtSignal

from um.models.RepeatModel import RepeatModel
from um.controllers.pv_controller import pvController
from um.models.pvServer import pvServer


class RepeatController(pvController):
    '''
    Repeat collection panel, available in every Standard. Emits start/done so the main
    controller can disable the rest of the UI the same way it does for a scan.
    '''

    repeatStartedSignal = pyqtSignal()
    repeatDoneSignal = pyqtSignal()

    def __init__(self, parent, isMain=False):

        model = RepeatModel(parent)
        super().__init__(parent, model, isMain)
        self.pv_server = pvServer()

        self.panel_items = ['n_collections',
                            'current_collection',
                            'clear_waterfall_on_start',
                            'latest_event',
                            'run_state']

        self.init_panel("Repeat collect", self.panel_items)
        self.make_connections()

        if isMain:
            self.show_widget()

    def make_connections(self):
        self.model.pvs['run_state'].value_changed_signal.connect(self.run_state_changed_callback)

    def run_state_changed_callback(self, tag, data):
        state = data[0]
        if state:
            self.repeatStartedSignal.emit()
        else:
            self.repeatDoneSignal.emit()

    def is_running(self):
        return bool(self.model.pvs['run_state']._val)

    def show_widget(self):
        self.panel.raise_widget()
