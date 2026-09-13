# Capturing the gain writes on Windows

Goal: find out what TotalMix actually sends when you change mic gain, since it
resolves 1 dB and the Linux driver only reaches 21 values about 3 dB apart.

Everything here happens on Windows. The analysis happens back on Linux.

## 1. Install USBPcap

From https://desktop.ostechnix.com/usbpcap or the USBPcap project page. It
installs a driver, so it wants a reboot. Wireshark is not required; the
command line tool writes the file on its own.

## 2. Plug the Babyface in and open TotalMix

Make sure it is in proprietary mode, the one RME's driver uses, not class
compliant. Leave it on the same input you measured, input 1.

Close anything else that talks to the device, so the capture contains as
little unrelated traffic as possible.

## 3. Start the capture

Run `USBPcapCMD.exe`. It lists the USB root hubs with the devices on each.
Pick the hub the Babyface is on, by number, and give it an output file:

    USBPcapCMD.exe -d \\.\USBPcap1 -o C:\Users\<you>\bbf-gain.pcap

Leave it running. Files grow quickly, so do not leave it capturing while you
find things in the UI; get everything ready first.

## 4. Move the gain, slowly and deliberately

In TotalMix, open input 1's settings panel so the Gain field is visible. If
you can click the number and type a value, do that, it makes the capture far
easier to read. Otherwise drag slowly.

Speed does not matter. **Pauses do.** Leave two to three seconds at each
value, so the writes separate cleanly in time and each one can be matched to
a known gain.

Sequence:

    0, 1, 2, 3, 4, 5        the small steps: does every 1 dB write something?
    10, 20, 30, 40          the middle of the range
    50, 60, 65              the top, where the Linux control runs out
    0                       back to the start

The first block is the important one. If every 1 dB produces a write with a
different value, the encoding is finer than 21 steps and we will see it
directly.

Touch nothing else. No faders, no PAD, no phantom, no output changes. Every
other click adds traffic that has to be filtered out later.

## 5. Stop and write down what you did

Ctrl-C the capture. Then, in a text file next to the pcap, note the exact
sequence of values you set and roughly when, for example "0 at start, then
1,2,3,4,5, then 10,20,30,40,50,60,65, then 0". If you deviated from the list
above, write down what you actually did rather than what was planned.

## 6. Bring both files back to Linux

The pcap and the note. The repo's `tools/usbdump` has the parsers used for
the original reverse engineering, so the analysis happens where that already
works.

## What we are looking for

Control transfers with `bRequest 0x1a`. The Linux driver writes gain there at
`wIndex 0x0000 + mic`, with the value in the low 5 bits, which is what limits
it to 21 steps. The questions are whether TotalMix writes more than 21
distinct values to that index, whether it uses more than 5 bits of the value,
or whether it writes a different index entirely.

Any of those answers tells us what to patch.
