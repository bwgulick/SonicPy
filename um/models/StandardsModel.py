
import os.path, sys

from PyQt5.QtCore import QThread, pyqtSignal

from um.models.pv_model import pvModel
from um.models.pvServer import pvServer
from um.models.StandardDefinitions import STANDARDS, STANDARD_ORDER, normalise


class StandardsModel(pvModel):
    '''
    Holds the selected measurement Standard and applies its pv defaults.

    Exposed as a pv ('Standard:selected') so the mode can be driven from a script or a
    saved setup in the same way as everything else in the app.
    '''

    model_value_changed_signal = pyqtSignal(dict)

    def __init__(self, parent, initial=None):
        pvModel.__init__(self, parent)
        self.pv_server = pvServer()

        self.instrument = 'Standard'
        self.settings_file_tag = 'Standard'
        self.offline = True

        self.initial = normalise(initial)

        self.tasks = {
                'selected':
                        {'desc': 'Standard', 'val': self.initial, 'list': list(STANDARD_ORDER),
                         'param': {'type': 'l'}},
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

    def _set_selected(self, name):
        name = normalise(name)
        self.pvs['selected']._val = name
        self.apply_pv_defaults(name)

    def apply_pv_defaults(self, name):
        standard = STANDARDS[normalise(name)]
        missing = []
        for pv_name, value in standard['pv_defaults'].items():
            try:
                self.pv_server.get_pv(pv_name).set(value)
            except KeyError:
                missing.append(pv_name)
        if missing:
            self.pvs['latest_event'].set('Unknown pv(s): ' + ', '.join(missing))
        else:
            self.pvs['latest_event'].set(standard['title'] + ' Standard applied')
