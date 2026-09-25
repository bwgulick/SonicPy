

import os

from PyQt5.QtCore import QObject, pyqtSignal

from um.models.StandardsModel import StandardsModel
from um.models.StandardDefinitions import STANDARDS, STANDARD_ORDER, normalise
from um.models.pvServer import pvServer


class StandardsController(QObject):
    '''
    Binds the Standard selector buttons in the main window to 'Standard:selected',
    swaps the visible panel set, and remembers the choice in devices/standard.txt.

    Deliberately a plain QObject rather than a pvController: the Standard is chosen from
    the button row, not from a panel of its own.
    '''

    standardChangedSignal = pyqtSignal(str)

    def __init__(self, parent, display_window, initial=None, settings_file=None):
        super().__init__()
        self.pv_server = pvServer()
        self.display_window = display_window
        self.settings_file = settings_file

        self.model = StandardsModel(parent, initial)
        self.current = normalise(initial)

        self.buttons = display_window.standard_btns
        self.make_connections()

    def make_connections(self):
        for name, btn in self.buttons.items():
            btn.toggled.connect(self._make_button_handler(name))
        self.model.pvs['selected'].value_changed_signal.connect(self.selected_changed_callback)

    def _make_button_handler(self, name):
        def handler(checked):
            if checked and name != self.current:
                self.model.pvs['selected'].set(name)
        return handler

    def selected_changed_callback(self, pv_name, data):
        self.apply(data[0])

    def apply(self, name):
        '''Apply a Standard to the UI. The pv side is done by the model's set handler.'''
        name = normalise(name)
        self.current = name
        standard = STANDARDS[name]

        visible = list(standard['left']) + list(standard['right'])
        self.display_window.show_panels(visible)

        btn = self.buttons.get(name)
        if btn is not None and not btn.isChecked():
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)

        self.save_choice(name)
        self.standardChangedSignal.emit(name)

    def apply_initial(self):
        '''
        Called once at the end of startup, after every model and panel exists. Applies
        both the pv defaults and the panel set for the Standard loaded from disk.
        '''
        name = self.current
        self.model.apply_pv_defaults(name)
        self.apply(name)

    def save_choice(self, name):
        if not self.settings_file:
            return
        try:
            with open(self.settings_file, 'w') as f:
                f.write(name + '\n')
        except OSError:
            pass

    def exit(self):
        self.model.exit()
