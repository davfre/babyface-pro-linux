# USBPcap captures, Babyface Pro (non-FS)

Windows, RME's own driver, TotalMix. Taken 13 Sep 2026 to decode the mic
gain encoding, on an original 2015 Babyface Pro rather than an FS.

Each capture is the Babyface alone on its own root hub: verified, every
packet in all four files is a single device address, so there is no other
USB traffic in them.

| file | what was done |
|---|---|
| `bbf-gain2.pcap` | Input 1 gain set to 0, 10, 20, 30, 40, 50, 60, 65 |
| `bbf-gain3.pcap` | the run the encoding was decoded from |
| `bbf-gain4.pcap` | Hi-Z inputs, and the 0.5 dB steps |
| `bbf-gain-finesteps.pcap` | the 0/1/2/3/4/5 fine block |

The `-notes.txt` beside each one has the timeline of what was changed
when, the vendor requests each change sends, and the decoded values.
`bbf-gain2-notes.txt` also records a pattern that looked convincing and
turned out to be a coincidence, kept because it is the reason the fine
block was captured at all.

Encoding, from `bbf-gain3`:

    coarse = min(dB / 3, 20)     bits 0-4, 3 dB per step
    fine   = dB - 3 * coarse     bits 5-7, the 0-2 dB remainder
    wValue = (fine << 5) | coarse

Above 60 dB coarse saturates at 20 and fine continues 3, 4, 5, so 65 dB
is 0xb4. 48 gain writes across the four captures, all matching.
