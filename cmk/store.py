#!/usr/bin/env python
# -*- encoding: utf-8; py-indent-offset: 4 -*-
# +------------------------------------------------------------------+
# |             ____ _               _        __  __ _  __           |
# |            / ___| |__   ___  ___| | __   |  \/  | |/ /           |
# |           | |   | '_ \ / _ \/ __| |/ /   | |\/| | ' /            |
# |           | |___| | | |  __/ (__|   <    | |  | | . \            |
# |            \____|_| |_|\___|\___|_|\_\___|_|  |_|_|\_\           |
# |                                                                  |
# | Copyright Mathias Kettner 2014             mk@mathias-kettner.de |
# +------------------------------------------------------------------+
#
# This file is part of Check_MK.
# The official homepage is at http://mathias-kettner.de/check_mk.
#
# check_mk is free software;  you can redistribute it and/or modify it
# under the  terms of the  GNU General Public License  as published by
# the Free Software Foundation in version 2.  check_mk is  distributed
# in the hope that it will be useful, but WITHOUT ANY WARRANTY;  with-
# out even the implied warranty of  MERCHANTABILITY  or  FITNESS FOR A
# PARTICULAR PURPOSE. See the  GNU General Public License for more de-
# tails. You should have  received  a copy of the  GNU  General Public
# License along with GNU Make; see the file  COPYING.  If  not,  write
# to the Free Software Foundation, Inc., 51 Franklin St,  Fifth Floor,
# Boston, MA 02110-1301 USA.
"""This module cares about Check_MK's file storage accessing. Most important
functionality is the locked file opening realized with the File() context
manager."""

import ast
import fcntl
import os
import pathlib2 as pathlib
import pprint
import tempfile
import time

from cmk.exceptions import MKGeneralException, MKTimeout
from cmk.i18n import _

# TODO: Make all methods handle paths the same way. e.g. mkdir() and makedirs()
# care about encoding a path to UTF-8. The others don't to that.

#.
#.
#   .--Directories---------------------------------------------------------.
#   |           ____  _               _             _                      |
#   |          |  _ \(_)_ __ ___  ___| |_ ___  _ __(_) ___  ___            |
#   |          | | | | | '__/ _ \/ __| __/ _ \| '__| |/ _ \/ __|           |
#   |          | |_| | | | |  __/ (__| || (_) | |  | |  __/\__ \           |
#   |          |____/|_|_|  \___|\___|\__\___/|_|  |_|\___||___/           |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   | Some small wrappers around the python standard directory handling    |
#   | functions.                                                           |
#   '----------------------------------------------------------------------'


def mkdir(path, mode=0770):
    pathlib.Path(path).mkdir(mode=mode, exist_ok=True)


def makedirs(path, mode=0770):
    pathlib.Path(path).mkdir(mode=mode, exist_ok=True, parents=True)


#.
#   .--.mk Configs---------------------------------------------------------.
#   |                     _       ____             __ _                    |
#   |           _ __ ___ | | __  / ___|___  _ __  / _(_) __ _ ___          |
#   |          | '_ ` _ \| |/ / | |   / _ \| '_ \| |_| |/ _` / __|         |
#   |         _| | | | | |   <  | |__| (_) | | | |  _| | (_| \__ \         |
#   |        (_)_| |_| |_|_|\_\  \____\___/|_| |_|_| |_|\__, |___/         |
#   |                                                   |___/              |
#   +----------------------------------------------------------------------+
#   | Loading and saving of .mk configuration files                        |
#   '----------------------------------------------------------------------'

# TODO: These functions could handle paths unicode > str conversion. This would make
#       the using code again shorter in some cases. It would not have to care about
#       encoding anymore.


# This function generalizes reading from a .mk configuration file. It is basically meant to
# generalize the exception handling for all file IO. This function handles all those files
# that are read with execfile().
def load_mk_file(path, default=None, lock=False):
    if default == None:
        raise MKGeneralException(
            _("You need to provide a config dictionary to merge with the "
              "read configuration. The dictionary should have all expected "
              "keys and their default values set."))

    if lock:
        aquire_lock(path)

    try:
        try:
            execfile(path, globals(), default)
            return default
        except IOError, e:
            if e.errno == 2:  # IOError: [Errno 2] No such file or directory
                return default
            else:
                raise

    except MKTimeout:
        raise
    except Exception, e:
        # TODO: How to handle debug mode or logging?
        raise MKGeneralException(_("Cannot read configuration file \"%s\": %s") % (path, e))


# A simple wrapper for cases where you only have to read a single value from a .mk file.
def load_from_mk_file(path, key, default, **kwargs):
    return load_mk_file(path, {key: default}, **kwargs)[key]


def save_mk_file(path, mk_content):
    content = "# Written by Check_MK store (%s)\n\n" % \
              time.strftime("%Y-%m-%d %H:%M:%S")
    content += mk_content
    content += "\n"
    save_file(path, content)


# Handle .mk files that are only holding a python data structure and often
# directly read via file/open and then parsed using eval.
# TODO: Consolidate with load_mk_file?
def load_data_from_file(path, default=None, lock=False):
    if lock:
        aquire_lock(path)

    try:
        try:
            content = file(path).read().strip()
            if not content:
                # May be created empty during locking
                return default

            return ast.literal_eval(content)
        except IOError, e:
            if e.errno == 2:  # IOError: [Errno 2] No such file or directory
                return default

            raise

    except MKTimeout:
        raise
    except Exception, e:
        if lock:
            release_lock(path)

        # TODO: How to handle debug mode or logging?
        raise MKGeneralException(_("Cannot read file \"%s\": %s") % (path, e))


# A simple wrapper for cases where you want to store a python data
# structure that is then read by load_data_from_file() again
def save_data_to_file(path, data, pretty=True):
    if pretty:
        try:
            formated_data = pprint.pformat(data)
        except UnicodeDecodeError:
            # When writing a dict with unicode keys and normal strings with garbled
            # umlaut encoding pprint.pformat() fails with UnicodeDecodeError().
            # example:
            #   pprint.pformat({'Z\xc3\xa4ug': 'on',  'Z\xe4ug': 'on', u'Z\xc3\xa4ugx': 'on'})
            # Catch the exception and use repr() instead
            formated_data = repr(data)
    else:
        formated_data = repr(data)

    save_file(path, "%s\n" % formated_data)


# Saving assumes a locked destination file (usually done by loading code)
# Then the new file is written to a temporary file and moved to the target path
def save_file(path, content, mode=0660):
    tmp_path = None
    try:
        # Normally the file is already locked (when data has been loaded before with lock=True),
        # but lock it just to be sure we have the lock on the file.
        #
        # Please note that this already creates the file with 0 bytes (in case it is missing).
        aquire_lock(path)

        with tempfile.NamedTemporaryFile(
                "w", dir=os.path.dirname(path), prefix=".%s.new" % os.path.basename(path),
                delete=False) as tmp:
            tmp_path = tmp.name
            os.chmod(tmp_path, mode)
            tmp.write(content)

            # The goal of the fsync would be to ensure that there is a consistent file after a
            # crash. Without the fsync it may happen that the file renamed below is just an empty
            # file. That may lead into unexpected situations during loading.
            #
            # Don't do a fsync here because this may run into IO performance issues. Even when
            # we can specify the fsync on a fd, the disk cache may be flushed completely because
            # the disk does not know anything about fds, only about blocks.
            #
            # For Check_MK 1.4 we can not introduce a good solution for this, because the changes
            # would affect too many parts of Check_MK with possible new issues. For the moment we
            # stick with the IO behaviour of previous Check_MK versions.
            #
            # In the future we'll find a solution to deal better with OS crash recovery situations.
            # for example like this:
            #
            # TODO(lm): The consistency of the file will can be ensured using copies of the
            # original file which are made before replacing it with the new one. After first
            # successful loading of the just written fille the possibly existing copies of this
            # file are deleted.
            # We can archieve this by calling os.link() before the os.rename() below. Then we need
            # to define in which situations we want to check out the backup file(s) and in which
            # cases we can savely delete them.
            #tmp.flush()
            #os.fsync(tmp.fileno())

        os.rename(tmp_path, path)

    except MKTimeout:
        raise
    except Exception, e:
        # In case an exception happens during saving cleanup the tempfile created for writing
        try:
            if tmp_path:
                os.unlink(tmp_path)
        except IOError, e:
            if e.errno == 2:  # No such file or directory
                pass
            else:
                raise

        # TODO: How to handle debug mode or logging?
        raise MKGeneralException(_("Cannot write configuration file \"%s\": %s") % (path, e))

    finally:
        release_lock(path)


# A simple wrapper for cases where you only have to write a single value to a .mk file.
def save_to_mk_file(path, key, value, pprint_value=False):
    format_func = pprint.pformat if pprint_value else repr

    if isinstance(value, dict):
        formated = "%s.update(%s)" % (key, format_func(value))
    else:
        formated = "%s += %s" % (key, format_func(value))

    save_mk_file(path, formated)


#.
#   .--File locking--------------------------------------------------------.
#   |          _____ _ _        _            _    _                        |
#   |         |  ___(_) | ___  | | ___   ___| | _(_)_ __   __ _            |
#   |         | |_  | | |/ _ \ | |/ _ \ / __| |/ / | '_ \ / _` |           |
#   |         |  _| | | |  __/ | | (_) | (__|   <| | | | | (_| |           |
#   |         |_|   |_|_|\___| |_|\___/ \___|_|\_\_|_| |_|\__, |           |
#   |                                                     |___/            |
#   +----------------------------------------------------------------------+
#   | Helper functions to lock files (between processes) for disk IO       |
#   | Currently only exclusive locks are implemented and they always will  |
#   | wait forever.                                                        |
#   '----------------------------------------------------------------------'

g_aquired_locks = []
g_locked_paths = []


def aquire_lock(path, blocking=True):
    if path in g_locked_paths:
        return True  # No recursive locking

    # Create file (and base dir) for locking if not existant yet
    if not os.path.exists(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path), mode=0770)

    fd = os.open(path, os.O_RDONLY | os.O_CREAT, 0660)

    # Handle the case where the file has been renamed in the meantime
    while True:
        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB

        fcntl.flock(fd, flags)
        fd_new = os.open(path, os.O_RDONLY | os.O_CREAT, 0660)
        if os.path.sameopenfile(fd, fd_new):
            os.close(fd_new)
            break
        else:
            os.close(fd)
            fd = fd_new

    g_aquired_locks.append((path, fd))
    g_locked_paths.append(path)


def try_aquire_lock(path):
    try:
        aquire_lock(path, blocking=False)
        return True
    except IOError, e:
        if e.errno == 11:  # Resource temporarily unavailable
            return False
        else:
            raise


def release_lock(path):
    if path not in g_locked_paths:
        return  # no unlocking needed

    for lock_path, fd in g_aquired_locks:
        if lock_path != path:
            continue

        try:
            os.close(fd)
        except OSError as e:
            if e.errno == 9:  # OSError: [Errno 9] Bad file descriptor
                pass
            else:
                raise

        g_aquired_locks.remove((lock_path, fd))
        break

    g_locked_paths.remove(path)


def have_lock(path):
    return path in g_locked_paths


def release_all_locks():
    global g_aquired_locks, g_locked_paths

    for path, _unused_fd in g_aquired_locks:
        release_lock(path)

    g_aquired_locks = []
    g_locked_paths = []


# Experimental but not used yet.
## Simple class to offer locked file access via flock for cross process locking
#class LockedOpen(object):
#    def __init__(self, path, *args, **kwargs):
#        self._path        = path
#        self._open_args   = args
#        self._open_kwargs = kwargs
#        self._file_obj    = None
#
#
#    def __enter__(self):
#        # If not existant, create the file that the open can not fail in
#        # read mode and the lock is possible
#        if not os.path.exists(self._path):
#            file(self._path, "a+")
#
#        f = file(self._path, *self._open_args, **self._open_kwargs)
#
#       # Handle the case where the file has been renamed while waiting
#        while True:
#            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
#            fnew = file(self._path, *self._open_args, **self._open_kwargs)
#            if os.path.sameopenfile(f.fileno(), fnew.fileno()):
#                fnew.close()
#                break
#            else:
#                f.close()
#                f = fnew
#
#        self._file_obj = f
#        self._file_obj.__enter__()
#        return self
#
#
#    def __exit__(self, _exc_type, _exc_value, _traceback):
#        result = self._file_obj.__exit__(_exc_type, _exc_value, _traceback)
#        return result
#
#
#    def __getattr__(self, name):
#        return getattr(self._file_obj, name)
#
#
## This class offers locked file opening. Read operations are made on the
## locked file. All write operation go to a temporary file which replaces
## the locked file while closing the object.
#class LockedOpenWithTempfile(LockedOpen):
#    def __init__(self, name, mode):
#        super(LockedOpenWithTempfile, self).__init__(name, "r")
#        self._new_file_obj = None
#        self._new_file_mode = mode
#
#
#    def __enter__(self):
#        super(LockedOpenWithTempfile, self).__enter__()
#        self._new_file_obj = tempfile.NamedTemporaryFile(self._new_file_mode,
#                                dir=os.path.dirname(self._path),
#                                prefix=os.path.basename(self._path)+"_tmp",
#                                delete=False)
#        self._new_file_obj.__enter__()
#        return self
#
#
#    def write(self, txt):
#        self._new_file_obj.write(txt)
#
#
#    def writelines(self, seq):
#        self._new_file_obj.writelines(seq)
#
#
#    def __exit__(self, _exc_type, _exc_value, _traceback):
#        self._new_file_obj.__exit__(_exc_type, _exc_value, _traceback)
#        os.rename(self._new_file_obj.name, self._path)
#        return super(LockedOpenWithTempfile, self).__exit__(_exc_type, _exc_value, _traceback)
#
#
#open = LockedOpenWithTempfile
