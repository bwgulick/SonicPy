#!/usr/bin/env python


import os, os.path, sys, platform, copy
from PyQt5 import uic, QtWidgets,QtCore
from PyQt5.QtWidgets import QMainWindow, QInputDialog, QMessageBox, QErrorMessage, QWidget
from PyQt5.QtCore import QObject, pyqtSignal, Qt

import pyqtgraph as pg
from pyqtgraph import QtCore, mkPen, mkColor, hsvColor, ViewBox
#from pyqtgraph.Qt import qWait
from um.widgets.CustomWidgets import HorizontalSpacerItem, VerticalSpacerItem, FlatButton, DoubleSpinBoxAlignRight, ListTableWidget, NoRectDelegate
import numpy as np

from um.widgets.PltWidget import SimpleDisplayWidget
from functools import partial

class UltrasoundAnalysisWidget(QWidget):
    
    preferences_signal = pyqtSignal()
    up_down_signal = pyqtSignal(str)
    panelClosedSignal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.initialized = False
        self.t = None
        self.spectrum = None


        self.setWindowTitle('Echo Selection')

        
        self.make_widget()


        self.create_plots()
    
     

    def clear(self):
        self.plot_widget.setText('',0)
        self.update_view([],[],'')

        self._reset_regions()

        self.clear_detail_plots()

    def _reset_regions(self):
        '''Trim both wave-type region lists back to the default two echoes and
        zero them. Extra regions are removed from the plot.'''
        for regions in (self.echo_bounds_p, self.echo_bounds_s):
            while len(regions) > 2:
                r = regions.pop()
                try:
                    self.plot_win.removeItem(r)
                except Exception:
                    pass
        for r in self.echo_bounds_p + self.echo_bounds_s:
            r.setRegion([0, 0])
        self._refresh_region_aliases()

    def clear_detail_plots(self):
        out = [[],[]]
        self.detail_plot0.setData(*out)
        self.detail_plot0_bg.setData(*out)
        self.detail_plot1.setData(*out)
        self.detail_plot1_bg.setData(*out)
        self.detail_plot2.setData(*out)
        self.detail_plot2_bg.setData(*out)


    def create_plots(self):

        
        self.plot_win = self.plot_widget.fig.win 
        self.plot_win.create_plots([],[],[],[],'Time')
        self.plot_win.set_colors( { 
                        'data_color': '#7AE7FF',\
                        'rois_color': '#FF6977', \
                        })
        self._CH1_plot = self.plot_win.plotForeground
        self.plot_demodulated = self.plot_win.plotRoi


        self.main_plot = self.plot_win.plotForeground

        self.plot_win_detail0 = self.detail_win0.fig.win
        self.plot_win_detail1 = self.detail_win1.fig.win
        self.plot_win_detail2 = self.detail_win2.fig.win

        detail_plot0 = self.detail_win0.fig.win
        detail_plot0.create_plots([],[],[],[],'Time')
        detail_plot0.set_colors( { 
                        'data_color': (0,200,255),\
                        'rois_color': (255,0,100), \
                        })
        self.detail_plot0 = detail_plot0.plotForeground
        self.detail_plot0_bg = detail_plot0.plotRoi
        self.detail_win0.setText('Echo 1' , 0)
        self.detail_win0.setText('Echo 2' , 1)

        detail_plot1 = self.detail_win1.fig.win
        detail_plot1.create_plots([],[],[],[],'Time')
        detail_plot1.set_colors( { 
                        'data_color': (0,200,255),\
                        'rois_color': (255,0,100), \
                        })
        self.detail_plot1 = detail_plot1.plotForeground
        self.detail_plot1_bg = detail_plot1.plotRoi
        self.detail_win1.setText('Echo 1' , 0)
        self.detail_win1.setText('Echo 2' , 1)

        detail_plot2 = self.detail_win2.fig.win
        detail_plot2.create_plots([],[],[],[],f'\N{GREEK SMALL LETTER TAU} (s)')
        detail_plot2.set_colors( { 
                        'data_color': (0,255,100),\
                        })
        self.detail_plot2 = detail_plot2.plotForeground
        self.detail_plot2_bg = pg.PlotDataItem([], [], title="",
                        antialias=True, pen=None, symbolBrush=(0,255,100,150), symbolPen=None)
        self.plot_win_detail2.addItem(self.detail_plot2_bg)
        self.detail_win2.setText('Correlation' , 0)
        
        

        # Dynamic per-wave-type lists of echo regions. Seeded with two echoes
        # each to match the historical fixed lr1/lr2 behaviour; the user can
        # add/remove more via the Echo Selection controls.
        self.current_wave_type = 'P'
        self.echo_bounds_p = [self._new_region(1), self._new_region(2)]
        self.echo_bounds_s = [self._new_region(1), self._new_region(2)]

        # P shown by default
        for r in self.echo_bounds_p:
            self.plot_win.addItem(r)

        self._refresh_region_aliases()

    def _new_region(self, number):
        '''Create a numbered LinearRegionItem for an echo window.'''
        region = pg.LinearRegionItem()
        region.setZValue(-10)
        region.setRegion([0, 0])
        try:
            region.echo_label = pg.InfLineLabel(region.lines[1], text=str(number),
                                                position=0.92, color=(200, 200, 200))
        except Exception:
            region.echo_label = None
        return region

    def set_region_label(self, region, text):
        '''Update the on-plot label of an echo region to show its name.'''
        label = getattr(region, 'echo_label', None)
        if label is None:
            return
        try:
            label.setFormat(str(text))
        except Exception:
            try:
                label.setText(str(text))
            except Exception:
                pass

    def _refresh_region_aliases(self):
        '''Keep the historical lr1_p/lr2_p/lr1_s/lr2_s names pointing at the
        first two echoes of each wave type so legacy callers keep working.'''
        self.lr1_p = self.echo_bounds_p[0]
        self.lr2_p = self.echo_bounds_p[1]
        self.lr1_s = self.echo_bounds_s[0]
        self.lr2_s = self.echo_bounds_s[1]

    def _regions_for(self, wave_type):
        return self.echo_bounds_p if wave_type == 'P' else self.echo_bounds_s

    def echo_count(self, wave_type):
        return len(self._regions_for(wave_type))

    def _centered_window(self):
        '''Return an [l, r] window centered in the main plot's current x-view so a
        newly added echo is immediately visible and grabbable (rather than sitting
        at t=0, off-screen). Width follows echo_width (ns) when it fits, otherwise
        ~8% of the current view.'''
        try:
            xmin, xmax = self.main_plot.getViewBox().viewRange()[0]
        except Exception:
            xmin, xmax = 0.0, 0.0
        span = xmax - xmin
        if span <= 0:
            return [0, 0]
        center = xmin + span / 2.0
        try:
            width = float(self.echo_width.value()) * 1e-9
        except Exception:
            width = 0.0
        if width <= 0 or width > span:
            width = span * 0.08
        return [center - width / 2.0, center + width / 2.0]

    def add_echo_region(self, wave_type):
        '''Append a new echo region for wave_type. Returns its index.'''
        regions = self._regions_for(wave_type)
        region = self._new_region(len(regions) + 1)
        region.setRegion(self._centered_window())
        regions.append(region)
        if self.current_wave_type == wave_type:
            self.plot_win.addItem(region)
        self._refresh_region_aliases()
        return len(regions) - 1

    def remove_echo_region(self, wave_type):
        '''Remove the last echo region for wave_type, keeping a minimum of two.
        Returns True if one was removed.'''
        regions = self._regions_for(wave_type)
        if len(regions) > 2:
            region = regions.pop()
            try:
                self.plot_win.removeItem(region)
            except Exception:
                pass
            self._refresh_region_aliases()
            return True
        return False

    def set_wave_type_regions(self, wave_type):
        '''Show only the region set for wave_type on the main plot.'''
        for r in self.echo_bounds_p + self.echo_bounds_s:
            try:
                self.plot_win.removeItem(r)
            except Exception:
                pass
        self.current_wave_type = wave_type
        for r in self._regions_for(wave_type):
            self.plot_win.addItem(r)

    def set_regions_from_defs(self, wave_type, defs):
        '''Rebuild the region list for wave_type to match a list of [l, r]
        bounds (used when restoring a persisted condition).'''
        regions = self._regions_for(wave_type)
        for r in regions:
            try:
                self.plot_win.removeItem(r)
            except Exception:
                pass
        target = max(2, len(defs) if defs else 0)
        while len(regions) > target:
            regions.pop()
        while len(regions) < target:
            regions.append(self._new_region(len(regions) + 1))
        for i, r in enumerate(regions):
            if defs and i < len(defs):
                r.setRegion(defs[i])
            else:
                r.setRegion([0, 0])
        if self.current_wave_type == wave_type:
            for r in regions:
                self.plot_win.addItem(r)
        self._refresh_region_aliases()

    def get_region_defs(self, wave_type):
        return [list(r.getRegion()) for r in self._regions_for(wave_type)]

    def get_echo_bounds_p(self, i):
        return self.echo_bounds_p[i].getRegion()

    def get_echo_bounds_s(self, i):
        return self.echo_bounds_s[i].getRegion()

    ################################################################
    # Echo pairs table + combos
    ################################################################

    def _setup_pairs_tw(self):
        tw = self.pairs_tw
        header_view = QtWidgets.QHeaderView(QtCore.Qt.Horizontal, tw)
        tw.setHorizontalHeader(header_view)
        tw.setHorizontalHeaderLabels(self.pairs_header_lbls)
        header_view.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for col in range(1, len(self.pairs_header_lbls)):
            header_view.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        tw.setItemDelegate(NoRectDelegate())

    def _setup_echoes_tw(self):
        tw = self.echoes_tw
        header_view = QtWidgets.QHeaderView(QtCore.Qt.Horizontal, tw)
        tw.setHorizontalHeader(header_view)
        tw.setHorizontalHeaderLabels(self.echoes_header_lbls)
        header_view.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        for col in range(2, len(self.echoes_header_lbls)):
            header_view.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        tw.setItemDelegate(NoRectDelegate())

    def set_echoes_rows(self, names, bounds, active_index=0):
        '''Rebuild the echoes table. `names` and `bounds` are parallel lists; only
        the Name column is editable. Emits itemChanged only for genuine user edits
        because we block signals during the rebuild.'''
        tw = self.echoes_tw
        tw.blockSignals(True)
        tw.setRowCount(0)
        for i, name in enumerate(names):
            row = tw.rowCount()
            tw.setRowCount(row + 1)
            try:
                l, r = bounds[i]
            except Exception:
                l, r = 0.0, 0.0
            start_str = '' if not l else '{0:.3f}'.format(l * 1e6)
            end_str = '' if not r else '{0:.3f}'.format(r * 1e6)
            values = [str(i + 1), name, start_str, end_str]
            for col, val in enumerate(values):
                item = QtWidgets.QTableWidgetItem(val)
                if col == 1:
                    item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
                    item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                else:
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                    align = QtCore.Qt.AlignHCenter if col == 0 else QtCore.Qt.AlignRight
                    item.setTextAlignment(align | QtCore.Qt.AlignVCenter)
                tw.setItem(row, col, item)
            tw.setRowHeight(row, 24)
        if 0 <= active_index < tw.rowCount():
            tw.selectRow(active_index)
        tw.blockSignals(False)

    def get_selected_echo_row(self):
        selected = self.echoes_tw.selectionModel().selectedRows()
        try:
            return selected[0].row()
        except IndexError:
            return -1

    def set_echo_combo_items(self, names):
        '''Populate the A/B echo pickers with the current echo names, keeping the
        current selection where possible.'''
        labels = list(names)
        count = len(labels)
        for cbx in (self.pair_a_cbx, self.pair_b_cbx):
            prev = cbx.currentIndex()
            cbx.blockSignals(True)
            cbx.clear()
            cbx.addItems(labels)
            if 0 <= prev < count:
                cbx.setCurrentIndex(prev)
            cbx.blockSignals(False)
        # sensible default: A=first echo, B=second echo
        if self.pair_a_cbx.currentIndex() < 0 and count:
            self.pair_a_cbx.setCurrentIndex(0)
        if self.pair_b_cbx.currentIndex() <= 0 and count > 1:
            self.pair_b_cbx.setCurrentIndex(1)

    def _echo_name(self, names, i):
        if names and 0 <= i < len(names):
            return names[i]
        return 'Echo %d' % (i + 1)

    def set_pairs_rows(self, pairs, names, active_index=0):
        '''Rebuild the pairs table from a list of pair dicts, showing echo A/B by
        their names.'''
        tw = self.pairs_tw
        tw.blockSignals(True)
        tw.setRowCount(0)
        for pair in pairs:
            row = tw.rowCount()
            tw.setRowCount(row + 1)
            tau = pair.get('tau')
            tau_std = pair.get('tau_std')
            tau_str = '' if tau is None else '{0:.3f}'.format(tau)
            tau_std_str = '' if tau_std is None else '{0:.3f}'.format(tau_std)
            values = [pair.get('name', ''),
                      self._echo_name(names, pair.get('a', 0)),
                      self._echo_name(names, pair.get('b', 1)),
                      tau_str, tau_std_str]
            for col, val in enumerate(values):
                item = QtWidgets.QTableWidgetItem(val)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                if col == 0:
                    item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                else:
                    item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                tw.setItem(row, col, item)
            tw.setRowHeight(row, 24)
        if 0 <= active_index < tw.rowCount():
            tw.selectRow(active_index)
        tw.blockSignals(False)

    def get_selected_pair_row(self):
        selected = self.pairs_tw.selectionModel().selectedRows()
        try:
            return selected[0].row()
        except IndexError:
            return -1

    def update_view(self, t, spectrum, fname):
        
        self.t, self.spectrum, self.fname = t, spectrum, fname
        if t is not None and spectrum is not None:
            self.main_plot.setData(self.t, self.spectrum)

    def update_demodulated(self, t, spectrum):
        
        if t is not None and spectrum is not None:
            self.plot_demodulated.setData(t, spectrum)

    def updatePlot1(self):
        self.lr1_pr = self.lr1_p.getRegion()
        self.plot_win_detail1.setXRange(*self.lr1_pr, padding=0)

    def updateRegion1(self):
        self.lr1_p.setRegion(self.detail_plot1.getViewBox().viewRange()[0])
        
    def updatePlot2(self):
        self.lr2_pr = self.lr2_p.getRegion()
        self.plot_win_detail2.setXRange(*self.lr2_pr, padding=0)

    def updateRegion2(self):
        self.lr2_p.setRegion(self.detail_plot2.getViewBox().viewRange()[0])


    def make_widget(self):
        
        self._layout = QtWidgets.QVBoxLayout()
        self._layout.setContentsMargins(0, 0, 0, 0)

        self.label = QtWidgets.QLabel("Echo Selection")
        self.label.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter)
        self.label.setStyleSheet('''font-size: 18pt;''')
        self._layout.addWidget(self.label)

        self.detail_widget = QtWidgets.QTabWidget()
        
        '''self._detail_layout = QtWidgets.QTabWidget()
        self._detail_layout.setContentsMargins(0, 0, 0, 0)'''
        self.buttons_widget_top = QWidget()
        self._buttons_layout_top = QtWidgets.QHBoxLayout()
        self._buttons_layout_top.setContentsMargins(0, 0, 0, 0)
        self.buttons_widget_bottom = QWidget()
        self._buttons_layout_bottom = QtWidgets.QHBoxLayout()
        self._buttons_layout_bottom.setContentsMargins(0, 0, 0, 0)
        self.open_btn = QtWidgets.QPushButton("Open")
        self.fname_lbl = QtWidgets.QLineEdit('')
        self.freq_lbl = QtWidgets.QLabel(' 𝑓')
        self.freq_ebx = DoubleSpinBoxAlignRight()
        self.freq_ebx.setMaximum(1000)
        self.freq_ebx.setMinimum(1)
        self.freq_ebx.setValue(21)
        self.N_cbx = QtWidgets.QCheckBox('+/-')
        self.N_cbx.setChecked(True)
        self.save_btn = QtWidgets.QPushButton('Save')
        self.arrow_plt_btn = QtWidgets.QPushButton(u'Inverse 𝑓')
        self.echo_width = DoubleSpinBoxAlignRight()
        self.echo_width.setDecimals(0)
        self.echo_width.setMaximum(10000)
        self.echo_width_lbl = QtWidgets.QLabel('Width (ns)')

        self.echo1_cursor_btn = QtWidgets.QPushButton('Echo 1')
        self.echo2_cursor_btn = QtWidgets.QPushButton('Echo 2')

        # Dynamic-echo + select-mode controls
        self.add_echo_btn = QtWidgets.QPushButton('+ Echo')
        self.remove_echo_btn = QtWidgets.QPushButton('- Echo')
        self.select_btn = QtWidgets.QPushButton('Select')
        self.select_btn.setCheckable(True)
        self.select_btn.setToolTip('Select an echo row below, then drag on the plot to set its window (instead of zooming)')


        
        #self._buttons_layout_top.addWidget(self.open_btn)
        #self._buttons_layout_top.addWidget(self.fname_lbl)
        self._buttons_layout_top.addWidget(self.freq_lbl)
        self._buttons_layout_top.addWidget(self.freq_ebx)
        #self._buttons_layout_top.addWidget(self.echo_width_lbl)
        #self._buttons_layout_top.addWidget(self.echo_width)
        self._buttons_layout_top.addWidget(self.echo1_cursor_btn)
        self._buttons_layout_top.addWidget(self.echo2_cursor_btn)
        #self._buttons_layout_top.addWidget(self.N_cbx)

        self.p_s_widget = QWidget(self.buttons_widget_top)
        self._p_s_widget_layout = QtWidgets.QHBoxLayout(self.p_s_widget)
        self._p_s_widget_layout.setContentsMargins(0,0,0,0)
        self._p_s_widget_layout.setSpacing(0)
        self.p_wave_btn = QtWidgets.QPushButton('P')
        self.p_wave_btn.setObjectName('p_wave_btn')
        self.p_wave_btn.setCheckable(True)
        self.s_wave_btn = QtWidgets.QPushButton('S')
        self.s_wave_btn.setObjectName('s_wave_btn')
        self.s_wave_btn.setCheckable(True)
        self._p_s_widget_layout.addWidget(self.p_wave_btn)
        self._p_s_widget_layout.addWidget(self.s_wave_btn)
        self.p_s_widget.setLayout(self._p_s_widget_layout)
        self.wave_btn_group = QtWidgets.QButtonGroup()
        self.wave_btn_group.addButton(self.p_wave_btn)
        self.wave_btn_group.addButton(self.s_wave_btn)
        self.p_wave_btn.setChecked(True)
        self._buttons_layout_top.addWidget(self.p_s_widget)
        # P/S is now a single flat named-echo list; keep the buttons (p_wave_btn
        # stays checked so downstream keeps deriving 'P') but hide the toggle.
        self.p_s_widget.hide()

        self._buttons_layout_top.addWidget(self.save_btn)
        self._buttons_layout_top.addSpacerItem(HorizontalSpacerItem())
        #self._buttons_layout_top.addWidget(self.arrow_plt_btn)

        self.buttons_widget_top.setLayout(self._buttons_layout_top)
        self._layout.addWidget(self.buttons_widget_top)

        # Second controls row: add/remove echoes + select-mode
        self.buttons_widget_row2 = QWidget()
        self._buttons_layout_row2 = QtWidgets.QHBoxLayout()
        self._buttons_layout_row2.setContentsMargins(0, 0, 0, 0)
        self._buttons_layout_row2.addWidget(self.add_echo_btn)
        self._buttons_layout_row2.addWidget(self.remove_echo_btn)
        self._buttons_layout_row2.addWidget(self.select_btn)
        self._buttons_layout_row2.addSpacerItem(HorizontalSpacerItem())
        self.buttons_widget_row2.setLayout(self._buttons_layout_row2)
        self._layout.addWidget(self.buttons_widget_row2)

        # Echoes table: name each echo window. Selecting a row makes it the active
        # echo for Select-mode drags.
        self.echoes_group = QtWidgets.QGroupBox('Echoes')
        self._echoes_group_layout = QtWidgets.QVBoxLayout(self.echoes_group)
        self._echoes_group_layout.setContentsMargins(6, 6, 6, 6)
        self._echoes_group_layout.setSpacing(4)
        self.echoes_header_lbls = ['Echo', 'Name', 'Start (µs)', 'End (µs)']
        self.echoes_tw = ListTableWidget(columns=len(self.echoes_header_lbls))
        self._setup_echoes_tw()
        self.echoes_tw.setMinimumHeight(90)
        self._echoes_group_layout.addWidget(self.echoes_tw)
        # (added to the main layout below the plot, just above the pairs group)

        params = "Ultrasound echo analysis", 'Amplitude', 'Time'


        self.splitter_vertical = QtWidgets.QSplitter(Qt.Vertical)


        self.plot_widget = SimpleDisplayWidget(params)
        self.splitter_vertical.addWidget(self.plot_widget)

        self.detail0 = "Selected echoes", 'Amplitude', 'Time'
        self.detail_win0 = SimpleDisplayWidget(self.detail0)
        self.detail1 = "Filtered echoes", 'Amplitude', 'Time'
        self.detail_win1 = SimpleDisplayWidget(self.detail1)
        self.detail2 = "Correlation", 'Amplitude', f'\N{GREEK SMALL LETTER TAU} (s)'
        self.detail_win2 = SimpleDisplayWidget(self.detail2)

        self.detail_widget.addTab(self.detail_win0, 'Selected')
        self.detail_widget.addTab(self.detail_win1, 'Filtered')
        self.detail_widget.addTab(self.detail_win2, 'Correlation')

        #self.detail_widget.setLayout(self._detail_layout)
        self._detail_widget = QtWidgets.QWidget()
        self._detail_widget_layout = QtWidgets.QVBoxLayout(self._detail_widget)
        self._detail_widget_layout.setContentsMargins(0,15,0,0)
        self._detail_widget_layout.addWidget(self. detail_widget)
        self.splitter_vertical.addWidget(self._detail_widget)

        self._layout.addWidget(self.splitter_vertical)

        self._layout.addWidget(self.echoes_group)

        # Echo pairs section: define freeform named pairs and read each pair's
        # full multi-frequency travel time (tau).
        self.pairs_group = QtWidgets.QGroupBox('Echo pairs')
        self._pairs_group_layout = QtWidgets.QVBoxLayout(self.pairs_group)
        self._pairs_group_layout.setContentsMargins(6, 6, 6, 6)
        self._pairs_group_layout.setSpacing(4)

        self._pairs_controls_widget = QWidget()
        self._pairs_controls_layout = QtWidgets.QHBoxLayout(self._pairs_controls_widget)
        self._pairs_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.pair_name_ebx = QtWidgets.QLineEdit('')
        self.pair_name_ebx.setPlaceholderText('Pair name')
        self.pair_a_cbx = QtWidgets.QComboBox()
        self.pair_b_cbx = QtWidgets.QComboBox()
        # Wide enough to show real echo names (not clipped to "Echo").
        for cbx in (self.pair_a_cbx, self.pair_b_cbx):
            cbx.setMinimumWidth(120)
            cbx.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.add_pair_btn = QtWidgets.QPushButton('+ Pair')
        self.remove_pair_btn = QtWidgets.QPushButton('- Pair')
        self.compute_pairs_btn = QtWidgets.QPushButton(u'Compute \N{GREEK SMALL LETTER TAU}')
        self._pairs_controls_layout.addWidget(self.pair_name_ebx)
        self._pairs_controls_layout.addWidget(QtWidgets.QLabel('A'))
        self._pairs_controls_layout.addWidget(self.pair_a_cbx)
        self._pairs_controls_layout.addWidget(QtWidgets.QLabel('B'))
        self._pairs_controls_layout.addWidget(self.pair_b_cbx)
        self._pairs_controls_layout.addWidget(self.add_pair_btn)
        self._pairs_controls_layout.addWidget(self.remove_pair_btn)
        self._pairs_controls_layout.addWidget(self.compute_pairs_btn)
        self._pairs_group_layout.addWidget(self._pairs_controls_widget)

        self.pairs_header_lbls = ['Pair', 'Echo A', 'Echo B',
                                  f'\N{GREEK SMALL LETTER TAU} (ns)',
                                  f'\N{GREEK SMALL LETTER TAU} \N{GREEK SMALL LETTER SIGMA} (ns)']
        self.pairs_tw = ListTableWidget(columns=len(self.pairs_header_lbls))
        self._setup_pairs_tw()
        self.pairs_tw.setMinimumHeight(90)
        self._pairs_group_layout.addWidget(self.pairs_tw)

        self._layout.addWidget(self.pairs_group)

        #self.calc_btn = QtWidgets.QPushButton('Correlate')
        #_buttons_layout_bottom.addWidget(calc_btn)
        #_buttons_layout_bottom.addWidget(QtWidgets.QLabel('2-way travel time:'))
        #self.output_ebx = QtWidgets.QLineEdit('')
        #_buttons_layout_bottom.addWidget(output_ebx)
        #self._buttons_layout_bottom.addSpacerItem(HorizontalSpacerItem())
        #self.buttons_widget_bottom.setLayout(self._buttons_layout_bottom)
        #self._layout.addWidget(self.buttons_widget_bottom)
        self.setLayout(self._layout)
        



