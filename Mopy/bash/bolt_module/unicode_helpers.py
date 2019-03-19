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
"""Contains methods and classes related to unicode support. Mostly used when
reading / writing text from / to sources with an unknown encoding (e.g. plugin
files, cosaves, etc.)."""
import os
import chardet

#--decode unicode strings
#  This is only useful when reading fields from mods, as the encoding is not
#  known.  For normal filesystem interaction, these functions are not needed
encodingOrder = (
    'ascii',    # Plain old ASCII (0-127)
    'gbk',      # GBK (simplified Chinese + some)
    'cp932',    # Japanese
    'cp949',    # Korean
    'cp1252',   # English (extended ASCII)
    'utf8',
    'cp500',
    'UTF-16LE',
    )
if os.name == u'nt':
    encodingOrder += ('mbcs',)

_encodingSwap = {
    # The encoding detector reports back some encodings that
    # are subsets of others.  Use the better encoding when
    # given the option
    # 'reported encoding':'actual encoding to use',
    'GB2312': 'gbk',        # Simplified Chinese
    'SHIFT_JIS': 'cp932',   # Japanese
    'windows-1252': 'cp1252',
    'windows-1251': 'cp1251',
    'utf-8': 'utf8',
    }

def getbestencoding(bitstream):
    """Tries to detect the encoding a bitstream was saved in.  Uses Mozilla's
       detection library to find the best match (heuristics)"""
    result = chardet.detect(bitstream)
    encoding_,confidence = result['encoding'],result['confidence']
    encoding_ = _encodingSwap.get(encoding_,encoding_)
    ## Debug: uncomment the following to output stats on encoding detection
    #print
    #print '%s: %s (%s)' % (repr(bitstream),encoding,confidence)
    return encoding_,confidence

# Preferred encoding to use when decoding/encoding strings in plugin files
# None = auto
# setting it tries the specified encoding first
pluginEncoding = None

def decode(byte_str, encoding=None, avoidEncodings=()):
    """Decode a byte string to unicode, using heuristics on encoding."""
    if isinstance(byte_str, unicode) or byte_str is None: return byte_str
    # Try the user specified encoding first
    # TODO(ut) monkey patch
    if encoding == 'cp65001':
        encoding = 'utf-8'
    if encoding:
        try: return unicode(byte_str, encoding)
        except UnicodeDecodeError: pass
    # Try to detect the encoding next
    encoding,confidence = getbestencoding(byte_str)
    if encoding and confidence >= 0.55 and (encoding not in avoidEncodings or confidence == 1.0):
        try: return unicode(byte_str, encoding)
        except UnicodeDecodeError: pass
    # If even that fails, fall back to the old method, trial and error
    for encoding in encodingOrder:
        try: return unicode(byte_str, encoding)
        except UnicodeDecodeError: pass
    raise UnicodeDecodeError(u'Text could not be decoded using any method')
