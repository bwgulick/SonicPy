#!/usr/bin/env python



from functools import partial
import os.path

from PyQt5.QtCore import QObject, Qt
from PyQt5 import QtWidgets
import numpy as np


def show_message(parent, icon, title, text):
    """Show a message box whose text can be selected and copied."""
    box = QtWidgets.QMessageBox(icon, title, text, QtWidgets.QMessageBox.Ok, parent)
    box.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
    return box.exec_()

#from utilities.utilities import *
from ia.widgets.ImageAnalysisWidget import ImageAnalysisWidget

from ia.models.ImageAnalysisModel import  ImageAnalysisModel
from um.widgets.UtilityWidgets import open_file_dialog, open_files_dialog, save_file_dialog

import pyqtgraph as pg
import csv
from .. import resources_path


############################################################

class ImageAnalysisController(QObject):
    def __init__(self, app=None, offline = False):
        super().__init__()
        self.model = ImageAnalysisModel()

        self.fname = None
        self.folder_path = ''
        if app is not None:
            self.setStyle(app)
        self.display_window = ImageAnalysisWidget()
        
        order = self.model.settings['edge_polynomial_order'][0]
        self.display_window.order_options.buttons()[order-1].setChecked(True)

        fit_threshold = self.model.settings['edge_fit_threshold'][0]
        self.display_window.threshold_num.setValue(fit_threshold)

        bins = self.model.settings['horizontal_bin']
        self.display_window.plots['absorbance'].getAxis('bottom').setScale(bins)
        self.display_window.plots['edge1 fit'].getAxis('bottom').setScale(bins)
        self.display_window.plots['edge2 fit'].getAxis('bottom').setScale(bins)
        #self.display_window.plots['sobel vertical mean'].getAxis('bottom').setScale(bins)
       
        
        self.make_connections()
        self.display_window.raise_widget()

        #path = '/Users/hrubiak/Globus/hpcat/16BMB/2021-2/s16bmb-20210717-e244302-Aihaiti/sam2/images'
        #self.set_folder_path(path)

        #fname = os.path.join(resources_path, '6031psi_049.tif')
        #self.update_data(filename=fname)
        
        '''filename='resources/ultrasonic/4000psi-300K_+21MHz000.csv'
        self.update_data(filename=filename)'''

    def make_connections(self): 
        self.display_window.file_widget.file_selected_signal.connect(self.update_data)
        self.display_window.open_btn.clicked.connect(self.open_btn_callback)
        self.display_window.file_widget.open_btn.clicked.connect(self.on_foler_clicked)
        self.display_window.compute_btn.clicked .connect(self.update_cropped)
        self.display_window.process_all_btn.clicked.connect(self.process_all_callback)


        self.display_window.crop_btn.clicked.connect(self.autocrop_btn_callback)
        self.display_window.rot_angle_edit.editingFinished.connect(self.rot_angle_callback)
      
        self.display_window.edge_roi_1.sigRegionChangeFinished.connect(self.roi_changed_callback)
        self.display_window.edge_roi_2.sigRegionChangeFinished.connect(self.roi_changed_callback) 
        self.display_window.crop_roi.sigRegionChangeFinished.connect(self.crop_roi_changed_callback)

        self.display_window.edge_options.buttonClicked.connect(self.edge_type_selection_btn_callback)
        self.display_window.order_options.buttonClicked.connect(self.order_options_callback)

        self.display_window.threshold_num.editingFinished.connect(self.threshold_num_callback)

        # Display-only contrast enhancement.
        self.display_window.contrast_combo.currentIndexChanged.connect(self.contrast_method_changed)
        self.display_window.contrast_num.editingFinished.connect(self.contrast_changed)

        # Left/right fit-window guides.
        self.display_window.lr_left.sigPositionChangeFinished.connect(self.lr_guides_changed)
        self.display_window.lr_right.sigPositionChangeFinished.connect(self.lr_guides_changed)

        self.display_window.file_widget.export_btn.clicked.connect(self.save_btn_callback)
        
        # Manual measurement connections
        self.display_window.measurement_mode_group.buttonClicked.connect(self.measurement_mode_changed)
        self.display_window.clear_points_btn.clicked.connect(self.clear_manual_points)
        
        # Connect mouse click on the source image for manual measurement
        self.display_window.plots['src'].scene().sigMouseClicked.connect(self.on_image_plot_click)

        # px -> um calibration input (below the file list)
        self.display_window.file_widget.calibration_edit.textChanged.connect(self.calibration_changed)

    def save_btn_callback(self):
        filename = save_file_dialog(self.display_window, 'Save as...', self.folder_path, '*.csv', True)
        if len(filename):
            self.export_table(filename)
        
    def export_table(self, filename):
        data = self.display_window.file_widget.fileModel.get_table_data()
        output_csv = filename
        with open(output_csv, "w", newline='') as csv_file:
            writer = csv.writer(csv_file, delimiter=',')
            
            for line in data:
                writer.writerow(line)
            csv_file.close()    



    def threshold_num_callback(self):
        num = self.display_window.threshold_num.value()
        
        self.model.settings['edge_fit_threshold'] = [num,num]

    def order_options_callback(self):
        btn = self.display_window.order_options.checkedButton()
        order  = int(btn.objectName()[6:7])
        self.model.settings['edge_polynomial_order'] = [order,order]

    def roi_changed_callback(self):
        self.update_roi()

    def update_roi(self):

        rois = [self.display_window.edge_roi_1,self.display_window.edge_roi_2]
        if self.model.src is not None:
            for i, roi in enumerate(rois):
                img = self.display_window.imgs['absorbance']
                selected = roi.getArrayRegion(self.model.image, img)
                self.model.rois[i].pos =  roi.pos() 
                self.model.rois[i].size =  roi.size()
                self.model.rois[i].image = selected
            
            edges = self.get_edge_types()
            self.set_edge_types(edges)

    def update_cropped(self):

        if self.model.src is not None and self.display_window.compute_btn.isChecked() :

            # Shared fit + distance math (same code the batch path uses).
            res = self.model.compute_distance()

            img_plots = [self.display_window.imgs['edge1 fit'],self.display_window.imgs['edge2 fit']]
            edge_plots = [self.display_window.edge1_plt, self.display_window.edge2_plt]
            abs_plot = self.display_window.abs_plt

            for i in range(len(self.model.rois)):
                img_plots[i].setImage(res['masked'][i])
                x_fit, y_fit = res['fits'][i]
                edge_plots[i].setData(x_fit, y_fit)

            y_diff = res['y_diff']
            std_dev = res['std_dev']

            output_txt = "mean: " + str(round(y_diff,1)) + '; std: ' +str(round(std_dev,1))
            cal = self.model.settings.get('calibration_um_per_pixel')
            if cal:
                output_txt += '  (%.2f um)' % (y_diff * cal)
            self.display_window.result_lbl.setText(output_txt)

            data_x = np.append(np.append(res['x_test'],np.nan),res['x_test'])
            data_y = np.append(np.append(res['edge1_y'],np.nan),res['edge2_y'])

            abs_plot.setData(data_x, data_y)
            fname = self.model.filename

            self.display_window.file_widget.fileModel.set_fname_result(fname, {'mean':str(round(y_diff,1)),
                                                                               'std.dev':str(round(std_dev,1)),
                                                                               'edge1':str(round(res['edge1_mean'],1)),
                                                                               'edge2':str(round(res['edge2_mean'],1)),
                                                                               'flag':'OK',
                                                                               'reason':''})
            self.display_window.file_widget.repaint()

    def _current_setup(self):
        """Capture the one-time setup (from the representative image) that the
        batch reuses for every file: crop box, sample type, fit order/threshold,
        edge-band height, edge x-extent, and a plausible separation range.

        Edge y-centers are NOT captured — the batch re-detects them per image
        (the sample can jump between frames).
        """
        roi1 = self.display_window.edge_roi_1
        roi2 = self.display_window.edge_roi_2

        h1 = roi1.size()[1]
        h2 = roi2.size()[1]
        band_half_height = (h1 + h2) / 4.0  # average box height / 2

        # Horizontal extent: intersection of the two boxes, so the fit stays on
        # the flat top/bottom surfaces the user bracketed.
        left = max(roi1.pos()[0], roi2.pos()[0])
        right = min(roi1.pos()[0] + roi1.size()[0], roi2.pos()[0] + roi2.size()[0])
        if right - left < 1:  # boxes don't overlap in x: fall back to full width
            left = 0
            right = self.model.image.shape[1]
        edge_x_pos = left
        edge_x_width = max(1, right - left)

        # Separation prior from the current box centers.
        c1 = roi1.pos()[1] + h1 / 2.0
        c2 = roi2.pos()[1] + h2 / 2.0
        sep = abs(c2 - c1)
        img_h = self.model.image.shape[0]
        min_sep = max(5, sep * 0.4) if sep > 0 else 5
        max_sep = min(img_h, sep * 2.0) if sep > 0 else img_h

        return dict(crop_limits=self.model.settings['crop_limits'],
                    edge_types=self.get_edge_types(),
                    orders=self.model.settings['edge_polynomial_order'],
                    thresholds=self.model.settings['edge_fit_threshold'],
                    band_half_height=band_half_height,
                    edge_x_pos=edge_x_pos, edge_x_width=edge_x_width,
                    min_sep=min_sep, max_sep=max_sep,
                    lr_limits=self.model.settings.get('lr_limits'))

    def process_all_callback(self, *args, **kwargs):
        """Process every image in the loaded folder using the current setup."""
        if self.model.src is None or not self.model.settings.get('crop_limits'):
            show_message(self.display_window, QtWidgets.QMessageBox.Warning, "Set up first",
                         "Load a representative image and set the crop + edge boxes "
                         "(and click Compute once) before running Process All.")
            return
        if len(self.model.rois) < 2:
            show_message(self.display_window, QtWidgets.QMessageBox.Warning, "Set up first",
                         "Two edge regions are required. Load an image and configure "
                         "the edge boxes before running Process All.")
            return

        setup = self._current_setup()

        fmodel = self.display_window.file_widget.fileModel
        files = list(fmodel.get_file_paths().values())
        if not files:
            show_message(self.display_window, QtWidgets.QMessageBox.Warning, "No files",
                         "No images found in the current folder.")
            return

        dlg = QtWidgets.QProgressDialog("Processing images...", "Cancel", 0, len(files),
                                        self.display_window)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)

        processed = 0
        flagged = 0
        for i, f in enumerate(files):
            if dlg.wasCanceled():
                break
            dlg.setValue(i)
            dlg.setLabelText(os.path.basename(f))
            result = self.model.process_file(f, **setup)
            fmodel.set_fname_result(f, result)
            processed += 1
            if result.get('flag') == 'LOW':
                flagged += 1
            QtWidgets.QApplication.processEvents()
        dlg.setValue(len(files))

        # Refresh the table so the new columns render.
        self.display_window.file_widget.listview.viewport().update()
        self.display_window.file_widget.repaint()

        show_message(self.display_window, QtWidgets.QMessageBox.Information, "Batch complete",
                     "Processed %d of %d images.\n%d flagged low-confidence." %
                     (processed, len(files), flagged))

    def update_frame(self, estimate_lr=True):
        image = self.model.image
        img_shape = image.shape

        #filtered = self.model.compute_sobel()

        self._display_absorbance()

        #self.display_window.imgs['frame cropped'].setImage(image )
        #self.display_window.imgs['sobel y'].setImage(filtered)

        # Robust signed-gradient edge detection. Places edge_roi_1 on the upper
        # edge and edge_roi_2 on the lower edge (matches get_edge_types()).
        # Detection uses the current left/right window (settings['lr_limits']);
        # if it can't confidently find both edges, the ROIs are left where they
        # are so the user can position them manually.
        sel = self.model.select_edges()

        rois = [self.display_window.edge_roi_1,self.display_window.edge_roi_2]

        if sel.get('ok'):
            # Auto-estimate the left/right window from the detected rows (unless
            # the user has already placed guides and we're only recomputing).
            if estimate_lr or not self.model.settings.get('lr_limits'):
                self.model.settings['lr_limits'] = self.model.estimate_lr_edges(
                    sel['row1'], sel['row2'])
            x_left, x_right = self.model.settings['lr_limits']
            self._place_lr_guides(x_left, x_right)

            # The guides own the horizontal extent: fit only those columns.
            geoms = self.model.edge_geometries(sel, x_pos=x_left,
                                               x_width=max(1, x_right - x_left))
            for i, (pos, size) in enumerate(geoms):
                roi = rois[i]
                roi.sigRegionChangeFinished.disconnect(self.roi_changed_callback)
                roi.setPos(pos[0], pos[1])
                roi.setSize((size[0], size[1]))
                roi.sigRegionChangeFinished.connect(self.roi_changed_callback)

        self.model.rois = []
        img = self.display_window.imgs['absorbance']
        for i, roi in enumerate(rois):
            selected = roi.getArrayRegion(self.model.image, img)
            self.model.add_ROI(selected, roi.pos(), roi.size())

        self.update_roi()

    def _place_lr_guides(self, x_left, x_right):
        """Move the left/right guide lines without triggering their callback."""
        for line, val in [(self.display_window.lr_left, x_left),
                          (self.display_window.lr_right, x_right)]:
            try:
                line.sigPositionChangeFinished.disconnect(self.lr_guides_changed)
            except (TypeError, RuntimeError):
                pass
            line.setValue(val)
            line.sigPositionChangeFinished.connect(self.lr_guides_changed)

    def lr_guides_changed(self, *args, **kwargs):
        """User dragged a left/right guide: store the new window, re-run edge
        detection within it and refresh the length (without re-estimating the
        guides, so the user's placement is respected)."""
        if self.model.src is None or self.model.image is None:
            return
        x_left = self.display_window.lr_left.value()
        x_right = self.display_window.lr_right.value()
        if x_right < x_left:
            x_left, x_right = x_right, x_left
        W = self.model.image.shape[1]
        x_left = int(max(0, min(x_left, W - 1)))
        x_right = int(max(x_left + 1, min(x_right, W)))
        self.model.settings['lr_limits'] = [x_left, x_right]
        self.update_frame(estimate_lr=False)
        self.update_cropped()

    def _display_src(self):
        """Show the source image with the current display-only contrast."""
        if self.model.src is None:
            return
        dc = self.model.settings.get('display_contrast', {})
        img = self.model.enhance_for_display(self.model.src, dc.get('method', 'none'),
                                             dc.get('param'))
        self.display_window.imgs['src'].setImage(img)

    def _display_absorbance(self):
        """Show the absorbance image with the current display-only contrast."""
        if self.model.image is None:
            return
        dc = self.model.settings.get('display_contrast', {})
        img = self.model.enhance_for_display(self.model.image, dc.get('method', 'none'),
                                             dc.get('param'))
        self.display_window.imgs['absorbance'].setImage(img)

    def contrast_method_changed(self, *args, **kwargs):
        """Contrast method combo changed: seed a sensible default parameter, then
        re-render."""
        method = self.display_window.contrast_combo.currentText().lower()
        defaults = {'none': 0, 'percentile': 2, 'clahe': 2, 'gamma': 0.5}
        self.display_window.contrast_num.setValue(defaults.get(method, 2))
        self.contrast_changed()

    def contrast_changed(self, *args, **kwargs):
        """Apply the display-only contrast enhancement (never touches the
        measured length)."""
        method = self.display_window.contrast_combo.currentText().lower()
        param = self.display_window.contrast_num.value()
        self.model.settings['display_contrast'] = {'method': method, 'param': param}
        self._display_src()
        self._display_absorbance()

    def set_folder_path(self, folder):
        self.folder_path = folder
        self.display_window.file_widget. folder_lbl.setText(folder)
        if os.path.isdir(folder):
            if not self.display_window.file_widget.initialized :
                self.display_window.file_widget.init_listview(folder)
            else:
                self.display_window.file_widget.set_root(folder)

    def on_foler_clicked(self, index):

        path = QtWidgets.QFileDialog.getExistingDirectory(self.display_window, caption='Select Images folder',
                                                     directory='')
        if len(path):
            self.set_folder_path(path)

    def open_btn_callback(self, *args, **kwargs):
        
        filename = open_file_dialog(None, "Select Image File.",filter='*.png;*.tif;*.bmp;*.jpg')
        
        if len(filename):
            path = os.path.split(filename)[0]
            self.display_window.file_widget.fileModel.folder_loaded.connect(self.loaded_callback)
            self.dialog_filename = filename
            self.set_folder_path(path)
            
            
            
            
    
    def loaded_callback(self, *args, **kwargs):
        self.display_window.file_widget.select_fname(os.path.split(self.dialog_filename)[-1])
        self.display_window.file_widget.fileModel.folder_loaded.disconnect(self.loaded_callback)

    def update_data(self, *args, **kwargs):
        
        if len(args):
            filename = args[0]
        else:
            filename = kwargs.get('filename', None)

        self.load_file(filename)

    def load_file(self, filename):

        # Read the image. If this fails, tell the user instead of failing
        # silently (a windowed .exe has no console to print the traceback to).
        try:
            self.model.load_file(filename)
        except Exception as e:
            show_message(
                self.display_window, QtWidgets.QMessageBox.Critical, "Image load error",
                "Could not load image:\n%s\n\n%s" % (filename, e))
            return

        self.display_window.fname_lbl.setText(os.path.split(filename)[-1])
        self._display_src()

        # A newly loaded image gets a fresh left/right auto-estimate (the sample
        # can jump between frames); the user's guide drags only persist until the
        # next load.
        self.model.settings['lr_limits'] = []

        # Automatic crop / edge detection is tuned for specific sample
        # geometries and may fail on other images. Don't let that hide the
        # loaded image or block Manual measurement mode.
        try:
            self.update_crop()
            self.model.filter_image()
            self.update_frame()
            self.update_cropped()
        except Exception as e:
            import traceback
            traceback.print_exc()
            show_message(
                self.display_window, QtWidgets.QMessageBox.Warning, "Automatic processing failed",
                "The image loaded, but automatic edge detection failed:\n\n%s\n\n"
                "Switch to Manual mode to measure by clicking two points." % e)

    def update_crop(self, *args, **kwargs):
        
        auto_crop = self.display_window.crop_btn.isChecked()
        if auto_crop :
            v_crop = self.get_vertical_autocrop()
            self.model.settings['crop_limits'] = self.model.get_auto_crop_limits(y=v_crop)
        self.model.crop()
        
        crop_limits = self.model.settings['crop_limits']
        self.display_window.crop_roi.sigRegionChangeFinished.disconnect(self.crop_roi_changed_callback)
        self.display_window.crop_roi.setPos((crop_limits[0][0],crop_limits[0][1]))
        self.display_window.crop_roi.setSize((crop_limits[1][0],crop_limits[1][1]))
        self.display_window.crop_roi.sigRegionChangeFinished.connect(self.crop_roi_changed_callback)

    def autocrop_btn_callback(self, btn):
        if btn:
            self.update_crop()
            self.model.filter_image()
            self.update_frame()

    def rot_angle_callback(self):

        filename = self.model.filename
        rot_angle= self.display_window.rot_angle_edit.value()
        self.model.settings['rotation_angle']= rot_angle
        if filename != '':
            self.model.load_file(filename)
            self.display_window.fname_lbl.setText(os.path.split( filename)[-1])
            self._display_src()

            self.update_crop()
            self.model.filter_image()
            self.update_frame()
            self.update_cropped()
         

    def crop_roi_changed_callback(self, roi:pg.graphicsItems.ROI.ROI):
        self.display_window.crop_btn.setChecked(False)
        pos = [int(roi.pos()[0]),int(roi.pos()[1])]
        size = [int(roi.size()[0]),int(roi.size()[1])]
        roi_limits = [pos,size]
        self.model.settings['crop_limits'] = roi_limits
        self.update_crop()
        self.model.filter_image()
        self.update_frame()
        

    def show_window(self):
        self.display_window.raise_widget()

    def edge_type_selection_btn_callback(self, *args, **kwargs):
        
        
        edges = self.get_edge_types()
        self.set_edge_types(edges)

    def get_edge_types(self):
        btn = self.display_window.edge_options.checkedButton()
        lbl = btn.objectName()[5:8]

        '''possible values for lbl should be '000', '100', '001', '101', '010', 
        where 0 = low Z layer, 1 = high Z layer
        edge type determine whether edge fitting is done using the 
        absorbance image (0-type edges) or the sobel-Y filtered image (1-type edges)
        '''

        edges = [ 1*(lbl[1]!=lbl[2]), 1*(lbl[0]!=lbl[1])]
        return edges

    def get_vertical_autocrop(self):
        btn = self.display_window.edge_options.checkedButton()
        lbl = btn.objectName()[5:8]
        v_crop = lbl[0] == '0' and lbl[2] == '0'
        return v_crop


    def set_edge_types(self, edges):
        
        rois = self.model.rois
        for i, roi in enumerate(rois):
            roi.edge_type = edges[i]
            

    def measurement_mode_changed(self):
        """Handle switching between automatic and manual measurement modes."""
        if self.display_window.mode_auto_btn.isChecked():
            self.model.measurement_mode = 'automatic'
            self.display_window.manual_mode_status.setText('Auto')
            self.display_window.manual_mode_status.setStyleSheet("QLabel { color: black; font-weight: bold; }")
            self.display_window.compute_btn.setEnabled(True)
            self.display_window.clear_points_btn.setEnabled(False)
            # Clear manual measurement overlay and restore automatic results.
            self.clear_manual_points()
            if self.model.src is not None:
                self.update_cropped()
        else:
            self.model.measurement_mode = 'manual'
            self.display_window.manual_mode_status.setText('Manual - click top then bottom of the sample')
            self.display_window.manual_mode_status.setStyleSheet("QLabel { color: green; font-weight: bold; }")
            self.display_window.compute_btn.setEnabled(False)
            self.display_window.clear_points_btn.setEnabled(True)

    def clear_manual_points(self):
        """Clear the selected measurement points."""
        self.model.manual_measurement.clear()
        self.display_window.manual_points_plot.setData([], [])
        self.display_window.manual_line_plot.setData([], [])
        self.display_window.result_lbl.setText('')
        self.display_window.manual_mode_status.setText('Manual - Click on image')

    def on_image_plot_click(self, event):
        """Handle mouse clicks on the source image for manual measurement."""
        if self.model.measurement_mode != 'manual':
            return
        if self.model.src is None:
            return
        if event.button() != 1:  # Only handle left mouse clicks
            return

        # The subplots share one scene, so ignore clicks outside the source image.
        vb = self.display_window.plots['src'].getViewBox()
        scene_pos = event.scenePos()
        if not vb.sceneBoundingRect().contains(scene_pos):
            return

        view_coords = vb.mapSceneToView(scene_pos)
        x = view_coords.x()
        y = view_coords.y()

        mm = self.model.manual_measurement
        if not mm.is_complete():
            if mm.point1 is None:
                mm.set_point1(x, y)
                status_text = 'Top point set. Click the bottom of the sample.'
            else:
                # Force a vertical line: keep point 1's x so only the
                # top-to-bottom (y) length is measured for a cylindrical sample.
                mm.set_point2(mm.point1[0], y)
                status_text = 'Both points set. See Length above.'
        else:
            # Start a fresh measurement on the next click after two points.
            mm.clear()
            mm.set_point1(x, y)
            status_text = 'Top point set. Click the bottom of the sample.'

        self.update_manual_measurement_visualization()
        self.display_window.manual_mode_status.setText(status_text)

    def update_manual_measurement_visualization(self):
        """Update the visualization of selected points and connecting line."""
        mm = self.model.manual_measurement

        points_x = []
        points_y = []
        if mm.point1 is not None:
            points_x.append(mm.point1[0])
            points_y.append(mm.point1[1])
        if mm.point2 is not None:
            points_x.append(mm.point2[0])
            points_y.append(mm.point2[1])
        self.display_window.manual_points_plot.setData(points_x, points_y)

        if mm.is_complete():
            line_x = [mm.point1[0], mm.point2[0]]
            line_y = [mm.point1[1], mm.point2[1]]
            self.display_window.manual_line_plot.setData(line_x, line_y)

            # Vertical (top-to-bottom) length in real source-image pixels.
            dy = abs(mm.point2[1] - mm.point1[1])

            cal = self.model.settings.get('calibration_um_per_pixel')
            if cal:
                result_text = "Length: %.1f px = %.2f um" % (dy, dy * cal)
            else:
                result_text = "Length: %.1f px" % dy
            self.display_window.result_lbl.setText(result_text)
        else:
            self.display_window.manual_line_plot.setData([], [])

    def calibration_changed(self, *args, **kwargs):
        """Read the '1 px = X um' box and refresh the current result."""
        txt = self.display_window.file_widget.calibration_edit.text().strip()
        try:
            val = float(txt)
            if val <= 0:
                val = None
        except (ValueError, TypeError):
            val = None
        self.model.settings['calibration_um_per_pixel'] = val

        # Refresh whichever result is currently shown.
        if self.model.measurement_mode == 'manual':
            self.update_manual_measurement_visualization()
        elif self.model.src is not None and self.display_window.compute_btn.isChecked():
            self.update_cropped()

    def preferences_module(self, *args, **kwargs):
        pass

    def saveFile(self, filename, params = {}):
        pass

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