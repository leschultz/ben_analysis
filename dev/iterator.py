#!/usr/bin/env python3

from matplotlib import pyplot as pl

from calculations import *

from os.path import join

import pandas as pd
import numpy as np

import sys
import os

datadir = sys.argv[1]  # The location of data
treelen = int(sys.argv[2])  # The length of folder structure

trajname = sys.argv[3]  # The name of the trajectory file
logname = sys.argv[4]  # The name of the LAMMPS log file

edge_threshold = float(sys.argv[5])  # The edge threshold
dominantvp = int(sys.argv[6])  # The top number of VP types

export = sys.argv[7]  # Location of export files

# Count the number of runs
total = 0
for path, subdir, files in os.walk(datadir):

    split = path.split('/')
    run = split[-treelen:]

    if '-' not in run[0]:
        continue

    total += 1

# Get current directory
cwd = os.getcwd()

# The dataframe for all runs
cols = ['system', 'composition', 'steps', 'job', 'framestep', 'vp']
df = pd.DataFrame(columns=cols)

# Construct dataframe containing VP indexes
count = 0
for path, subdir, files in os.walk(datadir):

    split = path.split('/')
    run = split[-treelen:]

    if '-' not in run[0]:
        continue

    system = run[-6]
    composition = run[-5]
    steps = run[-4]
    job = run[-3]
    framestep = run[-1]

    trajfile = join(path, trajname)
    logfile = join(path, logname)

    frames = log_frames(logfile)  # Get the numer of minimization frames
    indexes = vp(trajfile, frames, edge_threshold)  # VP indexes

    df.loc[count] = [system, composition, steps, job, framestep, indexes]

    count += 1

    # Print status
    print('VP ('+str(count)+'/'+str(total)+'): '+join(*run))

groups = df.groupby(cols[:4])

ngroups = len(groups)
iteration = 1
for group, data in groups:

    # Combine all the frames
    all_indexes = [pd.DataFrame(i) for i in data['vp']]
    d = pd.concat(all_indexes)
    d = d.fillna(0)  # Make cure indexes are zero if not included
    d = d.astype(int)  # Make sure all counts are integers

    # Count the number of unique VP
    coords, counts = np.unique(d.values, axis=0, return_counts=True)

    # Standard notation
    coords = coords[:, 2:]
    coords = np.array([tuple(np.trim_zeros(i)) for i in coords])

    # Sort counts and indexes by descending order
    indexes = counts.argsort()[::-1]
    coords = coords[indexes]
    counts = counts[indexes]

    total = sum(counts)  # The total number of atoms for all frames

    # Gather fraction values
    fractions = counts/total

    # Calculate variance from list including ordered fractions of VP
    variance = []
    for i in range(1, counts.shape[0]):
        variance.append(np.var(fractions[:i]))

    variance = np.array(variance)  # Numpy array
    vptypes = np.arange(1, len(variance)+1)  # Types of vp

    df_variance = {'number_of_vp': vptypes, 'variance': variance}
    df_variance = pd.DataFrame(df_variance)
    df_variance['number_of_vp'] = df_variance['number_of_vp'].astype(int)

    max_index = np.argmax(variance)
    max_variance = pd.DataFrame(df_variance.loc[max_index, :]).T
    max_variance['number_of_vp'] = max_variance['number_of_vp'].astype(int)

    run = join(*list(group))

    # Print status
    print('Variance ('+str(iteration)+'/'+str(ngroups)+'): '+run)

    # Export directory for data
    calcdir = join(*[export, run, 'data', 'variance'])
    if not os.path.exists(calcdir):
        os.makedirs(calcdir)

    # Export all variances calculated
    df_variance.to_csv(
                       join(calcdir, 'variance.txt'),
                       index=False
                       )

    max_variance.to_csv(
                        join(calcdir, 'max_variance.txt'),
                        index=False
                        )

    # Export directory for plots
    plotdir = join(*[export, run, 'plots', 'variance'])
    if not os.path.exists(plotdir):
        os.makedirs(plotdir)

    # Plot variance
    for i in [counts.shape[0], dominantvp]:

        fig, ax = pl.subplots()

        ax.plot(
                vptypes[:i],
                variance[:i],
                marker='.',
                linestyle='none',
                label='Data for '+str(data.shape[0])+' frames'
                )

        coordinate = (
                      max_variance['number_of_vp'].values[0],
                      max_variance['variance'].values[0]
                      )

        vlinelabel = (
                      'Max Variance: ' +
                      str(coordinate)
                      )
        ax.axvline(
                   max_variance['number_of_vp'].values[0],
                   color='k',
                   linestyle=':',
                   label=vlinelabel
                   )

        ax.set_ylabel('Variance of VP [-]')
        ax.set_xlabel('Number of VP Types [-]')

        ax.grid()
        ax.legend()

        plotname = 'variance_top_'+str(i)+'_from_'+str(counts.shape[0])+'.png'
        fig.tight_layout()
        fig.savefig(join(plotdir, plotname))

        pl.close('all')

    # Plot distribution of cluster types seen
    fig, ax = pl.subplots()

    x = [str(i) for i in coords[:dominantvp]][::-1]
    y = fractions[:dominantvp][::-1]

    ax.barh(x, y)

    ax.set_xlabel('Fraction of VP [-]')
    ax.set_ylabel('The '+str(dominantvp)+' Most Frequent VP [-]')

    fig.tight_layout()
    fig.savefig(join(plotdir, 'vp_top_'+str(dominantvp)+'.png'))

    pl.close('all')

    iteration += 1
