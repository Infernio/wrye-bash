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
"""Contains useful collections and methods related to them."""
import collections
from itertools import chain

class CIstr(unicode):
    """See: http://stackoverflow.com/q/43122096/281545"""
    __slots__ = ()

    #--Hash/Compare
    def __hash__(self):
        return hash(self.lower())
    def __eq__(self, other):
        if isinstance(other, CIstr):
            return self.lower() == other.lower()
        return NotImplemented
    def __ne__(self, other):
        if isinstance(other, CIstr):
            return self.lower() != other.lower()
        return NotImplemented
    def __lt__(self, other):
        if isinstance(other, CIstr):
            return self.lower() < other.lower()
        return NotImplemented
    def __ge__(self, other):
        if isinstance(other, CIstr):
            return self.lower() >= other.lower()
        return NotImplemented
    def __gt__(self, other):
        if isinstance(other, CIstr):
            return self.lower() > other.lower()
        return NotImplemented
    def __le__(self, other):
        if isinstance(other, CIstr):
            return self.lower() <= other.lower()
        return NotImplemented
    #--repr
    def __repr__(self):
        return '{0}({1})'.format(type(self).__name__,
                                 super(CIstr, self).__repr__())

def _ci_str(maybe_str):
    """dict keys can be any hashable object - only call CIstr if str"""
    return CIstr(maybe_str) if isinstance(maybe_str, basestring) else maybe_str

class LowerDict(dict):
    """Dictionary that transforms its keys to CIstr instances.
    See: https://stackoverflow.com/a/43457369/281545
    """
    __slots__ = () # no __dict__ - that would be redundant

    @staticmethod # because this doesn't make sense as a global function.
    def _process_args(mapping=(), **kwargs):
        if hasattr(mapping, 'iteritems'):
            mapping = getattr(mapping, 'iteritems')()
        return ((_ci_str(k), v) for k, v in
                chain(mapping, getattr(kwargs, 'iteritems')()))

    def __init__(self, mapping=(), **kwargs):
        # dicts take a mapping or iterable as their optional first argument
        super(LowerDict, self).__init__(self._process_args(mapping, **kwargs))

    def __getitem__(self, k):
        return super(LowerDict, self).__getitem__(_ci_str(k))

    def __setitem__(self, k, v):
        return super(LowerDict, self).__setitem__(_ci_str(k), v)

    def __delitem__(self, k):
        return super(LowerDict, self).__delitem__(_ci_str(k))

    def copy(self): # don't delegate w/ super - dict.copy() -> dict :(
        return type(self)(self)

    def get(self, k, default=None):
        return super(LowerDict, self).get(_ci_str(k), default)

    def setdefault(self, k, default=None):
        return super(LowerDict, self).setdefault(_ci_str(k), default)

    __no_default = object()
    def pop(self, k, v=__no_default):
        if v is LowerDict.__no_default:
            # super will raise KeyError if no default and key does not exist
            return super(LowerDict, self).pop(_ci_str(k))
        return super(LowerDict, self).pop(_ci_str(k), v)

    def update(self, mapping=(), **kwargs):
        super(LowerDict, self).update(self._process_args(mapping, **kwargs))

    def __contains__(self, k):
        return super(LowerDict, self).__contains__(_ci_str(k))

    @classmethod
    def fromkeys(cls, keys, v=None):
        return super(LowerDict, cls).fromkeys((_ci_str(k) for k in keys), v)

    def __repr__(self):
        return '{0}({1})'.format(type(self).__name__,
                                 super(LowerDict, self).__repr__())

class DefaultLowerDict(LowerDict, collections.defaultdict):
    """LowerDict that inherits from defaultdict."""
    __slots__ = () # no __dict__ - that would be redundant

    def __init__(self, default_factory=None, mapping=(), **kwargs):
        # note we can't use LowerDict __init__ directly
        super(LowerDict, self).__init__(default_factory,
                                        self._process_args(mapping, **kwargs))

    def copy(self):
        return type(self)(self.default_factory, self)

    def __repr__(self):
        return '{0}({1},{2})'.format(type(self).__name__, self.default_factory,
            super(collections.defaultdict, self).__repr__())
