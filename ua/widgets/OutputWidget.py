import os, os.path, sys, platform, copy
from functools import partial
from time import sleep
from PyQt5 import uic, QtWidgets,QtCore
from PyQt5.QtWidgets import QMainWindow, QInputDialog, QMessageBox, QErrorMessage
from PyQt5.QtCore import QObject, pyqtSignal, Qt

from um.widgets.CustomWidgets import DoubleSpinBoxAlignRight, HorizontalSpacerItem, VerticalSpacerItem, FlatButton, ListTableWidget, NoRectDelegate

class OutputWidget(QtWidgets.QWidget):
   
    def __init__(self, ctrls = [],params=[]):
        super().__init__()
        
        self._layout = QtWidgets.QVBoxLayout()
        #self._layout.setSpacing(0)
        self._layout.setContentsMargins(8, 12, 0, 0)
        

        self.label = QtWidgets.QLabel("Conditions Selection")
        self.label.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter)
        self.label.setStyleSheet('''font-size: 12pt;''')
        self._layout.addWidget(self.label)

        self.header_lbls = ['Condition']
        self.output_tw = ListTableWidget(columns=len(self.header_lbls))
        self.set_up_tw(self.output_tw, self.header_lbls)

        self._layout.addWidget(self.output_tw)
        self.output_settings_widget = OutputMenuWidget()
        self._layout.addWidget(self.output_settings_widget)

        self.setLayout(self._layout)

    def clear_widget(self):
        self.clear_output()

    def raise_widget(self):
        self.show()
        self.setWindowState(self.windowState() & ~QtCore.Qt.WindowMinimized | QtCore.Qt.WindowActive)
        self.activateWindow()
        #self.raise_()  

    ################################################################################################
    # Now comes all the tw stuff
    ################################################################################################        

    def set_up_tw(self, tw, header_lbls):
        header_view = QtWidgets.QHeaderView(QtCore.Qt.Horizontal, tw)
        tw.setHorizontalHeader(header_view)
        tw.setHorizontalHeaderLabels(header_lbls)
        header_view.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)

        tw.setItemDelegate(NoRectDelegate())

    def add_condition(self, name):
        self.output_tw.blockSignals(True)
        current_rows = self.output_tw.rowCount()
        self.output_tw.setRowCount(current_rows + 1)

        name_item = QtWidgets.QTableWidgetItem(name)
        name_item.setFlags(name_item.flags() & ~QtCore.Qt.ItemIsEditable)
        name_item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.output_tw.setItem(current_rows, 0, name_item)

        self.output_tw.setRowHeight(current_rows, 25)
        self.select_output(current_rows)
        self.output_tw.blockSignals(False)

    def re_order_rows(self, sort_order):
        table_data = self.get_table_data()
        row_names = {row[0]: row for row in table_data}

        for i, name in enumerate(sort_order):
            row = row_names[name]
            self.set_name(i, row[0])

    def select_output(self, ind):
        self.output_tw.blockSignals(True)
        self.output_tw.selectRow(ind)
        self.output_tw.blockSignals(False)

    def get_selected_output_row(self):
        selected = self.output_tw.selectionModel().selectedRows()
        try:
            row = selected[0].row()
        except IndexError:
            row = -1
        return row

    def get_output(self):
        pass

    def clear_output(self):
        num_rows = self.output_tw.rowCount()
        for row in range(num_rows):
            self.del_output(0)
        num_rows = self.output_tw.rowCount()
    

    def del_output(self, ind):
        self.output_tw.blockSignals(True)
        self.output_tw.removeRow(ind)
        self.output_tw.blockSignals(False)
       

        if self.output_tw.rowCount() > ind:
            self.select_output(ind)
        else:
            self.select_output(self.output_tw.rowCount() - 1)
    
    def get_table_data(self):
        rows = self.output_tw.rowCount()
        lines = [['Condition']]
        for row in range(rows):
            lines.append([self.get_name(row)])
        return lines

    def set_name(self, ind, name):
        name_item = self.output_tw.item(ind, 0)
        name_item.setText(name)

    def get_name(self, ind):
        name_item = self.output_tw.item(ind, 0).text()

        return name_item


       ########################################################################################


    

class OutputMenuWidget(QtWidgets.QWidget):
    
    def __init__(self, parent=None, ctrls = [],params=[]):
        super().__init__(parent = parent)  

        self._layout = QtWidgets.QHBoxLayout()
        self._layout.setSpacing(7)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self.save_btn = QtWidgets.QPushButton('Export table')
        #self._layout.addWidget(self.save_btn)

    

        self._layout.addSpacerItem(HorizontalSpacerItem())


        self.setLayout(self._layout)


