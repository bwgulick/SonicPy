
'''
Hard-coded broadband excitation pulse used by the SBU Standard.

The kernel below is the 45-sample impulse carried by every one of the reference
waveform files in examples/ (UXPERT0(1).WFM, UXPERT0-long(1).WFM and
Uxpert-long-20-70(1).tfw all contain the identical pattern - the files differ only in
record length and intended playback clock). It was extracted verbatim from
examples/UXPERT0-long(1).WFM samples 884..928, baseline removed and normalised so the
peak is +1.

Because it is a fixed sample pattern, the band it excites is set purely by the playback
sample rate, and the pulse repetition period is set by the record length:

    AFG record frequency = sample_rate / record_length
    repetition period    = record_length / sample_rate
    band scales with       sample_rate

At the SBU default of 250 MSa/s the -6 dB band is about 25-71 MHz, which covers both the
~30 MHz shear and ~50 MHz compressional windows; the P/S separation is done in post
processing, so no carrier frequency needs to be chosen here.
'''

import numpy as np

# 45-tap symmetric broadband impulse, peak-normalised
SBU_BROADBAND_PULSE = np.array([
    -0.057148479, +0.016103692, +0.009819324, -0.012666928, +0.064512961,
    +0.073252159, -0.020031434, -0.009721131, +0.018067557, -0.090337796,
    -0.103102917, +0.028377847, +0.009819324, -0.029261598, +0.148959150,
    +0.175373132, -0.050274952, -0.009721131, +0.068931657, -0.401512195,
    -0.608601733, +0.288688135, +1.000000000, +0.288688135, -0.608601733,
    -0.401512195, +0.068931657, -0.009721131, -0.050274952, +0.175373132,
    +0.148959150, -0.029261598, +0.009819324, +0.028377847, -0.103102917,
    -0.090337796, +0.018067557, -0.009721131, -0.020031434, +0.073252159,
    +0.064512961, -0.012666928, +0.009819324, +0.016103692, -0.057148479,
])

# defaults matching Uxpert-long-20-70(1).tfw played at 250 MSa/s
SBU_DEFAULT_SAMPLE_RATE = 250e6     # samples per second
SBU_DEFAULT_RECORD_LENGTH = 100000  # points
SBU_DEFAULT_PULSE_OFFSET = 884      # sample index of the first tap in the source files

# AFG3251 arbitrary memory ceiling
AFG3251_MAX_POINTS = 131072


def pulse_length():
    return len(SBU_BROADBAND_PULSE)


def sbu_broadband_record(points, pulse_offset):
    '''
    Build the full arbitrary-memory record: a flat baseline with the broadband pulse
    dropped in at pulse_offset. Returns a float array in the range covered by the kernel.
    '''
    n_pulse = len(SBU_BROADBAND_PULSE)
    points = int(points)
    if points < n_pulse:
        points = n_pulse
    offset = int(pulse_offset)
    # keep the whole pulse inside the record
    offset = max(0, min(offset, points - n_pulse))
    record = np.zeros(points)
    record[offset:offset + n_pulse] = SBU_BROADBAND_PULSE
    return record


def sbu_waveform(params):
    '''
    params: {'sample_rate': samples/s, 'record_length': points, 'pulse_offset': samples}
    returns {'t','waveform','points','clock'} ready for the AFG upload path.
    '''
    sample_rate = float(params['sample_rate'])
    points = int(params['record_length'])
    offset = int(params['pulse_offset'])

    record = sbu_broadband_record(points, offset)
    points = len(record)
    t = np.arange(points) / sample_rate
    return {'t': t, 'waveform': record, 'points': points, 'clock': sample_rate}
