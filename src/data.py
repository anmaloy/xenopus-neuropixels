"""Routines for data import and manipulation."""
import neo
import elephant
import quantities as pq
import sys
import csv
import glob
import matplotlib.pyplot as plt
import pandas as pd
import os
import numpy as np
import uuid

try:
    from . import readSGLX as readSGLX
except:
    import readSGLX
from pathlib import Path
# sys.path.append('../')
# sys.path.append(r'Y:\projects')
sys.path.append('C:\\Users\\anmal\\OneDrive\\Documents\\Yamaguchi Lab\\NeuroCode')
from spykes.plot import NeuroVis, PopVis
from tqdm import tqdm
import scipy.io.matlab as sio
import re
import quantities as pq
import scipy.interpolate

def binary_onsets(x,thresh):
    '''
    Get the onset and offset samples of a binary signal (
    :param x: signal
    :param thresh: Threshold
    :return: ons,offs
    '''
    xbool = x>thresh

    ons = np.where(np.diff(xbool.astype('int'))==1)[0]
    offs = np.where(np.diff(xbool.astype('int'))==-1)[0]
    if xbool[0]:
        offs = offs[1:]
    if xbool[-1]:
        ons = ons[:-1]
    if len(ons)!=len(offs):
        plt.plot(x)
        plt.axhline(thresh)
        raise ValueError('Onsets does not match offsets')


    return(ons,offs)

def spike_times_npy_to_sec(sp_fullPath, sample_rate=0, bNPY=True):
    # convert spike_times.npy to text of times in sec
    # return path to the new file. Can take sample_rate as a
    # parameter, or set to 0 to read from param file

    # get file name and create path to new file
    # FROM ECEPHYS, not NEB
    '''
    sp_fullPath: path to kilosort spiketimes output (data are in samples)
    sample_rate: default to 0 in order to read in from the param file
    bNPY: boolean flag for using npy files. Default to True. Vestigial but kept in case we need the flexibility

    '''

    sp_path, sp_fileName = os.path.split(sp_fullPath)
    baseName, bExt = os.path.splitext(sp_fileName)
    if bNPY:
        new_fileName = baseName + '_sec.npy'
    else:
        new_fileName = baseName + '_sec.txt'

    new_fullPath = os.path.join(sp_path, new_fileName)

    # load spike_times.npy; returns numpy array (Nspike,) as uint64
    spike_times = np.load(sp_fullPath)

    if sample_rate == 0:
        # get sample rate from params.py file, assuming sp_path is a full set
        # of phy output
        with open(os.path.join(sp_path, 'params.py'), 'r') as f:
            currLine = f.readline()
            while currLine != '':  # The EOF char is an empty string
                if 'sample_rate' in currLine:
                    sample_rate = float(currLine.split('=')[1])
                    print(f'sample_rate read from params.py: {sample_rate:.10f}')
                currLine = f.readline()

            if sample_rate == 0:
                print('failed to read in sample rate\n')
                sample_rate = 30000

    spike_times_sec = spike_times / sample_rate  # spike_times_sec dtype = float

    if bNPY:
        # write out npy file
        np.save(new_fullPath, spike_times_sec)
    else:
        # write out single column text file
        nSpike = len(spike_times_sec)
        with open(new_fullPath, 'w') as outfile:
            for i in range(0, nSpike - 1):
                outfile.write(f'{spike_times_sec[i]:.6f}\n')
            outfile.write(f'{spike_times_sec[nSpike - 1]:.6f}')

    return new_fullPath


def get_tvec(x_sync, sync_timestamps, sr):
    '''
    Get a time vector for NI that uses the sync signal

    :param x_sync:
    :param sync_timestamps: should be from the IMEC master probes
    :return: tvec
    '''
    tvec = np.empty_like(x_sync)
    onsets, offsets = binary_onsets(x_sync, 1)
    n_ons = len(onsets)
    n_ts = len(sync_timestamps)
    if n_ons != n_ts:
        raise ValueError(f"number of detected onsets {n_ons} does not match number expected {n_ts}")

    # Map all detected onsets to a timestamp and linearly interpolate
    for ii in range(len(onsets) - 1):
        nsamps = onsets[ii + 1] - onsets[ii]
        temp = np.linspace(sync_timestamps[ii], sync_timestamps[ii + 1], nsamps)
        tvec[onsets[ii]:onsets[ii + 1]] = temp

    # get times before first synch signal
    first_t = sync_timestamps[0] - onsets[0] / sr
    first_seg = np.linspace(first_t, sync_timestamps[0], onsets[0])
    tvec[:onsets[0]] = first_seg

    # get times after last synch signal
    last_seg_length = len(x_sync) - onsets[-1]
    last_seg = np.linspace(sync_timestamps[-1], sync_timestamps[-1] + last_seg_length / sr, last_seg_length)
    tvec[onsets[-1]:] = last_seg

    return (tvec)


def get_sr(ni_bin_fn):
    '''
    Conveneience function to the the sample rate from a nidaq bin file
    :param ni_bin_fn:
    :return:
    '''
    meta = readSGLX.readMeta(Path(ni_bin_fn))
    sr = readSGLX.SampRate(meta)
    return (sr)


def get_ni_analog(ni_bin_fn, chan_id):
    '''
    Convenience function to load in a NI analog channel
    :param ni_bin_fn: filename to load from
    :param chan_id: channel index to load
    :return: analog_dat
    '''
    meta = readSGLX.readMeta(Path(ni_bin_fn))
    bitvolts = readSGLX.Int2Volts(meta)
    ni_dat = readSGLX.makeMemMapRaw(ni_bin_fn, meta)
    analog_dat = ni_dat[chan_id] * bitvolts

    return (analog_dat)


def get_imec_analog(imec_bin_fn, chan_id, t0, tf):
    '''
    Convenience function to load in an imce analog channel
    :param imec_bin_fn: filename to load from
    :param chan_id: channel index to load
    :return: analog_dat
    '''
    if type(chan_id) is int:
        chan_id = [chan_id]
    meta = readSGLX.readMeta(Path(imec_bin_fn))
    sr = readSGLX.SampRate(meta)
    s0, sf = (int(t0 * sr), int(tf * sr))
    tvec = np.arange(t0, tf, 1 / sr)
    bitvolts = readSGLX.Int2Volts(meta)
    imec_dat = readSGLX.makeMemMapRaw(imec_bin_fn, meta)
    analog_dat = imec_dat[chan_id, s0:sf] * bitvolts
    tvec = tvec[:analog_dat.shape[1]]

    return (tvec, analog_dat)


def get_ni_bin_from_ks_dir(ks_dir, search_p=None):
    '''
    Load the binary auxiliarry data associeated with an imec recording
    Similar to get_ni_analog, but uses the kilosort directory as input
    :param ks_dir:
    :param search_p:
    :return:
    '''
    sess_spec = parse_dir(ks_dir)

    if search_p is None:
        if os.sys.platform == 'linux':
            search_p = '/active/ramirez_j/ramirezlab/nbush/projects/dynaresp/data/raw'
        else:
            search_p = 'Y:/projects/dynaresp/data/raw'

    ni_bin_list = glob.glob(
        f'{search_p}/{sess_spec["mouse_id"]}/{sess_spec["mouse_id"]}_g{sess_spec["gate"]}/*nidq.bin')

    if len(ni_bin_list) > 1:
        print('More than one trigger found, looking in processed for a concatenated nidaq file')
        if os.sys.platform == 'linux':
            search_p = '/active/ramirez_j/ramirezlab/nbush/projects/dynaresp/data/processed'
        else:
            search_p = 'Y:/projects/dynaresp/data/processed'
        ni_bin_list = glob.glob(
            f'{search_p}/{sess_spec["mouse_id"]}/*{sess_spec["mouse_id"]}_g{sess_spec["gate"]}/*tcat*nidq.bin')
    ni_bin_fn = ni_bin_list[0]

    return (ni_bin_fn)


def get_concatenated_spikes(ks_dir, use_label='intersect'):
    '''
    Built on top of create_spike_dict and create_spike_df
    Returns a minimal set of concatenated spike data. Probably the most useful
    way to import spike data
    :param ks_dir:
    :param use_label: define whether to use the phy label(default_, ks_label, or the intersection
    '''

    # spike_df = create_spike_df(ks2_dir)
    if os.path.isfile(f'{ks_dir}/spike_times_sec.npy'):
        ts = np.load(f'{ks_dir}/spike_times_sec.npy').ravel()
    else:
        print('NO SPIKETIMES_SEC FOUND. Converting and saving')
        t_samps = np.load(f'{ks_dir}/spike_times.npy').ravel()
        ap_bin = glob.glob(f'{ks_dir}/../*ap.bin')[0]
        meta = readSGLX.readMeta(Path(ap_bin))
        spike_sr = readSGLX.SampRate(meta)
        ts = t_samps / spike_sr
        with open(f'{ks_dir}/spike_times_sec.npy', 'wb') as fid:
            np.save(fid, ts)

    idx = np.load(f'{ks_dir}/spike_clusters.npy').ravel()
    try:
        metrics = pd.read_csv(f'{ks_dir}/metrics.csv')
    except:
        metrics = pd.read_csv(f'{ks_dir}/waveform_metrics.csv', )
    depths = np.load(f'{ks_dir}/channel_positions.npy')[:, 1]
    dd = pd.DataFrame()
    dd['peak_channel'] = np.arange(len(depths))
    dd['depth'] = depths
    metrics = metrics.merge(dd, how='left', on='peak_channel')

    spikes = pd.DataFrame()
    spikes['ts'] = ts
    spikes['cell_id'] = idx
    spikes = pd.merge(left=spikes, right=metrics[['cluster_id', 'depth']], how='left', left_on='cell_id',
                      right_on='cluster_id')

    if use_label == 'default':
        grp = pd.read_csv(f'{ks_dir}/cluster_group.tsv', delimiter='\t')
        clu_list = grp.query('group=="good"')['cluster_id']
        spikes = spikes[spikes['cluster_id'].isin(clu_list)]
        metrics = metrics.merge(grp, on='cluster_id')
    elif use_label == 'ks':
        grp = pd.read_csv(f'{ks_dir}/cluster_KSLabel.tsv', delimiter='\t')
        clu_list = grp.query('KSLabel=="good"')['cluster_id']
        spikes = spikes[spikes['cluster_id'].isin(clu_list)]
        metrics = metrics.merge(grp, on='cluster_id')
    elif use_label == 'intersect':
        grp = pd.read_csv(f'{ks_dir}/cluster_group.tsv', delimiter='\t')
        kslabel = pd.read_csv(f'{ks_dir}/cluster_KSLabel.tsv', delimiter='\t')

        # Merge and specify suffixes to avoid conflicts
        temp = pd.merge(grp, kslabel, how='inner', on='cluster_id', suffixes=('_group', '_KS'))
        metrics = metrics.merge(grp, on='cluster_id')
        metrics = metrics.merge(kslabel, on='cluster_id')

        # Query using the suffixed column names
        temp.query('group=="good" & KSLabel=="good"', inplace=True)

        clu_list = temp['cluster_id']
        spikes = spikes[spikes['cluster_id'].isin(clu_list)]
        metrics = metrics[metrics['cluster_id'].isin(clu_list)]

    else:
        raise NotImplementedError('Use a valid label filter[default,ks,intersect]')

    return (spikes, metrics)


def filter_by_metric(spikes, metrics, expression):
    '''
    Finds all the clusters that pass a particular QC metrics filter expression and keeps only the spikes from
    those clusters
    :param metrics: the metrics csv
    :param spikes: the spikes dataframe with columns [ts,cluster_id,depth]
    :param expression: logical expression to filter the spikes by
    :return: filtered spikes dataframe

    spikes_filt = filter_by_metric(metrics,spikes,'amplitude_cutoff<0.1')
    '''
    clu_list = metrics.query(expression)['cluster_id']
    spikes = spikes[spikes['cluster_id'].isin(clu_list)]
    metrics = metrics[metrics['cluster_id'].isin(clu_list)]
    return (spikes, metrics)


def filter_by_spikerate(spikes, metrics, thresh=100):
    '''
    remove units that have less than "thresh" spikes in the recording

    :return: spikes2
    '''
    n_spikes = spikes.groupby('cluster_id').count()['ts']
    mask = n_spikes[n_spikes > thresh].index
    spikes2 = spikes.loc[spikes['cluster_id'].isin(mask)]
    metrics = metrics.query('cluster_id in @mask')
    return (spikes2)


def filter_default_metrics(spikes, metrics):
    '''
    Runs filter_by_metric for a few standard metrics.
    Allen metrics : presence ratio >.95, isi_viol<1, amplitude_cutoff < 0.1
    NEB metrics: isi_viol < 2, amplitude_cutoff < 0.1,presence_ratio>0.9
    isi_violations should be relaxed a little given the bursty nature of these neurons
    :param metrics:
    :param spikes:
    :return: filtered_spikes
    '''
    spikes = filter_by_spikerate(spikes, metrics, 100)
    spikes, metrics = filter_by_metric(spikes, metrics, 'isi_viol<2 ')
    spikes, metrics = filter_by_metric(spikes, metrics, 'amplitude_cutoff<0.1')
    spikes, metrics = filter_by_metric(spikes, metrics, 'presence_ratio>0.9')
    # spikes = filter_by_metric(spikes,metrics,'amplitude>150')

    return (spikes, metrics)


def resort_by_depth(spikes):
    '''
    changes the cell_id column to be depth ordered, 0 indexed, and sequential
    That is, cell_id ranges from 0 to N_neurons and there are no skipped indexes
    :param spikes: spikes dataframe
    :return: spikes -- spikes dataframe with modified cell_id column
    '''
    dd = spikes[['cluster_id', 'depth']].groupby('cluster_id').mean()
    dd = dd.reset_index()
    dd = dd.sort_values('depth')
    dd = dd.reset_index().rename({'index': 'cell_id'}, axis=1)
    dd = dd.drop('depth', axis=1)
    spikes = spikes.drop('cell_id', axis=1)
    spikes = spikes.merge(dd, on='cluster_id')

    return (spikes)


def load_filtered_spikes(ks2_dir, use_filters=True):
    '''
    Convinience function to load the standard qc controlled spikes
    and map cell_id to the depth order
    :param ks2_dir:
    :return:
    '''
    spikes, metrics = get_concatenated_spikes(ks2_dir)
    if use_filters:
        spikes, metrics = filter_default_metrics(spikes, metrics)
    spikes = resort_by_depth(spikes)
    return (spikes, metrics)


def concatenate_probes(spikes_list, metrics_list, labels):
    '''
    concetanates spiking data from multiple probes into a single set of dataframes.
    :param spikes_list: list of spike dataframes
    :param metrics_list: list of metrics dataframes
    :param labels: list of labels (suggested is ['imec0','imec1....]
    :return: spikes,metrics - concatenated spikes and metrics dataframes
    '''
    n_probes = len(labels)
    for ii in range(n_probes):
        spikes_list[ii]['probe'] = labels[ii]
        metrics_list[ii]['probe'] = labels[ii]
        metrics_list[ii]['uuid'] = [uuid.uuid4() for _ in range(len(metrics_list[ii].index))]
        spikes_list[ii] = spikes_list[ii].merge(metrics_list[ii][['cluster_id', 'uuid']], on='cluster_id')

    spikes = pd.concat(spikes_list).reset_index(drop=True)
    metrics = pd.concat(metrics_list).sort_values(['probe', 'depth']).reset_index(drop=True).reset_index().rename(
        columns={'index': 'cell_id'})

    spikes = spikes.drop('cell_id', axis=1)
    spikes = spikes.merge(metrics[['uuid', 'cell_id']], on='uuid').sort_values('ts').reset_index(drop=True)
    return (spikes, metrics)


def load_concatenated_probes(gate_dir):
    '''
    Given the directory of a gate (which should include the subsequent ks2 folders)
    return the concatenated spike dataframes. This uses the standard battery of filters to exclude data, which may
    or may not be appropriate.
    :param gate_dir: Path object to the gate directory
    :return: spikes,metrics - dataframes with info on all the spikes.
    '''
    ks2_paths = list(gate_dir.rglob('imec*_ks2'))
    ks2_paths.sort()
    spikes_list, metrics_list = map(list, zip(*[load_filtered_spikes(x) for x in ks2_paths]))
    labels = [re.search('imec\d', str(x)).group() for x in ks2_paths]
    spikes, metrics = concatenate_probes(spikes_list, metrics_list, labels)
    return (spikes, metrics)


def load_alf(alf_path, keep_good=True):
    '''
    Load the IBL pipeline alf folder in the same format as we loaded in previosly, giving us the spikes and metrics dataframes
    May have some issues in the the fields in metrics is not all the same now.
    '''
    times = np.load(alf_path.joinpath('spikes.times.npy'))
    clusters = np.load(alf_path.joinpath('spikes.clusters.npy'))
    depths = np.load(alf_path.joinpath('spikes.depths.npy'))
    uuids = pd.read_csv(alf_path.joinpath('clusters.uuids.csv'))
    metrics = pd.read_csv(alf_path.joinpath('metrics.csv'), index_col=0)
    metrics['uuid'] = uuids
    spikes = pd.DataFrame()
    spikes['ts'] = times
    spikes['cluster_id'] = clusters
    spikes['depth'] = depths
    spikes = spikes.merge(metrics[['cluster_id', 'uuid']], on='cluster_id')

    if keep_good:
        use_uuid = metrics.query('label==1')['uuid']
        spikes = spikes.query('uuid in @use_uuid')
        metrics = metrics.query('uuid in @use_uuid')
    spikes['cell_id'] = spikes['cluster_id']
    spikes = resort_by_depth(spikes)
    metrics = metrics.merge(spikes[['cell_id', 'uuid']].drop_duplicates(), on='uuid', how='inner')

    return (spikes, metrics)


def create_spykes_pop(spikes, start_time=0, stop_time=np.inf):
    '''
    Convert a spikes dataframe to a Spykes neuron list and population object

    :param spikes: dataframe of spike times "ts" in seconds and "cell_id" in long form.
    :param start_time: ignore spikes before this time (s)
    :param stop_time: ignore spikes after this time (s)
    :return: neuron_list,pop
    '''

    sub_spikes = spikes[spikes['ts'] > start_time]
    sub_spikes = sub_spikes[sub_spikes['ts'] < stop_time]

    neuron_list = []
    cell_ids = sub_spikes['cell_id'].unique()
    cell_ids.sort()
    for ii, cell_id in enumerate(cell_ids):
        sub_df = sub_spikes[sub_spikes['cell_id'] == cell_id]
        if (len(sub_df.ts)) < 10:
            neuron = []
        else:
            neuron = NeuroVis(sub_df.ts, cell_id)
        neuron_list.append(neuron)

    pop = PopVis(neuron_list)
    return (neuron_list, pop)


def get_event_triggered_st(ts, events, idx, pre_win, post_win):
    '''
    Probably deprecated; Better to use Pavan's spykes code
    :param ts:
    :param events:
    :param idx:
    :param pre_win:
    :param post_win:
    :return:
    '''
    print('Calculating Time D')
    D = ts - events[:, np.newaxis]
    mask = np.logical_or(D < -pre_win, D > post_win)
    D[mask] = np.nan
    pop = []
    print('Working on all neurons')
    for ii in tqdm(np.unique(idx)):
        trains = []
        for jj in range(len(events)):
            sts = D[jj, idx == ii]
            sts = sts[np.isfinite(sts)]
            trains.append(sts)

        pop.append(trains)
    return (pop)


def load_aux(load_dir, t=0, mode='ks'):
    '''
    loads in the standard auxiliarry data from the neuropixel exp[eriments
    :param ks_dir: directory of the sorted data
    :param t: The trial index
    :param mode: string determines wether you have passed a kilosort directory or a gate directory (default=kilosort directory)
    :return: epochs,breaths,aux_dat
    '''
    if mode == 'ks':
        aux_dir = os.path.join(load_dir, '../../')
    elif mode == 'gate':
        aux_dir = load_dir
    else:
        raise NotImplementedError('Please choose a mode ["ks","gate"]')

    epoch_list = glob.glob(os.path.join(aux_dir, '*epochs*.csv'))
    epoch_list.sort()
    if len(epoch_list) == 0:
        raise ValueError(f'No epoch csv found in {aux_dir}')
    if len(epoch_list) > 1:
        aux_dat = sio.loadmat(glob.glob(os.path.join(aux_dir, '*tcat*aux*.mat'))[0])
        try:
            breaths = pd.read_csv(glob.glob(os.path.join(aux_dir, '*tcat*pleth*.csv'))[0], index_col=0)
        except:
            breaths = pd.read_csv(glob.glob(os.path.join(aux_dir, '*tcat*.csv'))[0], index_col=0)
        epochs = pd.DataFrame()
        last_time = 0
        mat_list = glob.glob(aux_dir + '*aux*.mat')
        mat_list.sort()
        mat_list = mat_list[:len(epoch_list)]
        for ii, ff in enumerate(epoch_list):
            mat_dum = sio.loadmat(mat_list[ii], variable_names=['t'])
            t_max = mat_dum['t'][-1][0]
            dum = pd.read_csv(ff)
            dum['t0'] += last_time
            dum['tf'] += last_time
            last_time += t_max / 60
            if np.isnan(dum['tf'].iloc[-1]):
                dum['tf'].iloc[-1] = last_time

            epochs = pd.concat([epochs, dum])
    else:
        aux_dat = sio.loadmat(glob.glob(os.path.join(aux_dir, '*aux*.mat'))[t])
        epochs = pd.read_csv(glob.glob(os.path.join(aux_dir, '*epochs*.csv'))[t])
        try:
            breaths = pd.read_csv(glob.glob(os.path.join(aux_dir, '*pleth*.csv'))[t], index_col=0)
        except:
            breaths = pd.read_csv(glob.glob(os.path.join(aux_dir, '*stat*.csv'))[t], index_col=0)

        if np.isnan(epochs['tf'].iloc[-1]):
            epochs['tf'].iloc[-1] = aux_dat['t'][-1][0] / 60

    breaths = breaths[breaths['duration_sec'] < 1]
    aux_t = aux_dat['t'].ravel()
    dia = aux_dat['dia'].ravel()
    pleth = aux_dat['pleth'].ravel()
    sr = aux_dat['sr'].ravel()[0]
    aux_dat = {}
    aux_dat['t'] = aux_t
    aux_dat['dia'] = dia
    aux_dat['pleth'] = pleth
    aux_dat['sr'] = sr
    try:
        breaths = breaths.reset_index().drop('Var1', axis=1)
    except:
        pass

    # For compatibility with changed burst_stats_dia versions.
    if 'IBI' not in breaths.columns:
        breaths = breaths.eval('IBI=duration_sec+postBI')
        breaths = breaths.eval('inst_freq=1/IBI')

    return (epochs, breaths, aux_dat)


def get_opto_df(raw_opto, v_thresh, ni_sr, min_dur=0.001, max_dur=10):
    '''

    :param raw_opto: raw current sent to the laser or LED (1V/A)
    :param v_thresh: voltage threshold to find crossing
    :param ni_sr: sample rate (Hz)
    :param min_dur: minimum stim duration in seconds
    :param max_dur: maximum stim duration in seconds
    :return: opto-df a dataframe with on, off, and amplitude
    '''
    ons, offs = binary_onsets(raw_opto, v_thresh)
    durs = offs - ons
    opto_df = pd.DataFrame()
    opto_df['on'] = ons
    opto_df['off'] = offs
    opto_df['durs'] = durs

    min_samp = ni_sr * min_dur
    max_samp = ni_sr * max_dur
    opto_df = opto_df.query('durs<=@max_samp & durs>=@min_samp').reset_index(drop=True)

    amps = np.zeros(opto_df.shape[0])
    for k, v in opto_df.iterrows():
        amps[k] = np.median(raw_opto[v['on']:v['off']])
    opto_df['amps'] = np.round(amps, 2)

    opto_df['on_sec'] = opto_df['on'] / ni_sr
    opto_df['off_sec'] = opto_df['off'] / ni_sr
    opto_df['dur_sec'] = np.round(opto_df['durs'] / ni_sr, 3)

    return (opto_df)


def parse_dir(ks_dir):
    '''
    Convecience function to parse the kilosort directory
    into a dict with mouse, gate, and probe fields
    :param ks_dir:
    :return: meta
    '''
    mouse_id = re.search('m\d\d\d\d-\d\d', ks_dir).group()
    gate = int(re.search('g\d', ks_dir).group()[1:])
    probe = re.search('imec\d', ks_dir).group()
    meta = {}
    meta['mouse_id'] = mouse_id
    meta['gate'] = gate
    meta['probe'] = probe
    return (meta)


def spikes2neo_trains(spikes, cell_id=None, t0=0, t_stop=None, out='dict'):
    all_cells = spikes['cell_id'].unique()
    if cell_id is None:
        cell_id = all_cells
    if type(cell_id) is int:
        cell_id = [cell_id]
    for ii in cell_id:
        if ii not in all_cells:
            raise (ValueError(f'Cell {ii} is not in Spikes'))
    if t_stop is None:
        t_stop = spikes['ts'].max() * pq.s
    elif type(t_stop) is not pq.Quantity:
        t_stop = t_stop * pq.s

    if type(t0) is not pq.Quantity:
        t0 = t0 * pq.s

    train_dict = {}
    train_list = []

    for ii in cell_id:
        sub_spikes = spikes.query('cell_id==@ii')
        ts = sub_spikes['ts'].values * pq.s
        clu_id = sub_spikes['cluster_id'].values[0]
        depth = sub_spikes['depth'].values[0]

        ts = ts[ts < t_stop]
        ts = ts[ts > t0]
        train = neo.SpikeTrain(ts, t_stop, t_start=t0, name=ii, description=f'clu_id={clu_id},depth={depth}')
        train_dict[ii] = train
        train_list.append(train)

    if out == 'dict':
        return (train_dict)
    elif out == 'list':
        return (train_list)
    else:
        return (0)


def calibrate_flowmeter(x, vin=9):
    '''
    This applies a calibration to the flow meter Honeywell AWN3303V to output in ml/min
    :param x: raw flowmeter in volts
    :return: y - calibrated flow in ml/min
    '''
    assert (x.dtype == 'float64')
    # raise Warning("This code does not yet integrate flow to zero..."
    v_calibrated = 9.58  # NEB 2022-10-07
    # First make the map as it is calibrated with 9.58v supply (NEB 2022-10-07)
    vout_map = np.array(
        [1.5944, 1.6923, 1.7822, 1.9068, 2.0688, 2.2803, 2.5628, 2.8907, 3.0907, 3.2433, 3.3619, 3.448, 3.5321])

    flow_map = np.array([300, 250, 200, 150, 100, 50, 0, -50, -100, -150, -200, -250, -300])

    # Then scale for the case where vin is not 9
    vout_map = vout_map * (vin / v_calibrated)

    f = scipy.interpolate.interp1d(vout_map, flow_map, fill_value='extrapolate')
    return (-f(x))


def extract_digital_bit(bin_fn, bit_to_read):
    '''
    Return a vector of the value of a given bit for an entire recording.
    :param bin_fn:
    :param bit_to_read:
    :return:
    '''
    meta = readSGLX.readMeta(Path(bin_fn))
    mmap = readSGLX.makeMemMapRaw(Path(bin_fn), meta)
    ftime = float(meta['fileTimeSecs'])
    sRate = readSGLX.SampRate(meta)

    last_samp = int(np.floor(sRate * ftime))
    bit = readSGLX.ExtractDigital(mmap, 0, last_samp - 1, 0, [bit_to_read], meta).ravel()
    bit = bit.astype('bool')
    return (bit)


def extract_digital_bit_dataframe(bin_fn, bit_to_read, active='HIGH'):
    bit = extract_digital_bit(bin_fn, bit_to_read)
    if active == "LOW":
        bit = np.logical_not(bit)

    bit_change = np.where(np.diff(bit) != 0)[0]
    value_at_change = bit[bit_change]
    high2low = bit_change[value_at_change]
    low2high = bit_change[np.logical_not(value_at_change)]

    df = pd.DataFrame()
    if len(low2high) != len(high2low):
        np.concatenate([high2low, len(bit)])  # add an offset at the end of the recording

    durations = high2low - low2high
    assert np.all(durations > 0), 'Offsets are not after onsets'

    df['on'] = low2high
    df['offs'] = high2low
    df['duration'] = durations

    return (df)
