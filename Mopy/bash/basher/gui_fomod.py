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
#  Wrye Bash copyright (C) 2005-2009 Wrye, 2010-2015 Wrye Bash Team
#  https://github.com/wrye-bash
#
# =============================================================================

import os

from .. import balt
from .. import bass
from .. import bolt
from .. import bosh
from .. import bush
from .. import env
import wx
import wx.wizard as wiz

from ..fomod import FomodInstaller, MissingDependency


class WizardReturn(object):
    __slots__ = ('cancelled', 'install_files', 'install', 'page_size', 'pos')

    def __init__(self):
        # cancelled: true if the user canceled or if an error occurred
        self.cancelled = False
        # install_files: file->dest mapping of files to install
        self.install_files = bolt.LowerDict()
        # install: boolean on whether to install the files
        self.install = True
        # page_size: Tuple/wxSize of the saved size of the Wizard
        self.page_size = balt.defSize
        # pos: Tuple/wxPoint of the saved position of the Wizard
        self.pos = balt.defPos


class InstallerFomod(wiz.Wizard):
    def __init__(self, parent_window, installer, page_size, pos):
        fomod_files = installer.fomod_files()
        info_path = fomod_files[0]
        if info_path is not None:
            info_path = info_path.s
        conf_path = fomod_files[1].s
        data_path = bass.dirs['mods']
        ver = env.get_file_version(bass.dirs['app'].join(bush.game.exe).s)
        game_ver = u'.'.join([unicode(i) for i in ver])
        self.parser = FomodInstaller(info_path, conf_path, dest=data_path,
                                     game_version=game_ver)
        mod_name = self.parser.name

        style = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX
        wiz.Wizard.__init__(self, parent_window,
                            title=_(u'Fomod Installer - ' + mod_name),
                            pos=pos, style=style)

        # 'dummy' page tricks the wizard into always showing the "Next" button
        self.dummy = wiz.PyWizardPage(self)
        self.next = None

        # True prevents actually moving to the 'next' page.
        # We use this after the "Next" button is pressed,
        # while the parser is running to return the _actual_ next page
        self.block_change = True
        # 'finishing' is to allow the "Next" button to be used
        # when it's name is changed to 'Finish' on the last page of the wizard
        self.finishing = False
        # saving this dict allows for faster processing of the files the fomod
        # installer will return.
        self.files_dict = installer.fileSizeCrcs

        self.is_archive = isinstance(installer, bosh.InstallerArchive)
        if self.is_archive:
            self.archive_path = bass.getTempDir()
        else:
            self.archive_path = bass.dirs['installers'].join(installer.archive)

        # Intercept the changing event so we can implement 'block_change'
        self.Bind(wiz.EVT_WIZARD_PAGE_CHANGING, self.on_change)
        self.ret = WizardReturn()
        self.ret.page_size = page_size

        # So we can save window size
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wiz.EVT_WIZARD_CANCEL, self.on_close)
        self.Bind(wiz.EVT_WIZARD_FINISHED, self.on_close)

        # Set the minimum size for pages, and setup on_size to resize the
        # First page to the saved size
        self.SetPageSize((600, 500))
        self.first_page = True

    # bain expects a "relative dest file" -> "relative src file"
    # mapping to install. Fomod provides multiple different
    # combinations of mappings, requiring this little hack
    def _process_fomod_dict(self, files_dict):
        final_dict = bolt.LowerDict()
        for src, dest in files_dict.iteritems():
            dest = dest.replace("/", os.sep).replace("\\", os.sep)
            src = src.replace("/", os.sep).replace("\\", os.sep)
            for file_tuple in self.files_dict:
                fpath = file_tuple[0].replace("/", os.sep).replace("\\", os.sep)
                if src.lower() == fpath.lower():  # src is a file
                    final_dict[dest] = src
                    break
                elif fpath.lower().startswith(src.lower()):  # src is a folder
                    src_len = len(src)
                    fdest = dest + fpath[src_len:]
                    if fdest.startswith(os.sep):
                        fdest = fdest[1:]
                    final_dict[fdest] = fpath
        return final_dict

    def on_close(self, event):
        if not self.IsMaximized():
            # Only save the current size if the page isn't maximized
            self.ret.page_size = self.GetSize()
            self.ret.pos = self.GetPosition()
        event.Skip()

    def on_size(self, event):
        if self.first_page:
            # On the first page, resize it to the saved size
            self.first_page = False
            self.SetSize(self.ret.page_size)
        else:
            # Otherwise, regular resize, save the size if we're not
            # maximized
            if not self.IsMaximized():
                self.ret.page_size = self.GetSize()
                self.pos = self.GetPosition()
            event.Skip()

    def get_next_page(self):
        step = next(self.parser)
        if step.get('finished', False):
            self.finishing = True
            return PageFinish(self)
        else:
            self.finishing = False
            return PageSelect(self, step['name'], step['groups'])

    def on_change(self, event):
        if event.GetDirection():
            if not self.finishing:
                # Next, continue script execution
                if self.block_change:
                    # Tell the current page that next was pressed,
                    # So the parser can continue parsing,
                    # Then show the page that the parser returns,
                    # rather than the dummy page
                    event.GetPage().on_next()
                    event.Veto()
                    self.block_change = False
                else:
                    self.block_change = True
                    return
            else:
                return
        else:
            # Previous, pop back to the last state,
            # and resume execution
            event.Veto()
            answer = {'previous_step': True}
            self.parser.send(answer)
            self.block_change = False
        self.next = self.get_next_page()
        self.ShowPage(self.next)

    def run(self):
        try:
            self.parser.send(None)
        except MissingDependency as exc:
            msg = "This installer cannot start due to the following unmet conditions:\n  - "
            dialog = wx.MessageDialog(self, msg + exc[1], caption="Cannot Run Installer",
                                      style=wx.OK | wx.CENTER | wx.ICON_EXCLAMATION)
            dialog.ShowModal()
            self.ret.cancelled = True
        else:
            page = self.get_next_page()
            self.ret.cancelled = not self.RunWizard(page)
            install_files = bolt.LowerDict(self.parser.collected_files)
            self.ret.install_files = self._process_fomod_dict(install_files)
        # Clean up temp files
        if self.is_archive:
            try:
                bass.rmTempDir()
            except Exception:
                pass
        return self.ret


# PageInstaller ----------------------------------------------
#  base class for all the parser wizard pages, just to handle
#  a couple simple things here
# ------------------------------------------------------------
class PageInstaller(wiz.PyWizardPage):
    def __init__(self, parent):
        wiz.PyWizardPage.__init__(self, parent)
        self.parent = parent
        self._enableForward(True)

    def _enableForward(self, enable):
        self.parent.FindWindowById(wx.ID_FORWARD).Enable(enable)

    def GetNext(self):
        return self.parent.dummy

    def GetPrev(self):
        return self.parent.dummy

    def on_next(self):
        # This is what needs to be implemented by sub-classes,
        # this is where flow control objects etc should be
        # created
        pass


# PageError --------------------------------------------------
#  Page that shows an error message, has only a "Cancel"
#  button enabled, and cancels any changes made
# -------------------------------------------------------------
class PageError(PageInstaller):
    def __init__(self, parent, title, error_msg):
        PageInstaller.__init__(self, parent)

        # Disable the "Finish"/"Next" button
        self._enableForward(False)

        # Layout stuff
        sizer_main = wx.FlexGridSizer(2, 1, 5, 5)
        text_error = balt.RoTextCtrl(self, error_msg, autotooltip=False)
        sizer_main.Add(balt.StaticText(parent, label=title))
        sizer_main.Add(text_error, 0, wx.ALL | wx.CENTER | wx.EXPAND)
        sizer_main.AddGrowableCol(0)
        sizer_main.AddGrowableRow(1)
        self.SetSizer(sizer_main)
        self.Layout()

    def GetNext(self):
        return None

    def GetPrev(self):
        return None


# PageSelect -------------------------------------------------
#  A Page that shows a message up top, with a selection box on
#  the left (multi- or single- selection), with an optional
#  associated image and description for each option, shown when
#  that item is selected
# ------------------------------------------------------------
class PageSelect(PageInstaller):
    def __init__(self, parent, step_name, list_groups):
        PageInstaller.__init__(self, parent)

        # group_sizer -> [option_button, ...]
        self.group_option_map = {}

        sizer_main = wx.FlexGridSizer(2, 1, 10, 10)
        label_step_name = wx.StaticText(self, wx.ID_ANY, step_name, style=wx.ALIGN_CENTER)
        label_step_name.SetFont(wx.Font(12, wx.DEFAULT, wx.NORMAL, wx.NORMAL, 0, ""))
        sizer_main.Add(label_step_name, 0, wx.EXPAND)
        sizer_content = wx.GridSizer(1, 2, 5, 5)

        sizer_extra = wx.GridSizer(2, 1, 5, 5)
        self.bmp_item = balt.Picture(self, 0, 0, background=None)
        self.text_item = balt.RoTextCtrl(self, autotooltip=False)
        sizer_extra.Add(self.bmp_item, 1, wx.EXPAND | wx.ALL)
        sizer_extra.Add(self.text_item, 1, wx.EXPAND | wx.ALL)

        panel_groups = wx.ScrolledWindow(self, -1)
        panel_groups.SetScrollbars(20, 20, 50, 50)
        sizer_groups = wx.FlexGridSizer(len(list_groups), 1, 5, 5)
        for row in xrange(len(list_groups)):
            sizer_groups.AddGrowableRow(row)
        for group in list_groups:
            group_name = group['name']
            group_type = group['type']
            group_id = group['id']
            options = group['plugins']
            options_num = len(options)

            sizer_group = wx.FlexGridSizer(2, 1, 7, 7)
            sizer_group.AddGrowableRow(1)
            sizer_group.group_id = group_id
            sizer_group.group_name = group_name
            sizer_group.group_type = group_type
            sizer_group.Add(balt.StaticText(panel_groups, group_name))

            sizer_options = wx.GridSizer(options_num, 1, 2, 2)
            sizer_group.Add(sizer_options)

            first_selectable = None
            any_selected = False

            # whenever there is a required option in a exactlyone/atmostone group
            # all other options need to be disable to ensure the required stays
            # selected
            required_disable = False

            # group type forces selection
            group_force_selection = group_type in ('SelectExactlyOne', 'SelectAtLeastOne')

            for option in options:
                if option == options[0]:
                    radio_style = wx.RB_GROUP
                else:
                    radio_style = 0

                option_id = option['id']
                option_name = option['name']
                option_image = option['image']
                option_desc = option['description']
                option_type = option['type']

                if group_type in ('SelectExactlyOne', 'SelectAtMostOne'):
                    button = wx.RadioButton(panel_groups, label=option_name, style=radio_style)
                else:
                    button = wx.CheckBox(panel_groups, label=option_name)
                    if group_type == 'SelectAll':
                        button.SetValue(True)
                        any_selected = True
                        button.Disable()

                if option_type == 'Required':
                    button.SetValue(True)
                    any_selected = True
                    if group_type in ('SelectExactlyOne', 'SelectAtMostOne'):
                        required_disable = True
                    else:
                        button.Disable()
                elif option_type == 'Recommended':
                    if not any_selected or not group_force_selection:
                        button.SetValue(True)
                        any_selected = True
                elif option_type in ('Optional', 'CouldBeUsable'):
                    if first_selectable is None:
                        first_selectable = button
                elif option_type == 'NotUsable':
                    button.SetValue(False)
                    button.Disable()

                button.option_id = option_id
                button.option_image = option_image
                button.option_desc = option_desc
                button.option_type = option_type

                sizer_options.Add(button)
                button.Bind(wx.EVT_ENTER_WINDOW, self.on_hover)
                self.group_option_map.setdefault(sizer_group, []).append(button)

            if not any_selected and group_force_selection:
                if first_selectable is not None:
                    first_selectable.SetValue(True)
                    any_selected = True

            if required_disable:
                for button in self.group_option_map[sizer_group]:
                    button.Disable()

            if group_type == 'SelectAtMostOne':
                none_button = wx.RadioButton(panel_groups, label='None')
                if not any_selected:
                    none_button.SetValue(True)
                elif required_disable:
                    none_button.Disable()
                sizer_options.Add(none_button)

            sizer_groups.Add(sizer_group, wx.ID_ANY, wx.EXPAND)

        panel_groups.SetSizer(sizer_groups)
        sizer_content.Add(panel_groups, 1, wx.EXPAND)
        sizer_content.Add(sizer_extra, 1, wx.EXPAND)
        sizer_main.Add(sizer_content, 1, wx.EXPAND)
        sizer_main.AddGrowableRow(1)
        sizer_main.AddGrowableCol(0)

        self.SetSizer(sizer_main)
        self.Layout()

    def on_hover(self, event):
        button = event.GetEventObject()
        self._enableForward(True)

        self.bmp_item.Freeze()
        img = self.parent.archive_path.join(button.option_image)
        if img.isfile():
            image = wx.Bitmap(img.s)
            self.bmp_item.SetBitmap(image)
        else:
            self.bmp_item.SetBitmap(None)
        self.bmp_item.Thaw()

        # these prefixes are added here instead of in a tooltip
        # to improve visiblity. Tooltips also don't show up in
        # disabled items so we don't lose anything
        if button.option_type == 'Required':
            prefix = "=== This option is required ===\n\n"
        elif button.option_type == 'Recommended':
            prefix = "=== This option is recommended ===\n\n"
        elif button.option_type == 'CouldBeUsable':
            prefix = "=== This option could result in instability ===\n\n"
        elif button.option_type == 'NotUsable':
            prefix = "=== This option cannot be selected ===\n\n"
        else:
            prefix = ""
        self.text_item.SetValue(prefix + button.option_desc)

    def on_error(self, msg):
        msg += ("\nPlease ensure the fomod files are correct and "
                "contact the Wrye Bash Dev Team.")
        dialog = wx.MessageDialog(self, msg, caption="Warning",
                                  style=wx.OK | wx.CENTER | wx.ICON_EXCLAMATION)
        dialog.ShowModal()

    def on_next(self):
        answer = {}

        for group_sizer, options in self.group_option_map.iteritems():
            group_id = group_sizer.group_id
            group_name = group_sizer.group_name
            group_type = group_sizer.group_type
            answer[group_id] = [a.option_id for a in options if a.GetValue()]

            option_len = len(answer[group_id])
            if group_type == 'SelectExactlyOne' and option_len != 1:
                msg = ("Group \"{}\" should have exactly 1 option selected "
                       "but has {}.".format(group_name, option_len))
                self.on_error(msg)
            elif group_type == 'SelectAtMostOne' and option_len > 1:
                msg = ("Group \"{}\" should have at most 1 option selected "
                       "but has {}.".format(group_name, option_len))
                self.on_error(msg)
            elif group_type == 'SelectAtLeast' and option_len < 1:
                msg = ("Group \"{}\" should have at least 1 option selected "
                       "but has {}.".format(group_name, option_len))
                self.on_error(msg)
            elif group_type == 'SelectAll' and option_len != len(options):
                msg = ("Group \"{}\" should have all options selected "
                       "but has only {}.".format(group_name, option_len))
                self.on_error(msg)

        self.parent.parser.send(answer)


class PageFinish(PageInstaller):
    def __init__(self, parent):
        PageInstaller.__init__(self, parent)

        sizer_main = wx.FlexGridSizer(3, 1, 10, 10)
        label_title = wx.StaticText(self, wx.ID_ANY, "Files To Install",
                                    style=wx.ALIGN_CENTER)
        label_title.SetFont(wx.Font(12, wx.DEFAULT, wx.NORMAL, wx.NORMAL, 0, ""))
        sizer_main.Add(label_title, 0, wx.EXPAND)
        text_item = balt.RoTextCtrl(self, autotooltip=False, hscroll=True)
        text_item.SetFont(wx.Font(9, wx.MODERN, wx.NORMAL, wx.NORMAL, 0, ""))
        files_dict = self.parent._process_fomod_dict(self.parent.parser.collected_files)
        text_item.SetValue(self.display_files(files_dict))
        sizer_main.Add(text_item, 1, wx.EXPAND | wx.ALL)
        self.check_install = balt.checkBox(self, 'Install this package',
                                           onCheck=self.on_check,
                                           checked=self.parent.ret.install)
        sizer_main.Add(self.check_install, 1, wx.EXPAND | wx.ALL)

        sizer_main.AddGrowableRow(1)
        sizer_main.AddGrowableCol(0)

        self.SetSizer(sizer_main)
        self.Layout()

    def on_check(self):
        self.parent.ret.install = self.check_install.IsChecked()

    def GetNext(self):
        return None

    @staticmethod
    def display_files(file_dict):
        center_char = " -> "
        final_text = ""
        max_key_len = len(max(file_dict.keys(), key=len))
        max_value_len = len(max(file_dict.values(), key=len))
        for key, value in file_dict.iteritems():
            final_text += "{0:<{1}}{2}{3:<{4}}\n".format(value, max_value_len,
                                                         center_char, key, max_key_len)
        lines = final_text.split("\n")
        lines.sort(key=str.lower)
        final_text = "\n".join(lines)
        return final_text
