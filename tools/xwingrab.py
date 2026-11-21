"""Save one X window's contents as a PNG (works on Xwayland, where grabbing the
whole screen is refused). Usage: python tools/xwingrab.py <window-id> <out.png>
"""
import ctypes, ctypes.util, sys
from PIL import Image
X = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11"))
class XImage(ctypes.Structure):
    _fields_ = [("width", ctypes.c_int), ("height", ctypes.c_int), ("xoffset", ctypes.c_int),
                ("format", ctypes.c_int), ("data", ctypes.c_void_p), ("byte_order", ctypes.c_int),
                ("bitmap_unit", ctypes.c_int), ("bitmap_bit_order", ctypes.c_int),
                ("bitmap_pad", ctypes.c_int), ("depth", ctypes.c_int), ("bytes_per_line", ctypes.c_int),
                ("bits_per_pixel", ctypes.c_int)]
class XWA(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("pad", ctypes.c_char * 256)]
X.XOpenDisplay.restype = ctypes.c_void_p
X.XGetImage.restype = ctypes.POINTER(XImage)
X.XGetImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                        ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
X.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XWA)]
d = X.XOpenDisplay(None)
win = int(sys.argv[1], 0)
a = XWA(); X.XGetWindowAttributes(d, win, ctypes.byref(a))
im = X.XGetImage(d, win, 0, 0, a.width, a.height, 0xFFFFFFFF, 2).contents
buf = ctypes.string_at(im.data, im.bytes_per_line * im.height)
Image.frombuffer("RGB", (im.width, im.height), buf, "raw", "BGRX", im.bytes_per_line, 1).save(sys.argv[2])
print("saved", sys.argv[2], im.width, im.height)
