#
# See top-level LICENSE.rst file for Copyright information
#
# -*- coding: utf-8 -*-
"""
This modules defines all contents of the PypeIt dev suite.  It is intended to be a single place to edit when adding new
instruments, setups, tests or test types.

To add a new instrument and/or setup to the dev suite:

1) Make sure the necessary raw data, pypeit files, and other test files are in the PypeIt-development-suite repo and
   the development suite google drive. See https://pypeit.readthedocs.io/en/latest/development.html#development-suite
2) Add the instrument and setup(s) to the develop_setups dict
3) If this is a new instrument, add the instrument to the supported_instruments list.
3) If additional tests are desired add 'instrument/setup' to the desired test attribute.

To add a new test for an existing setup:

1) Find the appropriate XXX_tests attribute for the test type. For example, to add a quick look test, edit
   quick_look_tests.
2) If the test type does not require any arguments, the attribute will be a set. Simply add the setup.
3) If the test type requires arguments, they will be passed to the PypeItTest subclasses constructor as keyword
   arguments. Put the arguments into a dict using the keyword argument as a key. For example:

   telluric_tests = {'gemini_gnirs/32_SB_SXD':
                         {'coadd_file': 'pisco_coadd.fits', 'redshift': 7.52, 'objmodel': 'qso'},

To add a new type of test:

1) Edit pypeit_tests.py to add a new subclass to run the new test type as a child process.
2) Add a new test list with at least one instrument/setup that runs the new test.
3) Add the test to the all_tests list. This list defines the order the test types are run for a test setup, the
   PypeItTest subclass that runs the test, and the test phase (prep, reduce, afterburn, quicklook).

Attributes:
    supported_instruments:   A list of the instruments supported by the test suite. This can be a substring of the
                             instrument name.
    develop_setups:          A dict of instruments to the supported test setups for the instrument. Each setup should
                             have data in $PYPEIT_DEV/RAW_DATA/instrument/setup

    all_tests:               A list of the test types supported by the dev suite and which test setups they are run
                             on.  The test types are listed in the order they run in so that tests can depend on the
                             result of previous tests.

                             Each test type is represented by a dict with the following keys:

                             'factory': A callable that builds a PypeItTest subclasss to run the test.
                             This callable will be passed a TestSetup object, the command line arguments to
                             pypeit_test (as returned by argparse.ArgumentParser), and any keyword arguments included
                             in the 'setups' key.

                             'type': A TestPhase enum that is either PREP, REDUCE, AFTERBURN, or QL.

                             'setups': Which setups should run the test along with any arguments needed to run the test.

                             The setup can be specified as '*' to indicate every setup should run the test type.
                             This is currently used so that every test setup will run at least one "run_pypeit"
                             data reduction test.

                             The setup can also be specified as an instrument name to indicate every setup for the
                             instrument should run the test type, or as 'instrument/setup' to indicate only a specific
                             setup should run the test type.

                             The value for 'setups' can be a list of setups, or a dict. If a dict is used, it maps
                             a setup specifier to the keyword arguments that will be passed to the PypeItTest __init__
                             method.  The key word arguments are represented as a dict and passed to the __init__
                             method with the ** operator.

                            The 'setups' values are taken from the following private attributes of this module:

                            _pypeit_setup:      Test setups that run pypeit_setup to generate a .pypeit file.
                            _additional_reduce: Test setups that run additional reduce tests beyond the default test.
                            _sensfunc:          Test setups that run pypeit_sensfunc.
                            _flux_setup:        Test setups that run pypeit_flux_setup.
                            _flux:              Test setups that run pypeit_flux_calib.
                            _coadd1d:           Test setups that run pypeit_coadd_1dspec.
                            _coadd2d:           Test setups that run pypeit_coadd_2dspec. For each test setup the
                            _telluric:          Test setups that run pypeit_tellfit. For each test setup the
                            _quick_look:        Test setups that run pypeit_ql_mos. For each test setup the

"""

from . import pypeit_tests
from enum import Enum, IntEnum, auto

class TestPhase(Enum):
    """Enumeration for specifying the test phase that a test runs in.

    Values:
    PREP
    REDUCE
    AFTERBURN
    QL
    """
    PREP      = auto()
    REDUCE    = auto()
    AFTERBURN = auto()
    QL        = auto()


supported_instruments = ['kast', 'deimos', 'kcwi', 'nires', 'nirspec', 'mosfire', 'lris', 'xshooter', 'gnirs', 'gmos',
                         'flamingos2', 'mage', 'fire', 'luci', 'mdm', 'alfosc', 'fors2', 'binospec', 'mmirs', 'mods',
                         'dbsp', 'tspec', 'bcs']


develop_setups = {'shane_kast_blue': ['452_3306_d57', '600_4310_d55', '830_3460_d46'],
                  'shane_kast_red': ['600_7500_d55_ret', '600_7500_d57', '600_5000_d46', '1200_5000_d57'],
                  'gemini_gnirs': ['32_SB_SXD', '10_LB_SXD'],
                  'gemini_gmos': ['GS_HAM_R400_700', 'GS_HAM_R400_860', 'GN_HAM_R400_885', 'GN_HAM_NS_B600_620'],
                  'gemini_flamingos2': ['HK_HK', 'JH_JH'],
                  'keck_deimos': ['600ZD_M_6500', '600ZD_tilted', '1200G_M_7750', '830G_LVM_8400', '830G_M_8100_26',
                                  '830G_M_8500', '830G_L_8100', '1200B_M_5200', '1200G_M_5500'],
                  'keck_kcwi': ['bh2_4200'],
                  'keck_nires': ['NIRES'],
                  'keck_nirspec': ['LOW_NIRSPEC-1'],
                  'keck_mosfire': ['Y_long', 'J_multi', 'K_long'],
                  'keck_lris_blue': ['multi_600_4000_d560', 'long_400_3400_d560', 'long_600_4000_d560',
                                     'multi_300_5000_d680'],
                  'keck_lris_blue_orig': ['long_600_4000_d500'],
                  'keck_lris_red': ['long_600_7500_d560', 'multi_1200_9000_d680_1x2',
                                    'multi_600_5000_d560', 'multi_1200_9000_d680',
                                    'multi_400_8500_d560',
                                    'long_400_8500_longread'],  # Longslit read-out mode
                  'keck_lris_red_orig': ['long_300_5000'],
                  'lbt_luci': ['LUCI-I', 'LUCI-II'],
                  'lbt_mods': ['MODS1R_Longslit', 'MODS2R_Longslit'],
                  'magellan_mage': ['1x1'],
                  'magellan_fire': ['FIRE_Echelle', 'FIRE_Long'],
                  'mdm_osmos': ['MDM4K'],
                  'mmt_bcs': ['300l'],
                  'mmt_binospec': ['Longslit_G600', 'Multislit_G270'],
                  'mmt_mmirs': ['HK_zJ', 'J_zJ', 'K_K'],
                  'not_alfosc': ['grism4', 'grism19'],
                  'p200_dbsp_blue': ['600_4000_d55'],
                  'p200_dbsp_red': ['316_7500_d55'],
                  'p200_tspec': ['TSPEC'],
                  'vlt_fors2': ['300I'],
                  'vlt_xshooter': ['VIS_1x1', 'VIS_2x1', 'VIS_2x2', 'VIS_manual', 'NIR'],
                  }

_pypeit_setup = ['shane_kast_blue/600_4310_d55']

_additional_reduce = {'keck_lris_red':
                          {'masters': True},
                      'gemini_gmos/GS_HAM_R400_860':
                          {'std': True},
                      }

_sensfunc = {'shane_kast_blue/600_4310_d55':
                 {'std_file': 'spec1d_*Feige66*.fits'},
             'gemini_gnirs/32_SB_SXD':
                 {'std_file': 'spec1d_*S0206-HIP62745*.fits', 'sens_file': 'gemini_gnirs_32_sb_sxd.sens'},
             'gemini_gmos/GS_HAM_R400_860':
                 {'std_file': 'spec1d_**GD71*.fits'},
             }

_flux_setup = ['shane_kast_blue/600_4310_d55',
               'gemini_gnirs/32_SB_SXD',
               'gemini_gmos/GS_HAM_R400_860',
               ]

_flux = ['shane_kast_blue/600_4310_d55',
         'gemini_gnirs/32_SB_SXD',
         'gemini_gmos/GS_HAM_R400_860',
         ]

_coadd1d = ['shane_kast_blue/600_4310_d55',
            'gemini_gnirs/32_SB_SXD',
            'gemini_gmos/GS_HAM_R400_860',
            ]

_coadd2d = {'gemini_gnirs/32_SB_SXD':
                {'obj': 'pisco'},
            'keck_lris_blue/multi_600_4000_d560':
                {'coadd_file': True},
            'vlt_xshooter/VIS_manual':
                {'coadd_file': True}
            }

_telluric = {'gemini_gnirs/32_SB_SXD':
                 {'coadd_file': 'pisco_coadd.fits', 'redshift': 7.52, 'objmodel': 'qso'},
             }

_quick_look = {'shane_kast_blue/600_4310_d55':
                   {'files': ['b1.fits.gz', 'b10.fits.gz', 'b27.fits.gz'], 'mos': True},
               'keck_nires/NIRES':
                   {'files': ['s190519_0067.fits', 's190519_0068.fits']}}

all_tests = [{'factory': pypeit_tests.PypeItSetupTest,
              'type':    TestPhase.PREP,
              'setups':  _pypeit_setup},
             {'factory': pypeit_tests.PypeItReduceTest,
              'type':    TestPhase.REDUCE,
              'setups':  ['*']},
             {'factory': pypeit_tests.PypeItReduceTest,
              'type':    TestPhase.REDUCE,
              'setups':  _additional_reduce},
             {'factory': pypeit_tests.PypeItSensFuncTest,
              'type':    TestPhase.AFTERBURN,
              'setups':  _sensfunc},
             {'factory': pypeit_tests.PypeItFluxSetupTest,
              'type':    TestPhase.AFTERBURN,
              'setups':  _flux_setup},
             {'factory': pypeit_tests.PypeItFluxTest,
              'type':    TestPhase.AFTERBURN,
              'setups':  _flux},
             {'factory': pypeit_tests.PypeItCoadd1DTest,
              'type':    TestPhase.AFTERBURN,
              'setups':  _coadd1d},
             {'factory': pypeit_tests.PypeItCoadd2DTest,
              'type':    TestPhase.AFTERBURN,
              'setups':  _coadd2d},
             {'factory': pypeit_tests.PypeItTelluricTest,
              'type':    TestPhase.AFTERBURN,
              'setups':  _telluric},
             {'factory': pypeit_tests.PypeItQuickLookTest,
              'type':    TestPhase.QL,
              'setups':  _quick_look},
             ]
