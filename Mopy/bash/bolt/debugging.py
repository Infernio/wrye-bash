# -*- coding: utf-8 -*-
#
# GPL License and Copyright Notice ============================================
#  This file is part of Wrye Bash.
#
#  Wrye Bash is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  Wrye Bash is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Wrye Bash; if not, write to the Free Software Foundation,
#  Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
#  Wrye Bash copyright (C) 2005-2009 Wrye, 2010-2019 Wrye Bash Team
#  https://github.com/wrye-bash
#
# =============================================================================
"""Contains methods and classes related to debugging. Used to isolate depring
from the rest of bolt."""
import StringIO
import inspect
import traceback

from .paths import GPath, Path

def deprint(*args,**keyargs):
    """Prints message along with file and line location."""
    if not deprintOn and not keyargs.get('on'): return

    if keyargs.get('trace', True):
        stack = inspect.stack()
        file_, line, function = stack[1][1:4]
        msg = u'%s %4d %s: ' % (GPath(file_).tail.s, line, function)
    else:
        msg = u''

    try:
        msg += u' '.join([u'%s'%x for x in args]) # OK, even with unicode args
    except UnicodeError:
        # If the args failed to convert to unicode for some reason
        # we still want the message displayed any way we can
        for x in args:
            try:
                msg += u' %s' % x
            except UnicodeError:
                msg += u' %s' % repr(x)

    if keyargs.get('traceback',False):
        o = StringIO.StringIO()
        traceback.print_exc(file=o)
        value = o.getvalue()
        try:
            msg += u'\n%s' % unicode(value, 'utf-8')
        except UnicodeError:
            traceback.print_exc()
            msg += u'\n%s' % repr(value)
        o.close()
    try:
        # Should work if stdout/stderr is going to wxPython output
        print msg
    except UnicodeError:
        # Nope, it's going somewhere else
        print msg.encode(Path.sys_fs_enc)

deprintOn = False

class tempDebugMode(object):
    __slots__= '_old'
    def __init__(self):
        global deprintOn
        self._old = deprintOn
        deprintOn = True

    def __enter__(self): return self
    def __exit__(self, exc_type, exc_value, exc_traceback):
        global deprintOn
        deprintOn = self._old
