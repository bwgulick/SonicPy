#!/usr/bin/env python


import os, os.path
from PyQt5 import uic, QtWidgets,QtCore, QtGui
from PyQt5.QtWidgets import QMainWindow, QInputDialog, QMessageBox, QErrorMessage
from PyQt5.QtCore import QObject, pyqtSignal, Qt

from pyqtgraph import QtCore, mkPen, mkColor, hsvColor, ViewBox
from um.widgets.CustomWidgets import HorizontalSpacerItem, VerticalSpacerItem, FlatButton


from .. import style_path, icons_path, title

class TimeOfFlightWidget(QMainWindow):
    
    preferences_signal = pyqtSignal()
    up_down_signal = pyqtSignal(str)
    panelClosedSignal = pyqtSignal()

    def __init__(self, app, overview_widget, multiple_frequencies_widget, analysis_widget, arrow_plot_widget, output_widget):
        super().__init__()
        self.app = app
        self.overview_widget = overview_widget

        self.multiple_frequencies_widget = multiple_frequencies_widget
        self.analysis_widget = analysis_widget
        self.output_widget = output_widget
        self.arrow_plot_widget = arrow_plot_widget

        self.setWindowTitle(title)

        self.resize(1440, 790)

        self.make_widget()

        self.create_menu()
        self.style_widgets()

        self.key_control_pressed = False

    def clear_title(self):
        self.setWindowTitle(title)

    def create_menu(self):
        
        menuBar = self.menuBar()
        # Creating menus using a QMenu object
        file_menu = QtWidgets.QMenu("&File", self)
        menuBar.addMenu(file_menu)
        # Creating menus using a title


        self.proj_new_act = QtWidgets.QAction('&New project', self)        
        file_menu.addAction(self.proj_new_act)
        self.proj_open_act = QtWidgets.QAction('&Open project', self)        
        file_menu.addAction(self.proj_open_act)
        self.proj_save_act = QtWidgets.QAction('&Save project', self)  
        self.proj_save_act.setEnabled(False)     
        file_menu.addAction(self.proj_save_act)
        self.proj_save_as_act = QtWidgets.QAction('Save project &as...', self)  
        self.proj_save_as_act.setEnabled(False)
        file_menu.addAction(self.proj_save_as_act)
        self.proj_close_act = QtWidgets.QAction('&Close project', self)        
        file_menu.addAction(self.proj_close_act)
        self.proj_close_act.setEnabled(False)

        file_menu.addSeparator()

        self.import_menu_mnu = QtWidgets.QMenu("&Import ultrasound data", self)
        self.import_menu_mnu.setEnabled(False)
        file_menu.addMenu(self.import_menu_mnu)
        self.import_multiple_freq_act = QtWidgets.QAction('&Discrete 𝑓', self)        
        self.import_menu_mnu.addAction(self.import_multiple_freq_act)
        self.import_broadband_act = QtWidgets.QAction('&Broadband', self)        
        self.import_menu_mnu.addAction(self.import_broadband_act)
        self.sort_data_act = QtWidgets.QAction('&Sort data points', self)        
        file_menu.addAction(self.sort_data_act)
        self.sort_data_act.setEnabled(False)

        file_menu.addSeparator()

        self.export_menu_mnu = QtWidgets.QMenu("&Export", self)
        self.export_menu_mnu.setEnabled(False)
        file_menu.addMenu(self.export_menu_mnu)
        self.export_results_act = QtWidgets.QAction(f'\N{GREEK SMALL LETTER TAU} results', self)        
        self.export_menu_mnu.addAction(self.export_results_act)
        self.export_overview_mnu = QtWidgets.QMenu('&Overview', self)        
        self.export_menu_mnu.addMenu(self.export_overview_mnu)

        self.export_single_frequency_plot_act = QtWidgets.QAction('&Single 𝑓', self)        
        self.export_overview_mnu.addAction(self.export_single_frequency_plot_act)
        self.export_single_condition_plot_act = QtWidgets.QAction('&Single condition', self)        
        self.export_overview_mnu.addAction(self.export_single_condition_plot_act)

        self.export_correlation_mnu = QtWidgets.QMenu("&Correlation", self)  
        self.export_menu_mnu.addMenu(self.export_correlation_mnu)

        self.export_selected_waveform_plot_act = QtWidgets.QAction('&Selected waveform', self)        
        self.export_correlation_mnu.addAction(self.export_selected_waveform_plot_act)
        self.export_selected_ehcoes_plot_act = QtWidgets.QAction('&Selected echoes', self)        
        self.export_correlation_mnu.addAction(self.export_selected_ehcoes_plot_act)
        self.export_filtered_echoes_plot_act = QtWidgets.QAction('&Filtered', self)        
        self.export_correlation_mnu.addAction(self.export_filtered_echoes_plot_act)
        self.export_correlation_plot_act = QtWidgets.QAction('&Correlation', self)        
        self.export_correlation_mnu.addAction(self.export_correlation_plot_act)

        self.export_arrow_plot_act = QtWidgets.QAction('&Inverse 𝑓', self)
        self.export_menu_mnu.addAction(self.export_arrow_plot_act)

        # View menu: toggle visibility / re-docking of each panel
        view_menu = QtWidgets.QMenu("&View", self)
        menuBar.addMenu(view_menu)
        for dock in getattr(self, 'docks', []):
            view_menu.addAction(dock.toggleViewAction())

    def keyPressEvent(self, e):
        
        if e.key() == Qt.Key_Control:
            pass
            
        elif e.key() == Qt.Key_Up:
            event = 'up'
        elif e.key() == Qt.Key_Down:
            event = 'down'

        else: 
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        
        if e.key() == Qt.Key_Control:
            pass
            
        else:
            super().keyReleaseEvent(e)


    def closeEvent(self, QCloseEvent, *event):
        self.app.closeAllWindows()
        self.panelClosedSignal.emit()

    def make_widget(self):
        # Every panel lives in its own dock so the user can drag, float, tab, or
        # hide it freely.  A hidden zero-content central widget lets the docks
        # fill the whole window.
        self.setDockNestingEnabled(True)
        dummy_central = QtWidgets.QWidget()
        dummy_central.setMaximumSize(0, 0)
        self.setCentralWidget(dummy_central)
        self.centralWidget().hide()

        self.overview_dock = self._make_dock('Overview', self.overview_widget)
        self.analysis_dock = self._make_dock('Echo Selection', self.analysis_widget)
        self.multiple_frequencies_dock = self._make_dock('Multiple frequencies', self.multiple_frequencies_widget)
        self.arrow_plot_dock = self._make_dock('Inverse 𝑓', self.arrow_plot_widget)
        self.output_dock = self._make_dock('Results output', self.output_widget)

        # The Echoes and Echo pairs tables live inside the Echo Selection widget
        # but the user wants to move/resize them independently, so pull them out
        # into their own docks. Reparenting into a QDockWidget removes them from
        # the analysis widget's layout; all controller references (echoes_tw,
        # pairs_tw, combos, buttons) stay valid because the widgets are unchanged.
        self.echoes_dock = self._make_dock('Echoes', self.analysis_widget.echoes_group)
        self.pairs_dock = self._make_dock('Echo pairs', self.analysis_widget.pairs_group)

        # Reproduce the original three-column layout:
        #   Overview | Echo Selection / Echoes / Echo pairs / Multiple frequencies
        #           | Inverse 𝑓 / Results output
        self.addDockWidget(Qt.LeftDockWidgetArea, self.overview_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.analysis_dock)
        self.splitDockWidget(self.analysis_dock, self.arrow_plot_dock, Qt.Horizontal)
        self.splitDockWidget(self.analysis_dock, self.echoes_dock, Qt.Vertical)
        self.splitDockWidget(self.echoes_dock, self.pairs_dock, Qt.Vertical)
        self.splitDockWidget(self.pairs_dock, self.multiple_frequencies_dock, Qt.Vertical)
        self.splitDockWidget(self.arrow_plot_dock, self.output_dock, Qt.Vertical)

        self.resizeDocks(
            [self.overview_dock, self.analysis_dock, self.arrow_plot_dock],
            [600, 600, 600], Qt.Horizontal)
        # Give the plot the lion's share; the tables get a usable, resizable slice.
        self.resizeDocks(
            [self.analysis_dock, self.echoes_dock, self.pairs_dock,
             self.multiple_frequencies_dock],
            [340, 150, 170, 130], Qt.Vertical)

        self.docks = [self.overview_dock, self.analysis_dock,
                      self.echoes_dock, self.pairs_dock,
                      self.multiple_frequencies_dock, self.arrow_plot_dock,
                      self.output_dock]

    def _make_dock(self, title, widget):
        dock = QtWidgets.QDockWidget(title, self)
        dock.setObjectName(title.replace(' ', '_'))
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable |
                         QtWidgets.QDockWidget.DockWidgetFloatable |
                         QtWidgets.QDockWidget.DockWidgetClosable)
        return dock

    

        


    def style_widgets(self):
        
        self.setStyleSheet("""
            #scope_waveform_widget FlatButton {
                min-width: 70;
                max-width: 70;
            }
            #scope_waveform_widget QLabel {
                min-width: 110;
                max-width: 110;
            }
            #controls_sidebar QLineEdit {
                min-width: 120;
                max-width: 120;
            }
            #controls_sidebar QLabel {
                min-width: 110;
                max-width: 110;
            }
            
        """)

    
 
 
    def create_menu_strip(self, orientation = "horizontal"):

        self._menu_layout = None
        if orientation == 'horizontal':
            self._menu_layout = QtWidgets.QHBoxLayout()
            spacer = QtWidgets.QSpacerItem(30, 10, QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        elif orientation == 'vertical':
            self._menu_layout = QtWidgets.QVBoxLayout()
            spacer = QtWidgets.QSpacerItem(10, 30, QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        if self._menu_layout !=None:

            self.save_as_btn = FlatButton()
            self.save_as_btn.setEnabled(False)
            self.save_btn = FlatButton()
            self.save_btn.setEnabled(False)
            self.load_btn = FlatButton()
            self.undo_btn = FlatButton()
            self.reset_btn = FlatButton()

            self._menu_layout.setContentsMargins(5, 0, 3, 0)
            self._menu_layout.setSpacing(5)

            self._menu_layout.addSpacerItem(spacer)
            self._menu_layout.addWidget(self.load_btn)
            self._menu_layout.addWidget(self.save_btn)
            self._menu_layout.addWidget(self.save_as_btn)
            self._menu_layout.addSpacerItem(spacer)
            self._menu_layout.addWidget(self.undo_btn)
            self._menu_layout.addWidget(self.reset_btn)
            self._menu_layout.addSpacerItem(spacer)

            self.style_menu_buttons()

    def style_menu_buttons(self):

            
        button_height = 32
        button_width = 32

        icon_size = QtCore.QSize(22, 22)
        self.save_btn.setIcon(QtGui.QIcon(os.path.join(icons_path, 'save.ico')))
        self.save_btn.setIconSize(icon_size)
        self.save_btn.setMinimumHeight(button_height)
        self.save_btn.setMaximumHeight(button_height)
        self.save_btn.setMinimumWidth(button_width)
        self.save_btn.setMaximumWidth(button_width)

        self.save_as_btn.setIcon(QtGui.QIcon(os.path.join(icons_path, 'save_as.ico')))
        self.save_as_btn.setIconSize(icon_size)
        self.save_as_btn.setMinimumHeight(button_height)
        self.save_as_btn.setMaximumHeight(button_height)
        self.save_as_btn.setMinimumWidth(button_width)
        self.save_as_btn.setMaximumWidth(button_width)

        self.load_btn.setIcon(QtGui.QIcon(os.path.join(icons_path, 'open.ico')))
        self.load_btn.setIconSize(icon_size)
        self.load_btn.setMinimumHeight(button_height)
        self.load_btn.setMaximumHeight(button_height)
        self.load_btn.setMinimumWidth(button_width)
        self.load_btn.setMaximumWidth(button_width)

        self.undo_btn.setIcon(QtGui.QIcon(os.path.join(icons_path, 'undo.ico')))
        self.undo_btn.setIconSize(icon_size)
        self.undo_btn.setMinimumHeight(button_height)
        self.undo_btn.setMaximumHeight(button_height)
        self.undo_btn.setMinimumWidth(button_width)
        self.undo_btn.setMaximumWidth(button_width)

        self.reset_btn.setIcon(QtGui.QIcon(os.path.join(icons_path, 'restore.ico')))
        self.reset_btn.setIconSize(icon_size)
        self.reset_btn.setMinimumHeight(button_height)
        self.reset_btn.setMaximumHeight(button_height)
        self.reset_btn.setMinimumWidth(button_width)
        self.reset_btn.setMaximumWidth(button_width)

    def preferences_module(self):
        self.preferences_signal.emit()

    def raise_widget(self):
        self.show()
        self.setWindowState(self.windowState() & ~QtCore.Qt.WindowMinimized | QtCore.Qt.WindowActive)
        self.activateWindow()
        self.raise_()  




