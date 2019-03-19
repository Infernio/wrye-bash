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

# Imports ---------------------------------------------------------------------
#--Standard
import StringIO
import cPickle
import csv
import datetime
import locale
import os
import re
import struct
import subprocess
import sys
import time
import traceback
from functools import partial
# Internal
import bass
import exception
from bolt_module.collect import DataDict, MainFunctions
from bolt_module.localization import initTranslator
from bolt_module.paths import GPath, Path
from bolt_module.output import WryeText
from bolt_module.unicode_utils import decode

# Needed for pickle backwards compatibility - these ARE used
# TODO(inf) Once we drop backwards compatibility with older settings, we could
# drop these imports too
from bolt_module.collect import CIstr, LowerDict

# structure aliases, mainly introduced to reduce uses of 'pack' and 'unpack'

struct_pack = struct.pack
struct_unpack = struct.unpack

#-- To make commands executed with Popen hidden
startupinfo = None
if os.name == u'nt':
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

# speed up os.walk
try:
    import scandir
    _walk = walkdir = scandir.walk
except ImportError:
    _walk = walkdir = os.walk
    scandir = None

def formatInteger(value):
    """Convert integer to string formatted to locale."""
    return decode(locale.format('%d', int(value), True),
                  locale.getpreferredencoding())

def formatDate(value):
    """Convert time to string formatted to to locale's default date/time."""
    try:
        local = time.localtime(value)
    except ValueError: # local time in windows can't handle negative values
        local = time.gmtime(value)
        # deprint(u'Timestamp %d failed to convert to local, using %s' % (
        #     value, local))
    return decode(time.strftime('%c', local), locale.getpreferredencoding())

def unformatDate(date, formatStr):
    """Basically a wrapper around time.strptime. Exists to get around bug in
    strptime for Japanese locale."""
    try:
        return time.strptime(date, '%c')
    except ValueError:
        if formatStr == '%c' and u'Japanese' in locale.getlocale()[0]:
            date = re.sub(u'^([0-9]{4})/([1-9])', r'\1/0\2', date, flags=re.U)
            return time.strptime(date, '%c')
        else:
            raise

def timestamp(): return datetime.datetime.now().strftime(u'%Y-%m-%d %H.%M.%S')

def round_size(kbytes):
    """Round non zero sizes to 1 KB."""
    return formatInteger(0 if kbytes == 0 else max(kbytes, 1024) / 1024) + u' KB'

# Helpers ---------------------------------------------------------------------
def sortFiles(files, __split=os.path.split):
    """Utility function. Sorts files by directory, then file name."""
    sort_keys_dict = dict((x, __split(x.lower())) for x in files)
    return sorted(files, key=sort_keys_dict.__getitem__)

#--Do translator test and set
if locale.getlocale() == (None,None):
    locale.setlocale(locale.LC_ALL,u'')
initTranslator(bass.language)

CBash = 0

# sio - StringIO wrapper so it uses the 'with' statement, so they can be used
#  in the same functions that accept files as input/output as well.  Really,
#  StringIO objects don't need to 'close' ever, since the data is unallocated
#  once the object is destroyed.
#------------------------------------------------------------------------------
class sio(StringIO.StringIO):
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_value, exc_traceback): self.close()

def clearReadOnly(dirPath):
    """Recursively (/S) clear ReadOnly flag if set - include folders (/D)."""
    cmd = ur'attrib -R "%s\*" /S /D' % dirPath.s
    subprocess.call(cmd, startupinfo=startupinfo)

# Util Constants --------------------------------------------------------------
#--Unix new lines
reUnixNewLine = re.compile(ur'(?<!\r)\n',re.U)

# Util Classes ----------------------------------------------------------------
#------------------------------------------------------------------------------
class CsvReader:
    """For reading csv files. Handles comma, semicolon and tab separated (excel) formats.
       CSV files must be encoded in UTF-8"""
    @staticmethod
    def utf_8_encoder(unicode_csv_data):
        for line in unicode_csv_data:
            yield line.encode('utf8')

    def __init__(self,path):
        self.ins = path.open('rb',encoding='utf-8-sig')
        format = ('excel','excel-tab')[u'\t' in self.ins.readline()]
        if format == 'excel':
            delimiter = (',',';')[u';' in self.ins.readline()]
            self.ins.seek(0)
            self.reader = csv.reader(CsvReader.utf_8_encoder(self.ins),format,delimiter=delimiter)
        else:
            self.ins.seek(0)
            self.reader = csv.reader(CsvReader.utf_8_encoder(self.ins),format)

    def __enter__(self): return self
    def __exit__(self, exc_type, exc_value, exc_traceback): self.ins.close()

    def __iter__(self):
        for iter in self.reader:
            yield [unicode(x,'utf8') for x in iter]

    def close(self):
        self.reader = None
        self.ins.close()

#------------------------------------------------------------------------------
class Flags(object):
    """Represents a flag field."""
    __slots__ = ['_names','_field']

    @staticmethod
    def getNames(*names):
        """Returns dictionary mapping names to indices.
        Names are either strings or (index,name) tuples.
        E.g., Flags.getNames('isQuest','isHidden',None,(4,'isDark'),(7,'hasWater'))"""
        namesDict = {}
        for index,name in enumerate(names):
            if isinstance(name,tuple):
                namesDict[name[1]] = name[0]
            elif name: #--skip if "name" is 0 or None
                namesDict[name] = index
        return namesDict

    #--Generation
    def __init__(self,value=0,names=None):
        """Initialize. Attrs, if present, is mapping of attribute names to indices. See getAttrs()"""
        object.__setattr__(self,'_field',int(value) | 0L)
        object.__setattr__(self,'_names',names or {})

    def __call__(self,newValue=None):
        """Returns a clone of self, optionally with new value."""
        if newValue is not None:
            return Flags(int(newValue) | 0L,self._names)
        else:
            return Flags(self._field,self._names)

    def __deepcopy__(self,memo={}):
        newFlags=Flags(self._field,self._names)
        memo[id(self)] = newFlags
        return newFlags

    #--As hex string
    def hex(self):
        """Returns hex string of value."""
        return u'%08X' % (self._field,)
    def dump(self):
        """Returns value for packing"""
        return self._field

    #--As int
    def __int__(self):
        """Return as integer value for saving."""
        return self._field
    def __getstate__(self):
        """Return values for pickling."""
        return self._field, self._names
    def __setstate__(self,fields):
        """Used by unpickler."""
        self._field = fields[0]
        self._names = fields[1]

    #--As list
    def __getitem__(self, index):
        """Get value by index. E.g., flags[3]"""
        return bool((self._field >> index) & 1)

    def __setitem__(self,index,value):
        """Set value by index. E.g., flags[3] = True"""
        value = ((value or 0L) and 1L) << index
        mask = 1L << index
        self._field = ((self._field & ~mask) | value)

    #--As class
    def __getattr__(self,name):
        """Get value by flag name. E.g. flags.isQuestItem"""
        try:
            names = object.__getattribute__(self,'_names')
            index = names[name]
            return (object.__getattribute__(self,'_field') >> index) & 1 == 1
        except KeyError:
            raise exception.AttributeError(name)

    def __setattr__(self,name,value):
        """Set value by flag name. E.g., flags.isQuestItem = False"""
        if name in ('_field','_names'):
            object.__setattr__(self,name,value)
        else:
            self.__setitem__(self._names[name],value)

    #--Native operations
    def __eq__( self, other):
        """Logical equals."""
        if isinstance(other,Flags):
            return self._field == other._field
        else:
            return self._field == other

    def __ne__( self, other):
        """Logical not equals."""
        if isinstance(other,Flags):
            return self._field != other._field
        else:
            return self._field != other

    def __and__(self,other):
        """Bitwise and."""
        if isinstance(other,Flags): other = other._field
        return self(self._field & other)

    def __invert__(self):
        """Bitwise inversion."""
        return self(~self._field)

    def __or__(self,other):
        """Bitwise or."""
        if isinstance(other,Flags): other = other._field
        return self(self._field | other)

    def __xor__(self,other):
        """Bitwise exclusive or."""
        if isinstance(other,Flags): other = other._field
        return self(self._field ^ other)

    def getTrueAttrs(self):
        """Returns attributes that are true."""
        trueNames = [name for name in self._names if getattr(self,name)]
        trueNames.sort(key = lambda xxx: self._names[xxx])
        return tuple(trueNames)

#--Commands Singleton
_mainFunctions = MainFunctions()
def mainfunc(func):
    """A function for adding funcs to _mainFunctions.
    Used as a function decorator ("@mainfunc")."""
    _mainFunctions.add(func)
    return func

#------------------------------------------------------------------------------
class PickleDict:
    """Dictionary saved in a pickle file.
    Note: self.vdata and self.data are not reassigned! (Useful for some clients.)"""
    def __init__(self,path,readOnly=False):
        """Initialize."""
        self.path = path
        self.backup = path.backup
        self.readOnly = readOnly
        self.vdata = {}
        self.data = {}

    def exists(self):
        return self.path.exists() or self.backup.exists()

    class Mold(Exception):
        def __init__(self, moldedFile):
            msg = (u'Your settings in %s come from an ancient Bash version. '
                   u'Please load them in 306 so they are converted '
                   u'to the newer format' % moldedFile)
            super(PickleDict.Mold, self).__init__(msg)

    def load(self):
        """Loads vdata and data from file or backup file.

        If file does not exist, or is corrupt, then reads from backup file. If
        backup file also does not exist or is corrupt, then no data is read. If
        no data is read, then self.data is cleared.

        If file exists and has a vdata header, then that will be recorded in
        self.vdata. Otherwise, self.vdata will be empty.

        Returns:
          0: No data read (files don't exist and/or are corrupt)
          1: Data read from file
          2: Data read from backup file
        """
        self.vdata.clear()
        self.data.clear()
        cor = cor_name =  None
        for path in (self.path,self.backup):
            if cor is not None:
                cor.moveTo(cor_name)
                cor = None
            if path.exists():
                try:
                    with path.open('rb') as ins:
                        try:
                            firstPickle = cPickle.load(ins)
                        except ValueError:
                            cor = path
                            cor_name = GPath(path.s + u' (%s)' % timestamp() +
                                    u'.corrupted')
                            deprint(u'Unable to load %s (moved to "%s")' % (
                                path, cor_name.tail), traceback=True)
                            continue # file corrupt - try next file
                        if firstPickle == 'VDATA2':
                            self.vdata.update(cPickle.load(ins))
                            self.data.update(cPickle.load(ins))
                        else:
                            raise PickleDict.Mold(path)
                    return 1 + (path == self.backup)
                except (EOFError, ValueError):
                    pass
        #--No files and/or files are corrupt
        return 0

    def save(self):
        """Save to pickle file.

        Three objects are writen - a version string and the vdata and data
        dictionaries, in this order. Current version string is VDATA2.
        """
        if self.readOnly: return False
        #--Pickle it
        self.vdata['boltPaths'] = True # needed so pre 307 versions don't blow
        with self.path.temp.open('wb') as out:
            for data in ('VDATA2',self.vdata,self.data):
                cPickle.dump(data,out,-1)
        self.path.untemp(doBackup=True)
        return True

# Structure wrappers ----------------------------------------------------------
def unpack_str8(ins): return ins.read(struct_unpack('B', ins.read(1))[0])
def unpack_str16(ins): return ins.read(struct_unpack('H', ins.read(2))[0])
def unpack_str32(ins): return ins.read(struct_unpack('I', ins.read(4))[0])
def unpack_int(ins): return struct_unpack('I', ins.read(4))[0]
def unpack_short(ins): return struct_unpack('H', ins.read(2))[0]
def unpack_float(ins): return struct_unpack('f', ins.read(4))[0]
def unpack_byte(ins): return struct_unpack('B', ins.read(1))[0]
def unpack_int_signed(ins): return struct_unpack('i', ins.read(4))[0]
def unpack_int64_signed(ins): return struct_unpack('q', ins.read(8))[0]
def unpack_4s(ins): return struct_unpack('4s', ins.read(4))[0]
def unpack_str16_delim(ins):
    str_value = ins.read(struct_unpack('Hc', ins.read(3))[0])
    ins.read(1) # discard delimiter
    return str_value
def unpack_int_delim(ins): return struct_unpack('Ic', ins.read(5))[0]
def unpack_byte_delim(ins): return struct_unpack('Bc', ins.read(2))[0]

def unpack_string(ins, string_len):
    return struct_unpack('%ds' % string_len, ins.read(string_len))[0]

def unpack_many(ins, fmt):
    return struct_unpack(fmt, ins.read(struct.calcsize(fmt)))

#------------------------------------------------------------------------------
class TableColumn:
    """Table accessor that presents table column as a dictionary."""
    def __init__(self,table,column):
        self.table = table
        self.column = column
    #--Dictionary Emulation
    def __iter__(self):
        """Dictionary emulation."""
        tableData = self.table.data
        column = self.column
        return (key for key in tableData.keys() if (column in tableData[key]))
    def keys(self):
        return list(self.__iter__())
    def items(self):
        """Dictionary emulation."""
        tableData = self.table.data
        column = self.column
        return [(key,tableData[key][column]) for key in self]
    def has_key(self,key):
        """Dictionary emulation."""
        return self.__contains__(key)
    def clear(self):
        """Dictionary emulation."""
        self.table.delColumn(self.column)
    def get(self,key,default=None):
        """Dictionary emulation."""
        return self.table.getItem(key,self.column,default)
    #--Overloaded
    def __contains__(self,key):
        """Dictionary emulation."""
        tableData = self.table.data
        return tableData.has_key(key) and tableData[key].has_key(self.column)
    def __getitem__(self,key):
        """Dictionary emulation."""
        return self.table.data[key][self.column]
    def __setitem__(self,key,value):
        """Dictionary emulation. Marks key as changed."""
        self.table.setItem(key,self.column,value)
    def __delitem__(self,key):
        """Dictionary emulation. Marks key as deleted."""
        self.table.delItem(key,self.column)

#------------------------------------------------------------------------------
class Table(DataDict):
    """Simple data table of rows and columns, saved in a pickle file. It is
    currently used by modInfos to represent properties associated with modfiles,
    where each modfile is a row, and each property (e.g. modified date or
    'mtime') is a column.

    The "table" is actually a dictionary of dictionaries. E.g.
        propValue = table['fileName']['propName']
    Rows are the first index ('fileName') and columns are the second index
    ('propName')."""

    def __init__(self,dictFile):
        """Initialize and read data from dictFile, if available."""
        self.dictFile = dictFile
        dictFile.load()
        self.vdata = dictFile.vdata
        self.data = dictFile.data
        self.hasChanged = False ##: move to PickleDict

    def save(self):
        """Saves to pickle file."""
        dictFile = self.dictFile
        if self.hasChanged and not dictFile.readOnly:
            self.hasChanged = not dictFile.save()

    def getItem(self,row,column,default=None):
        """Get item from row, column. Return default if row,column doesn't exist."""
        data = self.data
        if row in data and column in data[row]:
            return data[row][column]
        else:
            return default

    def getColumn(self,column):
        """Returns a data accessor for column."""
        return TableColumn(self,column)

    def setItem(self,row,column,value):
        """Set value for row, column."""
        data = self.data
        if row not in data:
            data[row] = {}
        data[row][column] = value
        self.hasChanged = True

    def setItemDefault(self,row,column,value):
        """Set value for row, column."""
        data = self.data
        if row not in data:
            data[row] = {}
        self.hasChanged = True
        return data[row].setdefault(column,value)

    def delItem(self,row,column):
        """Deletes item in row, column."""
        data = self.data
        if row in data and column in data[row]:
            del data[row][column]
            self.hasChanged = True

    def delRow(self,row):
        """Deletes row."""
        data = self.data
        if row in data:
            del data[row]
            self.hasChanged = True

    def delColumn(self,column):
        """Deletes column of data."""
        data = self.data
        for rowData in data.values():
            if column in rowData:
                del rowData[column]
                self.hasChanged = True

    def moveRow(self,oldRow,newRow):
        """Renames a row of data."""
        data = self.data
        if oldRow in data:
            data[newRow] = data[oldRow]
            del data[oldRow]
            self.hasChanged = True

    def copyRow(self,oldRow,newRow):
        """Copies a row of data."""
        data = self.data
        if oldRow in data:
            data[newRow] = data[oldRow].copy()
            self.hasChanged = True

    #--Dictionary emulation
    def __setitem__(self,key,value):
        self.data[key] = value
        self.hasChanged = True
    def __delitem__(self,key):
        del self.data[key]
        self.hasChanged = True
    def setdefault(self,key,default):
        if key not in self.data: self.hasChanged = True
        return self.data.setdefault(key,default)
    def pop(self,key,default=None):
        self.hasChanged = True
        return self.data.pop(key,default)

# Util Functions --------------------------------------------------------------
#------------------------------------------------------------------------------
def copyattrs(source,dest,attrs):
    """Copies specified attrbutes from source object to dest object."""
    for attr in attrs:
        setattr(dest,attr,getattr(source,attr))

def cstrip(inString): # TODO(ut): hunt down and deprecate - it's O(n)+
    """Convert c-string (null-terminated string) to python string."""
    zeroDex = inString.find('\x00')
    if zeroDex == -1:
        return inString
    else:
        return inString[:zeroDex]

def csvFormat(format):
    """Returns csv format for specified structure format."""
    csvFormat = u''
    for char in format:
        if char in u'bBhHiIlLqQ': csvFormat += u',%d'
        elif char in u'fd': csvFormat += u',%f'
        elif char in u's': csvFormat += u',"%s"'
    return csvFormat[1:] #--Chop leading comma

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

import inspect
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

def getMatch(reMatch,group=0):
    """Returns the match or an empty string."""
    if reMatch: return reMatch.group(group)
    else: return u''

def intArg(arg,default=None):
    """Returns argument as an integer. If argument is a string, then it converts it using int(arg,0)."""
    if arg is None: return default
    elif isinstance(arg, basestring): return int(arg,0)
    else: return int(arg)

def winNewLines(inString):
    """Converts unix newlines to windows newlines."""
    return reUnixNewLine.sub(u'\r\n',inString)

# Log/Progress ----------------------------------------------------------------
#------------------------------------------------------------------------------
class Log:
    """Log Callable. This is the abstract/null version. Useful version should
    override write functions.

    Log is divided into sections with headers. Header text is assigned (through
    setHeader), but isn't written until a message is written under it. I.e.,
    if no message are written under a given header, then the header itself is
    never written."""

    def __init__(self):
        """Initialize."""
        self.header = None
        self.prevHeader = None

    def setHeader(self,header,writeNow=False,doFooter=True):
        """Sets the header."""
        self.header = header
        if self.prevHeader:
            self.prevHeader += u'x'
        self.doFooter = doFooter
        if writeNow: self()

    def __call__(self,message=None,appendNewline=True):
        """Callable. Writes message, and if necessary, header and footer."""
        if self.header != self.prevHeader:
            if self.prevHeader and self.doFooter:
                self.writeFooter()
            if self.header:
                self.writeLogHeader(self.header)
            self.prevHeader = self.header
        if message: self.writeMessage(message,appendNewline)

    #--Abstract/null writing functions...
    def writeLogHeader(self, header):
        """Write header. Abstract/null version."""
        pass
    def writeFooter(self):
        """Write mess. Abstract/null version."""
        pass
    def writeMessage(self,message,appendNewline):
        """Write message to log. Abstract/null version."""
        pass

#------------------------------------------------------------------------------
class LogFile(Log):
    """Log that writes messages to file."""
    def __init__(self,out):
        self.out = out
        Log.__init__(self)

    def writeLogHeader(self, header):
        self.out.write(header+u'\n')

    def writeFooter(self):
        self.out.write(u'\n')

    def writeMessage(self,message,appendNewline):
        self.out.write(message)
        if appendNewline: self.out.write(u'\n')

#------------------------------------------------------------------------------
class Progress:
    """Progress Callable: Shows progress when called."""
    def __init__(self,full=1.0):
        if (1.0*full) == 0: raise exception.ArgumentError(u'Full must be non-zero!')
        self.message = u''
        self.full = 1.0 * full
        self.state = 0
        self.debug = False

    def getParent(self):
        return None

    def setFull(self,full):
        """Set's full and for convenience, returns self."""
        if (1.0*full) == 0: raise exception.ArgumentError(u'Full must be non-zero!')
        self.full = 1.0 * full
        return self

    def plus(self,increment=1):
        """Increments progress by 1."""
        self.__call__(self.state+increment)

    def __call__(self,state,message=''):
        """Update progress with current state. Progress is state/full."""
        if (1.0*self.full) == 0: raise exception.ArgumentError(u'Full must be non-zero!')
        if message: self.message = message
        if self.debug: deprint(u'%0.3f %s' % (1.0*state/self.full, self.message))
        self._do_progress(1.0 * state / self.full, self.message)
        self.state = state

    def _do_progress(self, state, message):
        """Default _do_progress does nothing."""

    # __enter__ and __exit__ for use with the 'with' statement
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_value, exc_traceback): pass

#------------------------------------------------------------------------------
class SubProgress(Progress):
    """Sub progress goes from base to ceiling."""
    def __init__(self,parent,baseFrom=0.0,baseTo='+1',full=1.0,silent=False):
        """For creating a subprogress of another progress meter.
        progress: parent (base) progress meter
        baseFrom: Base progress when this progress == 0.
        baseTo: Base progress when this progress == full
          Usually a number. But string '+1' sets it to baseFrom + 1
        full: Full meter by this progress' scale."""
        Progress.__init__(self,full)
        if baseTo == '+1': baseTo = baseFrom + 1
        if baseFrom < 0 or baseFrom >= baseTo:
            raise exception.ArgumentError(u'BaseFrom must be >= 0 and BaseTo must be > BaseFrom')
        self.parent = parent
        self.baseFrom = baseFrom
        self.scale = 1.0*(baseTo-baseFrom)
        self.silent = silent

    def __call__(self,state,message=u''):
        """Update progress with current state. Progress is state/full."""
        if self.silent: message = u''
        self.parent(self.baseFrom+self.scale*state/self.full,message)
        self.state = state

#------------------------------------------------------------------------------
def readCString(ins, file_path):
    """Read null terminated string, dropping the final null byte."""
    byte_list = []
    for b in iter(partial(ins.read, 1), ''):
        if b == '\0': break
        byte_list.append(b)
    else:
        raise exception.FileError(file_path,
                                  u'Reached end of file while expecting null')
    return ''.join(byte_list)

class StringTable(dict):
    """For reading .STRINGS, .DLSTRINGS, .ILSTRINGS files."""
    encodings = {
        # Encoding to fall back to if UTF-8 fails, based on language
        # Default is 1252 (Western European), so only list languages
        # different than that
        u'russian': 'cp1251',
        }

    def load(self, modFilePath, lang=u'English', progress=Progress()):
        baseName = modFilePath.tail.body
        baseDir = modFilePath.head.join(u'Strings')
        files = (baseName + u'_' + lang + x for x in
                 (u'.STRINGS', u'.DLSTRINGS', u'.ILSTRINGS'))
        files = (baseDir.join(file) for file in files)
        self.clear()
        progress.setFull(3)
        for i,file in enumerate(files):
            progress(i)
            self.loadFile(file,SubProgress(progress,i,i+1))

    def loadFile(self, path, progress, lang=u'english'):
        formatted = path.cext != u'.strings'
        backupEncoding = self.encodings.get(lang.lower(), 'cp1252')
        try:
            with open(path.s, 'rb') as ins:
                insSeek = ins.seek
                insTell = ins.tell

                insSeek(0,os.SEEK_END)
                eof = insTell()
                insSeek(0)
                if eof < 8:
                    deprint(u"Warning: Strings file '%s' file size (%d) is "
                            u"less than 8 bytes.  8 bytes are the minimum "
                            u"required by the expected format, assuming the "
                            u"Strings file is empty." % (path, eof))
                    return

                numIds,dataSize = unpack_many(ins, '=2I')
                progress.setFull(max(numIds,1))
                stringsStart = 8 + (numIds*8)
                if stringsStart != eof-dataSize:
                    deprint(u"Warning: Strings file '%s' dataSize element "
                            u"(%d) results in a string start location of %d, "
                            u"but the expected location is %d"
                            % (path, dataSize, eof-dataSize, stringsStart))

                id_ = -1
                offset = -1
                for x in xrange(numIds):
                    try:
                        progress(x)
                        id_,offset = unpack_many(ins, '=2I')
                        pos = insTell()
                        insSeek(stringsStart+offset)
                        if formatted:
                            value = unpack_str32(ins) # TODO(ut): unpack_str32_null
                            # seems needed, strings are null terminated
                            value = cstrip(value)
                        else:
                            value = readCString(ins, path) #drops the null byte
                        try:
                            value = unicode(value,'utf-8')
                        except UnicodeDecodeError:
                            value = unicode(value,backupEncoding)
                        insSeek(pos)
                        self[id_] = value
                    except:
                        deprint(u'Error reading string file:')
                        deprint(u'id:', id_)
                        deprint(u'offset:', offset)
                        deprint(u'filePos:',  insTell())
                        raise
        except:
            deprint(u'Error loading string file:', path.stail, traceback=True)
            return

# Main -------------------------------------------------------------------------
if __name__ == '__main__' and len(sys.argv) > 1:
    #--Commands----------------------------------------------------------------
    @mainfunc
    def genHtml(*args,**keywords):
        """Wtxt to html. Just pass through to WryeText.genHtml."""
        if not len(args):
            args = [u"..\Wrye Bash.txt"]
        WryeText.genHtml(*args,**keywords)

    #--Command Handler --------------------------------------------------------
    _mainFunctions.main()
