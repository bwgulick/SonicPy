
'''
Measurement "Standards": named presets that decide which panels are visible and whether
the HPCAT waveform-generator chain is allowed to drive the AFG.

The chain that HPCAT depends on, and that the other Standards must not let fire, is:

    burst_fixed_time:freq / g_wavelet:*   (auto_process)
        -> ArbModel:arb_waveform
        -> ArbFilter:waveform_in -> filter -> ArbFilter:waveform_out
        -> pvServer[ArbFilter:user1_channel]        <- AFG3251:user1_waveform for HPCAT
        -> AFG3251 auto upload (TRACE:DATA EMEMory, data:copy, FUNCtion:SHAPe, Frequency)

Each non-HPCAT Standard cuts it in three independent places: at the generators
(auto_process), at the AFG (auto_upload_user1_waveform) and at the wiring
(user1_channel re-pointed at a dead-end sink pv). All three are plain pv writes, so
switching back to HPCAT restores the original behaviour exactly.
'''

HPCAT = 'HPCAT'
SBU = 'SBU'
CUSTOM = 'Custom'

STANDARD_ORDER = [HPCAT, SBU, CUSTOM]

# pvs that every Standard sets, so switching is always a full restore rather than a diff
_ARMED = {
    'g_wavelet:auto_process': True,
    'burst_fixed_time:auto_process': True,
    'AFG3251:auto_upload_user1_waveform': True,
    'AFG3251:upload_slot': 'user1',
    'AFG3251:upload_frequency_override': 0.0,
    'ArbFilter:user1_channel': 'AFG3251:user1_waveform',
}

_DISARMED = {
    'g_wavelet:auto_process': False,
    'burst_fixed_time:auto_process': False,
    'AFG3251:auto_upload_user1_waveform': False,
    'AFG3251:upload_slot': 'user1',
    'AFG3251:upload_frequency_override': 0.0,
    'ArbFilter:user1_channel': 'ArbFilter:waveform_sink',
}

STANDARDS = {
    HPCAT: {
        'title': 'HPCAT',
        'tooltip': 'HPCAT Standard: synthesised USER1 waveform, frequency scanning',
        'left': ['scope', 'afg', 'arb_and_filter'],
        'right': ['scan', 'repeat', 'save_data'],
        'pv_defaults': dict(_ARMED),
    },
    SBU: {
        'title': 'SBU',
        'tooltip': 'SBU Standard: fixed broadband pulse, no frequency scanning',
        'left': ['scope', 'afg', 'sbu_pulse'],
        'right': ['repeat', 'save_data'],
        'pv_defaults': dict(_DISARMED),
    },
    CUSTOM: {
        'title': 'Custom',
        'tooltip': 'Custom Standard: load your own waveform file, manual AFG control',
        'left': ['scope', 'afg', 'custom_waveform'],
        'right': ['repeat', 'save_data'],
        'pv_defaults': dict(_DISARMED),
    },
}


def normalise(name):
    '''Map a stored/fuzzy name onto a known Standard, defaulting to HPCAT.'''
    if name:
        for known in STANDARD_ORDER:
            if str(name).strip().lower() == known.lower():
                return known
    return HPCAT
