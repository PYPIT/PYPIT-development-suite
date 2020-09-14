#!/usr/bin/env python3
#
# See top-level LICENSE.rst file for Copyright information
#
# -*- coding: utf-8 -*-

"""
This script runs the PypeIt development suite of tests
"""

import sys
import os
import os.path
import glob
import subprocess
from queue import PriorityQueue, Empty
from threading import Thread, Lock
from functools import total_ordering
import random
import traceback
import time
import datetime
from enum import Enum, IntEnum, auto
from abc import ABC, abstractmethod
from IPython import embed

import numpy as np

test_run_queue = PriorityQueue()
""":obj:`queue.Queue`: FIFO queue for test setups to be run."""


def develop_setups():
    """
    Return the list of development setups.
    """
    return {'shane_kast_blue': ['452_3306_d57', '600_4310_d55', '830_3460_d46'],
            'shane_kast_red': ['600_7500_d55_ret', '600_7500_d57', '600_5000_d46', '1200_5000_d57'],
            'keck_deimos': ['600ZD_M_6500', '600ZD_tilted', '1200G_M_7750', '830G_LVM_8400', '830G_M_8100_26',
                            '830G_M_8500', '830G_L_8100'],
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
            'vlt_xshooter': ['VIS_1x1', 'VIS_2x1', 'VIS_2x2', 'VIS_manual', 'NIR'],
            'gemini_gnirs': ['32_SB_SXD', '10_LB_SXD'],
            'gemini_gmos': ['GS_HAM_R400_700', 'GS_HAM_R400_860', 'GN_HAM_R400_885'],
            'gemini_flamingos2': ['HK_HK', 'JH_JH'],
            'magellan_mage': ['1x1'],
            'magellan_fire': ['FIRE_Echelle', 'FIRE_Long'],
            'mdm_osmos': ['MDM4K'],
            'not_alfosc': ['grism4', 'grism19'],
            'p200_dbsp_blue': ['600_4000_d55'],
            'p200_dbsp_red': ['316_7500_d55'],
            'p200_tspec':['TSPEC'],
            'vlt_fors2': ['300I'],
            'lbt_luci': ['LUCI-I', 'LUCI-II'],
            'mmt_binospec': ['Longslit_G600','Multislit_G270'],
            'mmt_mmirs': ['HK_zJ','J_zJ','K_K'],
            'lbt_mods': ['MODS1R_Longslit','MODS2R_Longslit']
            }


def supported_instruments():
    return ['kast', 'deimos', 'kcwi', 'nires', 'nirspec', 'mosfire', 'lris', 'xshooter', 'gnirs', 'gmos',
            'flamingos2', 'mage', 'fire', 'luci', 'mdm', 'alfosc', 'fors2', 'binospec', 'mmirs', 'mods',
            'dbsp','tspec']

class TestLength(IntEnum):
    """Enumeration for specifying the relative test duration of different test setups.

    Values:
    SHORT            For test setups that take < 10 minutes to test
    MEDIUM           For test setups that take 10-15 minutes to test
    LONG             For test setups that take 15-30 minutes to test
    VERY_LONG        For test setups that take 30-60 minutes to test
    EXTREMELY_LONG   For test setups that take over 1 hour to test
    DEFAULT          The default value for test setups that haven't been classified.
                     currently set to SHORT

    The numeric values set for this enum are used in a priority queue that considers, lower numbers to
    be higher priority. As such their order is reversed from the order of their durations, and the actual
    value doesn't matter.
    """
    SHORT          = 90
    MEDIUM         = 80
    LONG           = 70
    VERY_LONG      = 60
    EXTREMELY_LONG = 50
    DEFAULT        = 90



class TestSetup(object):
    """Representation of a test setup within the pypeit development suite.
    
    Attributes:
        instr (str):        The instrument for the test setup
        name (str):         The name of the test setup
        rawdir (str):       The directory with the raw data for the test setup
        rdxdir (str):       The output directory for the test setup. This can be changed as tests are run.
        dev_path (str):     The path of the Pypeit-development-suite repository
        pyp_file (str):     The .pypeit file used for the test. This may be created by a PypeItSetupTest.
        std_pyp_file (str): The standards .pypeit file used for some tests.

        length(:obj:`TestLength`):  The expected duration of the test.

        tests (:obj:`list` of :obj:`PypeItTest`): The list of tests to run in this test setup. The tests will be run
                                                  in sequential order

    """
    def __init__(self, instr, name, rawdir, rdxdir, dev_path):
        self.instr = instr
        self.name = name
        self.rawdir = rawdir
        self.rdxdir = rdxdir
        self.dev_path = dev_path

        self.pyp_file = None
        self.std_pyp_file = None
        self.tests = []
        self.length = self.determine_length()

    def __str__(self):
        """Return a string represetnation of this setup of the format "instr/name"""""
        return f"{self.instr}/{self.name}"

    def __lt__(self, other):
        """
        Compare this test setup with another using the "length" attribute. This is included so that a
        TestSetup  object can be placed into a PriorityQueue
        """
        return self.length < other.length

    def determine_length(self):
        """Determine the expected length of the test setup"""

        instr_lengths = {'mmt_binospec': TestLength.VERY_LONG,
                         'keck_kcwi': TestLength.VERY_LONG,
                         'keck_deimos': TestLength.LONG,
                         'vlt_xshooter': TestLength.MEDIUM,
                         'keck_mosfire': TestLength.MEDIUM,
                         'gemini_flamingos2': TestLength.MEDIUM}

        setup_lengths = {'mmt_binospec/Multislit_G270': TestLength.EXTREMELY_LONG,
                         'magellan_fire/FIRE_Echelle': TestLength.VERY_LONG,
                         'keck_lris_blue/multi_300_5000_d680': TestLength.MEDIUM,
                         'mmt_mmirs/J_zJ': TestLength.MEDIUM,
                         'vlt_xshooter/VIS_manual': TestLength.LONG,
                         'gemini_gmos/GS_HAM_R400_860': TestLength.LONG,
                         'gemini_gnirs/32_SB_SXD': TestLength.VERY_LONG,
                         'lbt_mods/MODS1R_Longslit': TestLength.VERY_LONG,
                         'lbt_mods/MODS2R_Longslit': TestLength.LONG}

        setup_key = str(self)

        # Look for a specific setup
        if setup_key in setup_lengths:
            return setup_lengths[setup_key]

        # Otherwise look for an instrument
        elif self.instr in instr_lengths:
            return instr_lengths[self.instr]

        # Otherwise fall back to the default
        return TestLength.DEFAULT


def red_text(text):
    """Utiltiy method to wrap text in the escape sequences to make it appear red in a terminal"""
    return f'\x1B[1;31m{text}\x1B[0m'

def green_text(text):
    """Utiltiy method to wrap text in the escape sequences to make it appear green in a terminal"""
    return f'\x1B[1;32m{text}\x1B[0m'


class TestReport(object):
    """Class for reporting on the status and results of testing.

    The test_started, test_skipped, and test_completed methods of this class are called during testing to keep track of
    status and provide incremental status updates to the console as tests are running.

    detailed_report and summary report are called after testing to report on the results.

    Attributes:

    pargs (:obj:`Namespace`:) The parsed command line arguments to pypeit_test
    setups (:obj:`list` of :obj:`TestSetup`):  The test setups that are being tested.

    start_time (:obj:`datetime.datetime`): The date and time testing started.
    end_time (:obj:`datetime.datetime`):   The date and time testing finished.

    num_tests (int):   The total number of tests in all of the test setups.
    num_passed (int):  The number of tests that have passed.
    num_failed (int):  The number of tests that have failed.
    num_skipped (int): The number of tests that were skipped because they depended on the results of a failed tests.
    num_active (int):  The number of tests that are currently in progress.

    failed_tests (:obj:`list` of str):  List of names of tests that have failed
    skipped_tests (:obj:`list` of str): List of names of tests that have been skipped

    testing_complete (bool): Whether testing has completed.
    lock (:obj:`threading.Lock`): Lock used to synchronize access when multiple threads are reporting status. This
                                  prevents scrambled output being sent to stdout.
    """
    def __init__(self, pargs, setups):
        self.pargs = pargs
        self.test_setups = setups
        self.start_time = None
        self.end_time = None

        self.num_tests = 0
        self.num_passed = 0
        self.num_failed = 0
        self.num_skipped = 0
        self.num_active = 0
        self.failed_tests = []
        self.skipped_tests = []
        self.lock = Lock()
        self.testing_complete = False


    def _get_test_counts(self):
        """Helper method to create a string with the curren test counts"""
        verbose_info = f'{self.num_active:2} active/' if self.pargs.verbose else ''
        return f'{verbose_info}{self.num_passed:2} passed/{self.num_failed:2} failed/{self.num_skipped:2} skipped'

    def test_started(self, test):
        """Called when a test has started executing"""
        with self.lock:
            self.num_tests += 1
            self.num_active += 1


            if not self.pargs.quiet:
                verbose_info = ''
                if self.pargs.verbose:
                    verbose_info = f' at {datetime.datetime.now().ctime()}'

                print(f'{self._get_test_counts()} STARTED {test}{verbose_info}')

    def test_skipped(self, test):
        """Called when a test has been skipped because a test before it has failed"""
        with self.lock:
            self.num_skipped += 1
            self.skipped_tests.append(test)

            if not self.pargs.quiet:
                print(f'{self._get_test_counts()} {red_text("SKIPPED")} {test}')

    def test_completed(self, test):
        """Called when a test has finished executing."""
        with self.lock:
            self.num_active -= 1
            if test.passed:
                self.num_passed += 1
            else:
                self.num_failed += 1
                self.failed_tests.append(test)

            if not self.pargs.quiet:
                verbose_info = ''
                if self.pargs.verbose:
                    if test.end_time is not None and test.start_time is not None:
                        duration = test.end_time-test.start_time
                    else:
                        duration = 'n/a'

                    verbose_info = f' with pid {test.pid} at {datetime.datetime.now().ctime()} Duration {duration}'

                if test.passed:
                    print(f'{self._get_test_counts()} {green_text("PASSED")}  {test}{verbose_info}')
                else:
                    print(f'{self._get_test_counts()} {red_text("FAILED")}  {test}{verbose_info}')
                    self.report_on_test(test)

    def detailed_report(self, output=sys.stdout):
        """Display a detailed report on testing to the given output stream"""

        # Report header information
        print('Reducing data for the following setups:', file=output)
        for setup in self.test_setups:
            print(f'    {setup}', file=output)
        print('', file=output)

        if self.pargs.threads > 1:
            print(f'Ran tests in {self.pargs.threads} parallel processes\n', file=output)

        for setup in self.test_setups:
            self.report_on_setup(setup, output)
        print ("-------------------------", file=output)
        self.summary_report(output)

    def summary_report(self, output=sys.stdout):
        """Display a summary report on the results of testing to the given output stream"""

        masters_text = 'reused' if self.pargs.masters else 'ignored'
        if self.num_tests == self.num_passed:
            print("\n" + "\x1B[" + "1;32m" +
                  "--- PYPEIT DEVELOPMENT SUITE PASSED {0}/{1} TESTS (Masters {2}) ---".format(
                      self.num_passed, self.num_tests, masters_text)
                  + "\x1B[" + "0m" + "\r", file=output)
        else:
            print("\n" + "\x1B[" + "1;31m" +
                  "--- PYPEIT DEVELOPMENT SUITE FAILED {0}/{1} TESTS (Masters {2}) ---".format(
                      self.num_failed, self.num_tests, masters_text)
                  + "\x1B[" + "0m" + "\r", file=output)
            print('Failed tests:', file=output)
            for t in self.failed_tests:
                print('    {0}'.format(t), file=output)
            print('Skipped tests:', file=output)
            for t in self.skipped_tests:
                print('    {0}'.format(t), file=output)

        print(f"Testing Started at {self.start_time.isoformat()}", file=output)
        print(f"Testing Completed at {self.end_time.isoformat()}", file=output)
        print(f"Total Time: {self.end_time - self.start_time}", file=output)


    def report_on_test(self, test, output=sys.stdout):
        """Print a detailed report on the status of a test to the given output stream."""

        if test.passed:
            result = green_text('--- PASSED')
        elif test.passed is None:
            result = red_text('--- SKIPPED')
        else:
            result = red_text('--- FAILED')

        if test.start_time is not None and test.end_time is not None:
            duration = test.end_time - test.start_time
        else:
            duration = None

        print("----", file=output)
        print(f"{test.setup} {test.description} Result: {result}\n", file=output)
        print(f'Logfile:    {test.logfile}', file=output)
        print(f'Process Id: {test.pid}', file=output)
        print(f'Start time: {test.start_time.ctime() if test.start_time is not None else "n/a"}', file=output)
        print(f'End time:   {test.end_time.ctime() if test.end_time is not None else "n/a"}', file=output)
        print(f'Duration:   {duration}', file=output)
        print(f"Command:    {' '.join(test.command_line) if test.command_line is not None else ''}", file=output)
        print('', file=output)
        print('Error Messages:', file=output)

        for msg in test.error_msgs:
            print(msg, file=output)

        print('', file=output)
        print("End of Log:", file=output)
        if test.logfile is not None and os.path.exists(test.logfile):
            result = subprocess.run(['tail', '-3', test.logfile], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            print(result.stdout.decode(), file=output)

        print('\n', file=output)

    def report_on_setup(self, setup, output=sys.stdout):
        """Print a detailed report on the status of a test setup and the tests within it to the given output stream."""

        print ("-------------------------", file=output)
        print (f"Test Setup: {setup}\n", file=output)
        print ("-------------------------", file=output)
        print("Directories:", file=output)
        print(f"         Raw data: {setup.rawdir}", file=output)
        print(f"    PypeIt output: {setup.rdxdir}", file=output)
        print("Files:", file=output)
        print(f"     .pypeit file: {setup.pyp_file}", file=output)
        print(f" Std .pypeit file: {setup.std_pyp_file}", file=output)

        print("Tests:", file=output)

        for t in setup.tests:
            self.report_on_test(t, output)


def get_unique_file(file):
    """Ensures a file name is unique on the file system, modifying it if neccessary.

    Args:
        file (str): The full pathname of the file.

    Return:
        A unique version of the passed in file name. If the file doesn't already exist it is returned
        unchanged, otherwise a number is added to name (before the file extension) to make it unique.
    """
    file_num = 2
    (file_base, file_ext) = os.path.splitext(file)
    while os.path.exists(file):
        file = f'{file_base}.{file_num}.{file_ext}'
        file_num += 1

    return file


class PypeItTest(ABC):
    """Abstract base class for classes that run pypeit tests and hold the results from those tests."""


    def __init__(self, setup, description, log_suffix):
        """
        Constructor

        Args:
            setup (:obj:`TestSetup`) Test setup containing the test.
            description (str): A description of the type of test performed.
            log_suffix (str): The suffix to use for the log file name for the type of test.
        """

        self.setup = setup
        self.description = description
        self.log_suffix = log_suffix

        self.passed = None
        """ bool: True if the test passed, False if the test failed, None if the test is in progress"""

        self.command_line = None
        """ :obj:`list` of :obj:`str`: The command and arguments that were run for the test."""

        self.error_msgs = []
        """ :obj:`list` of :obj:`str`: List of any error messages generated by the test."""

        self.logfile = None
        """ str: The log file for the test """

        self.pid = None
        """ int: The process id of the child process than ran the test"""

        self.start_time = None
        """ :obj:`datetime.datetime`: The date and time the test started."""

        self.end_time = None
        """ :obj:`datetime.datetime`: The date and time the test finished."""


    def __str__(self):
        """Return a summary of the test and the status.

           Example: 'shane_kast_red/600_7500_d57 pypeit (without masters)'
        """
        return f"{self.setup} {self.description}"

    def get_logfile(self):
        """Return a unique logifle name for the test"""
        # Get a unique log file to prevent a test from overwriting the log from a previous test
        name = '{0}_{1}.{2}.log'.format(self.setup.instr.lower(), self.setup.name.lower(), self.log_suffix)
        return get_unique_file(os.path.join(self.setup.rdxdir, name))



    @abstractmethod
    def build_command_line(self):
        pass

    def run(self):
        """Run a test in a child process."""

        try:
            # Open a log for the test
            child = None
            self.logfile = self.get_logfile()
            with open(self.logfile, "w") as f:
                try:
                    self.command_line = self.build_command_line()
                    self.start_time = datetime.datetime.now()
                    child = subprocess.Popen(self.command_line, stdout=f, stderr=f, cwd=self.setup.rdxdir)
                    self.pid = child.pid
                    child.wait()
                    self.end_time = datetime.datetime.now()
                    self.passed = (child.returncode == 0)
                finally:
                    # Kill the child if the parent script exits due to a SIGTERM or SIGINT (Ctrl+C)
                    if child is not None:
                        child.terminate()

        except Exception:
            # An exception occurred while running the test
            # Make sure it's marked as failed and document that an exception ocurred
            self.error_msgs.append(f"Exception in Test {self}:")
            self.error_msgs.append(traceback.format_exc())
            self.passed = False

        return self.passed


class PypeItSetupTest(PypeItTest):
    """Test subclass that runs pypeit_setup"""
    def __init__(self, setup):
        super().__init__(setup, "pypeit_setup", "setup")

    def run(self):

        if super().run():
            # Check for the pypeit file after running the test
            rdxdir = os.path.join(self.setup.rdxdir, self.setup.instr.lower() + '_A')
            pyp_file_glob = os.path.join(rdxdir, '*_A.pypeit')
            pyp_file = glob.glob(pyp_file_glob)
            if len(pyp_file) != 1:
                self.error_msgs.append(f"Could not find expected pypeit file {pyp_file_glob}")
                self.passed = False
            else:
                # If the pypeit file was created, put it's location and the new output
                # directory into the setup object for subsequent tests to use
                pyp_file = os.path.split(pyp_file[0])[1]

                self.setup.pyp_file = pyp_file
                self.setup.rdxdir = rdxdir

        return self.passed

    def build_command_line(self):
        return ['pypeit_setup', '-r', self.setup.rawdir, '-s',
                self.setup.instr, '-c all', '-o', '--output_path', self.setup.rdxdir]


class PypeItReduceTest(PypeItTest):
    """Test subclass that runs run_pypeit"""

    def __init__(self, setup, masters, std=False):
        description = f"pypeit {'standards ' if std else ''}(with{'out' if not masters else ''} masters)"
        super().__init__(setup, description, "test")

        self.masters = masters
        self.std = std


    def build_command_line(self):
        if self.std:
            pyp_file = self.setup.std_pyp_file
        else:
            pyp_file = self.setup.pyp_file

        command_line = ['run_pypeit', pyp_file, '-o']
        if self.masters:
            command_line += ['-m']

        return command_line


class PypeItSensFuncTest(PypeItTest):
    """Test subclass that runs pypeit_sensfunc"""
    def __init__(self, setup, std_file, sens_file=None):
        super().__init__(setup, "pypeit_sensfunc", "test_sens")
        self.std_file = std_file
        self.sens_file = sens_file

    def run(self):

        self.std_file = os.path.join(self.setup.rdxdir, "Science", self.std_file)

        if not os.path.isfile(self.std_file):
            self.error_msgs.append(f"File does not exist!: {self.std_file}")
            self.passed = False
        else:
            return super().run()

    def build_command_line(self):
        command_line = ['pypeit_sensfunc', self.std_file]

        if self.sens_file is not None:
            command_line += ['-s', self.sens_file]

        return command_line

class PypeItFluxSetupTest(PypeItTest):
    """Test subclass that runs pypeit_flux_setup"""
    def __init__(self, setup):
        super().__init__(setup, "pypeit_flux_setup", "test_flux_setup")

    def build_command_line(self):
        return ['pypeit_flux_setup', os.path.join(self.setup.rdxdir, 'Science')]


class PypeItFluxTest(PypeItTest):
    """Test subclass that runs pypeit_flux_calib"""
    def __init__(self, setup):
        super().__init__(setup, "pypeit_flux", "test_flux")

    def build_command_line(self):
        flux_file = os.path.join(self.setup.dev_path, 'fluxing_files',
                                 '{0}_{1}.flux'.format(self.setup.instr.lower(), self.setup.name.lower()))
        return ['pypeit_flux_calib', flux_file]


class PypeItCoadd1DTest(PypeItTest):
    """Test subclass that runs pypeit_coadd_1dspec"""

    def __init__(self, setup):
        super().__init__(setup, "pypeit_coadd_1dspec", "test_1dcoadd")

    def build_command_line(self):
        coadd_file = os.path.join(self.setup.dev_path, 'coadd1d_files',
                                  '{0}_{1}.coadd1d'.format(self.setup.instr.lower(), self.setup.name.lower()))
        return ['pypeit_coadd_1dspec', coadd_file]

class PypeItCoadd2DTest(PypeItTest):
    """Test subclass that runs pypeit_coadd_2dspec"""
    def __init__(self, setup, coadd_file=None, obj=None):
        super().__init__(setup, "pypeit_coadd_2dspec", "test_2dcoadd")
        self.obj = obj
        self.coadd_file = coadd_file

        if self.coadd_file is None and self.obj is None:
            raise ValueError('Must provide coadd2d file or object name.')

    def build_command_line(self):
        command_line = ['pypeit_coadd_2dspec']
        command_line += ['--obj', self.obj] if self.coadd_file is None else ['--file', self.coadd_file]
        return command_line

class PypeItTelluricTest(PypeItTest):
    """Test subclass that runs pypeit_tellfit"""

    def __init__(self, setup, coadd_file, redshift, objmodel):
        super().__init__(setup, "pypeit_tellfit", 'test_tellfit')
        self.coadd_file = coadd_file
        self.redshift = redshift
        self.objmodel = objmodel


    def build_command_line(self):
        command_line = ['pypeit_tellfit', os.path.join(self.setup.rdxdir, self.coadd_file)]
        command_line += ['--redshift', '{:}'.format(self.redshift)]
        command_line += ['--objmodel', self.objmodel]

        return command_line

class PypeItQuickLookTest(PypeItTest):
    """Test subclass that runs pypeit_ql_mos"""

    def __init__(self, setup, files, mos=False):
        super().__init__(setup, "pypeit_ql_mos", "test_ql")
        self.files = files
        self.mos = mos

    def build_command_line(self):
        command_line = ['pypeit_ql_mos', self.setup.instr] if self.mos else ['pypeit_ql_keck_nires']
        command_line += [self.setup.rawdir] + self.files

        return command_line

def raw_data_dir():
    return os.path.join(os.environ['PYPEIT_DEV'], 'RAW_DATA')


def available_data():
    walk = os.walk(raw_data_dir())
    return next(walk)[1]



def pypeit_file_name(instr, setup, std=False):
    base = '{0}_{1}'.format(instr.lower(), setup.lower())
    return '{0}_std.pypeit'.format(base) if std else '{0}.pypeit'.format(base)


def template_pypeit_file(dev_path, instr, setup, std=False):
    return os.path.join(dev_path, 'pypeit_files', pypeit_file_name(instr, setup, std=std))


def coadd2d_file_name(instr, setup):
    return '{0}_{1}.coadd2d'.format(instr.lower(), setup.lower())


def template_coadd2d_file(dev_path, instr, setup):
    return os.path.join(dev_path, 'coadd2d_files', coadd2d_file_name(instr, setup))


def fix_pypeit_file_directory(dev_path, raw_data, instr, setup, rdxdir, std=False):
    """
    Use template pypeit file to write the pypeit file relevant to the
    exising directory structure.

    Returns:
        str: The path to the corrected pypeit file.
    """
    # Read the pypeit file
    pyp_file = template_pypeit_file(dev_path, instr, setup, std=std)
    if not os.path.isfile(pyp_file):
        if std:
            return None
        raise FileNotFoundError('File does not exist: {0}'.format(pyp_file))
    with open(pyp_file, 'r') as infile:
        lines = infile.readlines()

    # Replace the default path with the local one
    for kk, iline in enumerate(lines):
        if 'data read' in iline:
            old_path = lines[kk+1].strip().split(' ')[1] if 'path' in lines[kk+1] \
                            else lines[kk+1].strip()
            subdir = ''
            newdpth = ' path ' if 'path' in lines[kk+1] else ' '
            newdpth += os.path.join(raw_data, instr, setup, subdir)
            newdpth += '\n'
            lines[kk+1] = newdpth
        elif 'flatfield' in iline and 'pixelflat_file' in lines[kk+1]:
            newcpth = os.path.join(dev_path, 'CALIBS', os.path.split(lines[kk+1])[1])
            lines[kk+1] = '        pixelflat_file = {0}'.format(newcpth)

    # Write the pypeit file
    pyp_file = os.path.join(rdxdir, pypeit_file_name(instr, setup, std=std))
    with open(pyp_file, 'w') as ofile:
        ofile.writelines(lines)
    return pyp_file



def parser(options=None):
    import argparse

    dirs = available_data()
    all_tests = np.unique([ [d.split('_')[0], d.split('_')[1]] for d in dirs ])

    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter,
                                     description='Run pypeit tests on a set of instruments.  '
                                                 'Typical call for testing pypeit when developing '
                                                 'new code is `./pypeit_test develop`.  Execution '
                                                 'requires you to have a PYPEIT_DEV environmental '
                                                 'variable, pointing to the top-level directory '
                                                 'of the dev-suite repository (typically the '
                                                 'location of this script).  Raw data for testing '
                                                 'is expected to be at ${PYPEIT_DEV}/RAW_DATA.  '
                                                 'To run all tests for the supported instruments, '
                                                 'use \'develop\'.  To only run the basic '
                                                 'reductions, use \'reduce\'.  To only run the '
                                                 'tests that use the results of the reductions, '
                                                 'use \'afterburn\'.  To run all possible tests '
                                                 '(beware!), use \'all\'.')

    parser.add_argument('tests', type=str, default=None,
                        help='Instrument or test to run.  For instrument-specific tests, you '
                             'can provide the telescope or the spectrograph, but beware of '
                             'non-unique matches.  E.g. \'mage\' selects all the magellan '
                             'instruments, not just \'magellan_mage\'.  Options include: '
                             'develop, reduce, afterburn, all, ql, {0}'.format(', '.join(all_tests)))
    parser.add_argument('-o', '--outputdir', type=str, default='REDUX_OUT',
                        help='Output folder.')
    # TODO: Why is this an option?
    parser.add_argument('-i', '--instrument', type=str, help="Restrict to input instrument")
    parser.add_argument('-s', '--setup', type=str, help="Single out a setup to run")
    parser.add_argument('--debug', default=False, action='store_true',
                        help='Debug using only blue setups')
    parser.add_argument('-p', '--prep_only', default=False, action='store_true',
                        help='Only prepare to execute run_pypeit, but do not actually run it.')
    parser.add_argument('-m', '--masters', default=False, action='store_true',
                        help='run pypeit using any existing masters')
    parser.add_argument('-t', '--threads', default=1, type=int,
                        help='Run THREADS number of parallel tests.')
    parser.add_argument('-q', '--quiet', default=False, action='store_true',
                        help='Supress all output to stdout. If -r is not a given, a report file will be '
                             'written to <outputdir>/pypeit_test_results.txt')
    parser.add_argument('-v', '--verbose', default=False, action='store_true',
                        help='Output additional detailed information while running the tests and output a '
                             'detailed report at the end of testing. This has no effect if -q is given')
    parser.add_argument('-r', '--report', default=None, type=str,
                        help='Write a detailed test report to REPORT.')

    return parser.parse_args() if options is None else parser.parse_args(options)

def thread_target(test_report):
    """Thread target method for running tests."""
    while not test_report.testing_complete:
        try:
            test_setup = test_run_queue.get(timeout=2)
        except Empty:
            # queue is currently empty but another thread may put another test on it, so try again
            continue

        passed = True
        for test in test_setup.tests:

            if not passed:
                test_report.test_skipped(test)
            else:
                test_report.test_started(test)
                passed = test.run()
                test_report.test_completed(test)

        # Count the test setup as done. This needs to be done to allow the join() call in main to return when
        # all of the tests have been completed
        test_run_queue.task_done()


def main():

    pargs = parser()

    if pargs.threads <=0:
        raise ValueError("Number of threads must be >= 1")
    elif pargs.threads > 1:
        # Set the OMP_NUM_THREADS to 1 to prevent numpy multithreading from competing for resources
        # with the multiple processes started by this script
        os.environ['OMP_NUM_THREADS'] = '1'

    # TODO: Once we're satisfied that an instrument passes, add it to
    # this list and add a series of setups to the development set!  Runs
    # of PypeIt must pass for all setups in the development list.  See
    # `develop_setups`.

    dev_path = os.getenv('PYPEIT_DEV')
    raw_data = raw_data_dir()
    if not os.path.isdir(raw_data):
        raise NotADirectoryError('No directory: {0}'.format(raw_data))

    all_instruments = available_data()
    flg_after = False
    flg_ql = False

    # Development instruments (in returned dictonary keys) and setups
    devsetups = develop_setups()
    tests_that_only_use_dev_setups = ['develop', 'reduce', 'afterburn', 'ql']

    # Setup
    unsupported = []
    if pargs.tests == 'all':
        instruments = np.array([item for item in all_instruments
                                        for inst in supported_instruments()
                                            if inst.lower() in item.lower()])
    elif pargs.tests in tests_that_only_use_dev_setups:
        instruments = np.array(list(devsetups.keys())) if pargs.instrument is None \
                        else np.array([pargs.instrument])
        if pargs.tests == 'afterburn':
            # Only do the flux-calibration and coadding tests
            flg_after = True
        elif pargs.tests == 'ql':
            flg_ql = True
    else:
        instruments = np.array([item for item in all_instruments 
                                    if pargs.tests.lower() in item.lower()])
        unsupported = [item for item in instruments 
                            if not np.any([inst.lower() in item.lower()
                                for inst in supported_instruments()]) ]

    # Check that instruments is not blank
    if len(instruments) == 0:
        print("\x1B[" + "1;31m" + "\nERROR - " + "\x1B[" + "0m" +
              "Invalid test selected: {0:s}\n\n".format(pargs.tests) +
              "Consult the help (pypeit_test -h) or select one of the " +
              "available RAW_DATA directories: {0}".format(', '.join(all_instruments)))
        return 1

    if len(unsupported) > 0:
        if not pargs.quiet:
            print("\x1B[" + "1;33m" + "\nWARNING - " + "\x1B[" + "0m" +
                  "The following tests have not been validated and may not pass: {0}\n\n".format(
                  unsupported))

    if not os.path.exists(pargs.outputdir):
        os.mkdir(pargs.outputdir)
    outputdir = os.path.abspath(pargs.outputdir)

    # Make sure we can create a writable report file (if needed) before starting the tests
    if pargs.report is None and pargs.quiet:
        # If there's no report file specified in the command line, but we're in quiet mode,
        # make up a report file name
        pargs.report = get_unique_file(os.path.join(outputdir, "pypeit_test_results.txt"))

    if pargs.report:
        try:
            report_file = open(pargs.report, "w")
        except Exception as e:
            print(f"Could not open report file {report_file}", file=stderr)
            traceback.print_exc()
            sys.exit(1)


    # Report
    if not pargs.quiet:
        print('Running tests on the following instruments:')
        for instr in instruments:
            print('    {0}'.format(instr))
        print('')

    #---------------------------------------------------------------------------
    # Check all the data and relevant files exists before starting!
    # TODO: Do this for "all", as well?
    if pargs.tests in tests_that_only_use_dev_setups:
        unsupported = []
        missing_data = []
        missing_pypfiles = []
        for instr in instruments:
            # Only do blue instruments
            if pargs.debug and 'blue' not in instr:
                continue
            if instr not in devsetups.keys():
                # TODO: We should never get here, right?
                unsupported += [ instr ]

            # Setups
            setups = next(os.walk(os.path.join(raw_data, instr)))[1]

            # Check all data before starting
            for setup in devsetups[instr]:
                if setup not in setups:
                    missing_data += [ '{0}/{1}'.format(instr, setup) ]

                if instr == 'shane_kast_blue' and '600' in setup:
                    # pypeit file is created by pypeit_setup
                    continue

                pyp_file = template_pypeit_file(dev_path, instr, setup)
                if not os.path.isfile(pyp_file):
                    missing_pypfiles += [pyp_file]

        if len(unsupported) > 0:
            raise ValueError('Unsupported instruments: {0}'.format(', '.join(unsupported)))
        if len(missing_data) > 0:
            raise ValueError('Missing the following test data: {0}'.format(
                                ', '.join(missing_data)))
        if len(missing_pypfiles) > 0:
            raise ValueError('Missing the following template pypeit files:\n    {0}'.format(
                                '\n    '.join(missing_pypfiles)))
    #---------------------------------------------------------------------------

    #---------------------------------------------------------------------------

    setups = []
    for instr in instruments:
        # Only do blue instruments
        if pargs.debug and 'blue' not in instr:
            continue

        # Setups
        setup_names = next(os.walk(os.path.join(raw_data, instr)))[1]
        if pargs.setup is not None and pargs.setup not in setup_names:
            # No setups selected
            continue
        # Limit to a single setup
        if pargs.setup is not None:
            setup_names = [ pargs.setup ]
        # Limit to development setups
        if pargs.tests in tests_that_only_use_dev_setups:
            setup_names = devsetups[instr]

        # Add tests to the test_run_queue
        for setup_name in setup_names:

            setup = build_test_setup(pargs, instr, setup_name, flg_after, flg_ql)
            setups.append(setup)
            test_run_queue.put(setup)

        # Report
        if not pargs.quiet:
            print('Reducing data from {0} for the following setups:'.format(instr))
            for name in setup_names:
                print('    {0}'.format(name))
            print('')


    if not pargs.quiet and pargs.threads > 1:
        print(f'Running tests in {pargs.threads} parallel processes')


    test_report = TestReport(pargs, setups)
    test_report.start_time = datetime.datetime.now()

    # Start threads to run the tests
    thread_pool = []
    for i in range(pargs.threads):
        new_thread = Thread(target=thread_target, args=[test_report])
        thread_pool.append(new_thread)
        new_thread.start()

    # Wait for the tests to finish
    test_run_queue.join()

    # Set the test status to complete and then wait for the threads to finish.
    # We don't run the threads as daemon threads so that main() can be called multiple times
    # in unit tests
    test_report.testing_complete = True
    for thread in thread_pool:
        thread.join()

    # Report on the test results
    test_report.end_time = datetime.datetime.now()

    if pargs.report is not None:
        test_report.detailed_report(report_file)

    if not pargs.quiet:
        if pargs.verbose:
            test_report.detailed_report()
        else:
            test_report.summary_report()

    return test_report.num_failed


def build_test_setup(pargs, instr, setup_name, flg_after, flg_ql):
    """Builds a TestSetup object including the tests that it will run"""

    dev_path = os.getenv('PYPEIT_DEV')
    raw_data = raw_data_dir()
    outputdir = os.path.abspath(pargs.outputdir)

    # Directory with raw data
    rawdir = os.path.join(raw_data, instr, setup_name)

    # Directory for reduced data
    rdxdir = os.path.join(outputdir, instr, setup_name)
    if not os.path.exists(rdxdir):
        # Make the directory
        os.makedirs(rdxdir)

    setup = TestSetup(instr, setup_name, rawdir, rdxdir, dev_path)

    # TODO: By default search for the appropriate pypeit file
    # and run pypeit_setup if it doesn't exist

    # TODO: Include option that forces the tests to run
    # pypeit_setup
    if setup.instr == 'shane_kast_blue' and '600' in setup.name:
        # Use pypeit_setup to generate the pypeit file
        setup.tests.append(PypeItSetupTest(setup))

    else:
        # Use pre-made PypeIt file
        setup.pyp_file = fix_pypeit_file_directory(setup.dev_path,
                                                   raw_data_dir(),
                                                   setup.instr,
                                                   setup.name,
                                                   setup.rdxdir)

        # Also try to find and fix pypeit files for
        # spectroscopic standards.  This is a KLUDGE for
        # gemini_gmos
        setup.std_pyp_file = fix_pypeit_file_directory(setup.dev_path,
                                                       raw_data_dir(),
                                                       setup.instr,
                                                       setup.name,
                                                       setup.rdxdir,
                                                       std=True)

    # Only want to prep
    if pargs.prep_only:
        return setup

    # ----------------------------------------------------------
    # Reduce tests
    # ----------------------------------------------------------
    # Run pypeit
    if not (flg_after or flg_ql):

        setup.tests.append(PypeItReduceTest(setup, pargs.masters))

        # Run pypeit on any standards, if they exist
        if setup.std_pyp_file:
            setup.tests.append(PypeItReduceTest(setup, pargs.masters, std=True))

        # Try re-running keck_lris_red setups with masters
        if setup.instr == 'keck_lris_red':
            setup.tests.append(PypeItReduceTest(setup, True))

    if pargs.tests == 'reduce':
        # Skip the afterburner tests
        return setup
    # ----------------------------------------------------------

    if not flg_ql:
        # ----------------------------------------------------------
        # SensFunc tests
        # ----------------------------------------------------------
        # UVIS algorithm without .sens file
        if setup.instr == 'shane_kast_blue' and '600' in setup.name:
            # TODO: Instead check for file with standard star in the
            # file name?
            std_file = 'spec1d_b24-Feige66_KASTb_2015May20T041246.960.fits'
            setup.tests.append(PypeItSensFuncTest(setup, std_file=std_file))

        # IR algorithm with .sens file
        if setup.instr == 'gemini_gnirs' and setup.name == '32_SB_SXD':
            std_file = 'spec1d_cN20170331S0206-HIP62745_GNIRS_2017Mar31T083351.681.fits'
            sens_file = os.path.join(setup.dev_path, 'sensfunc_files', 'gemini_gnirs_32_sb_sxd.sens')
            setup.tests.append(PypeItSensFuncTest(setup, std_file=std_file, sens_file=sens_file))

        # IR algorithm, multi-slit, without .sens file
        if setup.instr == 'gemini_gmos' and setup.name == 'GS_HAM_R400_860':
            std_file = 'spec1d_S20181219S0316-GD71_GMOS-S_1864May27T230832.356.fits'
            setup.tests.append(PypeItSensFuncTest(setup, std_file=std_file))

        # ----------------------------------------------------------

        # ----------------------------------------------------------
        # fluxing/coadd1d/tellfit tests
        # ----------------------------------------------------------
        flux_coadd1d_pairs = {'shane_kast_blue': '600_4310_d55',  # long-slit
                              'gemini_gnirs': '32_SB_SXD',  # echelle
                              'gemini_gmos': 'GS_HAM_R400_860'}  # multi-slit

        if any([setup.instr == key and setup.name == flux_coadd1d_pairs[key]
                for key in flux_coadd1d_pairs.keys()]):
            setup.tests.append(PypeItFluxSetupTest(setup))
            setup.tests.append(PypeItFluxTest(setup))
            setup.tests.append(PypeItCoadd1DTest(setup))

        # ----------------------------------------------------------

        # ----------------------------------------------------------
        # 2D coadding tests
        # ----------------------------------------------------------
        # Echelle
        if setup.instr == 'gemini_gnirs' and setup.name == '32_SB_SXD':
            setup.tests.append(PypeItCoadd2DTest(setup, obj='pisco'))

        # MultiSlit
        if setup.instr == 'keck_lris_blue' and setup.name == 'multi_600_4000_d560':
            coadd_file = template_coadd2d_file(setup.dev_path, setup.instr, setup.name)
            setup.tests.append(PypeItCoadd2DTest(setup, coadd_file=coadd_file))

        # Manual + Echelle
        if setup.instr == 'vlt_xshooter' and setup.name == 'VIS_manual':
            coadd_file = template_coadd2d_file(setup.dev_path, setup.instr, setup.name)
            setup.tests.append(PypeItCoadd2DTest(setup, coadd_file=coadd_file))

        # ----------------------------------------------------------

        # ----------------------------------------------------------
        # Telluric tests
        # ----------------------------------------------------------
        # Echelle
        if setup.instr == 'gemini_gnirs' and setup.name == '32_SB_SXD':
            setup.tests.append(PypeItTelluricTest(setup, coadd_file='pisco_coadd.fits',
                                                  redshift=7.52, objmodel='qso'))

        # MultiSlit
        # ToDo: Add a multislit test.
        # ----------------------------------------------------------

    # ----------------------------------------------------------
    # Quick-look tests
    # ----------------------------------------------------------

    ql_tests = []

    # MOS
    if setup.instr == 'shane_kast_blue' and '600' in setup.name:
        setup.tests.append(PypeItQuickLookTest(setup,
                                            files=['b1.fits.gz', 'b10.fits.gz', 'b27.fits.gz'],
                                            mos=True))


    # NIRES
    if setup.instr.lower() == 'keck_nires' and setup.name == 'NIRES':
        setup.tests.append(PypeItQuickLookTest(setup, files=['s190519_0067.fits', 's190519_0068.fits']))

    # ----------------------------------------------------------


    return setup


