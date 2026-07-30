#!/usr/bin/env python



import os.path, sys
import wave
from PyQt5 import QtWidgets
from PyQt5.QtCore import QObject, pyqtSignal
import numpy as np
#from functools import partial
#import json
#import copy
##from pathlib import Path
from numpy import arange
from utilities.utilities import *
from ua.widgets.UltrasoundAnalysisWidget import UltrasoundAnalysisWidget
from ua.widgets.ArrowPlotWidget import ArrowPlotWidget
from ua.models.UltrasoundAnalysisModel import UltrasoundAnalysisModel
from um.models.tek_fileIO import load_any_waveform_file 
from utilities.HelperModule import move_window_relative_to_screen_center, get_partial_index, get_partial_value
import math, time

from ua.controllers.ArrowPlotController import ArrowPlotController
from functools import partial

#from um.models.WaveformModel import Waveform

#from um.controllers.PhaseController import PhaseController


#import utilities.hpMCAutilities as mcaUtil
from utilities.HelperModule import increment_filename, increment_filename_extra
from um.widgets.UtilityWidgets import open_file_dialog

from ua.models.EchoesResultsModel import EchoesResultsModel

############################################################

class UltrasoundAnalysisController(QObject):
    cursor_position_signal = pyqtSignal(float)
    correlation_saved_signal = pyqtSignal(dict)
    wave_type_toggled_signal = pyqtSignal(str)
    compute_pairs_signal = pyqtSignal()
    pairs_changed_signal = pyqtSignal()

    def __init__(self, app=None, results_model= EchoesResultsModel()):
        super().__init__()
        self.model = UltrasoundAnalysisModel(results_model)
        self.fname = None

        # Freeform echo pairs, kept per wave type. A pair is name + two echo
        # indices (a, b); tau/tau_std are the computed full multi-f travel time.
        self.pairs_p = self._default_pairs()
        self.pairs_s = self._default_pairs()
        self.active_pair_p = 0
        self.active_pair_s = 0
        self._pair_counter = 1

        # User-editable names for each echo window (parallel to the widget's
        # echo_bounds_p/s region lists). Kept per wave type for symmetry with
        # persistence even though the P/S toggle is hidden (always 'P').
        self.echo_names_p = self._default_echo_names(2)
        self.echo_names_s = self._default_echo_names(2)
        self.active_echo_p = 0
        self.active_echo_s = 0

        
    
        if app is not None:
            self.setStyle(app)
        self.display_window = UltrasoundAnalysisWidget()
        
        self.make_connections()
       
        self.sync_widget_controls_with_model_non_signaling()
        
      

    def sync_widget_controls_with_model_non_signaling(self):

        self.display_window.echo_width.blockSignals(True)
  
        self.display_window.echo_width.setValue(self.model.settings['echo_width'])

        self.display_window.echo_width.blockSignals(False)

    def clear(self):
        self.display_window.clear()
        self.model.clear()

    def reset(self):
        self.clear()
        

    def _all_regions(self):
        return list(self.display_window.echo_bounds_p) + list(self.display_window.echo_bounds_s)

    def connect_regions(self):
        for r in self._all_regions():
            try:
                r.sigRegionChangeFinished.connect(self.calculate_data)
            except Exception:
                pass

    def disconnect_regions(self):
        for r in self._all_regions():
            try:
                r.sigRegionChangeFinished.disconnect(self.calculate_data)
            except Exception:
                pass

    def make_connections(self): 
        self.display_window.open_btn.clicked.connect(self.update_data)
        self.display_window.freq_ebx.valueChanged.connect(self.calculate_data)
        self.display_window.echo_width.valueChanged.connect(self.model.set_echo_width)

        self.connect_regions()

        self.display_window.N_cbx.stateChanged.connect(self.calculate_data)

        self.display_window.plot_widget.cursor_changed_singal.connect(self.sync_cursors)
        self.display_window.detail_win0.cursor_changed_singal.connect(self.sync_cursors)
        self.display_window.detail_win1.cursor_changed_singal.connect(self.sync_cursors)

        self.display_window.plot_widget.cursor_changed_singal.connect(self.emit_cursor)
        self.display_window.detail_win0.cursor_changed_singal.connect(self.emit_cursor)
        self.display_window.detail_win1.cursor_changed_singal.connect(self.emit_cursor)
        

        self.display_window.save_btn.clicked.connect(self.save_result)

       
        

        self.display_window.echo1_cursor_btn.clicked.connect(partial(self.set_echo_region_position,0))
        self.display_window.echo2_cursor_btn.clicked.connect(partial(self.set_echo_region_position,1))
    
        self.display_window.p_wave_btn.clicked.connect(partial(self.p_s_wave_btn_callback,'P'))
        self.display_window.s_wave_btn.clicked.connect(partial(self.p_s_wave_btn_callback,'S'))

        # Dynamic echoes + select mode
        self.display_window.add_echo_btn.clicked.connect(self.add_echo_callback)
        self.display_window.remove_echo_btn.clicked.connect(self.remove_echo_callback)
        self.display_window.select_btn.toggled.connect(self.toggle_select_mode)
        self.display_window.plot_win.regionDragSignal.connect(self.on_region_drag)

        # Pairs
        self.display_window.add_pair_btn.clicked.connect(self.add_pair_callback)
        self.display_window.remove_pair_btn.clicked.connect(self.remove_pair_callback)
        self.display_window.compute_pairs_btn.clicked.connect(self.compute_pairs_signal)
        self.display_window.pairs_tw.itemSelectionChanged.connect(self.pair_selection_changed)

        # Echoes table (naming + active-echo selection)
        self.display_window.echoes_tw.itemChanged.connect(self.echo_name_changed)
        self.display_window.echoes_tw.itemSelectionChanged.connect(self.echo_selection_changed)

        self._rebuild_pair_combos()
        self._refresh_pairs_table()
        self._refresh_echoes_table()
        self._apply_region_labels()

    ################################################################
    # Echo names
    ################################################################

    def _default_echo_names(self, n):
        return ['Echo %d' % (i + 1) for i in range(n)]

    def get_echo_names(self):
        return self.echo_names_p if self.model.wave_type == 'P' else self.echo_names_s

    def _set_echo_names(self, names):
        if self.model.wave_type == 'P':
            self.echo_names_p = names
        else:
            self.echo_names_s = names

    def _active_echo_index(self):
        return self.active_echo_p if self.model.wave_type == 'P' else self.active_echo_s

    def _set_active_echo_index(self, idx):
        if self.model.wave_type == 'P':
            self.active_echo_p = idx
        else:
            self.active_echo_s = idx

    def _sync_echo_names_length(self):
        '''Make the name list match the current number of echo regions, adding
        default names or trimming extras as needed.'''
        count = self.display_window.echo_count(self.model.wave_type)
        names = list(self.get_echo_names())
        while len(names) < count:
            names.append('Echo %d' % (len(names) + 1))
        while len(names) > count:
            names.pop()
        self._set_echo_names(names)
        return names

    def _apply_region_labels(self):
        '''Push the current echo names onto the on-plot region labels.'''
        wave_type = self.model.wave_type
        regions = (self.display_window.echo_bounds_p if wave_type == 'P'
                   else self.display_window.echo_bounds_s)
        names = self.get_echo_names()
        for i, r in enumerate(regions):
            label = names[i] if i < len(names) else 'Echo %d' % (i + 1)
            self.display_window.set_region_label(r, label)

    def _refresh_echoes_table(self):
        names = self._sync_echo_names_length()
        wave_type = self.model.wave_type
        regions = (self.display_window.echo_bounds_p if wave_type == 'P'
                   else self.display_window.echo_bounds_s)
        bounds = [list(r.getRegion()) for r in regions]
        self.display_window.set_echoes_rows(names, bounds, self._active_echo_index())

    def echo_name_changed(self, item):
        if item.column() != 1:
            return
        row = item.row()
        names = list(self.get_echo_names())
        if 0 <= row < len(names):
            new_name = item.text().strip() or ('Echo %d' % (row + 1))
            names[row] = new_name
            self._set_echo_names(names)
            self._apply_region_labels()
            self._rebuild_pair_combos()
            self._refresh_pairs_table()

    def echo_selection_changed(self):
        row = self.display_window.get_selected_echo_row()
        if row >= 0:
            self._set_active_echo_index(row)

    ################################################################
    # Echo pairs
    ################################################################

    def _default_pairs(self):
        return [{'id': 'pair0', 'name': 'Echo 1-2', 'a': 0, 'b': 1,
                 'tau': None, 'tau_std': None}]

    def _sanitize_pairs(self, pairs):
        if not pairs:
            return self._default_pairs()
        out = []
        for i, p in enumerate(pairs):
            out.append({'id': p.get('id', 'pair%d' % i),
                        'name': p.get('name', 'Pair %d' % (i + 1)),
                        'a': int(p.get('a', 0)),
                        'b': int(p.get('b', 1)),
                        'tau': p.get('tau'),
                        'tau_std': p.get('tau_std')})
        return out

    def get_active_pairs(self):
        return self.pairs_p if self.model.wave_type == 'P' else self.pairs_s

    def _active_index(self):
        return self.active_pair_p if self.model.wave_type == 'P' else self.active_pair_s

    def _set_active_index(self, idx):
        if self.model.wave_type == 'P':
            self.active_pair_p = idx
        else:
            self.active_pair_s = idx

    def get_active_pair(self):
        pairs = self.get_active_pairs()
        idx = self._active_index()
        if 0 <= idx < len(pairs):
            return pairs[idx]
        return pairs[0] if pairs else None

    def get_pair_bounds(self, pair):
        wave_type = self.model.wave_type
        regions = self.display_window.echo_bounds_p if wave_type == 'P' else self.display_window.echo_bounds_s
        a, b = pair['a'], pair['b']
        if a >= len(regions) or b >= len(regions):
            return [[0, 0], [0, 0]]
        [l1, r1] = regions[a].getRegion()
        [l2, r2] = regions[b].getRegion()
        return [[l1, r1], [l2, r2]]

    def _rebuild_pair_combos(self):
        self.display_window.set_echo_combo_items(self._sync_echo_names_length())

    def _refresh_pairs_table(self):
        self.display_window.set_pairs_rows(self.get_active_pairs(),
                                           self.get_echo_names(),
                                           self._active_index())

    def pair_selection_changed(self):
        row = self.display_window.get_selected_pair_row()
        if row >= 0:
            self._set_active_index(row)
            self.calculate_data()

    def add_pair_callback(self):
        a = self.display_window.pair_a_cbx.currentIndex()
        b = self.display_window.pair_b_cbx.currentIndex()
        if a < 0 or b < 0 or a == b:
            msg = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, "Notice",
                                        "Choose two different echoes for the pair")
            msg.exec()
            return
        name = self.display_window.pair_name_ebx.text().strip()
        if not name:
            name = 'Echo %d-%d' % (a + 1, b + 1)
        self._pair_counter += 1
        pair = {'id': 'pair%d' % self._pair_counter, 'name': name,
                'a': a, 'b': b, 'tau': None, 'tau_std': None}
        pairs = self.get_active_pairs()
        pairs.append(pair)
        self._set_active_index(len(pairs) - 1)
        self.display_window.pair_name_ebx.clear()
        self._refresh_pairs_table()
        self.pairs_changed_signal.emit()

    def remove_pair_callback(self):
        pairs = self.get_active_pairs()
        row = self.display_window.get_selected_pair_row()
        # Fall back to the active pair if the table lost its selection focus.
        if row < 0:
            row = self._active_index()
        if len(pairs) <= 1:
            msg = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, "Notice",
                                        "At least one echo pair must remain")
            msg.exec()
            return
        if 0 <= row < len(pairs):
            pairs.pop(row)
            self._set_active_index(min(self._active_index(), len(pairs) - 1))
            self._refresh_pairs_table()
            self.calculate_data()
            self.pairs_changed_signal.emit()

    def set_pair_tau(self, pair_id, tau, tau_std):
        for pairs in (self.pairs_p, self.pairs_s):
            for p in pairs:
                if p['id'] == pair_id:
                    p['tau'] = tau
                    p['tau_std'] = tau_std

    def add_echo_callback(self):
        self.disconnect_regions()
        self.display_window.add_echo_region(self.model.wave_type)
        self.connect_regions()
        self._sync_echo_names_length()
        self._apply_region_labels()
        self._rebuild_pair_combos()
        self._refresh_echoes_table()
        self.pairs_changed_signal.emit()

    def remove_echo_callback(self):
        wave_type = self.model.wave_type
        self.disconnect_regions()
        removed = self.display_window.remove_echo_region(wave_type)
        self.connect_regions()
        if removed:
            n = self.display_window.echo_count(wave_type)
            pairs = self.get_active_pairs()
            kept = [p for p in pairs if p['a'] < n and p['b'] < n]
            if not kept:
                kept = self._default_pairs()
            if wave_type == 'P':
                self.pairs_p = kept
                self.active_pair_p = min(self.active_pair_p, len(kept) - 1)
            else:
                self.pairs_s = kept
                self.active_pair_s = min(self.active_pair_s, len(kept) - 1)
            self._set_active_echo_index(min(self._active_echo_index(), n - 1))
            self._sync_echo_names_length()
            self._apply_region_labels()
            self._rebuild_pair_combos()
            self._refresh_pairs_table()
            self._refresh_echoes_table()
            self.pairs_changed_signal.emit()

    ################################################################
    # Select mode
    ################################################################

    def toggle_select_mode(self, state):
        self.display_window.plot_win.setSelectMode(state)

    def on_region_drag(self, l, r):
        wave_type = self.model.wave_type
        regions = self.display_window.echo_bounds_p if wave_type == 'P' else self.display_window.echo_bounds_s
        idx = self.display_window.get_selected_echo_row()
        if idx < 0:
            idx = self._active_echo_index()
        if 0 <= idx < len(regions):
            regions[idx].setRegion([l, r])
            self._refresh_echoes_table()

    ################################################################
    # Pair persistence state (used by MultipleFrequencyController)
    ################################################################

    def get_pairs_state(self):
        echoes_def = {'P': self.display_window.get_region_defs('P'),
                      'S': self.display_window.get_region_defs('S')}
        pairs = {'P': self.pairs_p, 'S': self.pairs_s}
        echo_names = {'P': self.echo_names_p, 'S': self.echo_names_s}
        return echoes_def, pairs, echo_names

    def _names_for_count(self, names, count):
        '''Coerce a persisted name list to `count` entries, defaulting missing
        names (e.g. old projects with none) to 'Echo N'.'''
        out = list(names) if names else []
        while len(out) < count:
            out.append('Echo %d' % (len(out) + 1))
        return out[:count]

    def set_pairs_state(self, echoes_def, pairs, echo_names=None):
        self.disconnect_regions()
        for wave_type in ('P', 'S'):
            defs = echoes_def.get(wave_type, []) if echoes_def else []
            self.display_window.set_regions_from_defs(wave_type, defs)
        self.pairs_p = self._sanitize_pairs(pairs.get('P') if pairs else None)
        self.pairs_s = self._sanitize_pairs(pairs.get('S') if pairs else None)
        self.active_pair_p = 0
        self.active_pair_s = 0
        self.echo_names_p = self._names_for_count(
            (echo_names or {}).get('P'), self.display_window.echo_count('P'))
        self.echo_names_s = self._names_for_count(
            (echo_names or {}).get('S'), self.display_window.echo_count('S'))
        self.active_echo_p = 0
        self.active_echo_s = 0
        self.connect_regions()
        self._apply_region_labels()
        self._rebuild_pair_combos()
        self._refresh_pairs_table()
        self._refresh_echoes_table()

    def p_s_wave_btn_callback(self, wave_type):
        self.display_window.clear_detail_plots()
        self.display_window.set_wave_type_regions(wave_type)

        self.model.wave_type = wave_type
        self._apply_region_labels()
        self._rebuild_pair_combos()
        self._refresh_pairs_table()
        self._refresh_echoes_table()
        self.calculate_data()

        self.wave_type_toggled_signal.emit(wave_type)



    def save_result(self, signaling=True):
        
        if self.fname is not None:
            filename = self.fname + '.json'
            '''before = time.time()'''
            out = self.model.save_result(self.fname)
            '''after = time.time()
            elapsed = after - before
            print ("file: " + self.fname + ", saving took: " + str(elapsed) + " s")'''
            if out['ok']: 
                self.correlation_saved_signal.emit(out['data'])
        else:
            msg = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information,"Notice","No waveform selected")
            msg.exec()


    def emit_cursor(self, pos):
        self.cursor_position_signal.emit(pos)

    def sync_cursors(self, pos):
        
        
        self.display_window.plot_widget.fig.set_cursor(pos)
        self.display_window.plot_widget.cursor_pos = pos
        self.display_window.detail_win0.fig.set_cursor(pos)
        self.display_window.detail_win0.cursor_pos = pos
        self.display_window.detail_win1.fig.set_cursor(pos)
        self.display_window.detail_win1.cursor_pos = pos


    def set_echo_region_position(self, index):
        center = self.display_window.plot_widget.cursor_pos
        pad = self.model.settings['echo_width'] * 1e-9
        wave_type = self.model.wave_type
        if wave_type == 'P':
            echo = self.display_window.echo_bounds_p[index]
            echo.setRegion([center, center+pad])
        elif wave_type == 'S':
            echo = self.display_window.echo_bounds_s[index]
            echo.setRegion([center, center+pad])
        
    def calculate_data_silent(self, freq, bounds):

        '''before = time.time()'''

        [l1, r1] = bounds [0]
        [l2, r2] = bounds [1]

        self.model.filter_echoes(l1, r1, l2, r2, freq)

        self.model.cross_correlate()
        self.model.exract_optima()
            
        '''after = time.time()
        elapsed = after - before
        print ("Frequency: " + str(freq) + ", calculation took: " + str(elapsed) + " s")'''

    def get_lr_bounds(self):
        # Bounds of the currently active pair (defaults to echoes 1 & 2, which
        # matches the historical single-pair behaviour).
        pair = self.get_active_pair()
        if pair is not None:
            return self.get_pair_bounds(pair)

        wave_type = self.model.wave_type
        if wave_type == 'P':
            [l1, r1] = self.display_window.get_echo_bounds_p(0)
            [l2, r2] = self.display_window.get_echo_bounds_p(1)
        elif wave_type == 'S':
            [l1, r1] = self.display_window.get_echo_bounds_s(0)
            [l2, r2] = self.display_window.get_echo_bounds_s(1)

        bounds = [[l1, r1],[l2, r2]]

        return bounds

    def set_freq(self, freq):
        self.display_window.freq_ebx.setValue(round(float(freq * 1e-6),1))

    def get_freq(self):
        freq = self.display_window.freq_ebx.value()*1e6
        return freq

    def calculate_data(self):

        # Keep the echoes table's Start/End columns in sync with the regions
        # (this handler fires on region-change-finished).
        self._refresh_echoes_table()

        freq = self.get_freq()
        t = self.model.t
        spectrum = self.model.spectrum
        bounds = self.get_lr_bounds()
        [l1, r1] = bounds [0]
        [l2, r2] = bounds [1]

        if t is not None and spectrum is not None:
            min_roi = abs(t[1]-t[0])*10
            if l1 >  0 and l2 >0 and abs(l1-r1) > min_roi and abs(l2-r2) > min_roi:
                self.calculate_data_silent(freq, bounds)
                self.display_window.detail_plot0.setData(*self.model.echo_tk1)
                self.display_window.detail_plot0_bg.setData(*self.model.echo_tk2)
                self.display_window.detail_plot1.setData(*self.model.filtered1)
                self.display_window.detail_plot1_bg.setData(*self.model.filtered2)
                self.display_window.detail_plot2.setData(self.model.cross_corr_shift, self.model.cross_corr)
                out = [np.append(self.model.maxima[0] ,self.model.minima[0]) , np.append(self.model.maxima[1] ,self.model.minima[1])]
                self.display_window.detail_plot2_bg.setData(*out)

    def cursorsCallback(self):
        pass
        

    def RecallSetupCallback(self):
        print('RecallSetupCallback')

    def SaveSetupCallback(self):
        print('SaveSetupCallback')

 
    def preferences_module(self, *args, **kwargs):
        pass

    def saveFile(self, filename, params = {}):
        pass

 
    def load_file(self, filename):

        t, spectrum = load_any_waveform_file(filename)
        
        return t,spectrum, filename

    def update_data(self, *args, **kwargs):
        filename = kwargs.get('filename', None)
        if filename is None:
            filename = open_file_dialog(None, "Load File(s).")
        if len(filename):
            t, spectrum, fname = self.load_file(filename)

            if len(spectrum):
                self._update_spectrum (t, spectrum, fname)
                self._update_view()

    def update_data_by_dict(self, data):
        t, spectrum, fname = data['t'], data['spectrum'], data['fname']
        self._update_spectrum(t, spectrum, fname)
        self._update_view()

    def update_data_by_dict_silent(self, data):
        if len(data):
            t, spectrum, fname = data['t'], data['spectrum'], data['fname']
            self._update_spectrum(t, spectrum, fname)
        
    def _update_spectrum(self, t, spectrum, fname):
        
        if len(spectrum):

            self.model.t, self.model.spectrum, self.fname = t, spectrum, fname
            

    def _update_view(self):
        #freq = self.display_window.freq_ebx.value()
        #amplitude_envelope  =  demodulate(t, spectrum, freq, True)
        #self.model.demodulated = amplitude_envelope
        self.display_window.update_view(self.model.t, self.model.spectrum, self.fname)
        #self.display_window.update_demodulated(t, self.model.demodulated)
    

        path = os.path.normpath(self.fname)
        fldr = path.split(os.sep)[-2]
        file = path.split(os.sep)[-1]
        name = os.path.join( fldr,file)
        self.display_window.plot_widget.setText(name,0)

    def cursor_dragged(self, cursor):
        pos = cursor.getYPos()
        c1 = self.display_window.hLine1
        c2 = self.display_window.hLine2
        
        ind = int(math.floor(pos))
        self.show_waveform(ind)
        if c1 is not cursor:
            c1.setPos(pos)
        if c2 is not cursor:
            c2.setPos(pos)

    def up_down_signal_callback(self, event):
        new_ind = self.waveform_index
        if event == 'up':
            new_ind = self.waveform_index + 1
        if event == 'down':
            new_ind = self.waveform_index - 1
        self.show_waveform(new_ind, update_cursor_pos=True)
                
    def export_plot(self,fname, tab):
        plot = None
    
        if tab == -1:
            plot = self.display_window.plot_win
        elif tab == 0:
            plot = self.display_window.plot_win_detail0
        elif tab == 1:
            plot = self.display_window.plot_win_detail1
        elif tab == 2:
            plot = self.display_window.plot_win_detail2
        
        if plot != None and len(fname):
            plot.export_plot_csv(fname)

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
