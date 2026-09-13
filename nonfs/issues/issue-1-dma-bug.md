**Title:** Stream never starts (`failed to start stream: -11`) on hosts with the IOMMU enabled

---

This is awesome, thank you for doing this! I've installed and tested this on a
Babyface Pro (2015, not FS), and found a small fix required for this to work on
modern desktops that use an IOMMU for DMA.

The card probes and registers fine, but no stream ever starts. Every attempt
fails in `babyface_stream_work()` with `-EAGAIN`, and anything that retries —
PipeWire, in my case — fills the log:

```
usb 3-5.1.2: failed to start stream: -11
usb 3-5.1.2: failed to start stream: -11
... roughly 86 times a second, indefinitely
```

The buffers are allocated with `usb_alloc_coherent()` and their DMA addresses
kept in `chip->dma_in[]` / `chip->dma_out[]`, but the URBs go out without
`transfer_dma` or `URB_NO_TRANSFER_DMA_MAP` ever being set. So
`usb_hcd_map_urb_for_dma()` calls `dma_map_single()` on a buffer that's already
a coherent allocation.

That works by accident when the allocation happens to be contiguous lowmem,
which I assume is the case on your machine. With the IOMMU translating, it can
be a vmap instead, and then the mapping just fails:

```
iommu: Default domain type: Translated
AMD-Vi: ...   (28 iommu groups)
```

This is the default on current AMD and Intel desktops, so I think it'd hit most
people who try the driver.

Setting the mapping explicitly fixes it:

```diff
--- a/sound/usb/babyfacepro/babyfacepro.c
+++ b/sound/usb/babyfacepro/babyfacepro.c
@@ -838,6 +838,20 @@ void babyface_stream_work(struct work_struct *work)
 					 usb_sndintpipe(chip->dev, BF_EP_OUT),
 					 chip->buf_out[i], urbsize,
 					 babyface_complete_out, chip, 1);
+			/* The buffers come from usb_alloc_coherent(), so
+			 * they are already mapped: hand the HCD the
+			 * mapping instead of letting it map them again.
+			 * Without this usb_hcd_map_urb_for_dma() calls
+			 * dma_map_single() on a coherent allocation, which
+			 * fails with -EAGAIN wherever that allocation is a
+			 * vmap (any IOMMU-translated host).
+			 */
+			chip->urbs_in[i]->transfer_dma = chip->dma_in[i];
+			chip->urbs_in[i]->transfer_flags |=
+				URB_NO_TRANSFER_DMA_MAP;
+			chip->urbs_out[i]->transfer_dma = chip->dma_out[i];
+			chip->urbs_out[i]->transfer_flags |=
+				URB_NO_TRANSFER_DMA_MAP;
 		}
 		for (i = 0; i < chip->nurbs; i++) {
 			ret = usb_submit_urb(chip->urbs_in[i], GFP_KERNEL);
```

With that applied the stream starts first time and a full-duplex `arecord` +
`aplay` pair at 48 kHz S32_LE runs clean, nothing in the log.

Tested on CachyOS, kernel 7.2.4-1-cachyos, x86_64, AMD, clang build, driver
from `tools/kernel/` at `bff0263`.

Separate issue to follow with some measurements from the non-FS unit — short
version is that it works unmodified, same IDs, same descriptors.
