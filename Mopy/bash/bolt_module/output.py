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
"""Contains classes and methods related to giving feedback to the user in
several ways (e.g. text output, progress bar backends, etc.)."""
import re

from .debugging import deprint
# TODO(inf) Have to use absolute import here, relative crashes - why?
from exception import ArgumentError, BoltError
from .paths import Path, GPath

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

class Progress:
    """Progress Callable: Shows progress when called."""
    def __init__(self,full=1.0):
        if (1.0*full) == 0: raise ArgumentError(u'Full must be non-zero!')
        self.message = u''
        self.full = 1.0 * full
        self.state = 0
        self.debug = False

    def getParent(self):
        return None

    def setFull(self,full):
        """Set's full and for convenience, returns self."""
        if (1.0*full) == 0: raise ArgumentError(u'Full must be non-zero!')
        self.full = 1.0 * full
        return self

    def plus(self,increment=1):
        """Increments progress by 1."""
        self.__call__(self.state+increment)

    def __call__(self,state,message=''):
        """Update progress with current state. Progress is state/full."""
        if (1.0*self.full) == 0: raise ArgumentError(u'Full must be non-zero!')
        if message: self.message = message
        if self.debug: deprint(u'%0.3f %s' % (1.0*state/self.full, self.message))
        self._do_progress(1.0 * state / self.full, self.message)
        self.state = state

    def _do_progress(self, state, message):
        """Default _do_progress does nothing."""

    # __enter__ and __exit__ for use with the 'with' statement
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_value, exc_traceback): pass

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
            raise ArgumentError(u'BaseFrom must be >= 0 and BaseTo must be > BaseFrom')
        self.parent = parent
        self.baseFrom = baseFrom
        self.scale = 1.0*(baseTo-baseFrom)
        self.silent = silent

    def __call__(self,state,message=u''):
        """Update progress with current state. Progress is state/full."""
        if self.silent: message = u''
        self.parent(self.baseFrom+self.scale*state/self.full,message)
        self.state = state

codebox = None
class WryeText:
    """This class provides a function for converting wtxt text files to html
    files.

    Headings:
    = XXXX >> H1 "XXX"
    == XXXX >> H2 "XXX"
    === XXXX >> H3 "XXX"
    ==== XXXX >> H4 "XXX"
    Notes:
    * These must start at first character of line.
    * The XXX text is compressed to form an anchor. E.g == Foo Bar gets anchored as" FooBar".
    * If the line has trailing ='s, they are discarded. This is useful for making
      text version of level 1 and 2 headings more readable.

    Bullet Lists:
    * Level 1
      * Level 2
        * Level 3
    Notes:
    * These must start at first character of line.
    * Recognized bullet characters are: - ! ? . + * o The dot (.) produces an invisible
      bullet, and the * produces a bullet character.

    Styles:
      __Text__
      ~~Italic~~
      **BoldItalic**
    Notes:
    * These can be anywhere on line, and effects can continue across lines.

    Links:
     [[file]] produces <a href=file>file</a>
     [[file|text]] produces <a href=file>text</a>
     [[!file]] produces <a href=file target="_blank">file</a>
     [[!file|text]] produces <a href=file target="_blank">text</a>

    Contents
    {{CONTENTS=NN}} Where NN is the desired depth of contents (1 for single level,
    2 for two levels, etc.).
    """

    # Data ------------------------------------------------------------------------
    htmlHead = u"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
    <html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
    <head>
    <meta http-equiv="Content-Type" content="text/html;charset=utf-8" />
    <title>%s</title>
    <style type="text/css">%s</style>
    </head>
    <body>
    """
    defaultCss = u"""
    h1 { margin-top: 0in; margin-bottom: 0in; border-top: 1px solid #000000; border-bottom: 1px solid #000000; border-left: none; border-right: none; padding: 0.02in 0in; background: #c6c63c; font-family: "Arial", serif; font-size: 12pt; page-break-before: auto; page-break-after: auto }
    h2 { margin-top: 0in; margin-bottom: 0in; border-top: 1px solid #000000; border-bottom: 1px solid #000000; border-left: none; border-right: none; padding: 0.02in 0in; background: #e6e64c; font-family: "Arial", serif; font-size: 10pt; page-break-before: auto; page-break-after: auto }
    h3 { margin-top: 0in; margin-bottom: 0in; font-family: "Arial", serif; font-size: 10pt; font-style: normal; page-break-before: auto; page-break-after: auto }
    h4 { margin-top: 0in; margin-bottom: 0in; font-family: "Arial", serif; font-style: italic; page-break-before: auto; page-break-after: auto }
    a:link { text-decoration:none; }
    a:hover { text-decoration:underline; }
    p { margin-top: 0.01in; margin-bottom: 0.01in; font-family: "Arial", serif; font-size: 10pt; page-break-before: auto; page-break-after: auto }
    p.empty {}
    p.list-1 { margin-left: 0.15in; text-indent: -0.15in }
    p.list-2 { margin-left: 0.3in; text-indent: -0.15in }
    p.list-3 { margin-left: 0.45in; text-indent: -0.15in }
    p.list-4 { margin-left: 0.6in; text-indent: -0.15in }
    p.list-5 { margin-left: 0.75in; text-indent: -0.15in }
    p.list-6 { margin-left: 1.00in; text-indent: -0.15in }
    .code-n { background-color: #FDF5E6; font-family: "Lucide Console", monospace; font-size: 10pt; white-space: pre; }
    pre { border: 1px solid; overflow: auto; width: 750px; word-wrap: break-word; background: #FDF5E6; padding: 0.5em; margin-top: 0in; margin-bottom: 0in; margin-left: 0.25in}
    code { background-color: #FDF5E6; font-family: "Lucida Console", monospace; font-size: 10pt; }
    td.code { background-color: #FDF5E6; font-family: "Lucida Console", monospace; font-size: 10pt; border: 1px solid #000000; padding:5px; width:50%;}
    body { background-color: #ffffcc; }
    """

    # Conversion ---------------------------------------------------------------
    @staticmethod
    def genHtml(ins,out=None,*cssDirs):
        """Reads a wtxt input stream and writes an html output stream."""
        import string, urllib
        # Path or Stream? -----------------------------------------------
        if isinstance(ins,(Path,str,unicode)):
            srcPath = GPath(ins)
            outPath = GPath(out) or srcPath.root+u'.html'
            cssDirs = (srcPath.head,) + cssDirs
            ins = srcPath.open(encoding='utf-8-sig')
            out = outPath.open('w',encoding='utf-8-sig')
        else:
            srcPath = outPath = None
        # Setup
        outWrite = out.write

        cssDirs = map(GPath,cssDirs)
        # Setup ---------------------------------------------------------
        #--Headers
        reHead = re.compile(ur'(=+) *(.+)',re.U)
        headFormat = u"<h%d><a id='%s'>%s</a></h%d>\n"
        headFormatNA = u"<h%d>%s</h%d>\n"
        #--List
        reWryeList = re.compile(ur'( *)([-x!?.+*o])(.*)',re.U)
        #--Code
        reCode = re.compile(ur'\[code\](.*?)\[/code\]',re.I|re.U)
        reCodeStart = re.compile(ur'(.*?)\[code\](.*?)$',re.I|re.U)
        reCodeEnd = re.compile(ur'(.*?)\[/code\](.*?)$',re.I|re.U)
        reCodeBoxStart = re.compile(ur'\s*\[codebox\](.*?)',re.I|re.U)
        reCodeBoxEnd = re.compile(ur'(.*?)\[/codebox\]\s*',re.I|re.U)
        reCodeBox = re.compile(ur'\s*\[codebox\](.*?)\[/codebox\]\s*',re.I|re.U)
        codeLines = None
        codeboxLines = None
        def subCode(match):
            try:
                return u' '.join(codebox([match.group(1)],False,False))
            except:
                return match(1)
        #--Misc. text
        reHr = re.compile(u'^------+$',re.U)
        reEmpty = re.compile(ur'\s+$',re.U)
        reMDash = re.compile(ur' -- ',re.U)
        rePreBegin = re.compile(u'<pre',re.I|re.U)
        rePreEnd = re.compile(u'</pre>',re.I|re.U)
        anchorlist = [] #to make sure that each anchor is unique.
        def subAnchor(match):
            text = match.group(1)
            # This one's weird.  Encode the url to utf-8, then allow urllib to do it's magic.
            # urllib will automatically take any unicode characters and escape them, so to
            # convert back to unicode for purposes of storing the string, everything will
            # be in cp1252, due to the escapings.
            anchor = unicode(urllib.quote(reWd.sub(u'',text).encode('utf8')),'cp1252')
            count = 0
            if re.match(ur'\d', anchor):
                anchor = u'_' + anchor
            while anchor in anchorlist and count < 10:
                count += 1
                if count == 1:
                    anchor += unicode(count)
                else:
                    anchor = anchor[:-1] + unicode(count)
            anchorlist.append(anchor)
            return u"<a id='%s'>%s</a>" % (anchor,text)
        #--Bold, Italic, BoldItalic
        reBold = re.compile(ur'__',re.U)
        reItalic = re.compile(ur'~~',re.U)
        reBoldItalic = re.compile(ur'\*\*',re.U)
        states = {'bold':False,'italic':False,'boldItalic':False,'code':0}
        def subBold(match):
            state = states['bold'] = not states['bold']
            return u'<b>' if state else u'</b>'
        def subItalic(match):
            state = states['italic'] = not states['italic']
            return u'<i>' if state else u'</i>'
        def subBoldItalic(match):
            state = states['boldItalic'] = not states['boldItalic']
            return u'<i><b>' if state else u'</b></i>'
        #--Preformatting
        #--Links
        reLink = re.compile(ur'\[\[(.*?)\]\]',re.U)
        reHttp = re.compile(ur' (http://[_~a-zA-Z0-9./%-]+)',re.U)
        reWww = re.compile(ur' (www\.[_~a-zA-Z0-9./%-]+)',re.U)
        reWd = re.compile(ur'(<[^>]+>|\[\[[^\]]+\]\]|\s+|[%s]+)' % re.escape(string.punctuation.replace(u'_',u'')),re.U)
        rePar = re.compile(ur'^(\s*[a-zA-Z(;]|\*\*|~~|__|\s*<i|\s*<a)',re.U)
        reFullLink = re.compile(ur'(:|#|\.[a-zA-Z0-9]{2,4}$)',re.U)
        reColor = re.compile(ur'\[\s*color\s*=[\s\"\']*(.+?)[\s\"\']*\](.*?)\[\s*/\s*color\s*\]',re.I|re.U)
        reBGColor = re.compile(ur'\[\s*bg\s*=[\s\"\']*(.+?)[\s\"\']*\](.*?)\[\s*/\s*bg\s*\]',re.I|re.U)
        def subColor(match):
            return u'<span style="color:%s;">%s</span>' % (match.group(1),match.group(2))
        def subBGColor(match):
            return u'<span style="background-color:%s;">%s</span>' % (match.group(1),match.group(2))
        def subLink(match):
            address = text = match.group(1).strip()
            if u'|' in text:
                (address,text) = [chunk.strip() for chunk in text.split(u'|',1)]
                if address == u'#': address += unicode(urllib.quote(reWd.sub(u'',text).encode('utf8')),'cp1252')
            if address.startswith(u'!'):
                newWindow = u' target="_blank"'
                address = address[1:]
            else:
                newWindow = u''
            if not reFullLink.search(address):
                address += u'.html'
            return u'<a href="%s"%s>%s</a>' % (address,newWindow,text)
        #--Tags
        reAnchorTag = re.compile(u'{{A:(.+?)}}',re.U)
        reContentsTag = re.compile(ur'\s*{{CONTENTS=?(\d+)}}\s*$',re.U)
        reAnchorHeadersTag = re.compile(ur'\s*{{ANCHORHEADERS=(\d+)}}\s*$',re.U)
        reCssTag = re.compile(u'\s*{{CSS:(.+?)}}\s*$',re.U)
        #--Defaults ----------------------------------------------------------
        title = u''
        level = 1
        spaces = u''
        cssName = None
        #--Init
        outLines = []
        contents = []
        outLinesAppend = outLines.append
        outLinesExtend = outLines.extend
        addContents = 0
        inPre = False
        anchorHeaders = True
        #--Read source file --------------------------------------------------
        for line in ins:
            line = line.replace('\r\n','\n')
            #--Codebox -----------------------------------
            if codebox:
                if codeboxLines is not None:
                    maCodeBoxEnd = reCodeBoxEnd.match(line)
                    if maCodeBoxEnd:
                        codeboxLines.append(maCodeBoxEnd.group(1))
                        outLinesAppend(u'<pre style="width:850px;">')
                        try:
                            codeboxLines = codebox(codeboxLines)
                        except:
                            pass
                        outLinesExtend(codeboxLines)
                        outLinesAppend(u'</pre>\n')
                        codeboxLines = None
                        continue
                    else:
                        codeboxLines.append(line)
                        continue
                maCodeBox = reCodeBox.match(line)
                if maCodeBox:
                    outLines.append(u'<pre style="width:850px;">')
                    try:
                        outLinesExtend(codebox([maCodeBox.group(1)]))
                    except:
                        outLinesAppend(maCodeBox.group(1))
                    outLinesAppend(u'</pre>\n')
                    continue
                maCodeBoxStart = reCodeBoxStart.match(line)
                if maCodeBoxStart:
                    codeboxLines = [maCodeBoxStart.group(1)]
                    continue
            #--Code --------------------------------------
                if codeLines is not None:
                    maCodeEnd = reCodeEnd.match(line)
                    if maCodeEnd:
                        codeLines.append(maCodeEnd.group(1))
                        try:
                            codeLines = codebox(codeLines,False)
                        except:
                            pass
                        outLinesExtend(codeLines)
                        codeLines = None
                        line = maCodeEnd.group(2)
                    else:
                        codeLines.append(line)
                        continue
                line = reCode.sub(subCode,line)
                maCodeStart = reCodeStart.match(line)
                if maCodeStart:
                    line = maCodeStart.group(1)
                    codeLines = [maCodeStart.group(2)]
            #--Preformatted? -----------------------------
            maPreBegin = rePreBegin.search(line)
            maPreEnd = rePreEnd.search(line)
            if inPre or maPreBegin or maPreEnd:
                inPre = maPreBegin or (inPre and not maPreEnd)
                outLinesAppend(line)
                continue
            #--Font/Background Color
            line = reColor.sub(subColor,line)
            line = reBGColor.sub(subBGColor,line)
            #--Re Matches -------------------------------
            maContents = reContentsTag.match(line)
            maAnchorHeaders = reAnchorHeadersTag.match(line)
            maCss = reCssTag.match(line)
            maHead = reHead.match(line)
            maList  = reWryeList.match(line)
            maPar   = rePar.match(line)
            maEmpty = reEmpty.match(line)
            #--Contents
            if maContents:
                if maContents.group(1):
                    addContents = int(maContents.group(1))
                else:
                    addContents = 100
                inPar = False
            elif maAnchorHeaders:
                anchorHeaders = maAnchorHeaders.group(1) != u'0'
                continue
            #--CSS
            elif maCss:
                #--Directory spec is not allowed, so use tail.
                cssName = GPath(maCss.group(1).strip()).tail
                continue
            #--Headers
            elif maHead:
                lead,text = maHead.group(1,2)
                text = re.sub(u' *=*#?$','',text.strip())
                anchor = unicode(urllib.quote(reWd.sub(u'',text).encode('utf8')),'cp1252')
                level = len(lead)
                if anchorHeaders:
                    if re.match(ur'\d', anchor):
                        anchor = u'_' + anchor
                    count = 0
                    while anchor in anchorlist and count < 10:
                        count += 1
                        if count == 1:
                            anchor += unicode(count)
                        else:
                            anchor = anchor[:-1] + unicode(count)
                    anchorlist.append(anchor)
                    line = (headFormatNA,headFormat)[anchorHeaders] % (level,anchor,text,level)
                    if addContents: contents.append((level,anchor,text))
                else:
                    line = headFormatNA % (level,text,level)
                #--Title?
                if not title and level <= 2: title = text
            #--Paragraph
            elif maPar and not states['code']:
                line = u'<p>'+line+u'</p>\n'
            #--List item
            elif maList:
                spaces = maList.group(1)
                bullet = maList.group(2)
                text = maList.group(3)
                if bullet == u'.': bullet = u'&nbsp;'
                elif bullet == u'*': bullet = u'&bull;'
                level = len(spaces)/2 + 1
                line = spaces+u'<p class="list-%i">'%level+bullet+u'&nbsp; '
                line = line + text + u'</p>\n'
            #--Empty line
            elif maEmpty:
                line = spaces+u'<p class="empty">&nbsp;</p>\n'
            #--Misc. Text changes --------------------
            line = reHr.sub(u'<hr>',line)
            line = reMDash.sub(u' &#150; ',line)
            #--Bold/Italic subs
            line = reBold.sub(subBold,line)
            line = reItalic.sub(subItalic,line)
            line = reBoldItalic.sub(subBoldItalic,line)
            #--Wtxt Tags
            line = reAnchorTag.sub(subAnchor,line)
            #--Hyperlinks
            line = reLink.sub(subLink,line)
            line = reHttp.sub(ur' <a href="\1">\1</a>',line)
            line = reWww.sub(ur' <a href="http://\1">\1</a>',line)
            #--Save line ------------------
            #print line,
            outLines.append(line)
        #--Get Css -----------------------------------------------------------
        if not cssName:
            css = WryeText.defaultCss
        else:
            if cssName.ext != u'.css':
                raise BoltError(u'Invalid Css file: ' + cssName.s)
            for css_dir in cssDirs:
                cssPath = GPath(css_dir).join(cssName)
                if cssPath.exists(): break
            else:
                raise BoltError(u'Css file not found: ' + cssName.s)
            with cssPath.open('r',encoding='utf-8-sig') as cssIns:
                css = u''.join(cssIns.readlines())
            if u'<' in css:
                raise BoltError(u'Non css tag in ' + cssPath.s)
        #--Write Output ------------------------------------------------------
        outWrite(WryeText.htmlHead % (title,css))
        didContents = False
        for line in outLines:
            if reContentsTag.match(line):
                if contents and not didContents:
                    baseLevel = min([level for (level,name,text) in contents])
                    for (level,name,text) in contents:
                        level = level - baseLevel + 1
                        if level <= addContents:
                            outWrite(u'<p class="list-%d">&bull;&nbsp; <a href="#%s">%s</a></p>\n' % (level,name,text))
                    didContents = True
            else:
                outWrite(line)
        outWrite(u'</body>\n</html>\n')
        #--Close files?
        if srcPath:
            ins.close()
            out.close()
