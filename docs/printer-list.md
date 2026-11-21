# Printers we know about

[← Back to the start](../README.md) · [Your printer](printer.md)

Food Labeler talks to label printers directly, in the printer's own
language. Most cheap 4-inch label printers speak the same one (called TSPL),
so many of them should work. But we have only **tested two kinds on paper**.

- **Tested** means we have printed real labels on one.
- **Alpha — not tested yet** means it should work from what the maker
  publishes (its driver and guide), but nobody has tried it with Food
  Labeler yet. In the app its name has *(alpha — not tested yet)* after it,
  and the first time you print to it, Food Labeler says so once.

Printers that aren't on this list at all also count as alpha. If yours works
(or doesn't), please tell us:
[open an issue on GitHub](https://github.com/lilfade/food-labeler/issues/new/choose)
(*Add my printer* or *My printer isn't working*). It's free to make an
account; or email hello@highthymekitchen.com if you're stuck.

## Tested

| Printer | How Food Labeler talks to it | Tested on paper | Notes |
|---|---|---|---|
| LP610BT-type label printers (Labelnize, Flexyva, Polono LP610BT and others) | TSPL | **yes** | 203 dpi, 4 in (104 mm) wide. |
| Zebra ZP450 | ZPL | **yes** | 203 dpi, 4.09 in (104 mm) wide. |

## Alpha (not tested yet)

| Printer | How Food Labeler talks to it | Tested on paper | Notes |
|---|---|---|---|
| Other Zebra printers (GK420d and others) | ZPL | no | Recognised by the name *Zebra* / *ZDesigner*. |
| MUNBYN ITPP941, RW941B, ITPP942 | TSPL | no | 203 dpi, 108 mm. USB ids from MUNBYN's own installer. [1] [2] |
| MUNBYN ITPP941P, RW941BP | TSPL | no | 300 dpi. On Linux it may show as the 203 dpi model: choose *Sharp (300 dpi)* in *My printers*. [1] [3] |
| MUNBYN ITPP130, RW130B | TSPL | no | 203 dpi. Print width not confirmed. [4] |
| MUNBYN ITPP941AP (Wi-Fi) | through the maker's driver | no | MUNBYN lists it as "OPL", not TSPL. On Windows, Food Labeler prints through MUNBYN's driver; on Linux it can't print to it yet. [1] |
| Rollo (X1038, USB) | TSPL | no | 203 dpi. [5] [6] |
| iDPRT SP410, SP420 and HPRT SL42, SL41, N41 | TSPL | no | 203 dpi, 108 mm. iDPRT and HPRT are the same company. [7] [8] [9] |
| Polono PL60 | TSPL | no | 203 dpi, 108 mm. Its driver calls it an HPRT N41. [10] |
| Polono / Nelko PL70e-BT | TSPL | no | 203 dpi, 104 mm. Polono and Nelko ship the same driver. [11] |
| Phomemo PM-241, PM-241-BT, PM-246S (also sold by OMEZIZY) | TSPL | no | 203 dpi. ASprink and Itari seem to sell the same printer, but we couldn't confirm it. [12] [13] |
| Jadens JD-168, JD-268BT, JD-468 and Beeprt BY-426, BY-482 | TSPL | no | 203 dpi. Jadens printers are made by Beeprt. [14] [15] |
| Xprinter XP-420B, XP-460B, XP-470B | TSPL | no | 203 dpi, 108 mm. [16] [17] [18] |
| Arkscan 2054A | TSPL | no | 203 dpi, 108 mm. Sold as 4BARCODE 4B-2054A too. [19] |

Many of these are the same printer sold under different names, so a
printer with another name on the box may still be matched as one of these.

## What we couldn't confirm

- USB ids for the Rollo, Polono PL60, PL70e-BT, Arkscan 2054A, HPRT models,
  MUNBYN ITPP941P and Phomemo PM-241 (non-Bluetooth) and PM-246S. They are
  recognised by name (Windows) or by their IEEE 1284 id (Linux) instead.
- Which of MUNBYN's four USB ids belongs to which MUNBYN model.
- Whether ASprink and Itari printers are the Phomemo PM-241 (they use the
  same app and model names).
- The MUNBYN RW401AP's language, and anything about OMEZIZY and ASprink
  USB ids.
- Steps for setting up a new roll by hand on the MUNBYN ITPP130 and ITPP941AP
  and the PL70e-BT (their guides don't give them).

## Sources

1. MUNBYN ITPP941 series (languages, 203 dpi, 108 mm): https://pos.munbyn.com/munbyn-itpp941-series-thermal-label-printer — MUNBYN macOS driver 1.6.6 (USB ids, TSPL filter, FAQ with the feed-button steps): https://munbyn.biz/941bmac
2. MUNBYN Windows install guide: https://munbyn.com/blogs/tips-and-tricks/how-to-install-munbyn-printer-driver-on-windows — same hardware as Beeprt/Rollo: https://forum.manjaro.org/t/munbyn-itpp941-stopped-no-available-printer/114284
3. MUNBYN 941P (300 dpi): https://munbyn.com/products/bluetooth-thermal-label-printer-p941b — Windows id: https://treexy.com/products/driver-fusion/database/printers/munbyn/itpp941p/
4. MUNBYN ITPP130 macOS driver 1.6.1 (USB id 5958:0130, TSPL filter): https://munbyn.biz/130bmac — https://munbyn.com/products/bluetooth-thermal-label-printer-p130b
5. Rollo open-source CUPS driver 1.8.4 (TSPL, 1284 id, 203 dpi): https://www.rollo.com/driver-linux/
6. Rollo USB user guide (paper width, setting up labels): https://rollo-main.b-cdn.net/wp-content/uploads/2022/09/Rollo-USB-User-Guide.pdf
7. iDPRT SP410 / SP420 (TSPL, 203 dpi, 108 mm): https://www.idprt.com/Products/4-Inch-Thermal-Label-Printer.html and https://www.idprt.com/data/downloads
8. USB id 20d1:7008 (iDPRT SP420): https://linux-hardware.org/?id=usb:20d1-7008
9. HPRT SL42 (TSPL, 108 mm) and its user guide: https://hprt.com/Product/Label-Printers/SL42.html — https://download.hprt.com/hprt/download/product_down_file/file/777/classify/43.html
10. Polono PL60 manual and Linux driver: https://cdn.shopify.com/s/files/1/0595/9739/0033/files/PL60-Digital-manual.pdf?v=1650614917 — https://cdn.shopify.com/s/files/1/0595/9739/0033/files/polono_pl60_label_printer_linux_driver_v1.2.0.tar.gz?v=1650613974 — Windows id: https://outbyte.com/drivers/printers/polono/polono-pl60/
11. Polono PL70e-BT Linux driver and manual: https://cdn.shopify.com/s/files/1/0595/9739/0033/files/POLONO_PL70e-BT_Linux_driver_file-amd64_v1.0_60530238-7c93-40d2-98e1-8a46d4be746a.deb?v=1688110283 — https://cdn.shopify.com/s/files/1/0595/9739/0033/files/PL70e-BT_Manaul_POLONO_EN_v1.0_77a47528-316b-4f34-80a8-4f70d4fb615f.pdf?v=1688110255
12. Labelife / Phomemo Linux driver (TSPL, PM-241 and PM-246S): https://oss.qu-in.ltd/Labelife/Label_Printer_Driver_Linux.zip — OMEZIZY driver page: https://omezizy.com/pages/driver-download-page
13. PM-241-BT USB id 2e3c:5750 and TSPL over USB: https://github.com/transcriptionstream/phomymo/issues/10 — PM-246S quick start guide: https://m.media-amazon.com/images/I/B1REB5JGJtL.pdf
14. Jadens Linux driver (TSPL) and JD-268BT manual: https://cdn.shopify.com/s/files/1/0574/8742/5675/files/jadens-printer-driver_linux_3.3.6.506.deb?v=1779691150 — https://cdn.shopify.com/s/files/1/0574/8742/5675/files/JD-268BT_User_Manual_English.pdf?v=1753157314
15. USB id 09c6:0426: https://github.com/moneypro/jadens_thermal_printer_linux — https://linux-hardware.org/?id=usb:09c6-0426 — Beeprt drivers: https://www.beeprt.com/download/all.html
16. Xprinter XP-420B (languages, 203 dpi, 108 mm): https://www.xprintertech.com/xp-420b-thermal-label-printer.html
17. XP-420B USB id 2d37:83d7 and 1284 id, raw TSPL working: https://github.com/RunTheWall/tspl-cups-driver/issues/4 — XP-460B USB id 2d37:4296: https://gist.github.com/dreamcat4/8a74f6b5151a321fcac076c68dd6aed7
18. XP-420B user manual (setting up labels): https://web-dev.skynet.com.my/assets/printers/420b/User_Manual_XP_420B.pdf
19. Arkscan 2054A (languages, 203 dpi, 108 mm), Linux driver with the 1284 id, and calibration: https://www.arkscan.com/product/shipping-label-printer/shipping-label-printer/2054a-thermal-shipping-label-printer — https://www.arkscan.com/images/products/2054A/Arkscan_2054A_Linux_Driver — https://arkscan.com/1-hand-calibration

For helpers: the entries are in `food_labeler/known_printers.json`
(format in [printer-definitions.md](printer-definitions.md)).
