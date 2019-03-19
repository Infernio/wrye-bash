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
"""Contains methods useful for localization and translation of Wrye Bash."""
import gettext
import locale
import os
import pkgutil
import re
import shutil
import subprocess
import sys
import traceback

from .unicode_utils import decode
from .paths import GPath, Path

def _findAllBashModules(files=[], bashPath=None, cwd=None,
                        exts=('.py', '.pyw'), exclude=(u'chardet',),
                        _firstRun=False):
    """Return a list of all Bash files as relative paths to the Mopy
    directory.

    :param files: files list cache - populated in first run. In the form: [
    u'Wrye Bash Launcher.pyw', u'bash\\balt.py', ..., u'bash\\__init__.py',
    u'bash\\basher\\app_buttons.py', ...]
    :param bashPath: the relative path from Mopy
    :param cwd: initially C:\...\Mopy - but not at the time def is executed !
    :param exts: extensions to keep in listdir()
    :param exclude: tuple of excluded packages
    :param _firstRun: internal use
    """
    if not _firstRun and files:
        return files # cache, not likely to change during execution
    cwd = cwd or os.getcwdu()
    files.extend([(bashPath or Path(u'')).join(m).s for m in
                  os.listdir(cwd) if m.lower().endswith(exts)])
    # find subpackages -- p=(module_loader, name, ispkg)
    for p in pkgutil.iter_modules([cwd]):
        if not p[2] or p[1] in exclude: continue
        _findAllBashModules(
            files, bashPath.join(p[1]) if bashPath else GPath(u'bash'),
            cwd=os.path.join(cwd, p[1]), _firstRun=True)
    return files

def dumpTranslator(outPath, lang, *files):
    """Dumps all translatable strings in python source files to a new text file.
       as this requires the source files, it will not work in WBSA mode, unless
       the source files are also installed"""
    outTxt = u'%sNEW.txt' % lang
    fullTxt = os.path.join(outPath,outTxt)
    tmpTxt = os.path.join(outPath,u'%sNEW.tmp' % lang)
    oldTxt = os.path.join(outPath,u'%s.txt' % lang)
    if not files: files = _findAllBashModules()
    args = [u'p',u'-a',u'-o',fullTxt]
    args.extend(files)
    if hasattr(sys,'frozen'):
        import pygettext
        old_argv = sys.argv[:]
        sys.argv = args
        pygettext.main()
        sys.argv = old_argv
    else:
        p = os.path.join(sys.prefix,u'Tools',u'i18n',u'pygettext.py')
        args[0] = p
        subprocess.call(args,shell=True)
    # Fill in any already translated stuff...?
    try:
        reMsgIdsStart = re.compile('#:')
        reEncoding = re.compile(r'"Content-Type:\s*text/plain;\s*charset=(.*?)\\n"$',re.I)
        reNonEscapedQuote = re.compile(r'([^\\])"')
        def subQuote(match): return match.group(1)+'\\"'
        encoding = None
        with open(tmpTxt,'w') as out:
            outWrite = out.write
            #--Copy old translation file header, and get encoding for strings
            with open(oldTxt,'r') as ins:
                for line in ins:
                    if not encoding:
                        match = reEncoding.match(line.strip('\r\n'))
                        if match:
                            encoding = match.group(1)
                    match = reMsgIdsStart.match(line)
                    if match: break
                    outWrite(line)
            #--Read through the new translation file, fill in any already
            #  translated strings
            with open(fullTxt,'r') as ins:
                header = False
                msgIds = False
                for line in ins:
                    if not header:
                        match = reMsgIdsStart.match(line)
                        if match:
                            header = True
                            outWrite(line)
                        continue
                    elif line[0:7] == 'msgid "':
                        stripped = line.strip('\r\n')[7:-1]
                        # Replace escape sequences
                        stripped = stripped.replace('\\"','"')      # Quote
                        stripped = stripped.replace('\\t','\t')     # Tab
                        stripped = stripped.replace('\\\\', '\\')   # Backslash
                        translated = _(stripped)
                        if stripped != translated:
                            # Already translated
                            outWrite(line)
                            outWrite('msgstr "')
                            translated = translated.encode(encoding)
                            # Re-escape the escape sequences
                            translated = translated.replace('\\','\\\\')
                            translated = translated.replace('\t','\\t')
                            translated = reNonEscapedQuote.sub(subQuote,translated)
                            outWrite(translated)
                            outWrite('"\n')
                        else:
                            # Not translated
                            outWrite(line)
                            outWrite('msgstr ""\n')
                    elif line[0:8] == 'msgstr "':
                        continue
                    else:
                        outWrite(line)
    except:
        try: os.remove(tmpTxt)
        except: pass
    else:
        try:
            os.remove(fullTxt)
            os.rename(tmpTxt,fullTxt)
        except:
            if os.path.exists(fullTxt):
                try: os.remove(tmpTxt)
                except: pass
    return outTxt

def initTranslator(lang=None, path=None):
    if not lang:
        try:
            lang = locale.getlocale()[0].split('_', 1)[0]
            lang = decode(lang)
        except UnicodeError:
            # TODO(inf) BOLT_MODULE: Move to regular import once done
            from bolt import deprint
            deprint(u'Still unicode problems detecting locale:', repr(locale.getlocale()),traceback=True)
            # Default to English
            lang = u'English'
    path = path or os.path.join(u'bash',u'l10n')
    if lang.lower() == u'german': lang = u'de'
    txt,po,mo = (os.path.join(path, lang + ext)
                 for ext in (u'.txt',u'.po',u'.mo'))
    if not os.path.exists(txt) and not os.path.exists(mo):
        if lang.lower() != u'english':
            print u'No translation file for language:', lang
        trans = gettext.NullTranslations()
    else:
        try:
            if not os.path.exists(mo) or (os.path.getmtime(txt) > os.path.getmtime(mo)):
                # Compile
                shutil.copy(txt,po)
                args = [u'm',u'-o',mo,po]
                if hasattr(sys,'frozen'):
                    import msgfmt
                    old_argv = sys.argv[:]
                    sys.argv = args
                    msgfmt.main()
                    sys.argv = old_argv
                else:
                    m = os.path.join(sys.prefix,u'Tools',u'i18n',u'msgfmt.py')
                    subprocess.call([m,u'-o',mo,po],shell=True)
                os.remove(po)
            # install translator
            with open(mo,'rb') as file:
                trans = gettext.GNUTranslations(file)
        except:
            print 'Error loading translation file:'
            traceback.print_exc()
            trans = gettext.NullTranslations()
    trans.install(unicode=True)
