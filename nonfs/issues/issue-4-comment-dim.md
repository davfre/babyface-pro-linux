<!-- gh issue comment 4 --body-file ... -->

More on the DIM point. The button cannot start a dim, because the
driver waits on a bit that only its own write sets.

`bf_panel_tick()` watches `st[1] & 0x20` for the sticky DIM state. That
bit reads back the dim indicator flag, and the flag only changes when
something writes `0x17` wVal=`0x2000` wIdx=`0x2000`. The only writer is
`bf_dim_put()`, so a front-panel press never reaches it.

The button is momentary:

```
DIM press:   00 25 8d 40 -> 00 25 8d 60 -> 00 25 8d 40
OUT press:   00 25 8d 40 -> 00 26 8d 48 -> 00 26 8d 40
```

`st[3]` flashes, `st[1]` does not move. `Front Panel Button` decodes it
as 6. I included the OUT press to show the rest of the decode is fine,
`st[1] & 0x07` going 5 -> 6.

Two smaller things from chasing it:

- `Front Panel Button` is the only panel control not passed to
  `bf_panel_notify()`, so a press is invisible to userspace. Polling
  does not help, since the value stays put between two presses of the
  same button.

- `Dim Switch` writes an absolute `0xcb` / `0x0333` to the Phones
  master rather than attenuating what is there, so below -20 dB it
  raises the level. Probably a capture taken at unity, where the two
  are the same. Easier for you to check than me: set the master away
  from unity in TotalMix, press DIM, see what gets written.

I have DIM working here off the button press, taking AN1/2 and PH3/4
down 20 dB from wherever they are. Happy to send it, but it changes
behaviour rather than fixing an encoding, so I would rather ask first.
