#!/usr/bin/env python

from audioop import avg
import os
import time
from PyQt5.QtCore import QObject, pyqtSignal
from ua.models.OutputModel import OutputModel
from ua.models.EchoesResultsModel import EchoesResultsModel
from ua.widgets.OutputWidget import OutputWidget

from ua.controllers.OverViewController import OverViewController
from ua.controllers.UltrasoundAnalysisController import UltrasoundAnalysisController
from ua.controllers.ArrowPlotController import ArrowPlotController

from PyQt5 import QtWidgets, QtCore

from um.widgets.UtilityWidgets import save_file_dialog

import csv

############################################################

class OutputController(QObject):

    condition_selected_signal = pyqtSignal(str)

    def __init__(self, overview_controller : OverViewController, 
                    correlation_controller: UltrasoundAnalysisController, 
                        arrow_plot_controller: ArrowPlotController, app=None, 
                            results_model : EchoesResultsModel = EchoesResultsModel()):
        super().__init__()
        self.echoes_results_model = results_model
        self.overview_controller = overview_controller
        self.correlation_controller = correlation_controller
        self.arrow_plot_controller = arrow_plot_controller
        
        self.model = OutputModel(results_model)

        self.widget = OutputWidget()

        self.make_connections()
        if app is not None:
            self.setStyle(app)
        
    def make_connections(self): 
        
        self.widget.output_tw.itemSelectionChanged.connect(self.option_tw_selection_changed_callback)
        self.widget.output_settings_widget.save_btn.clicked.connect(self.save_btn_callback)

    def reset(self):
        self.model.clear()
        self.widget.clear_widget()

    def folders_sorted_signal_callback(self, folders):
        self.model.set_conds(folders)
        self.widget.re_order_rows(folders)

    def option_tw_selection_changed_callback(self, *args):
        row = self.widget.get_selected_output_row()
        conds = self.model.conds
        condition = conds[row]
        self.condition_selected_signal.emit(condition)

    def select_condition(self, condition):
        conds = self.model.conds
        row = conds.index(condition)
        self.widget.select_output(row)

    def save_result(self, package):
        wave_type = package['wave_type']
        optima = package['optima']
        

        # save center opt in the individual MHz files
        # save rest of the result in a seperate [condition]_result.json file
        em = self.echoes_results_model
        centers = {}
        for opt in optima:
            
            optimum = optima[opt]
            filename_waveform = optimum['filename_waveform']
            center = optimum['center_opt']
            centers[filename_waveform]= center
            

            em.save_new_centers(optimum, wave_type)

        em.save_tof_result(package)

    def save_btn_callback(self, **kwargs):
        
        filename = save_file_dialog(self.widget, 'Save as...', self.model.results_model.folder, '*.csv', True)
        if len(filename):
            self.export_table(filename)

    def export_table(self, filename):
        data = self.widget.get_table_data()
        output_csv = filename
        with open(output_csv, "w", newline='') as csv_file:
            writer = csv.writer(csv_file, delimiter=',')
            
            for line in data:
                writer.writerow(line)
            csv_file.close()


    def delete_result(self, clear_info):
        # Per-wave-type tau is no longer displayed here (see the Echo pairs tab).
        pass

    def new_result(self, package):
        self.save_result(package)

    def update_conditions(self):
        conds = self.get_all_conditions()
        self.model.reset()
        self.model.set_conds(conds)
        self.widget.clear_output()
        for c in conds:
            self.widget.add_condition(c)

    def get_all_conditions(self):
        conds = self.overview_controller.get_conditions_list()
        return conds

    def setStyle(self, app):
        from .. import theme 
        from .. import style_path
        self.app = app
        if theme==1:
            WStyle = 'plastique'
            file = open(os.path.join(style_path, "stylesheet.qss"))
            stylesheet = file.read()
            self.app.setStyleSheet(stylesheet)
            file.close()
            self.app.setStyle(WStyle)
        else:
            WStyle = "windowsvista"
            self.app.setStyleSheet(" ")
            #self.app.setPalette(self.win_palette)
            self.app.setStyle(WStyle)