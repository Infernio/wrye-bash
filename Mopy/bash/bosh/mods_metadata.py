# -*- coding: utf-8 -*-
#
# GPL License and Copyright Notice ============================================
#  This file is part of Wrye Bash.
#
#  Wrye Bash is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation, either version 3
#  of the License, or (at your option) any later version.
#
#  Wrye Bash is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Wrye Bash.  If not, see <https://www.gnu.org/licenses/>.
#
#  Wrye Bash copyright (C) 2005-2009 Wrye, 2010-2020 Wrye Bash Team
#  https://github.com/wrye-bash
#
# =============================================================================
from __future__ import division
import os
import struct
from collections import defaultdict
from functools import partial

from ._mergeability import is_esl_capable
from .loot_parser import libloot_version, LOOTParser
from .. import balt, bolt, bush, bass, load_order
from ..bolt import GPath, deprint, sio, struct_pack, struct_unpack
from ..brec import ModReader, MreRecord, RecordHeader
from ..exception import CancelError, ModError

lootDb = None # type: LOOTParser

#------------------------------------------------------------------------------
class ConfigHelpers(object):
    """Encapsulates info from mod configuration helper files (LOOT masterlist, etc.)"""

    def __init__(self):
        """bass.dir must have been initialized"""
        global lootDb
        lootDb = LOOTParser()
        deprint(u'Initialized loot_parser, compatible with libloot '
                u'v%s' % libloot_version)
        # LOOT stores the masterlist/userlist in a %LOCALAPPDATA% subdirectory.
        self.lootMasterPath = bass.dirs[u'userApp'].join(
            os.pardir, u'LOOT', bush.game.fsName, u'masterlist.yaml')
        self.lootUserPath = bass.dirs[u'userApp'].join(
            os.pardir, u'LOOT', bush.game.fsName, u'userlist.yaml')
        self.lootMasterTime = None
        self.lootUserTime = None
        self.tagList = bass.dirs[u'taglists'].join(u'taglist.yaml')
        self.tagListModTime = None
        #--Bash Tags
        self.tagCache = {}
        #--Refresh
        self.refreshBashTags()

    def refreshBashTags(self):
        """Reloads tag info if file dates have changed."""
        path, userpath = self.lootMasterPath, self.lootUserPath
        #--Masterlist is present, use it
        if path.exists():
            if (path.mtime != self.lootMasterTime or
                (userpath.exists() and userpath.mtime != self.lootUserTime)):
                self.tagCache = {}
                self.lootMasterTime = path.mtime
                if userpath.exists():
                    self.lootUserTime = userpath.mtime
                    lootDb.load_lists(path, userpath)
                else:
                    lootDb.load_lists(path)
            return # no changes or we parsed successfully
        #--No masterlist or an error occurred while reading it, use the taglist
        if not self.tagList.exists():
            # Missing taglist is fine, happens if someone cloned without
            # running update_taglist.py
            return
        if self.tagList.mtime == self.tagListModTime: return
        self.tagListModTime = self.tagList.mtime
        self.tagCache = {}
        lootDb.load_lists(self.tagList)

    ##: move cache into loot_parser, then build more sophisticated invalidation
    # mechanism to handle CRCs, active status, etc. - ref #353
    def get_tags_from_loot(self, modName):
        """Gets bash tag info from the cache, or from loot_parser if it is not
        cached."""
        from . import process_tags ##: yuck
        if modName not in self.tagCache:
            tags = lootDb.get_plugin_tags(modName)
            tags = process_tags(tags[0]), process_tags(tags[1])
            self.tagCache[modName] = tags
            return tags
        else:
            return self.tagCache[modName]

    @staticmethod
    def getDirtyMessage(modName, mod_infos):
        ##: retrieve other messages (e.g. doNotClean, reqManualFix) here? or
        # perhaps in a more general method (get_loot_messages)?
        if lootDb.is_plugin_dirty(modName, mod_infos):
            return True, _(u'Contains dirty edits, needs cleaning.')
        else:
            return False, u''

    # BashTags dir ------------------------------------------------------------
    def get_tags_from_dir(self, plugin_name):
        """Retrieves a tuple containing a set of added and a set of deleted
        tags from the 'Data/BashTags/PLUGIN_NAME.txt' file, if it is
        present.

        :param plugin_name: The name of the plugin to check the tag file for.
        :return: A tuple containing two sets of added and deleted tags."""
        from . import process_tags ##: yuck
        # Check if the file even exists first
        tag_files_dir = bass.dirs[u'tag_files']
        tag_file = tag_files_dir.join(plugin_name.body + u'.txt')
        if not tag_file.isfile(): return set(), set()
        removed, added = set(), set()
        with tag_file.open('r') as ins:
            for tag_line in ins:
                # Strip out comments and skip lines that are empty as a result
                tag_line = tag_line.split(u'#')[0].strip()
                if not tag_line: continue
                for tag_entry in tag_line.split(u','):
                    # Guard against things (e.g. typos) like 'TagA,,TagB'
                    if not tag_entry: continue
                    tag_entry = tag_entry.strip()
                    # If it starts with a minus, it's removing a tag
                    if tag_entry[0] == u'-':
                        # Guard against a typo like '- C.Water'
                        removed.add(tag_entry[1:].strip())
                    else:
                        added.add(tag_entry)
        return process_tags(added), process_tags(removed)

    def save_tags_to_dir(self, plugin_name, plugin_tags, plugin_old_tags):
        """Compares plugin_tags to plugin_old_tags and saves the diff to
        Data/BashTags/PLUGIN_NAME.txt.

        :param plugin_name: The name of the plugin to modify the tag file for.
        :param plugin_tags: A set of all Bash Tags currently applied to the
            plugin in question.
        :param plugin_base_tags: A set of all Bash Tags applied to the plugin
            by its description and the LOOT masterlist / userlist."""
        tag_files_dir = bass.dirs[u'tag_files']
        tag_files_dir.makedirs()
        tag_file = tag_files_dir.join(plugin_name.body + u'.txt')
        # Calculate the diff and ignore the minus when sorting the result
        diff_tags = sorted(plugin_tags - plugin_old_tags |
                           {u'-' + t for t in plugin_old_tags - plugin_tags},
                           key=lambda t: t[1:] if t[0] == u'-' else t)
        with tag_file.open('w') as out:
            # Stick a header in there to indicate that it's machine-generated
            # Also print the version, which could be helpful
            out.write(u'# Generated by Wrye Bash %s\n' % bass.AppVersion)
            out.write(u', '.join(diff_tags) + u'\n')

    #--Mod Checker ------------------------------------------------------------
    _cleaning_wiki_url = u'[[!https://tes5edit.github.io/docs/5-mod-cleaning' \
                         u'-and-error-checking.html|Tome of xEdit]]'

    def checkMods(self, showModList=False, showCRC=False, showVersion=True,
                  mod_checker=None):
        """Checks currently loaded mods for certain errors / warnings.
        mod_checker should be the instance of ModChecker, to scan."""
        from . import modInfos
        active = set(load_order.cached_active_tuple())
        imported_ = modInfos.imported
        removeEslFlag = set()
        warning = u'=== <font color=red>'+_(u'WARNING:')+u'</font> '
        #--Header
        with sio() as out:
            log = bolt.LogFile(out)
            log.setHeader(u'= '+_(u'Check Mods'),True)
            if bush.game.check_esl:
                log(_(u'This is a report on your currently installed or '
                      u'active mods.'))
            else:
                log(_(u'This is a report on your currently installed, active, '
                      u'or merged mods.'))
            #--Mergeable/NoMerge/Deactivate tagged mods
            if bush.game.check_esl:
                shouldMerge = modInfos.mergeable
            else:
                shouldMerge = active & modInfos.mergeable
            if bush.game.check_esl:
                for m, modinf in modInfos.items():
                    if not modinf.is_esl():
                        continue # we check .esl extension and ESL flagged mods
                    if not is_esl_capable(modinf, modInfos, reasons=None):
                        removeEslFlag.add(m)
            shouldDeactivateA, shouldDeactivateB = [], []
            for x in active:
                tags = modInfos[x].getBashTags()
                if u'Deactivate' in tags: shouldDeactivateA.append(x)
                if u'NoMerge' in tags and x in modInfos.mergeable:
                    shouldDeactivateB.append(x)
            shouldActivateA = [x for x in imported_ if x not in active and
                        u'MustBeActiveIfImported' in modInfos[x].getBashTags()]
            #--Mods with invalid TES4 version
            invalidVersion = [(x,unicode(round(modInfos[x].header.version,6))) for x in active if round(modInfos[x].header.version,6) not in bush.game.Esp.validHeaderVersions]
            #--Look for dirty edits
            shouldClean = {}
            scan = []
            dirty_msgs = [(x, modInfos.getDirtyMessage(x)) for x in active]
            for x, y in dirty_msgs:
                if y[0]:
                    shouldClean[x] = y[1]
                elif mod_checker:
                    scan.append(modInfos[x])
            if mod_checker:
                try:
                    with balt.Progress(_(u'Scanning for Dirty Edits...'),u'\n'+u' '*60, parent=mod_checker, abort=True) as progress:
                        ret = ModCleaner.scan_Many(scan,ModCleaner.ITM|ModCleaner.UDR,progress)
                        for i,mod in enumerate(scan):
                            udrs,itms,fog = ret[i]
                            if mod.name == GPath(u'Unofficial Oblivion Patch.esp'): itms.discard((GPath(u'Oblivion.esm'),0x00AA3C))
                            if mod.isBP(): itms = set()
                            if udrs or itms:
                                cleanMsg = []
                                if udrs:
                                    cleanMsg.append(u'UDR(%i)' % len(udrs))
                                if itms:
                                    cleanMsg.append(u'ITM(%i)' % len(itms))
                                cleanMsg = u', '.join(cleanMsg)
                                shouldClean[mod.name] = cleanMsg
                except CancelError:
                    pass
            # below is always empty with current implementation
            shouldCleanMaybe = [(x, y[1]) for x, y in dirty_msgs if
                                not y[0] and y[1] != u'']
            for mod in tuple(shouldMerge):
                if u'NoMerge' in modInfos[mod].getBashTags():
                    shouldMerge.discard(mod)
            if shouldMerge:
                if bush.game.check_esl:
                    log.setHeader(u'=== '+_(u'ESL Capable'))
                    log(_(u'Following mods could be assigned an ESL flag but '
                          u'are not ESL flagged.'))
                else:
                    log.setHeader(u'=== ' + _(u'Mergeable'))
                    log(_(u'Following mods are active, but could be merged into '
                          u'the bashed patch.'))
                for mod in sorted(shouldMerge):
                    log(u'* __'+mod.s+u'__')
            if removeEslFlag:
                log.setHeader(u'=== ' + _(u'Incorrect ESL Flag'))
                log(_(u'Following mods have an ESL flag, but do not qualify. '
                      u"Either remove the flag with 'Remove ESL Flag', or "
                      u"change the extension to '.esp' if it is '.esl'."))
                for mod in sorted(removeEslFlag):
                    log(u'* __' + mod.s + u'__')
            if shouldDeactivateB:
                log.setHeader(u'=== '+_(u'NoMerge Tagged Mods'))
                log(_(u'Following mods are tagged NoMerge and should be '
                      u'deactivated and imported into the bashed patch but '
                      u'are currently active.'))
                for mod in sorted(shouldDeactivateB):
                    log(u'* __'+mod.s+u'__')
            if shouldDeactivateA:
                log.setHeader(u'=== '+_(u'Deactivate Tagged Mods'))
                log(_(u'Following mods are tagged Deactivate and should be '
                      u'deactivated and imported into the bashed patch but '
                      u'are currently active.'))
                for mod in sorted(shouldDeactivateA):
                    log(u'* __'+mod.s+u'__')
            if shouldActivateA:
                log.setHeader(u'=== '+_(u'MustBeActiveIfImported Tagged Mods'))
                log(_(u'Following mods to work correctly have to be active as '
                      u'well as imported into the bashed patch but are '
                      u'currently only imported.'))
                for mod in sorted(shouldActivateA):
                    log(u'* __'+mod.s+u'__')
            if shouldClean:
                log.setHeader(
                    u'=== ' + _(u'Mods that need cleaning with %s') %
                    bush.game.Xe.full_name)
                log(_(u'Following mods have identical to master (ITM) '
                      u'records, deleted records (UDR), or other issues that '
                      u'should be fixed with %(xedit_name)s. Visit the '
                      u'%(cleaning_wiki_url)s for more information.') % {
                    u'cleaning_wiki_url': self._cleaning_wiki_url,
                    u'xedit_name': bush.game.Xe.full_name})
                for mod in sorted(shouldClean.keys()):
                    log(u'* __'+mod.s+u':__  %s' % shouldClean[mod])
            if shouldCleanMaybe:
                log.setHeader(
                    u'=== ' + _(u'Mods with special cleaning instructions'))
                log(_(u'Following mods have special instructions for cleaning '
                      u'with %s') % bush.game.Xe.full_name)
                for mod in sorted(shouldCleanMaybe):
                    log(u'* __'+mod[0].s+u':__  '+mod[1])
            elif mod_checker and not shouldClean:
                log.setHeader(
                    u'=== ' + _(u'Mods that need cleaning with %s') %
                    bush.game.Xe.full_name)
                log(_(u'Congratulations, all mods appear clean.'))
            if invalidVersion:
                # Always an ASCII byte string, so this is fine
                header_sig_ = unicode(bush.game.Esp.plugin_header_sig,
                                      encoding=u'ascii')
                ver_list = u', '.join(sorted(
                    unicode(v) for v in bush.game.Esp.validHeaderVersions))
                log.setHeader(
                    u'=== ' + _(u'Mods with non-standard %s versions') %
                    header_sig_)
                log(_(u"The following mods have a %s version that isn't "
                      u'recognized as one of the standard versions '
                      u'(%s). It is untested what effects this can have on '
                      u'%s.') % (header_sig_, ver_list, bush.game.displayName))
                for mod in sorted(invalidVersion):
                    log(u'* __'+mod[0].s+u':__  '+mod[1])
            #--Missing/Delinquent Masters
            if showModList:
                log(u'\n'+modInfos.getModList(showCRC,showVersion,wtxt=True).strip())
            else:
                log.setHeader(warning+_(u'Missing/Delinquent Masters'))
                previousMods = set()
                for mod in load_order.cached_active_tuple():
                    loggedMod = False
                    for master in modInfos[mod].masterNames:
                        if master not in active:
                            label_ = _(u'MISSING')
                        elif master not in previousMods:
                            label_ = _(u'DELINQUENT')
                        else:
                            label_ = u''
                        if label_:
                            if not loggedMod:
                                log(u'* '+mod.s)
                                loggedMod = True
                            log(u'  * __%s__ %s' %(label_,master.s))
                    previousMods.add(mod)
            return log.out.getvalue()

#------------------------------------------------------------------------------
class ModCleaner(object):
    """Class for cleaning ITM and UDR edits from mods. ITM detection does not
    currently work with PBash."""
    UDR     = 0x01  # Deleted references
    ITM     = 0x02  # Identical to master records
    FOG     = 0x04  # Nvidia Fog Fix
    ALL = UDR|ITM|FOG
    DEFAULT = UDR|ITM

    class UdrInfo(object):
        # UDR info
        # (UDR fid, UDR Type, UDR Parent Fid, UDR Parent Type, UDR Parent Parent Fid, UDR Parent Block, UDR Paren SubBlock)
        def __init__(self,fid,Type=None,parentFid=None,parentEid=u'',
                     parentType=None,parentParentFid=None,parentParentEid=u'',
                     pos=None):
            self.fid = fid
            self.type = Type
            self.parentFid = parentFid
            self.parentEid = parentEid
            self.parentType = parentType
            self.pos = pos
            self.parentParentFid = parentParentFid
            self.parentParentEid = parentParentEid

        # Implement rich comparison operators, __cmp__ is deprecated
        def __eq__(self, other):
            return self.fid == other.fid
        def __ne__(self, other):
            return self.fid != other.fid
        def __lt__(self, other):
            return self.fid < other.fid
        def __le__(self, other):
            return self.fid <= other.fid
        def __gt__(self, other):
            return self.fid > other.fid
        def __ge__(self, other):
            return self.fid >= other.fid


    def __init__(self,modInfo):
        self.modInfo = modInfo
        self.itm = set()    # Fids for Identical To Master records
        self.udr = set()    # Fids for Deleted Reference records
        self.fog = set()    # Fids for Cells needing the Nvidia Fog Fix

    def scan(self,what=ALL,progress=bolt.Progress(),detailed=False):
        """Scan this mod for dirty edits.
           return (UDR,ITM,FogFix)"""
        udr,itm,fog = ModCleaner.scan_Many([self.modInfo],what,progress,detailed)[0]
        if what & ModCleaner.UDR:
            self.udr = udr
        if what & ModCleaner.ITM:
            self.itm = itm
        if what & ModCleaner.FOG:
            self.fog = fog
        return udr,itm,fog

    @staticmethod
    def scan_Many(modInfos, what=DEFAULT, progress=bolt.Progress(),
            detailed=False, __unpacker=struct.Struct(u'=12s2f2l2f').unpack):
        """Scan multiple mods for dirty edits"""
        if len(modInfos) == 0: return []
        if not (what & (ModCleaner.UDR|ModCleaner.FOG)):
            return [(set(), set(), set())] * len(modInfos)
        # Python can't do ITM scanning
        doUDR = what & ModCleaner.UDR
        doFog = what & ModCleaner.FOG
        progress.setFull(max(len(modInfos),1))
        ret = []
        for i,modInfo in enumerate(modInfos):
            progress(i,_(u'Scanning...') + u'\n%s' % modInfo.name)
            itm = set()
            fog = set()
            #--UDR stuff
            udr = {}
            parents_to_scan = defaultdict(set)
            if len(modInfo.masterNames) > 0:
                subprogress = bolt.SubProgress(progress,i,i+1)
                if detailed:
                    subprogress.setFull(max(modInfo.size*2,1))
                else:
                    subprogress.setFull(max(modInfo.size,1))
                #--File stream
                path = modInfo.getPath()
                #--Scan
                parentType = None
                parentFid = None
                parentParentFid = None
                # Location (Interior = #, Exteror = (X,Y)
                with ModReader(modInfo.name,path.open('rb')) as ins:
                    try:
                        insAtEnd = ins.atEnd
                        insTell = ins.tell
                        insUnpackRecHeader = ins.unpackRecHeader
                        insUnpackSubHeader = ins.unpackSubHeader
                        insRead = ins.read
                        ins_unpack = partial(ins.unpack, __unpacker)
                        headerSize = RecordHeader.rec_header_size
                        while not insAtEnd():
                            subprogress(insTell())
                            header = insUnpackRecHeader()
                            rtype,hsize = header.recType,header.size
                            #(type,size,flags,fid,uint2) = ins.unpackRecHeader()
                            if rtype == 'GRUP':
                                groupType = header.groupType
                                if groupType == 0 and header.label not in {'CELL','WRLD'}:
                                    # Skip Tops except for WRLD and CELL groups
                                    insRead(hsize-headerSize)
                                elif detailed:
                                    if groupType == 1:
                                        # World Children
                                        parentParentFid = header.label
                                        parentType = 1 # Exterior Cell
                                        parentFid = None
                                    elif groupType == 2:
                                        # Interior Cell Block
                                        parentType = 0 # Interior Cell
                                        parentParentFid = parentFid = None
                                    elif groupType in {6,8,9,10}:
                                        # Cell Children, Cell Persistent Children,
                                        # Cell Temporary Children, Cell VWD Children
                                        parentFid = header.label
                                    else: # 3,4,5,7 - Topic Children
                                        pass
                            else:
                                header_fid = header.fid
                                if doUDR and header.flags1 & 0x20 and rtype in (
                                    'ACRE',               #--Oblivion only
                                    'ACHR','REFR',        #--Both
                                    'NAVM','PHZD','PGRE', #--Skyrim only
                                    ):
                                    if not detailed:
                                        udr[header_fid] = ModCleaner.UdrInfo(header_fid)
                                    else:
                                        udr[header_fid] = ModCleaner.UdrInfo(
                                            header_fid, rtype, parentFid, u'',
                                            parentType, parentParentFid, u'',
                                            None)
                                        parents_to_scan[parentFid].add(header_fid)
                                        if parentParentFid:
                                            parents_to_scan[parentParentFid].add(header_fid)
                                if doFog and rtype == 'CELL':
                                    nextRecord = insTell() + hsize
                                    while insTell() < nextRecord:
                                        (nextType,nextSize) = insUnpackSubHeader()
                                        if nextType != 'XCLL':
                                            insRead(nextSize)
                                        else:
                                            color,near,far,rotXY,rotZ,fade,clip = ins_unpack(nextSize,'CELL.XCLL')
                                            if not (near or far or clip):
                                                fog.add(header_fid)
                                else:
                                    insRead(hsize)
                        if parents_to_scan:
                            # Detailed info - need to re-scan for CELL and WRLD infomation
                            ins.seek(0)
                            baseSize = modInfo.size
                            while not insAtEnd():
                                subprogress(baseSize+insTell())
                                header = insUnpackRecHeader()
                                rtype,hsize = header.recType,header.size
                                if rtype == 'GRUP':
                                    if header.groupType == 0 and header.label not in {'CELL','WRLD'}:
                                        insRead(hsize-headerSize)
                                else:
                                    fid = header.fid
                                    if fid in parents_to_scan:
                                        record = MreRecord(header,ins,True)
                                        record.loadSubrecords()
                                        eid = u''
                                        for subrec in record.subrecords:
                                            if subrec.subType == 'EDID':
                                                eid = bolt.decoder(subrec.data)
                                            elif subrec.subType == 'XCLC':
                                                pos = struct_unpack(
                                                    '=2i', subrec.data[:8])
                                        for udrFid in parents_to_scan[fid]:
                                            if rtype == 'CELL':
                                                udr[udrFid].parentEid = eid
                                                if udr[udrFid].parentType == 1:
                                                    # Exterior Cell, calculate position
                                                    udr[udrFid].pos = pos
                                            elif rtype == 'WRLD':
                                                udr[udrFid].parentParentEid = eid
                                    else:
                                        insRead(hsize)
                    except CancelError:
                        raise
                    except:
                        deprint(u'Error scanning %s, file read pos: %i:\n' % (modInfo.name,ins.tell()),traceback=True)
                        udr = itm = fog = None
                #--Done
            ret.append((udr.values() if udr is not None else None,itm,fog))
        return ret

#------------------------------------------------------------------------------
class NvidiaFogFixer(object):
    """Fixes cells to avoid nvidia fog problem."""
    def __init__(self,modInfo):
        self.modInfo = modInfo
        self.fixedCells = set()

    def fix_fog(self, progress,
                     __unpacker=struct.Struct(u'=12s2f2l2f').unpack):
        """Duplicates file, then walks through and edits file as necessary."""
        progress.setFull(self.modInfo.size)
        fixedCells = self.fixedCells
        fixedCells.clear()
        #--File stream
        path = self.modInfo.getPath()
        #--Scan/Edit
        with ModReader(self.modInfo.name,path.open('rb')) as ins:
            ins_unpack = partial(ins.unpack, __unpacker)
            with path.temp.open('wb') as  out:
                def copy(size):
                    buff = ins.read(size)
                    out.write(buff)
                def copyPrev(size):
                    ins.seek(-size,1)
                    buff = ins.read(size)
                    out.write(buff)
                while not ins.atEnd():
                    progress(ins.tell())
                    header = ins.unpackRecHeader()
                    type,size = header.recType,header.size
                    #(type,size,str0,fid,uint2) = ins.unpackRecHeader()
                    copyPrev(RecordHeader.rec_header_size)
                    if type == 'GRUP':
                        if header.groupType != 0: #--Ignore sub-groups
                            pass
                        elif header.label not in ('CELL','WRLD'):
                            copy(size - RecordHeader.rec_header_size)
                    #--Handle cells
                    elif type == 'CELL':
                        nextRecord = ins.tell() + size
                        while ins.tell() < nextRecord:
                            (type,size) = ins.unpackSubHeader()
                            copyPrev(6)
                            if type != 'XCLL':
                                copy(size)
                            else:
                                color, near, far, rotXY, rotZ, fade, clip = \
                                    ins_unpack(size, 'CELL.XCLL')
                                if not (near or far or clip):
                                    near = 0.0001
                                    fixedCells.add(header.fid)
                                out.write(struct_pack('=12s2f2l2f', color, near, far, rotXY, rotZ, fade,clip))
                    #--Non-Cells
                    else:
                        copy(size)
        #--Done
        if fixedCells:
            self.modInfo.makeBackup()
            path.untemp()
            self.modInfo.setmtime(crc_changed=True) # fog fixes
        else:
            path.temp.remove()

#------------------------------------------------------------------------------
class ModDetails(object):
    """Details data for a mods file. Similar to TesCS Details view."""
    def __init__(self):
        self.group_records = {} #--group_records[group] = [(fid0,eid0),(fid1,eid1),...]

    def readFromMod(self, modInfo, progress=None):
        """Extracts details from mod file."""
        def getRecordReader(flags, size):
            """Decompress record data as needed."""
            if not MreRecord.flags1_(flags).compressed:
                return ins,ins.tell()+size
            else:
                import zlib
                sizeCheck, = struct_unpack('I', ins.read(4))
                decomp = zlib.decompress(ins.read(size-4))
                if len(decomp) != sizeCheck:
                    raise ModError(ins.inName,
                        u'Mis-sized compressed data. Expected %d, got %d.' % (size,len(decomp)))
                reader = ModReader(modInfo.name,sio(decomp))
                return reader,sizeCheck
        progress = progress or bolt.Progress()
        group_records = self.group_records = {}
        records = group_records[bush.game.Esp.plugin_header_sig] = []
        with ModReader(modInfo.name,modInfo.getPath().open('rb')) as ins:
            while not ins.atEnd():
                header = ins.unpackRecHeader()
                recType, rec_siz = header.recType, header.size
                if recType == 'GRUP':
                    # FIXME(ut): monkey patch for fallout QUST GRUP
                    if bush.game.fsName in (u'Fallout4', u'Fallout4VR') and \
                            header.groupType == 10:
                        header.skip_group(ins)
                        continue
                    label = header.label
                    progress(1.0*ins.tell()/modInfo.size,_(u"Scanning: ")+label)
                    records = group_records.setdefault(label,[])
                    if label in ('CELL', 'WRLD', 'DIAL'): # skip these groups
                        header.skip_group(ins)
                else:
                    eid = u''
                    nextRecord = ins.tell() + rec_siz
                    recs, endRecs = getRecordReader(header.flags1, rec_siz)
                    while recs.tell() < endRecs:
                        (recType, rec_siz) = recs.unpackSubHeader()
                        if recType == 'EDID':
                            eid = recs.readString(rec_siz)
                            break
                        recs.seek(rec_siz, 1)
                    records.append((header.fid,eid))
                    ins.seek(nextRecord)
        del group_records[bush.game.Esp.plugin_header_sig]
