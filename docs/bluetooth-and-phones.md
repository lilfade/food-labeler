# Bluetooth printing and phones: research notes

Status: written November 2026 as research. **Desktop Bluetooth (part A)
was built in 1.5.0**: Linux prints over an RFCOMM socket and Windows over the
Bluetooth COM port, as recommended below. It is **not tested on paper yet**,
so Bluetooth printers are marked alpha (see
[Bluetooth printers](printer.md#bluetooth-printers-alpha) and
[ARCHITECTURE](ARCHITECTURE.md#bluetooth-alpha)). macOS was left out. The
phone part (B) is still research only.

## Summary

- **Our LP610BT-type printers speak Classic Bluetooth (SPP).** A passive scan found
  both units advertising the Serial Port Profile (UUID `0x1101`) with the RFCOMM
  protocol and a "printer" device class. Over SPP the printer receives exactly
  the same TSPL bytes we already send over USB, so the desktop app does not need
  a new printer language, only a new way to deliver the bytes. The units also
  advertise one BLE-style service (`0xFEE7`), so they may be dual-mode. That still
  has to be confirmed by connecting to them.
- **Desktop Bluetooth is cheap to add.** On Windows, a paired SPP printer shows
  up as a COM port, and the maker's driver can be installed on that port so it
  becomes an ordinary spooler printer. Our existing `windows_raw` method then
  works without changes. On Linux, Python's standard library can open RFCOMM
  sockets directly, so no new dependency is needed. macOS needs `pyserial` on the
  `/dev/cu.*` port that pairing creates.
- **Phones are where it gets hard.** iPhones cannot use Classic Bluetooth printers
  unless the printer is Apple MFi-certified, and these printers are not. That
  leaves BLE only, and only if the BLE side of these printers accepts print data,
  which we do not know yet. No iPhone browser supports Web Bluetooth (Bluefy is
  the exception). On Android, Chrome can reach Classic SPP through Web Serial and
  BLE through Web Bluetooth, so a web page can work there.
- **The Zebra ZP450 has no Bluetooth.** It stays USB only, so it is out of scope
  for phones.

## Recommendation

1. **Now (about 1 week), built in 1.5.0 (Linux and Windows; untested on
   paper):** add a `bluetooth` transport to the desktop app. On
   Linux use an RFCOMM socket. On macOS, and on Windows when no driver is
   installed, use a serial port. Document "install the driver on the Bluetooth
   COM port" for Windows. This is low risk, reuses every byte we already
   generate, and reaches the most bakers, since most of them already print from a
   laptop.
2. **Next, only if bakers ask for it (3 to 6 weeks):** an *Android-first* web app
   on the GitHub Pages site that prints over Web Serial (Classic SPP) or Web
   Bluetooth. It needs a TypeScript port of the layout, bitmap and TSPL code. The
   rule and printer JSON files can be reused as they are.
3. **Later or never: iPhone.** It is only possible over BLE, and only after we
   prove the printers accept TSPL over BLE GATT. Even then it needs a native app
   ($99 a year, App Store review). It is not worth starting until step 2 has users
   and the BLE question is answered on real hardware.

## What the scan on the development laptop showed

These were read-only commands: `bluetoothctl show/devices`, `hciconfig -a`,
`rfkill list`, and a 15-second passive `scan on`. Nothing was paired or
connected.

- Adapter: MediaTek, Bluetooth 5.4, powered, not soft-blocked, with both
  central and peripheral roles. It is usable for testing.
- Label printers seen:

| Name | Address | Class | Advertised UUIDs |
|---|---|---|---|
| `LP610BT` | `89:8F:10:xx:xx:xx` | `0x040680` (Imaging / Printer, "Rendering" service) | 1101 (SPP), 0003 (RFCOMM), 0001 (SDP), 0100 (L2CAP), 1200 (PnP), 1800, 180D, 180F, FEE7 |
| `LP610BT` | `D5:1F:77:xx:xx:xx` | same | same |

- RSSI was about -82 dBm, which is weak but in range. Both units use the same
  name, so the app must tell them apart by address. This is the same problem we
  have on USB, where identical clones share a serial number.
- The Epson `ET-4810 Series` was also visible. It is not a label printer. The
  Zebra was not seen, as expected.
- Reading the result: a device class is only reported over Classic (BR/EDR)
  inquiry, and the extended inquiry response lists SPP and RFCOMM, so **Classic
  SPP is confirmed as advertised**. `180D` (heart rate) and `180F` (battery) look
  like leftovers from a generic module firmware template. `FEE7` is a vendor
  service, common on Chinese BLE modules, that often carries a serial-style
  write/notify pair. Whether print data is accepted there is **unknown**.

## A. Bluetooth from the desktop app

### How cheap label printers use Bluetooth

| Style | How data goes | Examples | Notes |
|---|---|---|---|
| Classic SPP / RFCOMM | A plain byte stream, carrying the same TSPL, ZPL or ESC/POS as USB | LP610BT/Polono 4B family (our scan), most LabeLife-family printers, Zebra mobile printers | Needs pairing, sometimes with PIN 0000 or 1234. Reliable and fast enough. Not available on iPhone. |
| BLE GATT "serial" | The same command language, written in chunks to a vendor write characteristic (often `FF02` under service `FF00`, or the ISSC/Microchip `49535343-…` service) | Phomemo M110 (`0xFF02`, 128-byte chunks), Marklife (`0xFF02` write, `0xFF03` flow-control credits, 90-byte chunks) | Writes are limited to MTU-3 bytes, which is 20 by default and up to 244–512 after negotiation. Without flow control, cheap printers drop data on big bitmaps. |
| Proprietary packet protocol | Framed packets with checksums, sent over BLE | Niimbot (`55 55 … AA AA` frames), Dymo LetraTag, Fichero | These are app-locked but documented by open-source projects (niimblue/niimbluelib, niimprint, thermal-label/letratag). None of them are TSPL. |

The LP610BT family has no public SDK or published UUIDs that we could find. The
open-source `thermal-label/labelife` driver covers about 95 similar Aimo/Quyin
OEM TSPL printers over "BT SPP", BLE, TCP and USB, and notes that "most labelife
printers are classic-Bluetooth". It does not list the LP610BT, but it is the
closest reference.

### Python options

| OS | Classic SPP | BLE |
|---|---|---|
| Linux | `socket.socket(AF_BLUETOOTH, SOCK_STREAM, BTPROTO_RFCOMM)` from the standard library, or `/dev/rfcommN` (opening it matches our existing `device` method, since `device_path_ok` accepts `/dev/rfcomm0`). Pairing is done with BlueZ / `bluetoothctl`. | `bleak` (talks to BlueZ over D-Bus) |
| Windows | After pairing, Windows creates an outgoing COM port. Either install the maker's driver on it (then our `windows_raw` method works unchanged) or write to the port with `pyserial`. Python 3.9+ also has `AF_BLUETOOTH` RFCOMM sockets on Windows. | `bleak` (WinRT backend) |
| macOS | Pairing creates `/dev/cu.<name>`, which we write with `pyserial`. The standard library has no RFCOMM sockets on macOS. | `bleak` (CoreBluetooth). Needs a Bluetooth usage string in the app bundle. |

Packaging (PyInstaller): an RFCOMM socket needs nothing new. `pyserial` is pure
Python and small. `bleak` pulls in the `winrt-*` packages on Windows and
`pyobjc` on macOS. Recent `pyinstaller-hooks-contrib` versions handle it, but
check a frozen build with `--debug=imports`. BLE is also async, so it needs its
own thread with an asyncio loop, kept off the Tk thread. Start with Classic
only. Add `bleak` only if a printer we support turns out to be BLE-only.

### Transport design that fits `food_labeler/printers.py`

As built in 1.5.0 this is mostly what happened, with a few changes: the
connect timeout is 8 seconds; channels 1, 2 and 3 are tried in turn when
none is known, and the one that worked is remembered; the Windows COM port is
written with the standard library (no `pyserial`); Windows discovery reads
the Bluetooth COM ports from Plug and Play (`BTHENUM`) entries; and macOS is
not supported.

The module already dispatches on `cfg["method"]` (`windows_raw`, `windows_driver`,
`cups`, `device`, `network`) to a small `send_*(target, data)` function with an
injectable opener or connector for tests. A Bluetooth method fits the same
pattern:

- `method="bluetooth"`, `target="AA:BB:CC:DD:EE:FF"` or `"AA:BB:…:FF/1"` (with
  the RFCOMM channel), `id="bt:<address>"`. The address is stable, so it works
  as the per-printer settings id and tells identical units apart.
- `send_bluetooth(target, data, connect=_rfcomm_connect)`: connect with a
  5-second timeout, `sendall` in about 4 KB writes, wait briefly for an optional
  reply, then close. This mirrors `send_network`. Errors map to the existing
  plain-English `PrinterError` messages ("Is it switched on and paired?").
- `method="serial"`, `target="COM5"` or `"/dev/cu.LP610BT"`, for macOS and for
  Windows without a driver, using `pyserial` with an injectable opener.
- Discovery: on Linux, list *paired* devices only (from `bluetoothctl devices
  Paired` or BlueZ D-Bus) whose name matches `known_printers.json` patterns. On
  Windows, Bluetooth COM ports show up through the existing spooler discovery
  once a driver is installed. Pairing stays in the OS, and the app never pairs.
- `status()`: report "ready (Bluetooth)" without connecting, the same way the
  network method does, because opening an RFCOMM link just to check wakes the
  printer.
- A later BLE method: `method="ble"`, with `target` holding the address and the
  characteristic UUID, writing in MTU-3 chunks with write-without-response and
  a small delay, or credits if the printer offers a notify characteristic.

### Test plan

Without hardware (CI):
- Unit-test `send_bluetooth` and `send_serial` with fake connectors and openers,
  the same way `send_network` is tested. Assert that the bytes reaching the fake
  are byte-for-byte the existing TSPL job. Also cover timeout, refused and
  partial-write paths and their user messages.
- Golden byte streams: keep a recorded `.bin` TSPL job (`FOOD_LABELER_DRY_RUN`
  already writes these) and check that the Bluetooth path delivers it unchanged.
- For BLE later, use a fake GATT client that records each chunk. Assert that no
  chunk is larger than MTU-3 and that joining the chunks gives the job back.

With hardware (manual, on the laptop or the Pi 4 at the house; the Pi has
onboard Bluetooth and BlueZ):
1. `bluetoothctl` → `scan on`, `pair <addr>` (PIN 0000 or 1234 if asked),
   `trust <addr>`. These are one-time steps, done by a person.
2. Find the SPP channel with `sdptool browse <addr>` (or `bluetoothctl info`),
   which is usually channel 1.
3. Send a tiny job from Python with an RFCOMM socket:
   `SIZE 50 mm,30 mm` / `GAP 2 mm,0` / `CLS` / `TEXT 20,20,"3",0,1,1,"BT OK"` /
   `PRINT 1`. Then send a full rendered label from `FOOD_LABELER_DRY_RUN` output
   to check throughput on large bitmaps.
4. BLE probe: use `bleak` to list services and characteristics on `FEE7` and any
   `FF00` service, write the same tiny job in 20-byte chunks to a writable
   characteristic, and see whether it prints. This one experiment decides
   whether iPhone support is possible at all.
5. Windows: pair, install the maker's driver on the new outgoing COM port, and
   print with the existing `windows_raw` method.

## B. Phones

### Browsers (a PWA on GitHub Pages)

| Browser | Web Bluetooth (BLE GATT) | Web Serial (incl. Classic SPP) | WebUSB |
|---|---|---|---|
| Chrome / Edge desktop (Windows, macOS, ChromeOS) | Yes | Yes, with SPP over RFCOMM since Chrome 117, for paired devices | Yes |
| Chrome desktop Linux | Behind a flag | Yes | Yes |
| Chrome Android | Yes (Android 6+) | Bluetooth RFCOMM since about Chrome 137. Wired serial is arriving with Android 17. | Yes (USB OTG). The printer must not be claimed by another driver. |
| Safari / any iOS browser | No (all iOS browsers use WebKit) | No | No |
| Bluefy on iOS (third-party browser) | Yes, BLE only | No | No |
| Firefox | No | No | No |

GitHub Pages is HTTPS, which these APIs need. What a web app could reach:
- LP610BT on Android Chrome over Web Serial SPP. This is likely to work, since
  the scan shows SPP, and it reuses our TSPL as is.
- LP610BT on Android or desktop over USB with WebUSB. Possible, but desktop
  operating systems often claim the printer class, so it is less reliable.
- LP610BT on iPhone only through Bluefy, and only if the BLE side prints
  (unknown).
- Zebra ZP450 over USB only, which means WebUSB on desktop or Android OTG.

### What can be reused

- **As is:** `cottage_rules.json`, `known_printers.json`, `starter_ingredients.json`,
  and the stock and label definitions. These are plain JSON.
- **Needs a port:** layout and text fitting (`render.py`, `lettering.py`, the
  layout parts of `model.py`), 1-bit conversion and dithering, the QR code, and
  the TSPL (`tspl.py`, about 130 lines) and ZPL (`zpl.py`, about 100 lines)
  builders. The builders are small. Layout is the real work, because fonts must
  measure the same in the browser canvas as in Pillow.
- **Pyodide** could run the Python code as it is. It costs a 10+ MB download and
  slow start on phones, and Tk does not exist there, so the UI would still be
  new. It is a fallback, not a plan.

### Native options for Android and iPhone

| Option | BLE | Classic SPP on Android | USB OTG on Android | iPhone | Reuse | Rough effort |
|---|---|---|---|---|---|---|
| PWA only (Web Serial + Web Bluetooth) | Android, desktop | Yes (Chrome) | WebUSB | Bluefy only | TS port of render and TSPL | 3–6 weeks |
| Capacitor (wrap the PWA) + `@capacitor-community/bluetooth-le` + a community serial or SPP plugin | Yes | With a plugin | With a plugin | BLE only | Same web code | PWA + 1–2 weeks |
| Flutter (`flutter_blue_plus`, Classic plugins Android-only) | Yes | Yes (third-party plugins, maintenance varies) | `usb_serial` | BLE only | Dart rewrite of render and TSPL | 6–10 weeks |
| React Native (`react-native-ble-plx`, `react-native-bluetooth-classic`) | Yes | Yes | With a library | BLE only (Classic needs MFi) | JS/TS port, could be shared with the PWA | 5–8 weeks |
| Kivy / BeeWare (Python) | Plugins are thin. Android via pyjnius. | Android via pyjnius `BluetoothSocket` | Possible | Weak. iOS builds are hard. | Python rendering reused | 4–8 weeks, high risk |

For iPhone, Classic Bluetooth accessories need Apple's MFi program and the
External Accessory framework, and the printer has to be certified. Cheap label
printers are not, so on iPhone it is **BLE or nothing**.

Stores and sideloading:
- **Google Play:** a one-time $25 fee. New personal accounts must run a closed
  test with at least 12 testers for 14 days before going to production. There is
  also a Data safety form and a privacy policy.
- **Android developer verification:** this started on 30 September 2026 in
  Brazil, Indonesia, Singapore and Thailand, and goes global in 2027. Apps from
  unregistered developers can no longer be installed on certified devices there.
  There is an advanced "install unverified" flow and ADB, plus a free tier for
  sharing with up to 20 devices. Plan on registering in the Android Developer
  Console even for APKs shared from GitHub.
- **Apple:** $99 a year, App Review, and privacy "nutrition" labels. A thin web
  wrapper risks rejection under the minimum-functionality rule. Sideloading is
  not realistic for bakers (EU alternative marketplaces aside).

### Phone recommendation

The simplest path that reaches most bakers' phones is an **Android-first PWA on
the existing site**. It prints over Web Serial SPP to the printers they already
own, needs no store and no fees, and can later be wrapped with Capacitor if
store presence matters. iPhone needs a native BLE app and a printer whose BLE
side accepts print data, and neither exists today. Run the BLE probe (test plan,
step 4) before anyone promises iPhone support. Do the desktop Bluetooth transport
first: it is small, it can be tested, and the phone work can build on it.

## Sources

- Chrome: Serial over Bluetooth on the web (Chrome 117, SPP UUID) — https://developer.chrome.com/blog/serial-over-bluetooth
- Intent to Ship: Web Serial over Bluetooth on Android — https://groups.google.com/a/chromium.org/g/blink-dev/c/BqUGCcurReE
- Intent to Ship: Web Serial API on Android (wired, Android 17) — https://groups.google.com/a/chromium.org/g/blink-dev/c/HBJ-uYFvkpM
- Web Bluetooth implementation status — https://github.com/WebBluetoothCG/web-bluetooth/blob/main/implementation-status.md
- Chrome: Communicating with Bluetooth devices over JavaScript — https://developer.chrome.com/articles/bluetooth/
- Bluefy – Web BLE Browser (App Store) — https://apps.apple.com/app/id1492822055
- thermal-label/labelife (TSPL over SPP/BLE/TCP/USB, ~95 OEM printers) — https://github.com/thermal-label/labelife
- thermal-label WebBluetoothTransport (MTU-sized chunks, write-without-response) — https://thermal-label.github.io/transport/api/web/classes/WebBluetoothTransport
- Marklife Label Printer Web Kit (FF02 write, FF03 credits, 90-byte chunks) — https://unpkg.com/marklife-label-printer-web-kit@1.1.4/README.md
- pyphomemo (Phomemo M110 over BLE 0xFF02) — https://awesome.ecosyste.ms/projects/github.com%2Fmkuhlmann%2Fpyphomemo
- NiimBlue / niimbluelib (Niimbot protocol) — https://unpkg.com/@mmote/niimbluelib@0.0.1-alpha.38/README.md
- Reverse engineering the Fichero label printer protocol (Hackaday) — https://hackaday.com/2026/03/09/reverse-engineering-the-bluetooth-fichero-thermal-label-printer-protocol
- DYMO LetraTag BT protocol — https://thermal-label.github.io/letratag/protocol/letratag-bt
- Zebra Bluetooth LE app note — https://www.zebra.com/content/dam/support-dam/en/documentation/unrestricted/application-notes/AppNote-BlueToothLE-v4.pdf
- CPython bpo-36590: Bluetooth RFCOMM on Windows — https://mail.python.org/pipermail/new-bugs-announce/2019-April/035386.html
- Microsoft: Bluetooth and socket (Winsock RFCOMM) — https://learn.microsoft.com/en-us/windows/win32/bluetooth/bluetooth-and-socket
- bleak Windows backend — https://github.com/hbldh/bleak/blob/e285de5876c5b31bcb265668cc32ac054598211d/docs/backends/windows.rst
- PyInstaller hidden imports — https://pyinstaller.org/en/stable/feature-notes.html
- Labelnize app (App Store) — https://apps.apple.com/us/app/labelnize/id6450258039
- Google Play testing requirements for new personal accounts — https://support.google.com/googleplay/android-developer/answer/14151465
- Android developer verification — https://developer.android.com/developer-verification and https://android-developers.googleblog.com/2026/03/android-developer-verification.html
