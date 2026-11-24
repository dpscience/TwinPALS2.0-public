# Module 2 pulse-stream contract

Current format only; no old-format adapter. `.tpm2` contains the editable Module 2
profile (version 4) and the digitizer ID. `.tpdigitizer` exchanges individual
digitizers; `data/catalogue.tpdb` is shared with Module 1.

## Binary `.tppulses`

Little endian. File starts with 8-byte `TPPULS06`, uint32 JSON-header byte length,
then UTF-8 JSON. Header limit 16 MiB. Header includes format/version, run/stream
IDs, isotope, timestamp, class filter, settings SHA-256, actual Module 2 profile,
resolved digitizer snapshot (including generated cell-model parameters), immutable M1 analog response
snapshots and both M1 input identities. Referenced M1 photoelectron arrays and
their ordered transport ancestry are copied once per source record into `TRTH`
frames. Unused input records are not copied.
This permits reanalysis when current database entries change.

Each frame has 4-byte tag, uint32 payload length, uint32 payload CRC32. Limit
32 MiB. `WAVE` payload: uint32 metadata length, UTF-8 metadata, then four arrays
of N float32 values in order timeA(ns), voltageA(mV), timeB(ns), voltageB(mV).
Metadata includes waveform ID, exclusive class and flags, acquisition/trigger
absolute times, trigger cell, baseline/clipping flags, and every retained
analogue contribution's channel, primary role, decay/transport record IDs,
onset/source time, lifetime/component, amplitude and `light_origin`
(`scintillation`, `cherenkov`, or `mixed`). The same required origin is present
in timeline contributions. Both input snapshots use TPSTRM06. Pulse metadata refers back to the original M1 event; gain/TTS are not redrawn.
Each waveform also retains its end/busy times, accepted trigger channel and a
bounded absolute-time context (at most 256 surrounding analogue contributions,
exact known total, interval and `known_until_ns` horizon). This includes already
generated contributions during dead time for the reloaded timeline. Bounded
source generation can leave later dead-time context unknown; the plot marks
that horizon rather than implying there are no future contributions.
Display decimation never changes the complete in-window
origin list or waveform samples. Zero-response decays produce no pulse stem.

`TRTH` precedes the first `WAVE` that uses that source record. Payload starts with
`<IQI>`: source role index (0/1 in the input list), uint64 transport-record ID,
uint32 APLS payload length. The original APLS payload and original PROV payload
follow. Frame CRC and both embedded payloads are checked. Class-split files each
retain their own complete referenced truth; they do not depend on another file.

Each analogue contribution retains its unique M2 `decay` ID and its original
M1 role/record ID. Reusing an M1 record for shuffled Na-22 combinations creates
different M2 decay identities. Co-60 cascades stay matched. `origin_ns` maps stored
photoelectron onset to the waveform axis: `onset_in_waveform = onset_M1 + origin_ns`.
Thus overlapping contributions, their mixed optical origins and their individual
scattering paths remain recoverable even after the original M1 files are removed.
M3 must find pulses and CF times from the waveform alone, then associate the
selected interval with this truth. Ambiguous pile-up retains all contributors;
it must not be assigned a fabricated unique parent.

`DONE` contains status, record count and summary, including generated source
decays, source capacity, saved-pair count, stop reason and simulated exposure.
The run stops at `waveform_pairs` saved triggered pairs or source exhaustion;
`maximum` exhausts the unique combinations instead of using a pair target.
Acquisition rate divides saved pairs by exposure including the final busy cycle.
The display unit for dead time is separate from its stored physical `dead_ns`.
Completed streams are fsynced
and atomically renamed from `.tppulses.part`. Cancelled/failed outputs retain
`.part`; only complete CRC-valid records are read. Increasing finite time axes,
metadata types, class filters, counts, identity and settings hash are checked.
New acquisitions write one flagged stream containing every saved waveform pair with its original ID and class. Legacy settings requesting separate class files now produce the combined stream. Module 2 can still import existing disjoint class files, checks for duplicate records and restores acquisition order with a bounded merge. Module 3 opens one file per pass.

## Analysis and workflow

Generation updates in-memory features/counts directly. Import scans in background
and reconstructs the same features; full waveforms remain seekable by offset.
The index retains bounded-size features, not every sample array. The combined
Simulation & Analysis view shows baseline-subtracted pulse height and absolute
area using the saved axes. The older fixed class overview is no longer displayed;
its metadata is retained for inspection, not used as M3 lifetime classification.
Bins, stream import, HTML export, frozen settings and acquisition counts live in
this same view. Empty-state analysis controls are disabled.

For A AND B the displayed coincidence gate starts at the actual first accepted
threshold crossing and extends forward by the configured width. The second
crossing produces the common trigger. Both actual channel crossings and that
common trigger are shown on the waveform and absolute timeline. The common delay
is measured from the trigger to the acquisition-window end; it does not move or
extend the coincidence gate. A short pretrigger interval can omit the earlier
pulse; setup validation explains this separately from ADC clipping/polarity checks.

Simulation shows the latest generated/imported waveform plus immutable settings.
Setup remains editable. M1 and M2 jobs are independent; shared profile/database
mutations are blocked server-side while either job is active. Settings apply,
file replacement and import conflicts use application modals. Private autosave
contains both drafts/UI; `.tpprofile` is their explicit user exchange.

HTML reports embed plotted data, class counts, optical-origin metadata, settings and
source paths. They support zoom/reset and SVG/PNG/CSV/TXT export. New event cuts
or finer histograms require the original pulse files. No compatibility layer.

The reader verifies that both embedded M1 primary roles match the isotope, share run/settings identities, and contain the identical analog response used by acquisition. Changing the current database does not alter a reloaded pulse stream.

Optical origin is separate from waveform-pair classification. All eligible origins
participate in ordinary shuffling/acquisition; mixed detector pulses count once.
Input badges and HTML retain Cherenkov enablement and the crystal-energy cut from
M1, never from a subsequently edited setup.

TwinPALS 2.0 · © 2026 Danny Petschke · twinpals@proton.me. Scientific basis · Dominik Boras (2024), Universität Würzburg. [Dissertation](https://doi.org/10.25972/OPUS-37663)
