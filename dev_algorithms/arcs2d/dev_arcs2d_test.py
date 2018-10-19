""" For the development and testing of 2D ARCS
"""

from __future__ import (print_function, absolute_import, division,
                        unicode_literals)

# General imports
import numpy as np
import scipy
import matplotlib.pyplot as plt
from scipy.io import readsav
from astropy.io import ascii
from astropy.stats import sigma_clip

# PYPEIT imports
from pypeit.core import pydl

###############################################################
# Porting XIDL code x_fit2darc to python

# PURPOSE of the XIDL code:
#  To fit the arc lines identified in x_fitarc as a function of
#  their y-centroid and order number. The main routine is in
#  x_fit2darc. The fit is a simple least-squares with one round 
#  of rejection.

# Feige runned the code on his GNRIS data. I will use this to
# test that the PYPEIT code will arrive to the same outputs of
# XIDL

debug = False

# Reading in the output from XIDL for GNRIS.
# Order vector
order = [3, 4, 5, 6, 7, 8]

# Number of identified lines per order
pixid = np.zeros_like(order)

# Read pixels and wavelengths from sv_lines_clean.txt
# this is just reading the file that Feige gave me.
f = open('./sav_files/sv_lines_clean.txt', 'r')
PIXWL_str = f.readlines()
full = {}
index = 0
for line in PIXWL_str:
    full[index] = np.fromstring(line, dtype=float, sep=' ')
    index = index+1
all_pix = {}
all_wv = {}
index = 0
for ii in np.arange(0, 12, 2):
    all_pix[index] = full[ii][np.nonzero(full[ii])]
    all_wv[index] = full[ii+1][np.nonzero(full[ii+1])]
    pixid[index] = len(all_pix[index])
    index = index+1

# Now I have a dict with pixels [all_pix] , one with
# corresponding wavelengths [all_wl], and one vector with 
# the orders [order].
# I'm creating now the vectors resambling those in XIDL.

all_pix_pypeit = []
t_pypeit = []
all_wv_pypeit = []
npix_pypeit = []
index = 0

for ii in all_pix.keys():
    all_pix_pypeit = np.concatenate((all_pix_pypeit,
                                     np.array(all_pix[ii])))
    t_tmp = np.full_like(np.array(all_pix[ii]), np.float(order[index]))
    t_pypeit = np.concatenate((t_pypeit, t_tmp))
    all_wv_pypeit = np.concatenate((all_wv_pypeit,
                                     np.array(all_wv[ii])))
    npix_tmp = np.full_like(np.array(all_pix[ii]), np.size(all_pix[ii]))
    npix_pypeit = np.concatenate((npix_pypeit, npix_tmp))
    index = index + 1

# Setting the same format of XIDL
# all_wv_pypeit = all_wv_pypeit * t_pypeit


from dev_arcs2d import fit2darc

fit2darc(all_wv_pypeit, all_pix_pypeit, t_pypeit, debug=False)



