


import numpy as np
import scipy
import matplotlib.pyplot as plt
import os
from sklearn import mixture
from astropy.io import fits
from pypeit.core import pydl
import astropy.units as u
from astropy.io import fits
from astropy import stats
from pypeit.core import flux
from pypeit.core import load
from astropy import table
from pypeit.core import save
from pypeit.core import coadd2d
from pypeit.core import coadd1d
from pypeit.spectrographs import util
from pypeit import utils
from pypeit import msgs
import pickle
PYPEIT_FLUX_SCALE = 1e-17
from astropy.io import fits
import copy
from IPython import embed
import qso_pca
from pypeit.spectrographs.spectrograph import Spectrograph
from pypeit.spectrographs.util import load_spectrograph


##############################
#  Telluric model functions  #
##############################

def get_bounds_tell(tell_dict, resln_guess, resln_frac_bounds, pix_shift_bounds):

    # Set the bounds for the optimization
    bounds_tell = [(tell_dict['pressure_grid'].min(), tell_dict['pressure_grid'].max()),
                   (tell_dict['temp_grid'].min(), tell_dict['temp_grid'].max()),
                   (tell_dict['h2o_grid'].min(), tell_dict['h2o_grid'].max()),
                   (tell_dict['airmass_grid'].min(), tell_dict['airmass_grid'].max()),
                   (resln_guess * resln_frac_bounds[0], resln_guess * resln_frac_bounds[1]),
                   pix_shift_bounds]

    return bounds_tell

def read_telluric_grid(filename, wave_min=None, wave_max=None, pad = 0):

    hdul = fits.open(filename)
    wave_grid_full = 10.0*hdul[1].data
    model_grid_full = hdul[0].data
    nspec_full = wave_grid_full.size

    if wave_min is not None:
        ind_lower = np.argmin(np.abs(wave_grid_full - wave_min)) - pad
    else:
        ind_lower = 0
    if wave_max is not None:
        ind_upper = np.argmin(np.abs(wave_grid_full - wave_max)) + pad
    else:
        ind_upper=nspec_full
    wave_grid = wave_grid_full[ind_lower:ind_upper]
    model_grid = model_grid_full[:,:,:,:, ind_lower:ind_upper]

    pg = hdul[0].header['PRES0']+hdul[0].header['DPRES']*np.arange(0,hdul[0].header['NPRES'])
    tg = hdul[0].header['TEMP0']+hdul[0].header['DTEMP']*np.arange(0,hdul[0].header['NTEMP'])
    hg = hdul[0].header['HUM0']+hdul[0].header['DHUM']*np.arange(0,hdul[0].header['NHUM'])
    if hdul[0].header['NAM'] > 1:
        ag = hdul[0].header['AM0']+hdul[0].header['DAM']*np.arange(0,hdul[0].header['NAM'])
    else:
        ag = hdul[0].header['AM0']+1*np.arange(0,1)

    loglam = np.log10(wave_grid)
    dloglam = np.median(loglam[1:] - loglam[:-1])
    # Guess resolution from wavelength sampling of telluric grid if it is not provided
    resln_guess = 1.0/(3.0 * dloglam * np.log(10.0))  # assume roughly Nyquist sampling
    pix_per_R = 1.0/resln_guess / (dloglam * np.log(10.0)) / (2.0 * np.sqrt(2.0 * np.log(2)))
    tell_pad_pix = int(np.ceil(10.0 * pix_per_R))

    tell_dict = dict(wave_grid=wave_grid, dloglam=dloglam,
                     resln_guess=resln_guess, pix_per_R=pix_per_R, tell_pad_pix=tell_pad_pix,
                     pressure_grid=pg, temp_grid=tg, h2o_grid=hg, airmass_grid=ag, tell_grid=model_grid)
    return tell_dict


def interp_telluric_grid(theta,tell_dict):

    pg = tell_dict['pressure_grid']
    tg = tell_dict['temp_grid']
    hg = tell_dict['h2o_grid']
    ag = tell_dict['airmass_grid']
    model_grid = tell_dict['tell_grid']
    press,temp,hum,airmass = theta
    if len(pg) > 1:
        p_ind = int(np.round((press-pg[0])/(pg[1]-pg[0])))
    else:
        p_ind = 0
    if len(tg) > 1:
        t_ind = int(np.round((temp-tg[0])/(tg[1]-tg[0])))
    else:
        t_ind = 0
    if len(hg) > 1:
        h_ind = int(np.round((hum-hg[0])/(hg[1]-hg[0])))
    else:
        h_ind = 0
    if len(ag) > 1:
        a_ind = int(np.round((airmass-ag[0])/(ag[1]-ag[0])))
    else:
        a_ind = 0

    return model_grid[p_ind,t_ind,h_ind,a_ind]

def conv_telluric(tell_model, dloglam, res):

    pix_per_sigma = 1.0/res/(dloglam*np.log(10.0))/(2.0 * np.sqrt(2.0 * np.log(2))) # number of dloglam pixels per 1 sigma dispersion
    sig2pix = 1.0/pix_per_sigma # number of sigma per 1 pix
    #conv_model = scipy.ndimage.filters.gaussian_filter1d(tell_model, pix)
    # x = loglam/sigma on the wavelength grid from -4 to 4, symmetric, centered about zero.
    x = np.hstack([-1*np.flip(np.arange(sig2pix,4,sig2pix)),np.arange(0,4,sig2pix)])
    # g = Gaussian evaluated at x, sig2pix multiplied in to properly normalize the convolution
    g = (1.0/(np.sqrt(2*np.pi)))*np.exp(-0.5*(x)**2)*sig2pix
    conv_model = scipy.signal.convolve(tell_model,g,mode='same')
    return conv_model

def shift_telluric(tell_model, loglam, dloglam, shift):

    loglam_shift = loglam + shift*dloglam
    tell_model_shift = np.interp(loglam_shift, loglam, tell_model)
    return tell_model_shift


def eval_telluric(theta_tell, tell_dict, ind_lower=None, ind_upper=None):

    ntheta = len(theta_tell)
    tellmodel_hires = interp_telluric_grid(theta_tell[:4], tell_dict)

    ind_lower = 0 if ind_lower is None else ind_lower
    ind_upper = tell_dict['wave_grid'].size - 1 if ind_upper is None else ind_upper
    # Deal with padding for the convolutions
    ind_lower_pad = np.fmax(ind_lower - tell_dict['tell_pad_pix'], 0)
    ind_upper_pad = np.fmin(ind_upper + tell_dict['tell_pad_pix'], tell_dict['wave_grid'].size - 1)
    tell_pad_tuple = (ind_lower - ind_lower_pad, ind_upper_pad - ind_upper)
    tellmodel_conv = conv_telluric(tellmodel_hires[ind_lower_pad:ind_upper_pad + 1], tell_dict['dloglam'], theta_tell[4])

    if ntheta == 6:
        tellmodel_out = shift_telluric(tellmodel_conv, np.log10(tell_dict['wave_grid'][ind_lower_pad: ind_upper_pad+1]), tell_dict['dloglam'], theta_tell[5])
        return tellmodel_out[tell_pad_tuple[0]:-tell_pad_tuple[1]]
    else:
        return tellmodel_conv[tell_pad_tuple[0]:-tell_pad_tuple[1]]


############################
#  Fitting routines        #
############################

def tellfit_chi2(theta, flux, thismask, arg_dict):

    obj_model_func = arg_dict['obj_model_func']
    flux_ivar = arg_dict['ivar']

    theta_obj = theta[:-6]
    theta_tell = theta[-6:]
    tell_model = eval_telluric(theta_tell, arg_dict['tell_dict'],
                               ind_lower=arg_dict['ind_lower'], ind_upper=arg_dict['ind_upper'])
    obj_model, modelmask = obj_model_func(theta_obj, arg_dict['obj_dict'])

    if not np.any(modelmask):
        return np.inf
    else:
        totalmask = thismask & modelmask
        chi_vec = totalmask * (flux - tell_model*obj_model) * np.sqrt(flux_ivar)
        robust_scale = 2.0
        huber_vec = scipy.special.huber(robust_scale, chi_vec)
        loss_function = np.sum(np.square(huber_vec * totalmask))
        return loss_function

def tellfit(flux, thismask, arg_dict, **kwargs_opt):

    # Unpack arguments
    obj_model_func = arg_dict['obj_model_func'] # Evaluation function
    flux_ivar = arg_dict['ivar'] # Inverse variance of flux or counts
    bounds = arg_dict['bounds']  # bounds for differential evolution optimizaton
    seed = arg_dict['seed']      # Seed for differential evolution optimizaton
    result = scipy.optimize.differential_evolution(tellfit_chi2, bounds, args=(flux, thismask, arg_dict,), seed=seed,
                                                   **kwargs_opt)

    theta_obj  = result.x[:-6]
    theta_tell = result.x[-6:]
    tell_model = eval_telluric(theta_tell, arg_dict['tell_dict'],
                               ind_lower=arg_dict['ind_lower'], ind_upper=arg_dict['ind_upper'])
    obj_model, modelmask = obj_model_func(theta_obj, arg_dict['obj_dict'])
    totalmask = thismask & modelmask
    chi_vec = totalmask*(flux - tell_model*obj_model)*np.sqrt(flux_ivar)

    try:
        debug = arg_dict['debug']
    except KeyError:
        debug = False

    # Name of function for title in case QA requested
    obj_model_func_name = getattr(obj_model_func, '__name__', repr(obj_model_func))
    sigma_corr, maskchi = coadd1d.renormalize_errors(chi_vec, mask=totalmask, title = obj_model_func_name,
                                                     debug=debug)
    ivartot = flux_ivar/sigma_corr**2

    return result, tell_model*obj_model, ivartot


def unpack_orders(sobjs, ret_flam=False):

    # TODO This should be a general reader:
    #  For echelle:  read in all the orders into a (nspec, nporders) array
    #  FOr longslit: read in the stanard into a (nspec, 1) array
    # read in the


    # Read in the spec1d file
    norders = len(sobjs) # ToDO: This is incorrect if you have more than one object in the sobjs
    if ret_flam:
        nspec = sobjs[0].optimal['FLAM'].size
    else:
        nspec = sobjs[0].optimal['COUNTS'].size
    # Allocate arrays and unpack spectrum
    wave = np.zeros((nspec, norders))
    #wave_mask = np.zeros((nspec, norders),dtype=bool)
    flam = np.zeros((nspec, norders))
    flam_ivar = np.zeros((nspec, norders))
    flam_mask = np.zeros((nspec, norders),dtype=bool)
    for iord in range(norders):
        wave[:,iord] = sobjs[iord].optimal['WAVE']
        #wave_mask[:,iord] = sobjs[iord].optimal['WAVE'] > 0.0
        flam_mask[:,iord] = sobjs[iord].optimal['MASK']
        if ret_flam:
            flam[:,iord] = sobjs[iord].optimal['FLAM']
            flam_ivar[:,iord] = sobjs[iord].optimal['FLAM_IVAR']
        else:
            flam[:,iord] = sobjs[iord].optimal['COUNTS']
            flam_ivar[:,iord] = sobjs[iord].optimal['COUNTS_IVAR']

    return wave, flam, flam_ivar, flam_mask


def general_spec_reader(specfile, ret_flam=False):

    # Place holder routine that provides a generic spectrum reader

    bonus = {}
    try:
        # Read in the standard spec1d file produced by Pypeit
        sobjs, head = load.load_specobjs(specfile)
        wave, counts, counts_ivar, counts_mask = unpack_orders(sobjs, ret_flam=ret_flam)
        bonus['ECH_ORDER'] = (sobjs.ech_order).astype(int)
        bonus['ECH_ORDERINDX'] = (sobjs.ech_orderindx).astype(int)
        bonus['ECH_SNR'] = (sobjs.ech_snr).astype(float)
        bonus['NORDERS'] = wave.shape[1]
    except:
        # Read in the coadd 1d spectra file
        hdu = fits.open(specfile)
        head = hdu[0].header
        data = hdu[1].data
        wave_in, flux_in, flux_ivar_in, mask_in = data['OPT_WAVE'], data['OPT_FLAM'], data['OPT_FLAM_IVAR'], data[
            'OPT_MASK']
        wave = wave_in
        counts = flux_in
        counts_ivar = flux_ivar_in
        counts_mask = mask_in
        #wave = np.reshape(wave_in,(wave_in.size,1))
        #counts = np.reshape(flux_in,(wave_in.size,1))
        #counts_ivar = np.reshape(flux_ivar_in,(wave_in.size,1))
        #counts_mask = np.reshape(mask_in,(wave_in.size,1))

    try:
        spectrograph = load_spectrograph(head['INSTRUME'])
    except:
        # This is a hack until a generic spectrograph is implemented.
        spectrograph = load_spectrograph('shane_kast_blue')

    meta_spec = dict(core={}, bonus=bonus)
    core_keys = spectrograph.header_cards_for_spec()
    for key in core_keys:
        try:
            meta_spec['core'][key.upper()] = head[key.upper()]
        except KeyError:
            pass

    return wave, counts, counts_ivar, counts_mask, meta_spec, head

############################
#  Object model functions  #
############################


##############
# Sensfunc Model #
##############
def init_sensfunc_model(obj_params, iord, wave, flux, ivar, mask, tellmodel):

    # Model parameter guess for starting the optimizations
    flam_true = scipy.interpolate.interp1d(obj_params['std_dict']['wave'].value,
                                           obj_params['std_dict']['flux'].value, kind='linear',
                                           bounds_error=False, fill_value=np.nan)(wave)
    flam_true_mask = np.isfinite(flam_true)
    sensguess_arg = obj_params['exptime']*tellmodel*flam_true/(flux + (flux < 0.0))
    sensguess = np.log(sensguess_arg)
    fitmask = mask & np.isfinite(sensguess) & (sensguess_arg > 0.0) & np.isfinite(flam_true_mask)
    # Perform an initial fit to the sensitivity function to set the starting point for optimization
    mask, coeff = utils.robust_polyfit_djs(wave, sensguess, obj_params['polyorder_vec'][iord], function=obj_params['func'],
                                       minx=wave.min(), maxx=wave.max(), inmask=fitmask,
                                       lower=obj_params['sigrej'], upper=obj_params['sigrej'],
                                       use_mad=True)
    sensfit_guess = np.exp(utils.func_val(coeff, wave, obj_params['func'], minx=wave.min(), maxx=wave.max()))

    # Polynomial coefficient bounds
    bounds_obj = [(np.fmin(np.abs(this_coeff)*obj_params['delta_coeff_bounds'][0], obj_params['minmax_coeff_bounds'][0]),
                   np.fmax(np.abs(this_coeff)*obj_params['delta_coeff_bounds'][1], obj_params['minmax_coeff_bounds'][1]))
                   for this_coeff in coeff]
    # Create the obj_dict
    obj_dict = dict(wave=wave, wave_min=wave.min(), wave_max=wave.max(),
                    exptime=obj_params['exptime'], flam_true=flam_true, func=obj_params['func'],
                    polyorder=obj_params['polyorder_vec'][iord])

    if obj_params['debug']:
        plt.plot(wave, sensguess_arg, label='sensfunc estimate')
        plt.plot(wave, sensfit_guess, label='sensfunc fit')
        plt.ylim(-0.1 * sensfit_guess.min(), 1.3 * sensfit_guess.max())
        plt.legend()
        plt.title('Sensitivity Function Guess for iord={:d}'.format(iord))
        plt.show()

    return obj_dict, bounds_obj


# Sensitivity function evaluation function. Model for counts is flam_true/sensfunc
def eval_sensfunc_model(theta, obj_dict):

    wave_star = obj_dict['wave']
    wave_min = obj_dict['wave_min']
    wave_max = obj_dict['wave_max']
    flam_true = obj_dict['flam_true']
    func = obj_dict['func']
    exptime = obj_dict['exptime']

    sensfunc = np.exp(utils.func_val(theta, wave_star, func, minx=wave_min, maxx=wave_max))
    counts_model = exptime*flam_true/(sensfunc + (sensfunc == 0.0))

    return counts_model, (sensfunc > 0.0)

##############
# QSO Model #
##############
def init_qso_model(obj_params, iord, wave, flux, ivar, mask, tellmodel):

    pca_dict = qso_pca.init_pca(obj_params['pca_file'], wave, obj_params['z_qso'], obj_params['npca'])
    pca_mean = np.exp(pca_dict['components'][0, :])
    tell_mask = tellmodel > obj_params['tell_norm_thresh']
    # Create a reference model and bogus noise
    flux_ref = pca_mean * tellmodel
    ivar_ref = utils.inverse((pca_mean/100.0) ** 2)
    flam_norm_inv = coadd1d.robust_median_ratio(flux, ivar, flux_ref, ivar_ref, mask=mask, mask_ref=tell_mask)
    flam_norm = 1.0/flam_norm_inv

    # Set the bounds for the PCA and truncate to the right dimension
    coeffs = pca_dict['coeffs'][:,1:obj_params['npca']]
    # Compute the min and max arrays of the coefficients which are not the norm, i.e. grab the coeffs that aren't the first one
    coeff_min = np.amin(coeffs, axis=0)  # only
    coeff_max = np.amax(coeffs, axis=0)
    # QSO redshift: can vary within delta_zqso
    bounds_z = [(obj_params['z_qso'] - obj_params['delta_zqso'], obj_params['z_qso'] + obj_params['delta_zqso'])]
    bounds_flam = [(flam_norm*obj_params['bounds_norm'][0], flam_norm*obj_params['bounds_norm'][1])] # Norm: bounds determined from estimate above
    bounds_pca = [(i, j) for i, j in zip(coeff_min, coeff_max)]        # Coefficients:  determined from PCA model
    bounds_obj = bounds_z + bounds_flam + bounds_pca
    # Create the obj_dict
    obj_dict = dict(npca=obj_params['npca'], pca_dict=pca_dict)

    return obj_dict, bounds_obj

# QSO evaluation function. Model for QSO is a PCA spectrum
def eval_qso_model(theta, obj_dict):

    pca_model = qso_pca.pca_eval(theta, obj_dict['pca_dict'])
    # TODO Is the prior evaluation slowing things down??
    # TODO Disablingthe prior for now as I think it slows things down for no big gain
    #ln_pca_pri = qso_pca.pca_lnprior(theta_PCA, arg_dict['pca_dict'])
    #ln_pca_pri = 0.0
    #flux_model, tell_model, spec_model, modelmask
    return pca_model, (pca_model > 0.0)



# User defined functions
# obj_dict, bounds_obj = init_obj_model(obj_params, iord, wave, flux, ivar, mask, tellmodel)
# obj_model, modelmask =  eval_obj_model(theta_obj, obj_dict)

class Telluric(object):

    def __init__(self, wave, flux, ivar, mask, telgridfile, obj_params, init_obj_model, eval_obj_model,
                 sn_clip=50.0, airmass_guess=1.5, resln_guess=None,
                 resln_frac_bounds=(0.5, 1.5), pix_shift_bounds=(-2.0, 2.0),
                 maxiter=3, sticky=True, lower=3.0, upper=3.0,
                 seed=None, tol=1e-3, popsize=30, recombination=0.7, polish=True, disp=True, debug=False):

        # This init function performs the following steps:
        # 1) assignement of relevant input arguments
        # 2) reshape all spectra to be shape (nspec, norders) which the code operates on
        # 3) read in and initalize the telluric grid
        # 4) Interpolate spectra onto the fixed telluric wavelength grid, clip S/N
        # 5) Loop over orders to initialize object models, and determine index range of fits
        # 6) Initalize the output tables

        # 1) Assign arguments
        self.telgridfile = telgridfile
        self.obj_params = obj_params
        self.init_obj_model = init_obj_model
        self.airmass_guess = airmass_guess
        self.eval_obj_model = eval_obj_model
        self.resln_frac_bounds = resln_frac_bounds
        self.pix_shift_bounds = pix_shift_bounds
        self.maxiter = maxiter
        self.sticky = sticky
        self.lower = lower
        self.upper = upper
        self.tol = tol
        self.popsize = popsize
        self.recombination = recombination
        self.polish = polish
        self.disp = disp
        self.debug = debug

        # 2) Reshape all spectra to be (nspec, norders)
        self.wave_in_arr, self.flux_in_arr, self.ivar_in_arr, self.mask_in_arr, self.nspec_in, self.norders = \
            self.reshape(wave, flux, ivar, mask)

        # Optimizer requires a seed. This guarantees that the fit will be deterministic and hence reproducible
        self.seed = seed if seed is not None else 777
        rand = np.random.RandomState(seed=seed)
        seed_vec = rand.randint(2 ** 32 - 1, size=self.norders)

        # 3) Read the telluric grid and initalize associated parameters
        self.tell_dict = self.read_telluric_grid()
        self.wave_grid = self.tell_dict['wave_grid']
        self.ngrid = self.wave_grid.size
        self.resln_guess = resln_guess if resln_guess is not None else self.tell_dict['resln_guess']
        # Model parameter guess for determining the bounds with the init_obj_model function
        self.tell_guess = self.get_tell_guess()
        # Set the bounds for the telluric optimization
        self.bounds_tell = self.get_bounds_tell()

        # 4) Interpolate the input values onto the fixed telluric wavelength grid, clip S/N and process inmask
        self.flux_arr, self.ivar_arr, self.mask_arr = coadd1d.interp_spec(self.wave_grid, self.wave_in_arr, self.flux_in_arr,
                                                  self.ivar_in_arr, self.mask_in_arr)
        # This is a hack to get an interpolate mask indicating where wavelengths are good on each order
        _, _, self.wave_mask_arr = coadd1d.interp_spec(
            self.wave_grid, self.wave_in_arr, np.ones_like(self.flux_in_arr), np.ones_like(self.ivar_in_arr),
            (self.wave_in_arr > 1.0).astype(float))
        # Clip the ivar if that is requested (sn_clip = None simply returns the ivar otherwise)
        self.ivar_arr = utils.clip_ivar(self.flux_arr, self.ivar_arr, sn_clip, mask=self.mask_arr)

        # 5) Loop over orders to initialize object models, and determine index range of fits
        # sort the orders by the strength of their telluric absorption
        self.ind_lower, self.ind_upper = self.get_ind_lower_upper()
        self.srt_order_tell = self.sort_telluric()
        # Loop over the data to:
        #     1) determine the ind_lower, ind_upper for every order/spectrum
        #     2) initialize the obj_dict, and bounds by running the init_obj_model callable
        self.obj_dict_list = [None]*self.norders
        self.bounds_obj_list = [None]*self.norders
        self.bounds_list = [None]*self.norders
        self.arg_dict_list = [None]*self.norders
        self.max_ntheta_obj = 0
        for counter, iord in enumerate(self.srt_order_tell):
            msgs.info('Initializing object model for order: {:d}, {:d}/{:d}'.format(iord, counter, self.norders) +
                      ' with user supplied function: {:s}'.format(self.init_obj_model.__name__))
            tellmodel = eval_telluric(self.tell_guess, self.tell_dict,
                                      ind_lower=self.ind_lower[iord], ind_upper=self.ind_upper[iord])
            obj_dict, bounds_obj = init_obj_model(obj_params, iord,
                                                  self.wave_grid[self.ind_lower[iord]:self.ind_upper[iord]+1],
                                                  self.flux_arr[self.ind_lower[iord]:self.ind_upper[iord]+1, iord],
                                                  self.ivar_arr[self.ind_lower[iord]:self.ind_upper[iord]+1, iord],
                                                  self.mask_arr[self.ind_lower[iord]:self.ind_upper[iord]+1, iord],
                                                  tellmodel)
            self.obj_dict_list[iord] = obj_dict
            self.bounds_obj_list[iord] = bounds_obj
            self.max_ntheta_obj = np.fmax(self.max_ntheta_obj, len(bounds_obj))
            bounds_iord = bounds_obj + self.bounds_tell
            self.bounds_list[iord] = bounds_iord
            arg_dict_iord = dict(ivar=self.ivar_arr[self.ind_lower[iord]:self.ind_upper[iord]+1, iord],
                                 tell_dict=self.tell_dict, ind_lower=self.ind_lower[iord], ind_upper=self.ind_upper[iord],
                                 obj_model_func=self.eval_obj_model, obj_dict=obj_dict,
                                 bounds=bounds_iord, seed=seed_vec[iord], debug=debug)
            self.arg_dict_list[iord] = arg_dict_iord

        # 6) Initalize the output tables
        self.meta_table, self.out_table = self.init_output()

    def run(self, only_orders=None):

        only_orders = [only_orders] if (only_orders is not None and
                                        isinstance(only_orders, (int, np.int, np.int64, np.int32))) else only_orders
        good_orders = self.srt_order_tell if only_orders is None else only_orders
        # Run the fits
        self.result_list = [None]*self.norders
        self.outmask_list = [None]*self.norders
        self.obj_model_list = [None]*self.norders
        self.tellmodel_list = [None]*self.norders
        self.theta_obj_list = [None]*self.norders
        self.theta_tell_list = [None]*self.norders
        for counter, iord in enumerate(self.srt_order_tell):
            if iord not in good_orders:
                continue
            msgs.info('Fitting object + telluric model for order: {:d}, {:d}/{:d}'.format(iord, counter, self.norders) +
                      ' with user supplied function: {:s}'.format(self.init_obj_model.__name__))
            self.result_list[iord], ymodel, ivartot, self.outmask_list[iord] = utils.robust_optimize(
                self.flux_arr[self.ind_lower[iord]:self.ind_upper[iord]+1, iord], tellfit, self.arg_dict_list[iord],
                inmask=self.mask_arr[self.ind_lower[iord]:self.ind_upper[iord]+1, iord],
                maxiter=self.maxiter, lower=self.lower, upper=self.upper, sticky=self.sticky,
                tol=self.tol, popsize=self.popsize, recombination=self.recombination, polish=self.polish, disp=self.disp)
            self.theta_obj_list[iord] = self.result_list[iord].x[:-6]
            self.theta_tell_list[iord] = self.result_list[iord].x[-6:]
            self.obj_model_list[iord], modelmask = self.eval_obj_model(self.theta_obj_list[iord], self.obj_dict_list[iord])
            self.tellmodel_list[iord] = eval_telluric(self.theta_tell_list[iord], self.tell_dict,
                                                      ind_lower=self.ind_lower[iord],
                                                      ind_upper=self.ind_upper[iord])
            self.assign_output(iord)
            if self.debug:
                self.show_fit_qa(iord)

    def save(self, outfile):
        """
        Method for writing astropy tables containing fits to a multi-extension fits file

        Args:
            outfile:

        Returns:

        """
        # Write to outfile
        msgs.info('Writing object and telluric models to file: {:}'.format(outfile))
        hdu_meta = fits.table_to_hdu(self.meta_table)
        hdu_meta.name = 'METADATA'
        hdu_out = fits.table_to_hdu(self.out_table)
        hdu_out.name = 'OUT_TABLE'
        hdulist = fits.HDUList()
        hdulist.append(hdu_meta)
        hdulist.append(hdu_out)
        hdulist.writeto(outfile, overwrite=True)

    def show_fit_qa(self, iord):
        """
        Generates QA plot for telluric fitting

        Args:
            iord: the order being currently fit

        """

        wave_now = self.wave_grid[self.ind_lower[iord]:self.ind_upper[iord]+1]
        flux_now = self.flux_arr[self.ind_lower[iord]:self.ind_upper[iord]+1, iord]
        sig_now = np.sqrt(utils.inverse(self.ivar_arr[self.ind_lower[iord]:self.ind_upper[iord]+1, iord]))
        mask_now = self.mask_arr[self.ind_lower[iord]:self.ind_upper[iord]+1, iord]
        model_now = self.tellmodel_list[iord]*self.obj_model_list[iord]
        rejmask = mask_now & np.invert(self.outmask_list[iord])

        fig = plt.figure(figsize=(12, 8))
        plt.plot(wave_now, flux_now, drawstyle='steps-mid',
                 color='k', label='data', alpha=0.7, zorder=5)
        plt.plot(wave_now, sig_now, drawstyle='steps-mid', color='0.7', label='noise', alpha=0.7, zorder=1)
        plt.plot(wave_now, model_now, drawstyle='steps-mid', color='red', linewidth=1.0, label='model',
                 zorder=7, alpha=0.7)
        plt.plot(wave_now[rejmask], flux_now[rejmask], 's', zorder=10, mfc='None', mec='blue', label='rejected pixels')
        plt.plot(wave_now[np.invert(mask_now)], flux_now[np.invert(mask_now)], 'v', zorder=9, mfc='None', mec='orange',
                 label='originally masked')
        plt.ylim(-0.1 * model_now.max(), 1.3 * model_now.max())
        plt.legend()
        plt.xlabel('Wavelength')
        plt.ylabel('Flux or Counts')
        plt.title('QA plot for order: {:d}/{:d}'.format(iord, self.norders))
        plt.show()

    def init_output(self):

        # Allocate the meta parameter table, ext=1
        meta_table = table.Table(meta={'name': 'Parameter Values'})
        meta_table['TOL'] = [self.tol]
        meta_table['POPSIZE'] = [self.popsize]
        meta_table['RECOMBINATION'] = [self.recombination]
        meta_table['TELGRIDFILE'] = [os.path.basename(self.telgridfile)]
        if 'output_meta_keys' in self.obj_params:
            for key in self.obj_params['output_meta_keys']:
                meta_table[key.upper()] = [self.obj_params[key]]

        # Allocate the output table, ext=2
        out_table = table.Table(meta={'name': 'Object Model and Telluric Correction'})
        out_table['WAVE'] = np.zeros((self.norders, self.nspec_in))
        out_table['TELLURIC'] = np.zeros((self.norders, self.nspec_in))
        out_table['OBJ_MODEL'] = np.zeros((self.norders, self.nspec_in))
        out_table['TELL_THETA'] = np.zeros((self.norders, 6))
        out_table['TELL_PRESS'] = np.zeros(self.norders)
        out_table['TELL_TEMP'] = np.zeros(self.norders)
        out_table['TELL_H2O'] = np.zeros(self.norders)
        out_table['TELL_AIRMASS'] = np.zeros(self.norders)
        out_table['TELL_RESLN'] = np.zeros(self.norders)
        out_table['TELL_SHIFT'] = np.zeros(self.norders)
        out_table['OBJ_THETA'] = np.zeros((self.norders, self.max_ntheta_obj))
        out_table['CHI2'] = np.zeros(self.norders)
        out_table['SUCCESS'] = np.zeros(self.norders, dtype=bool)
        out_table['NITER'] = np.zeros(self.norders, dtype=int)
        out_table['IND_LOWER'] = self.ind_lower
        out_table['IND_UPPER'] = self.ind_upper
        out_table['WAVE_MIN'] = self.wave_grid[self.ind_lower]
        out_table['WAVE_MAX'] = self.wave_grid[self.ind_upper]


        return meta_table, out_table

    def assign_output(self, iord):

        ## TODO Store the outmask with rejected pixels??
        gdwave = self.wave_in_arr[:,iord] > 1.0
        wave_in_gd = self.wave_in_arr[gdwave,iord]
        wave_grid_now = self.wave_grid[self.ind_lower[iord]:self.ind_upper[iord]+1]
        self.out_table['WAVE'][iord] = self.wave_in_arr[:,iord]
        self.out_table['TELLURIC'][iord][gdwave] = scipy.interpolate.interp1d(
            wave_grid_now, self.tellmodel_list[iord], kind='linear', bounds_error=False, fill_value=0.0)(wave_in_gd)
        self.out_table['OBJ_MODEL'][iord][gdwave] = scipy.interpolate.interp1d(
            wave_grid_now, self.obj_model_list[iord], kind='linear', bounds_error=False, fill_value=0.0)(wave_in_gd)
        self.out_table['TELL_THETA'][iord] = self.theta_tell_list[iord]
        self.out_table['TELL_PRESS'][iord] = self.theta_tell_list[iord][0]
        self.out_table['TELL_TEMP'][iord] = self.theta_tell_list[iord][1]
        self.out_table['TELL_H2O'][iord] = self.theta_tell_list[iord][2]
        self.out_table['TELL_AIRMASS'][iord] = self.theta_tell_list[iord][3]
        self.out_table['TELL_RESLN'][iord] = self.theta_tell_list[iord][4]
        self.out_table['TELL_SHIFT'][iord] = self.theta_tell_list[iord][5]
        ntheta_iord = len(self.theta_obj_list[iord])
        self.out_table['OBJ_THETA'][iord][0:ntheta_iord+1] = self.theta_obj_list[iord]
        self.out_table['CHI2'][iord] = self.result_list[iord].fun
        self.out_table['SUCCESS'][iord] = self.result_list[iord].success
        self.out_table['NITER'][iord] = self.result_list[iord].nit


    def interpolate_inmask(self, mask, wave_inmask, inmask):

        if inmask is not None:
            if wave_inmask is None:
                msgs.error('If you are specifying a mask you need to pass in the corresponding wavelength grid')
            # TODO we shoudld consider refactoring the interpolator to take a list of images and masks to remove the
            # the fake zero images in the call below
            _, _, inmask_int = coadd1d.interp_spec(self.wave_grid, wave_inmask, np.ones_like(wave_inmask),
                                                   np.ones_like(wave_inmask), inmask)
            # If the data mask is 2d, and inmask is 1d, tile to create the inmask aligned with the data
            if mask.ndim == 2 & inmask.ndim == 1:
                inmask_out = np.tile(inmask_int, (self.norders, 1)).T
            # If the data mask and inmask have the same dimensionlaity, interpolated mask has correct dimensions
            elif mask.ndim == inmask.ndim:
                inmask_out = inmask_int
            else:
                msgs.error('Unrecognized shape for data mask')
            return (mask & inmask_out)
        else:
            return mask


    def get_ind_lower_upper(self):

        ind_lower = np.zeros(self.norders, dtype=int)
        ind_upper = np.zeros(self.norders, dtype=int)
        for iord in range(self.norders):
            # This presumes that the data has been interpolated onto the telluric model grid
            wave_grid_ma = np.ma.array(np.copy(self.wave_grid))
            # For the ind lower and upper, use the good wavelength mask, not the data mask. This gives
            # us the model everywhere where wavelengths are not zero
            wave_grid_ma.mask = np.invert(self.wave_mask_arr[:, iord])
            #wave_grid_ma.mask = np.invert(self.mask_arr[:,iord])
            ind_lower[iord] = np.ma.argmin(wave_grid_ma)
            ind_upper[iord] = np.ma.argmax(wave_grid_ma)
        return ind_lower, ind_upper

    def reshape(self, wave, flux, ivar, mask):
        # Repackage the data into arrays of shape (nspec, norders)
        if flux.ndim == 1:
            nspec = flux.size
            norders = 1
            wave_arr = wave.reshape(nspec,1)
            flux_arr = flux.reshape(nspec, 1)
            ivar_arr = ivar.reshape(nspec, 1)
            mask_arr = mask.reshape(nspec, 1)
        else:
            nspec, norders = flux.shape
            if wave.ndim == 1:
                wave_arr = np.tile(wave, (norders, 1)).T
            else:
                wave_arr = wave
            flux_arr = flux
            ivar_arr = ivar
            mask_arr = mask

        return wave_arr, flux_arr, ivar_arr, mask_arr, nspec, norders

    ##########################
    ## telluric grid methods #
    ##########################
    def read_telluric_grid(self, wave_min=None, wave_max=None, pad=0):
        """
        Wrapper for utility function read_telluric_grid
        Args:
            wave_min:
            wave_max:
            pad:

        Returns:

        """

        return read_telluric_grid(self.telgridfile, wave_min=wave_min, wave_max=wave_max, pad=pad)


    def get_tell_guess(self):

        tell_guess = (np.median(self.tell_dict['pressure_grid']),
                      np.median(self.tell_dict['temp_grid']),
                      np.median(self.tell_dict['h2o_grid']),
                      self.airmass_guess, self.resln_guess, 0.0)

        return tell_guess

    def get_bounds_tell(self):

        # Set the bounds for the optimization
        bounds_tell = [(self.tell_dict['pressure_grid'].min(), self.tell_dict['pressure_grid'].max()),
                       (self.tell_dict['temp_grid'].min(), self.tell_dict['temp_grid'].max()),
                       (self.tell_dict['h2o_grid'].min(), self.tell_dict['h2o_grid'].max()),
                       (self.tell_dict['airmass_grid'].min(), self.tell_dict['airmass_grid'].max()),
                       (self.resln_guess * self.resln_frac_bounds[0], self.resln_guess * self.resln_frac_bounds[1]),
                       self.pix_shift_bounds]

        return bounds_tell

    def sort_telluric(self):

        tell_med = np.zeros(self.norders)
        # Do a quick loop over all the orders to sort them in order of strongest to weakest telluric absorption
        for iord in range(self.norders):
            tm_grid = self.tell_dict['tell_grid'][:, :, :, :, self.ind_lower[iord]:self.ind_upper[iord] + 1]
            tell_model_mid = tm_grid[tm_grid.shape[0] // 2, tm_grid.shape[1] // 2, tm_grid.shape[2] // 2,
                             tm_grid.shape[3] // 2, :]
            tell_med[iord] = np.mean(tell_model_mid)

        # Perform fits in order of telluric strength
        srt_order_tell = tell_med.argsort()

        return srt_order_tell


def mask_star_lines(wave_star, mask_width=10.0):
    """
    Mask stellar recombination lines
    Args:
        wave_star: ndarray, shape (nspec,) or (nspec, nimgs)
        mask_width: float, width to mask around each line centers in Angstroms
    Returns:
        mask: ndarray, same shape as wave_star, True=Good (i.e. does not hit a stellar absorption line)
    """

    mask_star = np.ones_like(wave_star, dtype=bool)
    # Mask Balmer, Paschen, Brackett, and Pfund recombination lines
    msgs.info("Masking stellar lines: Balmer, Paschen, Brackett, Pfund")
    # Mask Balmer
    msgs.info(" Masking Balmer")
    lines_balm = np.array([3836.4, 3969.6, 3890.1, 4102.8, 4102.8, 4341.6, 4862.7, 5407.0,
                           6564.6, 8224.8, 8239.2])
    for line_balm in lines_balm:
        ibalm = np.abs(wave_star - line_balm) <= mask_width
        mask_star[ibalm] = False
    # Mask Paschen
    msgs.info(" Masking Paschen")
    # air wavelengths from:
    # https://www.subarutelescope.org/Science/Resources/lines/hi.html
    lines_pasc = np.array([8203.6, 8440.3, 8469.6, 8504.8, 8547.7, 8600.8, 8667.4, 8752.9,
                           8865.2, 9017.4, 9229.0, 9546.0, 10049.4, 10938.1,
                           12818.1, 18751.0])
    for line_pasc in lines_pasc:
        ipasc = np.abs(wave_star - line_pasc) <= mask_width
        mask_star[ipasc] = False
    # Mask Brackett
    msgs.info(" Masking Brackett")
    # air wavelengths from:
    # https://www.subarutelescope.org/Science/Resources/lines/hi.html
    lines_brac = np.array([14584.0, 18174.0, 19446.0, 21655.0, 26252.0, 40512.0])
    for line_brac in lines_brac:
        ibrac = np.abs(wave_star - line_brac) <= mask_width
        mask_star[ibrac] = False
    # Mask Pfund
    msgs.info(" Masking Pfund")
    # air wavelengths from:
    # https://www.subarutelescope.org/Science/Resources/lines/hi.html
    lines_pfund = np.array([22788.0, 32961.0, 37395.0, 46525.0, 74578.0])
    for line_pfund in lines_pfund:
        ipfund = np.abs(wave_star - line_pfund) <= mask_width
        mask_star[ipfund] = False

    return mask_star

def sensfunc_telluric(spec1dfile, telgridfile, outfile, star_type=None, star_mag=None, star_ra=None, star_dec=None,
                      polyorder=8, mask_abs_lines=True, delta_coeff_bounds=(-20.0, 20.0), minmax_coeff_bounds=(-5.0, 5.0),
                      only_orders=None, tol=1e-3, popsize=30, recombination=0.7, polish=True, disp=True,
                      debug_init=False, debug=False):


    # Read in the data
    wave, counts, counts_ivar, counts_mask, meta_spec, header = general_spec_reader(spec1dfile, ret_flam=False)
    # Read in standard star dictionary and interpolate onto regular telluric wave_grid
    star_ra = meta_spec['core']['RA'] if star_ra is None else star_ra
    star_dec = meta_spec['core']['DEC'] if star_dec is None else star_dec
    std_dict = flux.get_standard_spectrum(star_type=star_type, star_mag=star_mag, ra=star_ra, dec=star_dec)

    if counts.ndim == 2:
        norders = counts.shape[1]
    else:
        norders = 1

    # Create the polyorder_vec
    if np.size(polyorder) > 1:
        if np.size(polyorder) != norders:
            msgs.error('polyorder must have either have norder elements or be a scalar')
        polyorder_vec = np.array(polyorder)
    else:
        polyorder_vec = np.full(norders, polyorder)

    # Initalize the object parameters
    obj_params = dict(std_dict=std_dict, airmass=meta_spec['core']['AIRMASS'],
                      delta_coeff_bounds=delta_coeff_bounds, minmax_coeff_bounds=minmax_coeff_bounds,
                      polyorder_vec=polyorder_vec, exptime=meta_spec['core']['EXPTIME'],
                      func='legendre', sigrej=3.0,
                      std_source=std_dict['std_source'], std_ra=std_dict['std_ra'], std_dec=std_dict['std_dec'],
                      std_name=std_dict['name'], std_calfile=std_dict['cal_file'],
                      output_meta_keys=('airmass', 'polyorder_vec', 'exptime', 'func', 'std_source',
                                        'std_ra', 'std_dec', 'std_name', 'std_calfile'),
                      debug=debug_init)

    # Optionally, mask prominent stellar absorption features
    if mask_abs_lines:
        inmask = mask_star_lines(wave)
        mask_tot = inmask & counts_mask
    else:
        mask_tot = counts_mask

    # parameters lowered for testing
    TelObj = Telluric(wave, counts, counts_ivar, mask_tot, telgridfile, obj_params,
                      init_sensfunc_model, eval_sensfunc_model,  tol=tol, popsize=popsize, recombination=recombination,
                      polish=polish, disp=disp, debug=debug)

    TelObj.run(only_orders=only_orders)
    TelObj.save(outfile)

    return TelObj

def create_bal_mask(wave):

    # example of a BAL mask
    bal_mask =  (wave > 12000.0) & (wave < 12100)
    return np.invert(bal_mask)



def qso_telluric(spec1dfile, telgridfile, pca_file, z_qso, telloutfile, outfile, npca = 8, create_bal_mask=None,
                 delta_zqso=0.1, bounds_norm=(0.1, 3.0), tell_norm_thresh=0.9, only_orders=None,
                 tol=1e-3, popsize=30, recombination=0.7, polish=True, disp=True, debug=False, show=False):


    obj_params = dict(pca_file=pca_file, npca=npca, z_qso=z_qso, delta_zqso=delta_zqso, bounds_norm=bounds_norm,
                      tell_norm_thresh=tell_norm_thresh,
                      output_meta_keys=('pca_file', 'npca', 'z_qso', 'delta_zqso','bounds_norm', 'tell_norm_thresh'))

    wave, flux, ivar, mask, meta_spec, header = general_spec_reader(spec1dfile, ret_flam=True)
    header = fits.getheader(spec1dfile) # clean this up!
    # Mask the IGM and mask wavelengths that extend redward of our PCA
    qsomask = (wave > (1.0 + z_qso)*1220.0) & (wave < 3100.0*(1.0 + z_qso))
    # TODO this 3100 is hard wired now, but make the QSO PCA a PypeIt product and determine it from the file
    if create_bal_mask is not None:
        bal_mask = create_bal_mask(wave)
        mask_tot = mask & qsomask & bal_mask
    else:
        mask_tot = mask & qsomask

    # parameters lowered for testing
    TelObj = Telluric(wave, flux, ivar, mask_tot, telgridfile, obj_params, init_qso_model, eval_qso_model,
                      tol=tol, popsize=popsize, recombination=recombination,
                      polish=polish, disp=disp, debug=debug)
    TelObj.run(only_orders=only_orders)
    TelObj.save(telloutfile)

    # Apply the telluric correction
    meta_table = table.Table.read(telloutfile, hdu=1)
    out_table = table.Table.read(telloutfile, hdu=2)

    telluric = out_table['TELLURIC'][0,:]
    pca_model = out_table['OBJ_MODEL'][0,:]
    #if show:
    # Plot the telluric corrected and rescaled orders
    flux_corr = flux/(telluric + (telluric == 0.0))
    ivar_corr = (telluric > 0.0) * ivar * telluric * telluric
    mask_corr = (telluric > 0.0) * mask
    sig_corr = np.sqrt(utils.inverse(ivar_corr))

    if show:
        # Median filter
        med_width = int(flux.size*0.001)
        flux_med = utils.fast_running_median(flux_corr, med_width)
        fig = plt.figure(figsize=(12, 8))
        plt.plot(wave, flux_corr, drawstyle='steps-mid', color='0.7', label='corrected data', alpha=0.7, zorder=5)
        plt.plot(wave, flux_med, drawstyle='steps-mid', color='k', label='corrected data', alpha=0.7, zorder=5)
        plt.plot(wave, sig_corr, drawstyle='steps-mid', color='r', label='noise', alpha=0.3, zorder=1)
        plt.plot(wave, pca_model, color='cornflowerblue', linewidth=1.0, label='PCA model', zorder=7, alpha=0.7)
        plt.plot(wave, pca_model.max()*0.9*telluric, color='magenta', drawstyle='steps-mid', label='pca', alpha=0.4)
        plt.ylim(-0.1*pca_model.max(), 1.5*pca_model.max())
        plt.legend()
        plt.xlabel('Wavelength')
        plt.ylabel('Flux')
        plt.show()

    save.save_coadd1d_to_fits(outfile, wave, flux_corr, ivar_corr, mask_corr, telluric=telluric, obj_model=pca_model,
                              header=header, ex_value='OPT', overwrite=True)


