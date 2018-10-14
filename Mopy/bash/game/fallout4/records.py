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
"""This module contains the Fallout 4 record classes. The great majority are
imported from skyrim, but only after setting MelModel to the FO4 format."""
import itertools

from ... import brec
from ...bass import null1, null2, null3, null4
from ...bolt import Flags, struct_pack, encode
from ...brec import MelBase, MelGroup, MreHeaderBase, MelSet, MelString, \
    MelStruct, MelUnicode, MelNull, MelFidList, MreLeveledListBase, \
    MelGroups, MelFid, FID, MelOptStruct, MelLString, MelStructA
from ...exception import ModSizeError
# Set brec.MelModel to the Fallout 4 one - do not import from skyrim.records yet

class MelMODS(MelBase): # copy pasted from game.skyrim.records.MelMODS
    """MODS/MO2S/etc/DMDS subrecord"""
    def hasFids(self,formElements):
        """Include self if has fids."""
        formElements.add(self)

    def setDefault(self,record):
        """Sets default value for record instance."""
        record.__setattr__(self.attr,None)

    def loadData(self, record, ins, sub_type, size_, readId):
        """Reads data from ins into record attribute."""
        insUnpack = ins.unpack
        count, = insUnpack('I',4,readId)
        data = []
        dataAppend = data.append
        for x in xrange(count):
            string = ins.readString32(readId)
            fid = ins.unpackRef()
            index, = ins.unpack('I',4,readId)
            dataAppend((string,fid,index))
        record.__setattr__(self.attr,data)

    def dumpData(self,record,out):
        """Dumps data from record to outstream."""
        data = record.__getattribute__(self.attr)
        if data is not None:
            data = record.__getattribute__(self.attr)
            outData = struct_pack('I', len(data))
            for (string,fid,index) in data:
                outData += struct_pack('I', len(string))
                outData += encode(string)
                outData += struct_pack('=2I', fid, index)
            out.packSub(self.subType,outData)

    def mapFids(self,record,function,save=False):
        """Applies function to fids.  If save is true, then fid is set
           to result of function."""
        attr = self.attr
        data = record.__getattribute__(attr)
        if data is not None:
            data = [(string,function(fid),index) for (string,fid,index) in record.__getattribute__(attr)]
            if save: record.__setattr__(attr,data)

if brec.MelModel is None:
    class _MelModel(MelGroup):
        """Represents a model record."""
        # MODB and MODD are no longer used by TES5Edit
        typeSets = {'MODL': ('MODL', 'MODT', 'MODS'),
                    'MOD2': ('MOD2', 'MO2T', 'MO2S'),
                    'MOD3': ('MOD3', 'MO3T', 'MO3S'),
                    'MOD4': ('MOD4', 'MO4T', 'MO4S'),
                    'MOD5': ('MOD5', 'MO5T', 'MO5S'),
                    'DMDL': ('DMDL', 'DMDT', 'DMDS'), }

        class MelModelHash(MelBase):
            """textureHashes are not used for loose files. There is never a
            Bashed Patch, 0.bsa. The record will be read if
            present but no defaults are set and the record will not be written."""
            def loadData(self, record, ins, sub_type, size_, readId):
                MelBase.loadData(self, record, ins, sub_type, size_, readId)
            def getSlotsUsed(self):
                return ()
            def setDefault(self,record): return
            def dumpData(self,record,out): return

        def __init__(self, attr='model', subType='MODL'):
            """Initialize."""
            types = self.__class__.typeSets[subType]
            MelGroup.__init__(self, attr, MelString(types[0],'modPath'),
                              self.MelModelHash(types[1],'textureHashes'),
                              MelMODS(types[2],'alternateTextures'), )

        def debug(self, on=True):
            """Sets debug flag on self."""
            for element in self.elements[:2]: element.debug(on)
            return self
    brec.MelModel = _MelModel
from ...brec import MelModel
# Now we can import from parent game records file
from ..skyrim.records import MelBounds
# Those are unused here, but need be in this file as are accessed via it
from ..skyrim.records import MreGmst

from_iterable = itertools.chain.from_iterable

#------------------------------------------------------------------------------
# Record Elements    ----------------------------------------------------------
#------------------------------------------------------------------------------
class MelCoed(MelOptStruct):
    """Needs custom unpacker to look at FormID type of owner.  If owner is an
	NPC then it is followed by a FormID.  If owner is a faction then it is
	followed by an signed integer or '=Iif' instead of '=IIf' """ # see #282
    def __init__(self):
        MelOptStruct.__init__(self,'COED','=IIf',(FID,'owner'),(FID,'glob'),
                              'itemCondition')

#------------------------------------------------------------------------------
# Fallout 4 Records  ----------------------------------------------------------
#------------------------------------------------------------------------------
class MreHeader(MreHeaderBase):
    """TES4 Record.  File header."""
    classType = 'TES4'

    #--Data elements
    melSet = MelSet(
        MelStruct('HEDR','f2I',('version',0.95),'numRecords',('nextObject',0xCE6)),
        MelBase('TNAM', 'tnam_p'),
        MelUnicode('CNAM','author',u'',512),
        MelUnicode('SNAM','description',u'',512),
        MreHeaderBase.MelMasterName('MAST','masters'),
        MelNull('DATA'), # 8 Bytes in Length
        MelFidList('ONAM','overrides',),
        MelBase('SCRN', 'scrn_p'),
        MelBase('INTV','intv_p'),
        MelBase('INCC', 'incc_p'),
        )
    __slots__ = melSet.getSlotsUsed()

#------------------------------------------------------------------------------
# Marker for organization please don't remove ---------------------------------
# GLOB ------------------------------------------------------------------------
# Defined in brec.py as class MreGlob(MelRecord) ------------------------------
#------------------------------------------------------------------------------
class MreLeveledList(MreLeveledListBase):
    """Skyrim Leveled item/creature/spell list."""

    class MelLevListLvlo(MelGroups):
        def __init__(self):
            MelGroups.__init__(self,'entries',
                MelStruct('LVLO','=3I','level',(FID,'listId',None),('count',1)),
                MelCoed(),
                )
        def dumpData(self,record,out):
            out.packSub('LLCT','B',len(record.entries))
            MelGroups.dumpData(self,record,out)

    __slots__ = MreLeveledListBase.__slots__


#------------------------------------------------------------------------------
class MreLvli(MreLeveledList):
    classType = 'LVLI'
    copyAttrs = ('chanceNone','maxCount','glob','filterKeywordChances',
                 'epicLootChance','overrideName')

    melSet = MelSet(
        MelString('EDID','eid'),
        MelBounds(),
        MelStruct('LVLD','B','chanceNone'),
        MelStruct('LVLM','B','maxCount'),
        MelStruct('LVLF','B',(MreLeveledListBase._flags,'flags',0L)),
        MelOptStruct('LVLG','I',(FID,'glob')),
        MelNull('LLCT'),
        MreLeveledList.MelLevListLvlo(),
        MelStructA('LLKC','2I','filterKeywordChances',(FID,'keyword',None),
                      ('chance',0)),
        MelFid('LVSG', 'epicLootChance'),
        MelLString('ONAM', 'overrideName')
        )
    __slots__ = melSet.getSlotsUsed()

#------------------------------------------------------------------------------
class MreLvln(MreLeveledList):
    classType = 'LVLN'
    copyAttrs = ('chanceNone','maxCount','glob','filterKeywordChances',
                 'model','modt_p')

    melSet = MelSet(
        MelString('EDID','eid'),
        MelBounds(),
        MelStruct('LVLD','B','chanceNone'),
        MelStruct('LVLM','B','maxCount'),
        MelStruct('LVLF','B',(MreLeveledListBase._flags,'flags',0L)),
        MelOptStruct('LVLG','I',(FID,'glob')),
        MelNull('LLCT'),
        MreLeveledList.MelLevListLvlo(),
        MelStructA('LLKC','2I','filterKeywordChances',(FID,'keyword',None),
                      ('chance',0)),
        MelString('MODL','model'),
        MelBase('MODT','modt_p'),
        )
    __slots__ = melSet.getSlotsUsed()
