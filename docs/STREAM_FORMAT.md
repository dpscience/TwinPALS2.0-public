# TwinPALS analog event stream 6

Current development format only. Explicit little endian, no C++ ABI layout and
no old-format adapter. Completed files end `.tpstream`; active/interrupted files
end `.tpstream.part`. Only complete CRC-verified event pairs are analysed.

## Header and framing

The header is `TPSTRM06` (8 bytes), uint32 JSON length, then UTF-8 JSON (maximum
64 MiB). It includes version 6, source role, run/stream IDs, the frozen M1 profile
(version 8), canonical settings SHA-256, runtime material names, detector front
points/axes, `pmt_snapshot` and two immutable `analog_response` records. These
contain order/tau, charge, gain, operating HV, polarity, effective load, voltage
scale, timing conventions and calibration conditions. Exact optics reruns still
require the corresponding catalogue; this is not a second material database.
The required `physics` object records `include_cherenkov` (boolean) and
`minimum_energy_keV` (finite, nonnegative). It must agree with the saved setup. The required `light_components` dictionary
uses consecutive uint8 IDs and records volume, readable label and material.

Frames have a 4-byte tag, uint32 payload length, uint32 CRC32(payload), then the
payload (maximum 16 MiB). Each event is `APLS`, `PROV`, then `EVNT`.
IDs start at zero and increase by one. A partial trailing frame/pair contributes
no event. CRC corruption is an error, never silently skipped.

## Photoelectrons and complete analytic pulse

`APLS`: `<QII>` = event ID, PE count A, PE count B; then A's rows followed by B's.
The physical array contains four float64 values per row:

1. Accepted optical-photon arrival time, ns relative to gamma emission.
2. PMT kernel onset, ns in the same reference (calibrated transit plus independent
   per-photoelectron TTS already applied).
3. Local cathode X, mm.
4. Local cathode Y, mm.

After **all** physical rows (A then B), a second array stores two uint8 values
per PE in the same order: mechanism (1 scintillation, 2 Cherenkov) and birth
component ID. Frame length is `16 + 34 * (countA + countB)`. Secondary optical
re-emission inherits the original production label. Readers verify labels,
component IDs, Cherenkov enablement and agreement with the detector mask.

Coordinates originate as float32 mm; their exact stored values are used on
reload. They lie in the active surface, centred on the tube axis. The row count
must equal the detector's QE count, and the mean raw arrival must agree with
its optical mean. Onsets/positions stay in corresponding PE order. The current
is the signed sum of unit-area Erlang kernels times eG; voltage is current times
the stored effective resistive load. This specifies the complete infinite-tail
analog pulse without storing digitizer samples or truncating a physical tail.
Numerical plotting/acquisition support uses a declared 1e-12 tail-charge bound.

## Ordered transport ancestry

`PROV` contains `<QIIII>`: event ID, node count, PE count A, PE count B,
process-dictionary byte count; then that UTF-8 JSON string array, the nodes,
and A's then B's uint32 PE references. Nodes are one-based; parent zero is the
root. Each reference corresponds to the same row in `APLS`. The header's
`light_components` dictionary also identifies all transport volumes, including
each configured shielding instance separately.

Each node is 128 bytes: six uint32 values (parent node, track ID, parent track ID,
primary slot, component before and after the step), int32 PDG, uint32 process
index, followed by twelve float64 values (time ns, position xyz mm, kinetic energy
before/after keV, direction before xyz and after xyz). Parent IDs must precede
children. Readers check lengths, finite values, counts, IDs and dictionary bounds.

Track births and non-optical steps are retained without an angular cut. Repeated
component visits and branches remain distinct. A new optical photon's reference
is frozen at birth, so subsequent scattering cannot change its preceding history.
Optical steps that produce descendants are recorded as relay nodes; this includes
optical absorption followed by secondary scintillation in the configured Geant4
physics. Production mechanism and birth component remain separate `APLS` labels.
For Co-60, both role streams carry the shared tree and their own projected PE
references. Preview path decimation never changes this ancestry.

The complete tree is written once per event on disk. Live histogram updates use
the compact summaries and photoelectron arrays without serializing the tree into
the browser. M2 copies referenced transport records into its own stream for M3.

## Compact event summary

`EVNT` is 324 bytes, without padding:

| Field | Encoding |
| --- | --- |
| Event ID | uint64 |
| Primary mask | uint32 |
| Source position | 3 float64, mm |
| Primary directions | 9 float64, three xyz vectors |
| Primary emission offsets | 3 float64, all zero ns |
| Detector A | 96 bytes |
| Detector B | 96 bytes |

Prefix struct `<QI15d` (132 bytes); detector `<IQ7dQI2d` (96 bytes):
flags:uint32, QE count:uint64, energy:float64 keV, optical mean:float64 ns,
first gamma interaction xyz:3float64 mm, interaction time:float64 ns,
mean accepted optical track length:float64 mm, reflection count:uint64,
gamma reentries:uint32, analog minimum/maximum:2float64 mV (including baseline
zero). The absolute pulse height is max(-minimum, maximum).

Flags: bit 0 mean-valid; bit 1 interaction-valid; bit 2 deposited energy >= the
saved `minimum_energy_keV`; bit 3 non-optical entry into this crystal; bits 4/5
accepted scintillation/Cherenkov PE present. These two bits give none (0),
scintillation (1), Cherenkov (2), mixed (3), after shifting by 4. A mixed response
counts once per detector, not once per component. Bits 6/7 independently record
scintillation/Cherenkov photons **created inside this crystal**, before transport
or QE. They use the same 0/1/2/3 coding after shifting by 6. Window and coupling
production never sets these crystal bits. Undetected crystal light does set them.
These flags support the distinct Crystal and Anode histogram populations. Readers
verify bit 2 against the actual deposited energy. Absent quantities are zero with
their validity bit unset, never NaN. The optical mean includes gamma flight,
scintillation timing and optical transport, **before PMT transit/TTS**.
Interaction depth projects the earliest gamma-interaction position from the
front plane along the crystal axis; it is not a gamma path length. Reflections
cover tracked optical photons of the primary ancestry, not only accepted ones.

Both detector records are always present, including scattering between them or
zero response in either. One primary event is counted once: any interaction or
positive energy in either crystal wins; otherwise entry is pass-through; else
miss. A Na-22 annihilation pair is one event. Streams partition primary ancestry,
never detector channel. Slots/masks: Na 1275 slot 0/mask 1; Na 511 pair slots 1/2,
opposite directions, mask 6; Co 1173/1332 slots 0/1, mask 3, matched in both files.
Co detector data are projected onto their named primary, not duplicated totals.

The energy threshold selects each detector response separately, for all primary
types. Below-threshold responses are omitted from histograms, cathode maps,
persistence, per-event optical plots and M2 pulse generation. Equality passes;
zero accepts every response, including window-only light with no crystal deposit.
Raw `APLS`/`EVNT` data, physical outcome counters, source-clock events and Co-60
cascade identities remain intact. This is not a particle tracking cutoff.

## Preview, completion and analysis

`TRAK` retains bounded preview geometry and event onsets for I(t). This sampled
preview is not the full PE library. Its `energy_accepted` pair describes A/B
eligibility before a live event is committed to the analysis buffer. Preview
PE labels retain correspondence with arrival/onset arrays. `cherenkov_births`
stores at most 64 accepted-PE birth positions per detector for display; these
positions do not define the full origin statistics.
`DONE` contains status, verified event count and per-detector observed absolute
maximum mV, plus `eligible_maximum_mV` for responses passing the energy threshold.
`pulse_origin_counts` contains a 2×4 table (A/B; none/scintillation/Cherenkov/mixed),
independent of energy filtering. `eligible_response_counts` supplies energy-
eligible pulses for M2 bounds. Cherenkov birth-component counts are reconstructed
from complete PE labels. M2 headroom uses the eligible maximum. Completed output is fsynced and
atomically renamed. Cancelled/failed complete prefixes remain `.part` files.

Readers reject mixed run/settings identities, duplicate stream IDs, unknown
roles, nonfinite/invalid analog records and inconsistent summary counts/extrema.
Both Co projections may have different complete-prefix lengths during a live
run. Windows shared file handles permit the final rename while analysis reads.

Live analysis receives packed summaries plus local-hit batches directly from
the worker. It never tails the output for plotting. Summary RAM is approximately
324 MB per million events. Hit positions use bounded RAM and a private spill
file per detector/role. Cached 2D histograms update from new hits only; a bin
change reuses exact positions. Imported files are scanned once, rebuilding the
same summary/hit cache. M2 memory-maps APLS offsets for pulse superposition.

Optical-origin filters intersect detector, primary, response and energy selections.
Crystal outcome counts remain independent. A window-only Cherenkov response can
coexist with a crystal miss and is eligible when the minimum energy is zero.

TwinPALS 2.0 · © 2026 Danny Petschke · twinpals@proton.me. Scientific basis · Dominik Boras (2024), Universität Würzburg. [Dissertation](https://doi.org/10.25972/OPUS-37663)
