#!/usr/bin/env python
# coding: utf-8

# In[2]:


import os
import sys
from os.path import join as pj
from os.path import exists
import subprocess
from copy import deepcopy
from IPython import get_ipython
from astropy.io import fits
import gc

import numpy as np
import scipy.linalg as slg
from scipy.stats import norm


# In[3]:


# For debugging purposes
from IPython import get_ipython
def in_notebook():
    ip = get_ipython()
    
    if ip:
        return True
    else:
        return False


# In[4]:


_HOME_DIR = os.path.expanduser("~")
if in_notebook():
    _SPARCFIRE_DIR = pj(_HOME_DIR, "sparcfire_matt") 
    _MODULE_DIR    = pj(_SPARCFIRE_DIR, "GalfitModule")
else:
    try:
        _SPARCFIRE_DIR = os.environ["SPARCFIRE_HOME"]
        _MODULE_DIR = pj(_SPARCFIRE_DIR, "GalfitModule")
    except KeyError:
        # print("SPARCFIRE_HOME is not set. Please run 'setup.bash' inside SpArcFiRe directory if not done so already.")
        # print("Running on the assumption that GalfitModule is in your home directory... (if not this will fail and quit!)") 
        _MODULE_DIR = pj(_HOME_DIR, "GalfitModule")

sys.path.append(_MODULE_DIR)

from Functions.helper_functions import *
from Classes.Components import *
from Classes.Containers import *


# In[5]:


class HDU:
    def __init__(self, 
                 name   = "observation",
                 header = {}, 
                 data   = None):
        self.name   = name
        self.header = dict(header)
        self.data   = data
        
    def to_dict(self):
        return {"name"   : name,
                "header" : header,
                "data"   : data
               }
    
    def __str__(self):
        header_str = ""
        for k,v in self.header.items():
            header_str += f"{k} = {v}\n"
            
        output_str = f"{self.name}\n{header_str}Img size: {np.shape(self.data)}"
        return output_str


# In[6]:


class FitsFile:
    def __init__(self,
                 filepath,
                 name = "observation",
                 wait = False,
                 **kwargs
                ):
        
        self.name     = name
        self.filepath = filepath
        
        # Use split over rstrip in case a waveband designation is given
        # (rstrip will remove any character that matches in the substring)
        # i.e. 12345678910_g would lose the _g for "_galfit_out.fits"
        # TODO: Replace rstrip with split in the rest of these scripts...
        self.gname    = kwargs.get("gname", os.path.basename(filepath).split("_galfit_out.fits")[0])
        # self.num_hdu  = 0
        # self.num_imgs = 1
        
        assert os.path.splitext(filepath)[-1] == ".fits", "File being passed into FitsHandler must be .fits!"
        
        try:
            file_in = fits.open(filepath)
            
        except FileNotFoundError:
            print(f"Can't open to read the file, {filepath}. Check name/permissions/directory.")
            raise(Exception()) 

        except OSError as ose:
            print(f"Something went wrong! {ose}")
            raise(Exception())
        
        # FITS starts the index at 0 but GALFIT outputs the observation image at 1
        # Also converting the header to a dict to save some trouble
        try:
            self.header = dict(file_in[1].header)
            self.data   = file_in[1].data
            self.num_imgs = len(file_in) - 1
        except IndexError:
            self.header = dict(file_in[0].header)
            self.data   = file_in[0].data
            self.num_imgs = 1       
        
        hdu = HDU(name = name, header = self.header, data = self.data)
        self.observation = hdu
        
        self.all_hdu  = {name : hdu}
        self.file = file_in
        
        # Wait is for continuing to use the file in some other capacity
        # i.e. for outputfits below to grab more info
        if not wait:
            file_in.close(verbose = True)
        
        #print("Did it close?", file_in.closed)
        # assert hdu_num == 4, "File being passed into FitsHandler has too few output HDUs."
# ==========================================================================================================

    #def close(self):
    #    self.file.close(verbose = True)
    #    return

    def close(self):
        """Destructor for closing FITS files."""
        
        for ext in self.file:
            try:
                del ext.data
                del ext.header
            except AttributeError as ae:
                pass
            gc.collect()

        try:
            self.file.close(verbose = True)
        except Exception as ee:
            print(f'Failed to close FITS instance for {self.gname}: {ee}')
            print("May already be closed...")

# ==========================================================================================================

    def to_png(self, cleanup = True, **kwargs): #tmp_fits_path = "", tmp_png_path = "", out_filename = ""):
        
        gname         = kwargs.get("gname", self.gname)
        
        tmp_fits_path = kwargs.get("tmp_fits_path", self.filepath)
        # .../galfits -> galfit_png
        tmp_png_dir   = os.path.split(tmp_fits_path)[0].rstrip("s") + "_png"
        tmp_png_path  = pj(tmp_png_dir, gname)
        tmp_png_path  = kwargs.get("tmp_png_path", tmp_png_path)
        out_png_dir   = kwargs.get("out_png_dir", "./")
        
        capture_output = bool(kwargs.get("silent", False))
        
        fitspng_param = "0.25,1" #1,150"
        
        # run_fitspng from HelperFunctions, string path to fitspng program
        fitspng_cmd1 = f"{run_fitspng} -fr \"{fitspng_param}\" -o {tmp_png_path}.png {tmp_fits_path}[1]"
        
        fitspng_cmd2 = f"{run_fitspng} -fr \"{fitspng_param}\" -o {tmp_png_path}_out.png {tmp_fits_path}[2]"
        
        fitspng_cmd3 = f"{run_fitspng} -fr \"{fitspng_param}\" -o {tmp_png_path}_residual.png {tmp_fits_path}[3]"
        
        cmds = [fitspng_cmd1, fitspng_cmd2, fitspng_cmd3]
        
        # sp is from HelperFunctions, subprocess.run call
        for cmd in cmds[:self.num_imgs]:
            _ = sp(cmd, capture_output = capture_output)
        
        im1 = f"{tmp_png_path}.png"
        im2 = f"{tmp_png_path}_out.png"
        im3 = f"{tmp_png_path}_residual.png"
        
        combined = ""
        if self.num_imgs > 1:
            combined = "_combined"
        
        montage_cmd = "montage " + \
                      " ".join(im_cmd for idx, im_cmd in enumerate([im1, im2, im3]) 
                               if idx <= self.num_imgs)
        
        # Combining the images using ImageMagick
        # If this is a single image, it'll also resize for me so that's why I leave it in
        montage_cmd += f" -tile {self.num_imgs}x1 -geometry \"175x175+2+0<\" \
                        {pj(out_png_dir, gname)}{combined}.png"
            
        _ = sp(montage_cmd, capture_output = capture_output)
        
        if cleanup:
            _ = sp(f"rm {im1} {im2} {im3}")
        else:
            self.observation_png = im1
            self.model_png       = im2
            self.residual_png    = im3            
            
        self.combined_png    = f"{pj(out_png_dir, gname)}{combined}.png"

# ==========================================================================================================

    def __sub__(self, other):
        
        names = self.all_hdu.keys()
        # Python doesn't care if they're different lengths but
        # (for instance in the residual) we don't want to compare one to one
        result = {k : a[k].data - b[k].data for k, a, b in zip(names, self.all_hdu, other.all_hdu)}
        
        return result

# ==========================================================================================================

    # # Use str to display feedme(?)
    # def __str__(self):
    #     pass
        
        #return output_str
        
# ==========================================================================================================

    # Use str to display feedme(?)
    def header_dict(self, name = ""):
        
        if name:
            output_dict = dict(self.all_hdu[name].header)
        else:
            output_dict = {name : dict(hdu.header) for name, hdu in self.all_hdu.items()}
            
        return output_dict
        
# ==========================================================================================================

    def update_params(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


# In[7]:


class OutputFits(FitsFile):

    def __init__(self, filepath, names = []):
        
        FitsFile.__init__(self, filepath = filepath, wait = True)
        
        # by initializing FitsFile we already have observation
        if not names:
            names = ["model", "residual"]
            
        # Don't need these but for posterity
        # self.hdu_num  = 4
        # self.num_imgs = self.hdu_num - 1
        
        # Exclude observation and primary HDU (0)
        for num, name in zip(range(2, 4), names):
            hdu = HDU(name, self.file[num].header, self.file[num].data)
            self.all_hdu[name] = hdu
            
        # For convenience, we usually use the model here
            
        self.update_params(**self.all_hdu) 
        
        # Dict is very redundant here but just for funsies
        self.header = dict(self.model.header)
        _header = GalfitHeader()
        # Can call the helper directly since we're just using the header dict
        _header.from_file_helper(self.header)
        self.feedme = FeedmeContainer(path_to_feedme = filepath, header = _header)
        self.feedme.from_file(self.header)
        
        self.data = self.model.data
        
        self.close()
        
        # self.observation = self.all_hdu.get("observation", None)
        # self.model       = self.all_hdu.get("model", None)
        # self.residual    = self.all_hdu.get("residual", None)
        
        
    def generate_masked_residual(self, mask):

        crop_box = self.feedme.header.region_to_fit

        # To adjust for python indexing
        box_min, box_max = crop_box[0] - 1, crop_box[1]

        # To invert the matrix since galfit keeps 0 valued areas 
        crop_mask = 1 - mask.data[box_min:box_max, box_min:box_max]
        
        try:
            self.masked_residual = (self.observation.data - self.model.data)*crop_mask

            self.norm_observation = slg.norm(crop_mask*self.observation.data)
            self.norm_model = slg.norm(crop_mask*self.model.data)
            self.norm_residual = slg.norm(crop_mask*self.residual.data)
            self.masked_residual_normalized = self.masked_residual/min(self.norm_observation, self.norm_model)
            # Masked residual normalized
            # I seem to use this acronym a lot
            self.nmr = slg.norm(self.masked_residual_normalized)

        except ValueError:
            print(f"There is probably an observation error with galaxy {self.gname}, continuing...")
            # print(np.shape(mask_fits_file.data))
            # print(np.shape(fits_file.data))
            # print(crop_box)
            return None
        
        return self.masked_residual_normalized


# In[8]:


if __name__ == "__main__":
    from RegTest.RegTest import *


# In[9]:


# Testing from_file
if __name__ == "__main__":
    
    gname = "1237671124296532233"
    obs   = pj(TEST_DATA_DIR, "test-in", f"{gname}.fits")
    model = pj(TEST_DATA_DIR, "test-out", gname, f"{gname}_galfit_out.fits")
    mask  = pj(TEST_DATA_DIR, "test-out", gname, f"{gname}_star-rm.fits")
    
    test_obs   = FitsFile(obs)
    test_model = OutputFits(model)
    test_mask  = FitsFile(mask)
    
    print(test_obs.observation)
    print()
    print(test_model.feedme)
    print()
    print(test_model.model)
    
    # Purposefully do not fill in some of the header parameters
    # since those do not exist in the output FITS header
    # This is done to remind the user/programmer that the 
    # OutputFits object only serves to represent the header
    # nothing more, nothing less and so also reminds them to
    # use a different method to fill in the header.
    #print(test_model.feedme.header)
    
#     _header = GalfitHeader()
#     _header.from_file_helper(test_out.header)
    
#     crop_box = _header.region_to_fit
#     # To adjust for python indexing
#     box_min, box_max = crop_box[0] - 1, crop_box[1]
        
#     print(np.shape(test_in.data[box_min:box_max, box_min:box_max]))
    print("\nThese should all be the same .")
    print(np.shape(test_model.observation.data))
    print(np.shape(test_model.data))
    print(np.shape(test_model.residual.data))
    crop_box = test_model.feedme.header.region_to_fit
    # + 1 to account for python indexing
    crop_rad = crop_box[1] - crop_box[0] + 1
    print(f"({crop_rad}, {crop_rad})")
    print("Andddd pre crop")
    print(np.shape(test_obs.observation.data))


# In[10]:


# Unit test to check value of masked residual
if __name__ == "__main__":
    
    _ = test_model.generate_masked_residual(test_mask)
    print(f"{test_model.norm_observation:.4f}")
    print(f"{test_model.norm_model:.4f}")
    print(f"{test_model.norm_residual:.4f}")
    print(f"{test_model.nmr:.4f}")


# In[11]:


if __name__ == "__main__":
    export_to_py("FitsHandlers", pj(_MODULE_DIR, "Classes", "FitsHandlers"))

