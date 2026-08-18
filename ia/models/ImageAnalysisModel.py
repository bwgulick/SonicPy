
from utilities.utilities import *

import numpy as np

from scipy.signal import medfilt2d
from scipy.ndimage import rotate

from um.models.tek_fileIO import *

from utilities.utilities import zero_phase_bandpass_filter
import json
import cv2
import numpy as np

print(cv2.__file__)

#from skimage.transform import resize
from scipy import interpolate
import copy

from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

class ManualMeasurement():
    """Handles manual point-based distance measurements in X-ray images."""
    def __init__(self):
        self.point1 = None  # (x, y) in image coordinates
        self.point2 = None  # (x, y) in image coordinates
        self.distance_pixels = None
        self.calibration_um_per_pixel = None  # If set, can calculate micron distance
    
    def set_point1(self, x, y):
        """Set the first measurement point."""
        self.point1 = (x, y)
    
    def set_point2(self, x, y):
        """Set the second measurement point."""
        self.point2 = (x, y)
    
    def calculate_distance(self):
        """Calculate the distance between two points in pixels."""
        if self.point1 is None or self.point2 is None:
            return None
        
        x1, y1 = self.point1
        x2, y2 = self.point2
        self.distance_pixels = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
        return self.distance_pixels
    
    def get_distance_microns(self):
        """Get distance in micrometers if calibration is available."""
        if self.distance_pixels is None or self.calibration_um_per_pixel is None:
            return None
        return self.distance_pixels * self.calibration_um_per_pixel
    
    def clear(self):
        """Clear the measurement points."""
        self.point1 = None
        self.point2 = None
        self.distance_pixels = None
    
    def is_complete(self):
        """Check if both points are set."""
        return self.point1 is not None and self.point2 is not None

class ImageROI():
    def __init__(self, image, pos, size):
        self.image = image

        self.pos = pos
        self.width = size
        self.size = size  # (width, height); kept in sync so compute_distance can read the x-extent
        self.edge_type = 0  # 0 - foil, 1 - edge

        self.text = ''

    def get_sobel_y(self):
        image = self.image
        sobely= cv2.Sobel(image,cv2.CV_64F, dx=0,dy=1)
        sobely= abs(sobely)
        results = sobely
        return results


    def compute(self, threshold=0.2, order = 3):

        if self.edge_type == 0:
            img = self.image
        else:
            img = self.get_sobel_y()

        img_bg = self.get_background(img, 15 )
       
        bg_removed = img - img_bg
       
        mx = np.amax(bg_removed)
        th = np.amax(bg_removed)*threshold
        normalized = (bg_removed-th)/(mx-threshold)

        mask = normalized < 0
        masked = copy.deepcopy(normalized)
        masked[mask]= 0
        self.x_fit, self.y_fit = self.fit(masked, order = order, threshold=0.1)
        return masked, self.x_fit, self.y_fit
        
    def fit(self, I_orig, order = 3, threshold=0.2):
        
        #order = 3
        self.w_weighted = pixel_cluster_polynom_fit(I_orig, order=order, threshold = threshold)
        
        '''w_weighted = copy.copy(self.w_weighted)
        w_weighted[0]=w_weighted[0]+self.pos[1]
        w_strings = []
        for w in w_weighted:
            text = "{:.3e}".format(w)
            w_strings.append(text)

        self.text = '['+ ','.join(w_strings) +']'''
        
        # Generate test points
        n_samples = 50
        x_test = np.linspace(0, I_orig.shape[1], n_samples)
        
        y_test_weighted = self.predict(x_test,order)
        return x_test, y_test_weighted

    def predict(self, x, order):
        # Predict y coordinates at test points
        x = feature(x, order)
        y_test_weighted = x.dot(self.w_weighted)
        return y_test_weighted

    def get_background(self, img, pad ):

        (m,n) = img.shape
        remove_index_x= range(pad, m-pad)
        img_del = np.delete(img, remove_index_x, 0)
        x = np.asarray(range(m))
        y = np.asarray(range(n))
        new_y = np.delete(x, remove_index_x)
        new_x = y
        z = img_del.astype(float)

        # Linearly interpolate/extrapolate the background across the full image
        # height from the retained top/bottom bands. (scipy.interpolate.interp2d
        # was removed in SciPy 1.14; RegularGridInterpolator is the replacement.)
        rgi = interpolate.RegularGridInterpolator(
            (new_y.astype(float), new_x.astype(float)), z,
            method='linear', bounds_error=False, fill_value=None)
        rows, cols = np.meshgrid(x.astype(float), y.astype(float), indexing='ij')
        pts = np.stack([rows.ravel(), cols.ravel()], axis=-1)
        znew = rgi(pts).reshape(m, n)

        bg_image = cv2.GaussianBlur(znew,(17,17),sigmaX=17, sigmaY=17)
        return bg_image

class ImageAnalysisModel():
    def __init__(self):
        self.image = None
        self.filename =''
        self.src = None
        self.cropped = None
        self.cropped_resized = None
        self.rois = []
        self.manual_measurement = ManualMeasurement()
        self.measurement_mode = 'automatic'  # 'automatic' or 'manual'
        self.settings = {'horizontal_bin':15,
                         'median_kernel_size':3,
                         'image_bits':8,
                         'crop_limits':[],
                         'edges_roi':  [],
                         'edge_polynomial_order':[2,2],
                         'edge_fit_threshold':[0.3,0.3],
                         'rotation_angle':0,
                         'lr_limits':[],  # [x_left, x_right] in binned absorbance columns; [] -> auto 0.25/0.75
                         'display_contrast':{'method':'none','param':None},  # display-only, never affects measurement
                         'calibration_um_per_pixel': None}  # Optional calibration

    def add_ROI(self, selected,pos, size):


        roi = ImageROI(selected, pos, size)
        self.rois.append(roi)


    def crop(self):
        crop_limits=self.settings['crop_limits']

        src = self.src
        [[x, y],[width, height]] = crop_limits
        self.cropped = src[y: y+height,x: x+ width]

    def resize_without_skimage(self, image, horizontal_bin):
        # Calculate the new width
        new_width = image.shape[1] // horizontal_bin
        
        # Resize the image
        resized_image = np.mean(image[:, :new_width * horizontal_bin].reshape(image.shape[0], new_width, horizontal_bin), axis=2)
        
        return resized_image

    def filter_image(self):
        horizontal_bin = self.settings['horizontal_bin']
        median_kernel_size= self.settings['median_kernel_size']
        image_bits = self.settings['image_bits']
     
        max_bit = 2**image_bits
        cropped = self.cropped
        image = medfilt2d(cropped,kernel_size=median_kernel_size) 
        

        image_resized = self.resize_without_skimage(image, horizontal_bin)

        self.cropped_resized = image_resized

        # confert to absrobance
        tsrc = -1* np.log10 (image_resized/max_bit)
        mn = np.amin(tsrc)
        tsrc = tsrc - mn

        m = np.amax(tsrc)
        tsrc = tsrc/m*max_bit
        image = tsrc
        #image = cv2.transpose(src)
        #image = medfilt2d(tsrc,kernel_size=median_kernel_size)
        #self.base_surface = self.get_base_surface(image)
        self.image = image # - self.base_surface

    @staticmethod
    def read_image_gray(fname):
        """Read an image file as a 2D grayscale float array scaled to the 0..255
        range used by the processing pipeline.

        Robust to:
          - non-ASCII paths on Windows (cv2.imread returns None for these), by
            reading the raw bytes and using cv2.imdecode
          - 16-bit / float TIFFs from X-ray detectors (rescaled to 8-bit range)
          - color images (converted to grayscale)
          - files cv2 can't decode (falls back to Pillow)

        Raises IOError with a clear message if the file cannot be read.
        """
        img = None

        # Unicode-safe read: bypass cv2.imread's broken handling of non-ASCII
        # Windows paths by decoding the raw bytes ourselves.
        try:
            buf = np.fromfile(fname, dtype=np.uint8)
            if buf.size:
                img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
        except Exception:
            img = None

        # Plain read as a second attempt.
        if img is None:
            try:
                img = cv2.imread(fname, cv2.IMREAD_UNCHANGED)
            except Exception:
                img = None

        # tifffile handles the 16-bit / compressed / BigTIFF variants produced
        # by X-ray detectors that OpenCV's libtiff build often can't decode.
        errors = []
        if img is None:
            try:
                import tifffile
                img = tifffile.imread(fname)
            except Exception as e:
                errors.append("tifffile: %s" % e)

        # Pillow as an additional fallback for other formats.
        if img is None:
            try:
                from PIL import Image
                img = np.asarray(Image.open(fname))
            except Exception as e:
                errors.append("PIL: %s" % e)

        if img is None:
            raise IOError("Unable to read image file:\n%s\n\n%s" %
                          (fname, "\n".join(errors) if errors else "unknown decode error"))

        img = np.asarray(img)
        if img.size == 0:
            raise IOError("Image file is empty or unreadable:\n%s" % fname)

        # Collapse color images to grayscale (imdecode returns BGR order).
        if img.ndim == 3:
            img = img[..., :3].astype(float).mean(axis=2)

        img = img.astype(float)

        # Scale higher-bit-depth data into the 8-bit range the pipeline expects.
        mx = float(img.max()) if img.size else 0.0
        if mx > 255.0:
            img = img / mx * 255.0

        return img

    @staticmethod
    def enhance_for_display(img, method='none', param=None):
        """Return a contrast-enhanced *copy* of ``img`` for display only.

        This never mutates the input and is never used by the measurement math,
        so the reported length is identical with or without enhancement. It
        exists because at high pressure the very dark WC anvils dominate the
        global min/max stretch and squash the faint sample edges.

        method:
          'none'       - returned unchanged
          'percentile' - clip to [param, 100-param] percentiles then stretch to
                         0..255 (param defaults to 2). Robust to WC/air extremes.
          'clahe'      - contrast-limited adaptive histogram equalization
                         (param = clipLimit, default 2.0). Best at pulling faint
                         edges out of the dark band.
          'gamma'      - ((img/255)**param)*255 (param default 0.5) to brighten darks.
        """
        if img is None or method in (None, 'none', ''):
            return img
        out = np.asarray(img, dtype=float)
        try:
            if method == 'percentile':
                p = float(param) if param else 2.0
                p = min(max(p, 0.0), 49.0)
                lo, hi = np.percentile(out, [p, 100.0 - p])
                if hi > lo:
                    out = np.clip((out - lo) / (hi - lo), 0.0, 1.0) * 255.0
            elif method == 'clahe':
                clip = float(param) if param else 2.0
                mn, mx = float(out.min()), float(out.max())
                scaled = (out - mn) / (mx - mn) * 255.0 if mx > mn else out * 0.0
                clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8))
                out = clahe.apply(scaled.astype(np.uint8)).astype(float)
            elif method == 'gamma':
                g = float(param) if param else 0.5
                if g <= 0:
                    g = 0.5
                mx = float(out.max())
                norm = out / mx if mx > 0 else out
                out = np.power(np.clip(norm, 0.0, 1.0), g) * 255.0
        except Exception:
            # Enhancement is cosmetic; on any failure fall back to the raw image.
            return img
        return out

    def load_file(self, fname, autocrop=False):
        self.filename = fname
        img = self.read_image_gray(fname)
        src = np.flip(img, axis=0)
        angle = self.settings.get('rotation_angle', 0)
        if angle:
            src = rotate(src, angle, reshape=False)

        self.src = src
        

    def get_base_surface(self, img, iterations = 30):
        sig_work = copy.copy(img)
        for i in range(iterations):
            f = cv2.GaussianBlur(sig_work,(21,21),sigmaX=21, sigmaY=21)
            less = f <= sig_work
            sig_work[less] = f[less]
        f = cv2.GaussianBlur(sig_work,(21,21),sigmaX=21, sigmaY=21)
        return f

    def estimate_edges(self):
        filtered = self.compute_sobel()
        y_size = filtered.shape[1]
        min_y=(int(y_size*0.25))
        max_y=(int(y_size*0.75))
        self.sobel_mean_vertical = filtered[:,min_y:max_y].mean(axis=1)
        self.blured_sobel_mean_vertical = gaussian_filter1d(self.sobel_mean_vertical,10)
        peaks = find_peaks(self.blured_sobel_mean_vertical/np.amax(self.blured_sobel_mean_vertical), height=0.2, width=5 )
        
        peaks_heights = {}
        for i, peak in enumerate(peaks[1]['peak_heights']):
            w = peaks[1]['widths'][i]
            peaks_heights[round(peak,4)] = [peaks[0][i],w]
        
        edges_combined = {}
        for edge in peaks_heights:
            new_edge = True
            for i, combined_edge in enumerate(edges_combined.keys()):
                diff = abs(combined_edge-peaks_heights[edge][0])
                if diff< 100:
                    new_edge=False
                    break
            if new_edge:
                edges_combined[peaks_heights[edge][0]] = (edge, peaks_heights[edge][1])
            else:
                average_edge=round((combined_edge+peaks_heights[edge][0])/2)
                average_height=round(((edges_combined[combined_edge][0]+edge)/2),4)
                new_width = edges_combined[combined_edge][0]/2+peaks_heights[edge][1]/2+diff
                edges_combined[average_edge]=(average_height,new_width)
                del(edges_combined[combined_edge])

        return edges_combined

    def get_auto_crop_limits(self, x=True, y=True):
        median_kernel_size= self.settings['median_kernel_size']
        src = self.src
        img = medfilt2d(src,kernel_size=median_kernel_size)
        crop_tightness = 5
        

        hor = img.mean(axis=0)
        ver = img.mean(axis=1)
        m = min( min(hor), min(ver))
        crop_limit = m*crop_tightness
        
        if x:
            hor_first, hor_last = self.get_1d_limits(hor,crop_limit, pad=36)
        else:
            hor_first, hor_last = 0, img.shape[1]-1
        if y:
            ver_first, ver_last = self.get_1d_limits(ver,crop_limit, pad=24)
        else:
            ver_first, ver_last = 0, img.shape[0]-1
        width = hor_last -hor_first
        height = ver_last- ver_first

        


        return [hor_first, ver_first],[width, height]

    def get_1d_limits(self, profile, limit, pad=0):
        first = np.argmax(profile>limit) + pad
        last = len(profile) - np.argmax(np.flip(profile)> limit) - pad
        return [first,last]

    '''def compute_canny(self, img):

        image = img
        # Below code convert image gradient in both x and y direction
        lap = cv2.Laplacian(image,cv2.CV_64F,ksize=3) 
        lap = np.uint8(np.absolute(lap))
        
        # Below code convert image gradient in x direction
        sobelx= cv2.Sobel(image,cv2.CV_64F, dx=1,dy=0)
        sobelx= abs(sobelx)

        # Below code convert image gradient in y direction
        sobely= cv2.Sobel(image,cv2.CV_64F, dx=0,dy=1)
        sobely= abs(sobely)
        sobel_yx = 1.0 * (sobely > sobelx )
        edges2 = 1* sfeature.canny(img/np.amax(img), sigma=3, low_threshold=.15)
        horizontal_edges = edges2 * sobel_yx
        return image, horizontal_edges, sobely'''

    def compute_sobel(self):
        image = self.image
        image = cv2.GaussianBlur(image,(5,5),sigmaX=5, sigmaY=0)

        '''# Below code convert image gradient in both x and y direction
        lap = cv2.Laplacian(image,cv2.CV_64F,ksize=3) 
        lap = np.uint8(np.absolute(lap))
        '''
        # Below code convert image gradient in x direction
        #sobelx= cv2.Sobel(image,cv2.CV_64F, dx=1,dy=0)
        #sobelx= abs(sobelx)
        # Below code convert image gradient in y direction
        sobely= cv2.Sobel(image,cv2.CV_64F, dx=0,dy=1)
        sobely= abs(sobely)
        results = sobely
        return results

    # ------------------------------------------------------------------
    # Reusable edge-detection + distance math.
    #
    # These operate on ``self.image`` (the cropped, horizontally-binned
    # absorbance image) and are shared by the interactive path (controller
    # update_frame / update_cropped) and the headless batch path
    # (process_file).  Keeping the math here means the "Process All" batch and
    # a single interactive Compute produce identical numbers.
    #
    # Coordinate notes (see also the plan):
    #   - x is BINNED by settings['horizontal_bin']; y (rows) is unbinned.
    #   - All length math is vertical (rows) so binning never affects it.
    #   - self.src is vertically flipped on load; y_0 = crop_limits[0][1] is
    #     added back so reported edge positions are in src coordinates.
    #   - Edge ordering matches get_edge_types(): rois[0] = edge_roi_1 = the
    #     upper (smaller-row) edge; rois[1] = edge_roi_2 = the lower edge.
    # ------------------------------------------------------------------

    def compute_signed_edge_profile(self, x_lo_frac=0.25, x_hi_frac=0.75, x_lo=None, x_hi=None):
        """Mean *signed* vertical gradient per row over the central columns.

        Unlike estimate_edges (which uses abs(sobel_y) and so cannot tell a
        rising edge from a falling one), the sign is preserved.  Note self.image
        is the ABSORBANCE image, in which the dark X-ray sample is a *bright*
        band: going down the image, its upper edge is a rising (positive) peak
        and its lower edge is a falling (negative) peak.  Returns a 1D array of
        length self.image.shape[0].
        """
        image = cv2.GaussianBlur(self.image, (5, 5), sigmaX=5, sigmaY=0)
        sobely = cv2.Sobel(image, cv2.CV_64F, dx=0, dy=1)
        y_size = sobely.shape[1]
        if x_lo is None or x_hi is None:
            lo = int(y_size * x_lo_frac)
            hi = max(lo + 1, int(y_size * x_hi_frac))
        else:
            # Absolute column bounds from the left/right guides.
            lo = int(max(0, min(x_lo, y_size - 1)))
            hi = int(max(lo + 1, min(x_hi, y_size)))
        return sobely[:, lo:hi].mean(axis=1)

    def resolve_lr_bounds(self, x_lo=None, x_hi=None):
        """Resolve the horizontal fit window to absolute (x_lo, x_hi) columns.

        Explicit args win; otherwise fall back to settings['lr_limits']; if that
        is empty return (None, None) so the fractional 0.25/0.75 default is used.
        """
        if x_lo is not None and x_hi is not None:
            return x_lo, x_hi
        lr = self.settings.get('lr_limits') or []
        if len(lr) == 2 and lr[1] > lr[0]:
            return lr[0], lr[1]
        return None, None

    def select_edges(self, band_half_height=None, min_sep=None, max_sep=None,
                     x_lo_frac=0.25, x_hi_frac=0.75, min_conf=0.2,
                     x_lo=None, x_hi=None):
        """Pick exactly one upper and one lower edge row bracketing the sample,
        using the signed gradient profile.

        In the absorbance image the sample is a bright band, so its upper edge
        is a rising (positive) peak and its lower edge is a falling (negative)
        peak.  Among all valid (upper positive, lower negative) pairs with
        upper_row < lower_row and a plausible separation, the pair with the
        greatest combined prominence wins.

        Returns a dict:
          {'ok':bool, 'reason':str, 'row1':float, 'row2':float,
           'conf1':float, 'conf2':float, 'sep':float, 'w1':float, 'w2':float}
        where row1 < row2 (row1 -> edge_roi_1, row2 -> edge_roi_2).
        """
        x_lo, x_hi = self.resolve_lr_bounds(x_lo, x_hi)
        prof = gaussian_filter1d(
            self.compute_signed_edge_profile(x_lo_frac, x_hi_frac, x_lo=x_lo, x_hi=x_hi), 10)
        n = len(prof)
        if min_sep is None:
            min_sep = max(5, int(n * 0.03))
        if max_sep is None:
            max_sep = n

        norm = np.max(np.abs(prof)) if n else 0.0
        if norm <= 0:
            return {'ok': False, 'reason': 'no gradient'}
        p = prof / norm

        pos_peaks, pos_props = find_peaks(p, height=min_conf, width=3)   # rising -> upper edge
        neg_peaks, neg_props = find_peaks(-p, height=min_conf, width=3)  # falling -> lower edge
        if len(pos_peaks) == 0 or len(neg_peaks) == 0:
            return {'ok': False, 'reason': 'edge not found'}

        best = None
        for pi, pr in enumerate(pos_peaks):
            for ni, nr in enumerate(neg_peaks):
                if nr <= pr:
                    continue
                sep = nr - pr
                if sep < min_sep or sep > max_sep:
                    continue
                conf = pos_props['peak_heights'][pi] + neg_props['peak_heights'][ni]
                if best is None or conf > best[0]:
                    best = (conf, pr, nr,
                            pos_props['peak_heights'][pi], neg_props['peak_heights'][ni],
                            pos_props['widths'][pi], neg_props['widths'][ni])

        if best is None:
            return {'ok': False, 'reason': 'separation implausible'}

        _, row1, row2, conf1, conf2, w1, w2 = best
        return {'ok': True, 'reason': '',
                'row1': float(row1), 'row2': float(row2),
                'conf1': float(conf1), 'conf2': float(conf2),
                'sep': float(row2 - row1), 'w1': float(w1), 'w2': float(w2)}

    def estimate_lr_edges(self, row_lo, row_hi, frac=0.5):
        """Estimate the sample's left/right columns from the horizontal
        absorbance profile between the two detected top/bottom edge rows.

        In the absorbance image the sample is a bright band, so over the rows
        between its top and bottom edges the columns where the sample sits are
        brighter than the surrounding background. We take the mean absorbance
        per column across that vertical band and pick left/right where the
        smoothed profile crosses ``frac`` of the way from its background (min)
        to its peak (max). Falls back to the central 0.25/0.75 columns when the
        profile is flat/unusable.

        Returns [x_left, x_right] in binned absorbance-image columns.
        """
        W = self.image.shape[1]
        default = [int(W * 0.25), int(W * 0.75)]
        try:
            r0 = int(max(0, min(row_lo, row_hi)))
            r1 = int(min(self.image.shape[0], max(row_lo, row_hi)))
            if r1 - r0 < 1:
                return default
            prof = self.image[r0:r1, :].mean(axis=0)
            prof = gaussian_filter1d(prof, max(1, int(W * 0.02)))
            lo, hi = float(prof.min()), float(prof.max())
            if hi - lo <= 0:
                return default
            thr = lo + frac * (hi - lo)
            above = np.where(prof > thr)[0]
            if above.size < 2:
                return default
            x_left, x_right = int(above[0]), int(above[-1])
            if x_right - x_left < max(2, int(W * 0.05)):
                return default
            return [x_left, x_right]
        except Exception:
            return default

    def edge_geometries(self, sel, x_pos=0, x_width=None, band_half_height=None):
        """Turn a select_edges() result into two (pos, size) rectangles in
        absorbance-image coords, ordered [edge_roi_1 (upper), edge_roi_2 (lower)].

        If band_half_height is None the band height is derived from the detected
        peak width (matching the old auto-placement of width+80); otherwise the
        supplied half-height (from the one-time setup) is used for both edges.
        """
        if x_width is None:
            x_width = self.image.shape[1]
        geoms = []
        for row, w in [(sel['row1'], sel.get('w1', 20)), (sel['row2'], sel.get('w2', 20))]:
            half = band_half_height if band_half_height is not None else (w / 2.0 + 40)
            geoms.append(((x_pos, row - half), (x_width, 2 * half)))
        return geoms

    def build_edge_rois(self, geoms, edge_types):
        """Build self.rois from geometry by slicing self.image directly (no
        pyqtgraph widget needed).  Used by the headless batch path.  Clamps
        each rectangle to the image bounds and stores pos/size for
        compute_distance's x-range.
        """
        self.rois = []
        H, W = self.image.shape
        for i, (pos, size) in enumerate(geoms):
            x0 = max(0, min(int(round(pos[0])), W - 1))
            y0 = max(0, min(int(round(pos[1])), H - 1))
            x1 = max(x0 + 1, min(int(round(pos[0] + size[0])), W))
            y1 = max(y0 + 1, min(int(round(pos[1] + size[1])), H))
            selected = self.image[y0:y1, x0:x1]
            self.add_ROI(selected, (x0, y0), (x1 - x0, y1 - y0))
            self.rois[-1].edge_type = edge_types[i] if i < len(edge_types) else 0
        return self.rois

    def compute_distance(self, orders=None, thresholds=None, n_samples=50):
        """Fit both edge ROIs and return the vertical distance between them.

        This is the single source of truth for the length measurement, factored
        out of the controller so batch and interactive share it.  Returns a dict
        with the scalar results plus the arrays needed to draw the interactive
        overlays.
        """
        if orders is None:
            orders = self.settings['edge_polynomial_order']
        if thresholds is None:
            thresholds = self.settings['edge_fit_threshold']

        masked_imgs = []
        fits = []
        for i, roi in enumerate(self.rois):
            masked_img, x_fit, y_fit = roi.compute(threshold=thresholds[i], order=orders[i])
            masked_imgs.append(masked_img)
            fits.append((x_fit, y_fit))

        x_extents = []
        for roi in self.rois:
            x0 = roi.pos[0]
            w = roi.size[0]
            x_extents.append((x0, x0 + w))
        min_x = min(e[0] for e in x_extents)
        max_x = max(e[1] for e in x_extents)
        x_test = np.linspace(min_x, max_x, n_samples)

        edge1_y = self.rois[0].predict(x_test - self.rois[0].pos[0], orders[0]) + self.rois[0].pos[1]
        edge2_y = self.rois[1].predict(x_test - self.rois[1].pos[0], orders[1]) + self.rois[1].pos[1]

        y_diff = abs(np.mean(edge2_y - edge1_y))
        std_dev = np.std(edge2_y - edge1_y)
        y_0 = self.settings['crop_limits'][0][1]

        return {'y_diff': y_diff, 'std_dev': std_dev,
                'edge1_mean': np.mean(edge1_y) + y_0,
                'edge2_mean': np.mean(edge2_y) + y_0,
                'x_test': x_test, 'edge1_y': edge1_y, 'edge2_y': edge2_y,
                'masked': masked_imgs, 'fits': fits}

    def process_file(self, fname, crop_limits, edge_types, orders, thresholds,
                     band_half_height, edge_x_pos, edge_x_width, min_sep, max_sep,
                     std_dev_abs=5.0, std_dev_frac=0.15, weak_conf=0.3, min_conf=0.2,
                     lr_limits=None):
        """Headless full-pipeline measurement of one image for batch processing.

        Reuses the one-time setup (crop box, sample type, order, threshold, edge
        band size) but re-detects the edges per image (sample position can jump).
        Never raises: a bad frame returns a result flagged 'LOW' with a reason so
        the batch keeps running.  Interactive model state is snapshotted and
        restored so the on-screen image/ROIs are untouched afterwards.
        """
        snap = (self.src, self.cropped, self.cropped_resized, self.image,
                self.rois, self.filename, list(self.settings['crop_limits']))
        result = {'mean': '', 'std.dev': '', 'edge1': '', 'edge2': '',
                  'flag': 'LOW', 'reason': ''}
        try:
            self.load_file(fname)
            H, W = self.src.shape
            (cx, cy), (cw, ch) = crop_limits
            if cw <= 0 or ch <= 0 or cx < 0 or cy < 0 or cx + cw > W or cy + ch > H:
                result['reason'] = 'crop out of bounds'
                return result

            self.settings['crop_limits'] = crop_limits
            self.crop()
            self.filter_image()

            # Horizontal fit window from the left/right guides (same window the
            # user set interactively); falls back to the given edge x-extent.
            x_lo = x_hi = None
            if lr_limits and len(lr_limits) == 2 and lr_limits[1] > lr_limits[0]:
                x_lo, x_hi = int(lr_limits[0]), int(lr_limits[1])
                edge_x_pos, edge_x_width = x_lo, max(1, x_hi - x_lo)

            sel = self.select_edges(band_half_height=band_half_height,
                                    min_sep=min_sep, max_sep=max_sep, min_conf=min_conf,
                                    x_lo=x_lo, x_hi=x_hi)
            if not sel.get('ok'):
                result['reason'] = sel.get('reason', 'edge not found')
                return result

            geoms = self.edge_geometries(sel, x_pos=edge_x_pos, x_width=edge_x_width,
                                         band_half_height=band_half_height)
            self.build_edge_rois(geoms, edge_types)
            res = self.compute_distance(orders=orders, thresholds=thresholds)

            y_diff = res['y_diff']
            std_dev = res['std_dev']
            result['mean'] = str(round(y_diff, 1))
            result['std.dev'] = str(round(std_dev, 1))
            result['edge1'] = str(round(res['edge1_mean'], 1))
            result['edge2'] = str(round(res['edge2_mean'], 1))

            reasons = []
            if std_dev > max(std_dev_abs, std_dev_frac * y_diff):
                reasons.append('fit unstable')
            if sel['conf1'] < weak_conf or sel['conf2'] < weak_conf:
                reasons.append('weak contrast')
            result['flag'] = 'LOW' if reasons else 'OK'
            result['reason'] = '; '.join(reasons)
        except Exception as e:
            result['flag'] = 'LOW'
            result['reason'] = 'processing error: %s' % e
        finally:
            (self.src, self.cropped, self.cropped_resized, self.image,
             self.rois, self.filename, self.settings['crop_limits']) = snap
        return result

    def save_result(self, filename):

        data = {'edges':[]}
        if filename.endswith('.json'):
            with open(filename, 'w') as json_file:
                json.dump(data, json_file,indent = 2)    

    

def feature(x, order=3):
    """Generate polynomial feature of the form
    [1, x, x^2, ..., x^order] where x is the column of x-coordinates
    and 1 is the column of ones for the intercept.
    """
    x = x.reshape(-1, 1)
    return np.power(x, np.arange(order+1).reshape(1, -1)) 

def pixel_cluster_polynom_fit(I, order=3, threshold = .2):
    '''
    We find all (xi, yi) coordinates of the bright regions, 
    then set up a regularized least squares system where the we want to 
    find the vector of weights, (w0, ..., wd) such that 
    yi = w0 + w1 xi + w2 xi^2 + ... + wd xi^d "as close as possible" 
    in the least squares sense.
    Source: https://stackoverflow.com/questions/52802648/how-do-i-fit-a-line-to-a-cluster-of-pixels
    '''
    
    # Mask out region
    mask = I > threshold

    # Get coordinates of pixels corresponding to marked region
    X = np.argwhere(mask)

    # Use the value as weights later
    weights = I[mask] / float(I.max())
    # Convert to diagonal matrix
    W = np.diag(weights)

    # Column indices
    x = X[:, 1].reshape(-1, 1)
    # Row indices to predict. Note origin is at top left corner
    y = X[:, 0]


    # Ridge regression, i.e., least squares with l2 regularization. 
    # Should probably use a more numerically stable implementation, 
    # e.g., that in Scikit-Learn
    # alpha is regularization parameter. Larger alpha => less flexible curve
    alpha = 0.01

    # Construct data matrix, A
    #order = 3
    A = feature(x, order)
    # w = inv (A^T A + alpha * I) A^T y
    #w_unweighted = np.linalg.pinv( A.T.dot(A) + alpha * np.eye(A.shape[1])).dot(A.T).dot(y)
    # w = inv (A^T W A + alpha * I) A^T W y
    w_weighted = np.linalg.pinv( A.T.dot(W).dot(A) + alpha * \
                             np.eye(A.shape[1])).dot(A.T).dot(W).dot(y)

    return w_weighted
