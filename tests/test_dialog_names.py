"""Windows must not reuse tkinter's own method names.

A window class that defines, say, ``_setup`` replaces the method tkinter
itself calls while creating the window, and the window then fails to open.
The other tests never open windows, so this checks the names instead.
"""
import inspect
import tkinter as tk

from food_labeler import bakery_dialogs, dialogs, font_dialogs, picture_dialogs, widgets

TK_NAMES = {name for cls in tk.Toplevel.__mro__ if cls is not object
            for name in vars(cls)}


def _window_classes():
    for mod in (dialogs, bakery_dialogs, font_dialogs, picture_dialogs, widgets):
        for _name, cls in inspect.getmembers(mod, inspect.isclass):
            if issubclass(cls, tk.Toplevel) and cls.__module__ == mod.__name__:
                yield cls


def test_no_window_replaces_a_tkinter_method():
    clashes = []
    for cls in _window_classes():
        for name in vars(cls):
            if name in TK_NAMES and not (name.startswith("__") and name.endswith("__")) \
                    and name not in ("destroy",):
                clashes.append(f"{cls.__name__}.{name}")
    assert not clashes, clashes


def test_there_are_windows_to_check():
    assert len(list(_window_classes())) >= 10
