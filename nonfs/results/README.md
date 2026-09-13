# Measurements

Babyface Pro (non-FS, 2015), CachyOS, kernel 7.2.4-1-cachyos, x86_64.
Taken with `../bbf-measure.py` against the merged driver.

| file | result |
|---|---|
| `2026-09-13-digital-upstream.txt` | output master law: 1.000 dB/dB, 0.00 dB spread over 36 dB |
| `2026-09-13-noise-upstream.txt` | mic gain law, 35-65 dB: 0.994 dB per dB |
| `2026-09-13-noise-top-1db.txt` | 1 dB steps, 50-65 dB, through where `coarse` saturates |
| `2026-09-13-pad-ab.txt` | PAD, A/B at a fixed operating point |
| `2026-09-13-panel-dim-bytes.txt` | front-panel DIM status bytes, with method |
| `probe-cc.txt`, `probe-pc.txt` | USB descriptors, class compliant and proprietary |

Neither of the first two needs a cable. Both take about two minutes.

`archive/` holds earlier exploratory runs, superseded by the above.
