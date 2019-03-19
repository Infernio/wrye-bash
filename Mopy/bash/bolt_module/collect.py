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
from collections import defaultdict, MutableSet
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

class DefaultLowerDict(LowerDict, defaultdict):
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
            super(defaultdict, self).__repr__())

class OrderedSet(list, MutableSet):
    """A set like object, that remembers the order items were added to it.
       Since it has order, a few list functions were added as well:
        - index(value)
        - __getitem__(index)
        - __call__ -> to enable 'enumerate'
       If an item is discarded, then later readded, it will be added
       to the end of the set.
    """
    def update(self, *args, **kwdargs):
        if kwdargs: raise TypeError("update() takes no keyword arguments")
        for s in args:
            for e in s:
                self.add(e)

    def add(self, elem):
        if elem not in self:
            self.append(elem)
    def discard(self, elem): self.pop(self.index(elem),None)
    def __or__(self,other):
        left = OrderedSet(self)
        left.update(other)
        return left
    def __repr__(self): return u'OrderedSet%s' % unicode(list(self))[1:-1]
    def __unicode__(self): return u'{%s}' % unicode(list(self))[1:-1]

class DataDict(object):
    """Mixin class that handles dictionary emulation, assuming that
    dictionary is its 'data' attribute."""

    def __contains__(self,key):
        return key in self.data
    def __getitem__(self,key):
        """Return value for key or raise KeyError if not present."""
        return self.data[key]
    def __setitem__(self,key,value):
        self.data[key] = value
    def __delitem__(self,key):
        del self.data[key]
    def __len__(self):
        return len(self.data)
    def setdefault(self,key,default):
        return self.data.setdefault(key,default)
    def keys(self):
        return self.data.keys()
    def values(self):
        return self.data.values()
    def items(self):
        return self.data.items()
    def has_key(self,key):
        return self.data.has_key(key)
    def get(self,key,default=None):
        return self.data.get(key,default)
    def pop(self,key,default=None):
        return self.data.pop(key,default)
    def iteritems(self):
        return self.data.iteritems()
    def iterkeys(self):
        return self.data.iterkeys()
    def itervalues(self):
        return self.data.itervalues()

class MemorySet(object):
    """Specialization of the OrderedSet, where it remembers the order of items
       event if they're removed.  Also, combining and comparing to other MemorySet's
       takes this into account:
        a|b -> returns union of a and b, but keeps the ordering of b where possible.
               if an item in a was also in b, but deleted, it will be added to the
               deleted location.
        a&b -> same as a|b, but only items 'not-deleted' in both a and b are marked
               as 'not-deleted'
        a^b -> same as a|b, but only items 'not-deleted' in a but not b, or b but not
               a are marked as 'not-deleted'
        a-b -> same as a|b, but any 'not-deleted' items in b are marked as deleted

        a==b -> compares the 'not-deleted' items of the MemorySets.  If both are the same,
                and in the same order, then they are equal.
        a!=b -> oposite of a==b
    """
    def __init__(self, *args, **kwdargs):
        self.items = OrderedSet(*args, **kwdargs)
        self.mask = [True] * len(self.items)

    def add(self,elem):
        if elem in self.items: self.mask[self.items.index(elem)] = True
        else:
            self.items.add(elem)
            self.mask.append(True)
    def discard(self,elem):
        if elem in self.items: self.mask[self.items.index(elem)] = False
    discarded = property(lambda self: OrderedSet([x for i, x in enumerate(self.items) if not self.mask[i]]))

    def __len__(self): return sum(self.mask)
    def __iter__(self):
        for i,elem in enumerate(self.items):
            if self.mask[i]: yield self.items[i]
    def __str__(self): return u'{%s}' % (','.join(map(repr,self._items())))
    def __repr__(self): return u'MemorySet([%s])' % (','.join(map(repr,self._items())))
    def forget(self, elem):
        # Permanently remove an item from the list.  Don't remember its order
        if elem in self.items:
            idex = self.items.index(elem)
            self.items.discard(elem)
            del self.mask[idex]

    def _items(self): return OrderedSet([x for x in self])

    def __or__(self,other):
        """Return items in self or in other"""
        discards = (self.discarded-other._items())|(other.discarded-self._items())
        right = list(other.items)
        left = list(self.items)

        for idex,elem in enumerate(left):
            # elem is already in the other one, skip
            if elem in right: continue

            # Figure out best place to put it
            if idex == 0:
                # put it in front
                right.insert(0,elem)
            elif idex == len(left)-1:
                # put in in back
                right.append(elem)
            else:
                # Find out what item it comes after
                afterIdex = idex-1
                while afterIdex > 0 and left[afterIdex] not in right:
                    afterIdex -= 1
                insertIdex = right.index(left[afterIdex])+1
                right.insert(insertIdex,elem)
        ret = MemorySet(right)
        ret.mask = [x not in discards for x in right]
        return ret
    def __and__(self,other):
        items = self.items & other.items
        discards = self.discarded | other.discarded
        ret = MemorySet(items)
        ret.mask = [x not in discards for x in items]
        return ret
    def __sub__(self,other):
        discards = self.discarded | other._items()
        ret = MemorySet(self.items)
        ret.mask = [x not in discards for x in self.items]
        return ret
    def __xor__(self,other):
        items = (self|other).items
        discards = items - (self._items()^other._items())
        ret = MemorySet(items)
        ret.mask = [x not in discards for x in items]
        return ret

    def __eq__(self,other): return list(self) == list(other)
    def __ne__(self,other): return list(self) != list(other)
