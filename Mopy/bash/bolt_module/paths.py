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
"""Contains the Path API. Paths are immutable objects representing a file
system paths. They offer many convenience methods for reducing boilerplate."""
import codecs
import errno
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from binascii import crc32
from functools import partial

# TODO(inf) Have to use absolute import here, relative crashes - why?
from exception import StateError
from .unicode_utils import decode

_gpaths = {}

def GPath(name):
    """Path factory and cache.
    :rtype: Path
    """
    if name is None: return None
    elif isinstance(name,Path): norm = name._s
    elif not name: norm = name # empty string - bin this if ?
    elif isinstance(name,unicode): norm = os.path.normpath(name)
    else: norm = os.path.normpath(decode(name))
    path = _gpaths.get(norm)
    if path is not None: return path
    else: return _gpaths.setdefault(norm,Path(norm))

def GPathPurge():
    """Cleans out the _gpaths dictionary of any unused bolt.Path objects.
       We cannot use a weakref.WeakValueDictionary in this case for 2 reasons:
        1) bolt.Path, due to its class structure, cannot be made into weak
           references
        2) the objects would be deleted as soon as the last reference goes
           out of scope (not the behavior we want).  We want the object to
           stay alive as long as we will possibly be needing it, IE: as long
           as we're still on the same tab.
       So instead, we'll manually call our flushing function a few times:
        1) When switching tabs
        2) Prior to building a bashed patch
        3) Prior to saving settings files
    """
    for key in _gpaths.keys():
        # Using .keys() allows use to modify the dictionary while iterating
        if sys.getrefcount(_gpaths[key]) == 2:
            # 1 for the reference in the _gpaths dictionary,
            # 1 for the temp reference passed to sys.getrefcount
            # meanin the object is not reference anywhere else
            del _gpaths[key]

class Path(object):
    """Paths are immutable objects that represent file directory paths.
     May be just a directory, filename or full path."""

    #--Class Vars/Methods -------------------------------------------
    sys_fs_enc = sys.getfilesystemencoding() or 'mbcs'
    invalid_chars_re = re.compile(ur'(.*)([/\\:*?"<>|]+)(.*)', re.I | re.U)

    @staticmethod
    def getNorm(name):
        """Return the normpath for specified name/path object."""
        if isinstance(name,Path): return name._s
        elif not name: return name
        elif isinstance(name,str): name = decode(name)
        return os.path.normpath(name)

    @staticmethod
    def __getCase(name):
        """Return the normpath+normcase for specified name/path object."""
        if not name: return name
        if isinstance(name, str): name = decode(name)
        return os.path.normcase(os.path.normpath(name))

    @staticmethod
    def getcwd():
        return Path(os.getcwdu())

    def setcwd(self):
        """Set cwd."""
        os.chdir(self._s)

    @staticmethod
    def has_invalid_chars(string):
        match = Path.invalid_chars_re.match(string)
        if not match: return None
        return match.groups()[1]

    #--Instance stuff --------------------------------------------------
    #--Slots: _s is normalized path. All other slots are just pre-calced
    #  variations of it.
    __slots__ = ('_s', '_cs', '_sroot', '_shead', '_stail', '_ext',
                 '_cext', '_sbody')

    def __init__(self, name):
        """Initialize."""
        if isinstance(name,Path):
            self.__setstate__(name._s)
        else:
            self.__setstate__(name)

    def __getstate__(self):
        """Used by pickler. _cs is redundant,so don't include."""
        return self._s

    def __setstate__(self,norm):
        """Used by unpickler. Reconstruct _cs."""
        # Older pickle files stored filename in str, not unicode
        if not isinstance(norm,unicode): norm = decode(norm)
        self._s = norm
        self._cs = os.path.normcase(self._s)

    def __len__(self):
        return len(self._s)

    def __repr__(self):
        return u"bolt.Path("+repr(self._s)+u")"

    def __unicode__(self):
        return self._s

    #--Properties--------------------------------------------------------
    #--String/unicode versions.
    @property
    def s(self):
        """Path as string."""
        return self._s
    @property
    def cs(self):
        """Path as string in normalized case."""
        return self._cs
    @property
    def sroot(self):
        """Root as string."""
        try:
            return self._sroot
        except AttributeError:
            self._sroot, self._ext = os.path.splitext(self._s)
            return self._sroot
    @property
    def shead(self):
        """Head as string."""
        try:
            return self._shead
        except AttributeError:
            self._shead, self._stail = os.path.split(self._s)
            return self._shead
    @property
    def stail(self):
        """Tail as string."""
        try:
            return self._stail
        except AttributeError:
            self._shead, self._stail = os.path.split(self._s)
            return self._stail
    @property
    def sbody(self):
        """For alpha\beta.gamma returns beta as string."""
        try:
            return self._sbody
        except AttributeError:
            self._sbody = os.path.basename(self.sroot)
            return self._sbody
    @property
    def csbody(self):
        """For alpha\beta.gamma returns beta as string in normalized case."""
        return os.path.normcase(self.sbody)

    #--Head, tail
    @property
    def headTail(self):
        """For alpha\beta.gamma returns (alpha,beta.gamma)"""
        return map(GPath, (self.shead, self.stail))
    @property
    def head(self):
        """For alpha\beta.gamma, returns alpha."""
        return GPath(self.shead)
    @property
    def tail(self):
        """For alpha\beta.gamma, returns beta.gamma."""
        return GPath(self.stail)
    @property
    def body(self):
        """For alpha\beta.gamma, returns beta."""
        return GPath(self.sbody)

    #--Root, ext
    @property
    def root(self):
        """For alpha\beta.gamma returns alpha\beta"""
        return GPath(self.sroot)
    @property
    def ext(self):
        """Extension (including leading period, e.g. '.txt')."""
        try:
            return self._ext
        except AttributeError:
            self._sroot, self._ext = os.path.splitext(self._s)
            return self._ext
    @property
    def cext(self):
        """Extension in normalized case."""
        try:
            return self._cext
        except AttributeError:
            self._cext = os.path.normcase(self.ext)
            return self._cext
    @property
    def temp(self,unicodeSafe=True):
        """Temp file path.  If unicodeSafe is True, the returned
        temp file will be a fileName that can be passes through Popen
        (Popen automatically tries to encode the name)"""
        baseDir = GPath(unicode(tempfile.gettempdir(), Path.sys_fs_enc)).join(u'WryeBash_temp')
        baseDir.makedirs()
        dirJoin = baseDir.join
        if unicodeSafe:
            try:
                self._s.encode('ascii')
                return dirJoin(self.tail+u'.tmp')
            except UnicodeEncodeError:
                ret = unicode(self._s.encode('ascii','xmlcharrefreplace'),'ascii')+u'_unicode_safe.tmp'
                return dirJoin(ret)
        else:
            return dirJoin(self.tail+u'.tmp')

    @staticmethod
    def tempDir(prefix=u'WryeBash_'):
        try: # workaround for http://bugs.python.org/issue1681974 see there
            return GPath(tempfile.mkdtemp(prefix=prefix))
        except UnicodeDecodeError:
            try:
                traceback.print_exc()
                print 'Trying to pass temp dir in...'
                tempdir = unicode(tempfile.gettempdir(), Path.sys_fs_enc)
                return GPath(tempfile.mkdtemp(prefix=prefix, dir=tempdir))
            except UnicodeDecodeError:
                try:
                    traceback.print_exc()
                    print 'Trying to encode temp dir prefix...'
                    return GPath(tempfile.mkdtemp(
                        prefix=prefix.encode(Path.sys_fs_enc)).decode(
                        Path.sys_fs_enc))
                except:
                    traceback.print_exc()
                    print 'Failed to create tmp dir, Bash will not function ' \
                          'correctly.'

    @staticmethod
    def baseTempDir():
        return GPath(unicode(tempfile.gettempdir(), Path.sys_fs_enc))

    @property
    def backup(self):
        """Backup file path."""
        return self+u'.bak'

    #--size, atime, ctime
    @property
    def size(self):
        """Size of file or directory."""
        if self.isdir():
            join = os.path.join
            getSize = os.path.getsize
            try:
                # TODO(inf) BOLT_MODULE: Move to regular import once done
                from ..bolt import _walk
                return sum([sum(map(getSize,map(lambda z: join(x,z),files))) for x,y,files in _walk(self._s)])
            except ValueError:
                return 0
        else:
            return os.path.getsize(self._s)

    @property
    def atime(self):
        return os.path.getatime(self._s)
    @property
    def ctime(self):
        return os.path.getctime(self._s)

    #--Mtime
    def _getmtime(self):
        """Return mtime for path."""
        return int(os.path.getmtime(self._s))
    def _setmtime(self, mtime):
        os.utime(self._s, (self.atime, int(mtime)))
    mtime = property(_getmtime, _setmtime, doc="Time file was last modified.")

    def size_mtime(self):
        lstat = os.lstat(self._s)
        return lstat.st_size, int(lstat.st_mtime)

    def size_mtime_ctime(self):
        lstat = os.lstat(self._s)
        return lstat.st_size, int(lstat.st_mtime), lstat.st_ctime

    @property
    def stat(self):
        """File stats"""
        return os.stat(self._s)

    @property
    def version(self):
        """File version (exe/dll) embedded in the file properties."""
        from env import get_file_version
        try:
            version = get_file_version(self._s)
            if version is None:
                version = (0,0,0,0)
        except: # TODO: pywintypes.error?
            version = (0,0,0,0)
        return version

    @property
    def strippedVersion(self):
        """.version with leading and trailing zeros stripped."""
        version = list(self.version)
        while len(version) > 1 and version[0] == 0:
            version.pop(0)
        while len(version) > 1 and version[-1] == 0:
            version.pop()
        return tuple(version)

    #--crc
    @property
    def crc(self):
        """Calculates and returns crc value for self."""
        crc = 0L
        with self.open('rb') as ins:
            for block in iter(partial(ins.read, 2097152), ''):
                crc = crc32(block, crc) # 2MB at a time, probably ok
        return crc & 0xffffffff

    #--Path stuff -------------------------------------------------------
    #--New Paths, subpaths
    def __add__(self,other):
        return GPath(self._s + Path.getNorm(other))
    def join(*args):
        norms = [Path.getNorm(x) for x in args]
        return GPath(os.path.join(*norms))
    def list(self):
        """For directory: Returns list of files."""
        if not os.path.exists(self._s): return []
        return [GPath(x) for x in os.listdir(self._s)]
    def walk(self,topdown=True,onerror=None,relative=False):
        """Like os.walk."""
        # TODO(inf) BOLT_MODULE: Move to regular import once done
        from ..bolt import _walk
        if relative:
            start = len(self._s)
            for root_dir,dirs,files in _walk(self._s,topdown,onerror):
                yield (GPath(root_dir[start:]), [GPath(x) for x in dirs], [
                    GPath(x) for x in files])
        else:
            for root_dir,dirs,files in _walk(self._s,topdown,onerror):
                yield (GPath(root_dir), [GPath(x) for x in dirs], [GPath(x) for x in files])

    def split(self):
        """Splits the path into each of it's sub parts.  IE: C:\Program Files\Bethesda Softworks
           would return ['C:','Program Files','Bethesda Softworks']"""
        dirs = []
        drive, path = os.path.splitdrive(self.s)
        path = path.strip(os.path.sep)
        l,r = os.path.split(path)
        while l != u'':
            dirs.append(r)
            l,r = os.path.split(l)
        dirs.append(r)
        if drive != u'':
            dirs.append(drive)
        dirs.reverse()
        return dirs
    def relpath(self,path):
        return GPath(os.path.relpath(self._s, Path.getNorm(path)))

    def drive(self):
        """Returns the drive part of the path string."""
        return GPath(os.path.splitdrive(self._s)[0])

    #--File system info
    #--THESE REALLY OUGHT TO BE PROPERTIES.
    def exists(self):
        return os.path.exists(self._s)
    def isdir(self):
        return os.path.isdir(self._s)
    def isfile(self):
        return os.path.isfile(self._s)
    def isabs(self):
        return os.path.isabs(self._s)

    #--File system manipulation
    @staticmethod
    def _onerror(func,path,exc_info):
        """shutil error handler: remove RO flag"""
        if not os.access(path,os.W_OK):
            os.chmod(path,stat.S_IWUSR|stat.S_IWOTH)
            func(path)
        else:
            raise

    def clearRO(self):
        """Clears RO flag on self"""
        if not self.isdir():
            os.chmod(self._s,stat.S_IWUSR|stat.S_IWOTH)
        else:
            try:
                # TODO(inf) BOLT_MODULE: Move to regular import once done
                # May not be possible in this case(?)
                from ..bolt import clearReadOnly
                clearReadOnly(self)
            except UnicodeError:
                flags = stat.S_IWUSR|stat.S_IWOTH
                chmod = os.chmod
                # TODO(inf) BOLT_MODULE: Move to regular import once done
                from ..bolt import _walk
                for root_dir,dirs,files in _walk(self._s):
                    rootJoin = root_dir.join
                    for directory in dirs:
                        try: chmod(rootJoin(directory),flags)
                        except: pass
                    for filename in files:
                        try: chmod(rootJoin(filename),flags)
                        except: pass

    def open(self,*args,**kwdargs):
        if self.shead and not os.path.exists(self.shead):
            os.makedirs(self.shead)
        if 'encoding' in kwdargs:
            return codecs.open(self._s,*args,**kwdargs)
        else:
            return open(self._s,*args,**kwdargs)
    def makedirs(self):
        try:
            os.makedirs(self._s)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
    def remove(self):
        try:
            if self.exists(): os.remove(self._s)
        except OSError:
            # Clear RO flag
            os.chmod(self._s,stat.S_IWUSR|stat.S_IWOTH)
            os.remove(self._s)
    def removedirs(self):
        try:
            if self.exists(): os.removedirs(self._s)
        except OSError:
            self.clearRO()
            os.removedirs(self._s)
    def rmtree(self,safety='PART OF DIRECTORY NAME'):
        """Removes directory tree. As a safety factor, a part of the directory name must be supplied."""
        if self.isdir() and safety and safety.lower() in self._cs:
            shutil.rmtree(self._s,onerror=Path._onerror)

    #--start, move, copy, touch, untemp
    def start(self, exeArgs=None):
        """Starts file as if it had been doubleclicked in file explorer."""
        if self.cext == u'.exe':
            if not exeArgs:
                subprocess.Popen([self.s], close_fds=True)
            else:
                subprocess.Popen(exeArgs, executable=self.s, close_fds=True)
        else:
            os.startfile(self._s)
    def copyTo(self,destName):
        """Copy self to destName, make dirs if necessary and preserve mtime."""
        destName = GPath(destName)
        if self.isdir():
            shutil.copytree(self._s,destName._s)
        else:
            if destName.shead and not os.path.exists(destName.shead):
                os.makedirs(destName.shead)
            shutil.copyfile(self._s,destName._s)
            destName.mtime = self.mtime
    def moveTo(self,destName):
        if not self.exists():
            raise StateError(self._s + u' cannot be moved because it does not exist.')
        destPath = GPath(destName)
        if destPath._cs == self._cs: return
        if destPath.shead and not os.path.exists(destPath.shead):
            os.makedirs(destPath.shead)
        elif destPath.exists():
            destPath.remove()
        try:
            shutil.move(self._s,destPath._s)
        except OSError:
            self.clearRO()
            shutil.move(self._s,destPath._s)

    def tempMoveTo(self,destName):
        """Temporarily rename/move an object.  Use with the 'with' statement"""
        class temp(object):
            def __init__(self,oldPath,newPath):
                self.newPath = GPath(newPath)
                self.oldPath = GPath(oldPath)

            def __enter__(self): return self.newPath
            def __exit__(self, exc_type, exc_value, exc_traceback): self.newPath.moveTo(self.oldPath)
        self.moveTo(destName)
        return temp(self,destName)

    def unicodeSafe(self):
        """Temporarily rename (only if necessary) the file to a unicode safe name.
           Use with the 'with' statement."""
        try:
            self._s.encode('ascii')
            class temp(object):
                def __init__(self,path):
                    self.path = path
                def __enter__(self): return self.path
                def __exit__(self, exc_type, exc_value, exc_traceback): pass
            return temp(self)
        except UnicodeEncodeError:
            return self.tempMoveTo(self.temp)

    def touch(self):
        """Like unix 'touch' command. Creates a file with current date/time."""
        if self.exists():
            self.mtime = time.time()
        else:
            with self.temp.open('w'):
                pass
            self.untemp()
    def untemp(self,doBackup=False):
        """Replaces file with temp version, optionally making backup of file first."""
        if self.temp.exists():
            if self.exists():
                if doBackup:
                    self.backup.remove()
                    shutil.move(self._s, self.backup._s)
                else:
                    # this will fail with Access Denied (!) if self._s is
                    # (unexpectedly) a directory
                    try:
                        os.remove(self._s)
                    except OSError as e:
                        if e.errno != errno.EACCES:
                            raise
                        self.clearRO()
                        os.remove(self._s)
            shutil.move(self.temp._s, self._s)

    def editable(self):
        """Safely check whether a file is editable."""
        delete = not os.path.exists(self._s)
        try:
            with open(self._s,'ab') as f:
                return True
        except:
            return False
        finally:
            # If the file didn't exist before, remove the created version
            if delete:
                try:
                    os.remove(self._s)
                except:
                    pass

    #--Hash/Compare, based on the _cs attribute so case insensitive. NB: Paths
    # directly compare to basestring and Path and will blow for anything else
    def __hash__(self):
        return hash(self._cs)
    def __eq__(self, other):
        if isinstance(other, Path):
            return self._cs == other._cs
        else:
            return self._cs == Path.__getCase(other)
    def __ne__(self, other):
        if isinstance(other, Path):
            return self._cs != other._cs
        else:
            return self._cs != Path.__getCase(other)
    def __lt__(self, other):
        if isinstance(other, Path):
            return self._cs < other._cs
        else:
            return self._cs < Path.__getCase(other)
    def __ge__(self, other):
        if isinstance(other, Path):
            return self._cs >= other._cs
        else:
            return self._cs >= Path.__getCase(other)
    def __gt__(self, other):
        if isinstance(other, Path):
            return self._cs > other._cs
        else:
            return self._cs > Path.__getCase(other)
    def __le__(self, other):
        if isinstance(other, Path):
            return self._cs <= other._cs
        else:
            return self._cs <= Path.__getCase(other)