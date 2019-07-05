import os
import numpy as np

import telluric
from flux1d import apply_sensfunc
from pypeit.core import coadd1d
from pypeit import msgs

debug = False
show = True
do_sens = True

z_qso = 6.51
npca = 8
ex_value = 'OPT'
qsoname = 'J0224-4711'

datapath = os.path.join(os.getenv('HOME'), 'Dropbox/PypeIt_Redux/XSHOOTER/J0224-4711/pypeit/Science/')

# TODO: change the spec1dlist to the pypeit format and change the reader accordingly
spec1dlist = 'spec1dlist'
spec1dfiles = np.genfromtxt(os.path.join(datapath, spec1dlist),dtype='str')
nfiles = len(spec1dfiles)
fnames = []
for ifile in range(nfiles):
    fnames.append(os.path.join(datapath,spec1dfiles[ifile]))

#TODO: the objids shoul be read in from the pypeit format file as noted above.
objids = ['OBJ0001']*nfiles

std1dfile = os.path.join(os.getenv('HOME'),'Dropbox/PypeIt_Redux/XSHOOTER/J0224-4711/pypeit/Science/spec1d_XSHOO.2018-01-18T08:43:18.841-LTT3218_XShooter_VIS_2018Jan18T084318.841.fits')

# get the pca pickle file and atmosphere model grid
pca_file = os.path.join(os.getenv('HOME'),'Dropbox/PypeIt_Redux/qso_pca_1200_3100.pckl')
telgridfile = os.path.join(os.getenv('HOME'),'Dropbox/PypeIt_Redux/XSHOOTER/TelFit_Paranal_VIS_4900_11100_R25000.fits')

# TODO: set sensfile=None if you want to derive sensfunc from std1dfile
sensfile = os.path.join(os.getenv('HOME'), 'Dropbox/PypeIt_Redux/XSHOOTER/LTT3218_sens_tell_vis.fits')
if do_sens:
    if std1dfile is None:
        msgs.error('You need either give a std1dfile to derive sensfunc')
    else:
        # run telluric.sensfunc_telluric to get the sensfile
        TelSens = telluric.sensfunc_telluric(std1dfile, telgridfile, sensfile, mask_abs_lines=True, debug=True, disp=True)

## Apply the sensfunc to all spectra (only sensfunc but not tellluric)
# TODO: change show=False to show=show
#apply_sensfunc(fnames, sensfile, extinct_correct=False, tell_correct=False, debug=debug, show=False)

fnames_flux = [f.replace('.fits', '_flux.fits') for f in fnames]

## Let's coadd all the fluxed spectra
# you should get a coadded spectrum named as 'spec1d_stack_{:}.fits'.format(qsoname)
#                a straight merge of individual order stacked spectra named as 'spec1d_merge_{:}.fits'.format(qsoname)
#                a individual order stacked spectra (multi-extension) named as 'spec1d_order_{:}.fits'.format(qsoname)
# TODO: change the outfile to work with datapath. It's a hard coding on these names in coadd1d
wave_stack, flux_stack, ivar_stack, mask_stack = coadd1d.ech_combspec(fnames_flux, objids, sensfile=sensfile,
                                                                      ex_value='OPT', outfile=qsoname+'_newcoadd',
                                                                      show_order_scale=False, debug=False, show=True,
                                                                      show_exp=True)
#
# run telluric.qso_telluric to get the final results
spec1dfluxfile = 'spec1d_stack_{:}.fits'.format(qsoname)
telloutfile = 'spec1d_stack_{:}_tellmodel.fits'.format(qsoname)
outfile = 'spec1d_stack_{:}_tellcorr.fits'.format(qsoname)

from IPython import embed
embed()
# TODO: add other modes here
TelQSO = telluric.qso_telluric(spec1dfluxfile, telgridfile, pca_file, z_qso, telloutfile, outfile,
                               create_bal_mask=None, debug=True, show=show)