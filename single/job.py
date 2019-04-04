from matplotlib import pyplot as pl

from kneefinder import *

import pymatgen as mg
import pandas as pd
import scipy as sc
import numpy as np

import traj
import test
import dep

import os


def volume_sphere(r):
    '''
    Calculate of a sphere given a radius.
    '''

    return 4./3.*sc.pi*r**3.


class job:
    '''
    Setup all the data per job for analysis.
    '''

    def __init__(self, path):
        '''
        Load all data needed from a job for analysis.
        '''

        # The location of the job
        self.path = path

        # Save path for plots
        self.plotpath = os.path.join(self.path, 'analysis_plots')

        # The name of saving directories
        self.datadirname = 'analysis_data'
        self.plotdirname = 'analysis_plots'

        self.calculations = []  # The calculations done

        print('Analysis for: '+path)

    def input_file(self, depdotin):
        '''
        Gather parameters from the input file.

        inputs:
            self = The object reference
            depdotin = The name of the input file
        '''

        file_dep = os.path.join(self.path, depdotin)  # Input file

        # Important paramters from the input file
        depparams = dep.info(file_dep)

        self.timestep = depparams['timestep']
        self.hold1 = depparams['hold1']
        self.hold2 = depparams['hold2']
        self.hold3 = depparams['hold3']
        self.increment = depparams['increment']
        self.iterations = depparams['iterations']
        self.deltatemp = depparams['deltatemp']
        self.elements = depparams['elements']

    def sys(self, testdotout):
        '''
        Gather thermodynamic data from the out file.

        inputs:
            self = The object reference
            testdotout = The name of the out file
        '''

        file_system = os.path.join(self.path, testdotout)  # Output file

        # Thermodynamic data from test.out file
        self.dfsys = test.info(file_system)

        self.dfsys['time'] = self.dfsys['Step']*self.timestep

        self.calculations.append('system')

    def box(self, trajdotlammpstrj):
        '''
        Gather trajectories from the trajectory file.

        inputs:
            self = The object reference
            trajdotlammpstrj = The name of the input file
        '''

        file_trajs = os.path.join(self.path, trajdotlammpstrj)  # Trajectories

        # Information from traj.lammpstrj file
        self.dftraj, counts = traj.info(file_trajs)

        self.dftraj['time'] = self.dftraj['Step']*self.timestep

        # Element counts from actual element
        self.natoms = 0  # Count the total number of atoms
        elements = {}
        for key, count in counts.items():
            self.natoms += count

            element = mg.Element(self.elements[key])
            atomicradii = element.atomic_radius  # in Am
            atomicvol = volume_sphere(atomicradii)  # in Am^3

            elements[self.elements[key]] = {
                                            'counts': count,
                                            'radius': atomicradii,
                                            'volume': atomicvol,
                                            }

        dfelprops = pd.DataFrame(elements).T

        self.dfelprops = dfelprops  # The properties of elements

        self.calculations.append('box')

    def volume(self):
        '''
        Calculate the volume from box dimensions.

        inputs:
            self = The object reference
        outputs:
            self.dfvol = The volumes for trajectory snapshots
        '''

        print('Calculating volume')

        try:
            self.dftraj
        except Exception:
            job.box(self)

        df = pd.DataFrame()

        # Find the box lengths
        df['dx'] = self.dftraj['xhi']-self.dftraj['xlo']  # Am
        df['dy'] = self.dftraj['yhi']-self.dftraj['ylo']  # Am
        df['dz'] = self.dftraj['zhi']-self.dftraj['zlo']  # Am

        self.dfvol = pd.DataFrame()

        # Find the box volume
        self.dfvol['time'] = self.dftraj['time']
        self.dfvol['Volume'] = df['dx']*df['dy']*df['dz']  # Am^3

        self.calculations.append('volume')

        return self.dfvol

    def apd(self, plot=True):
        '''
        Calculate the atomic packing density.

        inputs:
            self = The object reference
        outputs:
            self.dfapd = The APD for trajectory snapshots

        '''

        print('Calculating APD')

        try:
            self.dfsys
        except Exception:
            job.sys(self)

        try:
            self.dfvol
        except Exception:
            job.volume(self)

        # Merge dfsys and dfvol on matching steps
        df = pd.merge(
                      self.dfsys.loc[:, self.dfsys.columns != 'Volume'],
                      self.dfvol, on=['time']
                      )

        # Calculate the atomic packing density (APD)
        numerator = np.sum(self.dfelprops['counts']*self.dfelprops['volume'])

        # Create a dataframe for APD
        self.dfapd = pd.DataFrame()
        self.dfapd['Temp'] = df['Temp']
        self.dfapd['APD'] = numerator/df['Volume']

        if plot:

            # Create the path to work in
            if not os.path.exists(self.plotpath):
                os.makedirs(self.plotpath)

            # Plot only the cooling data
            fig, ax = pl.subplots()

            ax.plot(
                    self.dfapd['Temp'][df['Step'] >= self.hold1],
                    self.dfapd['APD'][df['Step'] >= self.hold1],
                    marker='.',
                    linestyle='none'
                    )

            ax.set_xlabel('Temperature [K]')
            ax.set_ylabel('ATD [-]')
            ax.grid()

            fig.tight_layout()
            fig.savefig(os.path.join(self.plotpath, 'atp'))

            pl.close('all')

        self.calculations.append('apd')

        return self.dfapd

    def etg(self, plot=True):
        '''
        Calculate the glass transition temperature based on E-3kt.

        inputs:
            self = The object reference
        outputs:
            self.tgfrome = The Tg
            self.dfetg = The data used to determine Tg
        '''

        print('Calculating Tg from E-3kT')

        try:
            self.dfsys
        except Exception:
            job.sys(self)

        try:
            self.dfvol
        except Exception:
            job.volume(self)

        k = sc.constants.physical_constants['Boltzmann constant in eV/K']

        df = pd.DataFrame()

        e = self.dfsys['TotEng']/self.natoms-3.*k[0]*self.dfsys['Temp']

        df['Temp'] = self.dfsys['Temp']
        df['E-3kT'] = e

        # Use data at and after start of cooling
        condition = self.dfsys['Step'] >= self.hold1
        dfcool = df[condition]
        dfcool = dfcool.sort_values(by=['Temp'])  # Needed for spline

        # Find the polynomial coefficients for a fit
        tfit, efit, ddefit, kneeindex = knees(
                                              dfcool['Temp'].values,
                                              dfcool['E-3kT'].values
                                              )

        self.tgfrome = tfit[kneeindex]

        self.dfetg = df

        if plot:

            # Create the path to work in
            if not os.path.exists(self.plotpath):
                os.makedirs(self.plotpath)

            plotknee(
                     dfcool['Temp'],
                     dfcool['E-3kT'],
                     tfit,
                     efit,
                     ddefit,
                     kneeindex,
                     self.plotpath,
                     'etg'
                     )

        self.calculations.append('etg')

        return self.tgfrome, self.dfetg

    def vtg(self, plot=True):
        '''
        Calculate the glass transition temperature based on specific volume.

        inputs:
            self = The object reference
        outputs:
            self.tgfromv = The Tg
            self.dfvtg = The data used to determine Tg
        '''

        print('Calculating Tg from specific volume')

        try:
            self.dfsys
        except Exception:
            job.sys(self)

        try:
            self.dfvol
        except Exception:
            job.volume(self)

        k = sc.constants.physical_constants['Boltzmann constant in eV/K']

        df = pd.DataFrame()

        v = self.dfvol['Volume']/self.natoms

        # Merge dfsys and dfvol on matching steps to get temp
        dfmerge = pd.merge(self.dfsys, self.dfvol, on=['time'])

        df['Temp'] = dfmerge['Temp']
        df['v'] = v

        # Use data at and after start of cooling
        condition = dfmerge['Step'] >= self.hold1
        dfcool = df[condition]
        dfcool = dfcool.sort_values(by=['Temp'])  # Needed for spline

        # Find the polynomial coefficients for a fit
        tfit, vfit, ddvfit, kneeindex = knees(
                                              dfcool['Temp'].values,
                                              dfcool['v'].values
                                              )

        self.tgfromv = tfit[kneeindex]

        self.dfvtg = df

        if plot:

            # Create the path to work in
            if not os.path.exists(self.plotpath):
                os.makedirs(self.plotpath)

            plotknee(
                     dfcool['Temp'],
                     dfcool['v'],
                     tfit,
                     vfit,
                     ddvfit,
                     kneeindex,
                     self.plotpath,
                     'vtg'
                     )

        self.calculations.append('vtg')

        return self.tgfromv, self.dfvtg

    def apd_single(self, traj_path, in_path):
        '''
        Calculate the APD for a single trajectory.

        inputs:
            traj_path = Path with the trajectory snapshots name
            in_path = The path to the input file.

        outputs:
            self.apd_snapshot = The APD for the last trajectory snapsot
        '''

        print('Calculating APD from: '+traj_path)

        df, counts = traj.info(traj_path)

        # Find the box lengths
        df['dx'] = df['xhi']-df['xlo']  # Am
        df['dy'] = df['yhi']-df['ylo']  # Am
        df['dz'] = df['zhi']-df['zlo']  # Am

        df['volume'] = df['dx']*df['dy']*df['dz']  # Am^3

        # Gather input file parameters
        allelements = {}
        with open(in_path) as f:
            for line in f:
                line = line.strip().split(' ')
                if 'pair_coeff' in line:
                    line = [i for i in line if i != ''][4:]

                    count = 1
                    for item in line:
                        allelements[count] = item
                        count += 1

        # Element counts from actual element
        self.natoms = 0  # Count the total number of atoms
        elements = {}
        for key, count in counts.items():
            self.natoms += count

            element = mg.Element(allelements[key])
            atomicradii = element.atomic_radius  # in Am
            atomicvol = volume_sphere(atomicradii)  # in Am^3

            elements[allelements[key]] = {
                                          'counts': count,
                                          'radius': atomicradii,
                                          'volume': atomicvol,
                                          }

        dfelprops = pd.DataFrame(elements).T

        # Calculate the atomic packing density (APD)
        d = np.sum(dfelprops['counts']*dfelprops['volume'])
        d /= df['volume']
        df['apd'] = d

        self.apd_snapshot = df['apd'].values[-1]

        self.calculations.append('apd_single')

        return self.apd_snapshot

    def save_data(self):
        '''
        Save all data as csv.
        '''

        print('Saving data')

        # Create a directory for the analysis files
        savepath = os.path.join(self.path, self.datadirname)
        if not os.path.exists(savepath):
            os.makedirs(savepath)

        # Save system data
        if 'system' in self.calculations:
            self.dfsys.to_csv(
                              os.path.join(savepath, 'system.txt'),
                              index=False
                              )

        # Save information of simulation box
        if 'box' in self.calculations:
            self.dftraj.to_csv(
                               os.path.join(savepath, 'boxboundary.txt'),
                               index=False
                               )

        # Save APD data
        if 'apd' in self.calculations:
            self.dfapd.to_csv(
                              os.path.join(savepath, 'apd.txt'),
                              index=False
                              )

        # Save Tg data from E-3kT
        if 'etg' in self.calculations:
            self.dfetg.to_csv(
                              os.path.join(savepath, 'etg.txt'),
                              index=False
                              )

            # Export the glass transition temperature
            with open(os.path.join(savepath, 'tg_e.txt'), 'w+') as outfile:
                outfile.write(str(self.tgfrome))

        # Save Tg data from specific volume
        if 'vtg' in self.calculations:
            self.dfetg.to_csv(
                              os.path.join(savepath, 'vtg.txt'),
                              index=False
                              )

            # Export the glass transition temperature
            with open(os.path.join(savepath, 'tg_v.txt'), 'w+') as outfile:
                outfile.write(str(self.tgfromv))

        # Save APD from a specific trajectory file
        if 'apd_single' in self.calculations:
            name = os.path.join(savepath, 'apd_single.txt')
            with open(name, 'w+') as outfile:
                outfile.write(str(self.apd_snapshot))
