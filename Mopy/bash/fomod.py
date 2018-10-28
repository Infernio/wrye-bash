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


""" Fomod installer

FomodInstaller - the actual class that does all the work. More docs in the docstring

MissingDependency - raised whenever a dependencies tag is not met. Can be used
                    to provide more info about the dependency to the user

ChainMap - a similar enough implementation to python 3's ChainMap

NestedChainMap - similar to ChainMap, but allows the flattening to affect
                 a dictionary nested one level deep.

_assert_dependencies - checks if the dependencies tag is met, or raise

_collect_files - collects the files to be installed in a chainmap

_collect_flags - collects the altered flags in a chainmap
"""

import os
import uuid

from collections import OrderedDict, MutableMapping
from distutils.version import LooseVersion
from xml.etree import ElementTree as etree

from .bolt import Path
from .load_order import cached_is_active


class MissingDependency(Exception):
    """
    Exception raised whenever there is a missing dependency
    in a dependency network related element container.
    """
    def __init__(self, type_, expected, actual):
        msg = type_ + " dependency not met. "
        if type_ == 'Version':
            msg += "Game version is " + actual
            msg += ", " + expected + " or newer is required."
        elif type_ == 'File':
            msg += actual + " should be " + expected + "."
        elif type_ == "Flag":
            msg += "Expected value of " + expected
            msg += " instead of " + actual
        else:
            raise ValueError('Unexpected dependency type.')
        super(MissingDependency, self).__init__(self, msg)


class ChainMap(MutableMapping):
    def __init__(self, *maps):
        '''Initialize a ChainMap by setting *maps* to the given mappings.
        If no mappings are provided, a single empty dictionary is used.
        '''
        self.maps = list(maps) or [{}]  # always at least one map

    def __missing__(self, key):
        raise KeyError(key)

    def __getitem__(self, key):
        for mapping in self.maps:
            try:
                return mapping[key]
            except KeyError:
                pass
        return self.__missing__(key)

    def get(self, key, default=None):
        return self[key] if key in self else default

    def __len__(self):
        return len(set().union(*self.maps))

    def __iter__(self):
        d = {}
        for mapping in reversed(self.maps):
            d.update(mapping)
        return iter(d)

    def __setitem__(self, key, value):
        self.maps[0][key] = value

    def __delitem__(self, key):
        try:
            del self.maps[0][key]
        except KeyError:
            raise KeyError(
                    'Key not found in the first mapping: {!r}'.format(key))


class _NestedChainMap(ChainMap):
    """
    Subclass of stdlib's ChainMap that allows chaining nested dictionaries
    one level deep only.
    """
    def __getitem__(self, key):
        values = []
        for mapping in self.maps:
            try:
                values.append(mapping[key])
            except KeyError:
                pass

        if not values:
            raise KeyError(key)

        if not isinstance(values[0], dict):
            return values[0]
        result = {}
        for value in reversed(values):
            if isinstance(value, dict):
                result.update(value)
        return result


def _assert_dependencies(depend, flag_states, dest=None, game_version=None):
    """
    Runs through all dependencies in **depend** and if it is found to be
    lacking, MissingDependency is raised. **And** operators are shortcut
    while **Or** operators must be looked at all the way.

    Anything that the user doesn't provide is assumed to be met.
    """
    if depend is None:
        return
    operator = depend.get('operator', 'And')

    checks = depend.findall('*')
    missed_dep_num = 0

    for check in checks:
        missed_dep = ()

        if check.tag == 'gameDependency':
            if game_version is None:
                continue
            if LooseVersion(game_version) < LooseVersion(check.get('version')):
                missed_dep = ('Version', check.get('version'), game_version)
                missed_dep_num += 1

        elif check.tag == 'fileDependency':
            if dest is None:
                continue
            else:
                file_state = os.path.exists(os.path.join(dest.s,
                                                         check.get('file')))
                if check.get('state') == 'Missing' and file_state:
                    missed_dep = ('File', 'missing', check.get('file'))
                    missed_dep_num += 1
                else:
                    is_active = cached_is_active(Path(check.get('file')))
                    if check.get('state') == 'Active' and not is_active:
                        missed_dep = ('File',
                                      check.get('state').lower(),
                                      check.get('file'))
                        missed_dep_num += 1
                    elif check.get('state') == 'Inactive' and is_active:
                        missed_dep = ('File',
                                      check.get('state').lower(),
                                      check.get('file'))
                        missed_dep_num += 1

        elif check.tag == 'flagDependency':
            if check.get('value') != flag_states.get(check.get('flag'), ''):
                missed_dep = ('Flag',
                              check.get('value'),
                              flag_states.get(check.get('flag'), ''))
                missed_dep_num += 1

        elif check.tag == 'dependencies':
            _assert_dependencies(check, flag_states, dest, game_version)

        # short-circuiting
        if operator == 'And' and missed_dep:
            raise MissingDependency(*missed_dep)

    if operator == 'Or' and missed_dep_num == len(checks):
        raise MissingDependency(*missed_dep)


def _collect_files(file_list, collected_files):
    """
    Collects all files from **file_list** and adds them to **collected_files**
    chain mapping. If **file_list** is ``None``, add an empty dict anyway to
    keep parity among install steps (no need to track which install steps added
    files this way).
    """
    file_dict = {}

    if file_list is not None:
        items = file_list.findall('*')

        for item in items:
            source = item.get('source')
            if source.endswith(("/", "\\")):
                source = source[:-1]
            dest = item.get('destination', '')
            prio = item.get('priority', '0')
            prio_dict = file_dict.get(prio, {})
            if item.tag == "file" and (not dest or dest.endswith(("/", "\\"))):
                # if empty or with a trailing slash then dest refers
                # to a folder. Post-processing to add the filename to the
                # end of the path.
                dest = Path(dest).join(Path(source).tail).s
            prio_dict[source] = dest
            file_dict[prio] = prio_dict

    collected_files.maps.insert(0, file_dict)


def _collect_flags(flag_list, flag_states):
    """
    Much like ``_collect_files`` above, except with flags.
    """
    flag_dict = {}
    if flag_list is not None:
        flags = flag_list.findall('*')
        for flag in flags:
            flag_dict[flag.get('name')] = flag.text or ''
    flag_states.maps.insert(0, flag_dict)


def _explicit_list(root):
    """
    Very simply, return a list of all elements below **root**,
    excluding comments.
    """
    if root is None:
        return []
    return root.findall('*')


def _ordered_list(root):
    """
    Returns a list of all element with an attribute ``"name"`` under root
    which must contain an attribute ``"order"`` which determines the order
    of the list.
    """
    if root is None:
        return []
    order = root.get('order', 'Ascending')
    if order == 'Explicit':
        return _explicit_list(root)
    elif order == 'Ascending':
        reverse = False
    else:
        reverse = True
    return sorted(root.findall('*'),
                  key=lambda x: x.get('name'),
                  reverse=reverse)


class FomodInstaller(object):
    """
    Creates an installer for the fomod in **source**.

    **dest** should be the target destination directory where the mod will be
    installed and **game_version** the game version. These three arguments are
    all optional.

    If **dest** is not provided, all *fileDependency* tags are assumed to be
    met (meaning it will be ignored and never raise `MissingDependency`).
    The same can be applied to **game_version** and *gameDependency*.

    The following pseudo-code illustrates basic usage::

        >>> from ... import FomodInstaller, MissingDependency
        >>> fomod = 'path/to/fomod'
        >>> target = 'path/to/target'
        >>> game_version = '1.0.0'
        >>> installer = FomodInstaller(fomod, target, game_version)
        >>> # prime it (checking for dependencies, first item collection, etc.)
        >>> try:
        ...     installer.send(None)
        ... except MissingDependency:
        ...     # handle missing dependency
        ...
        >>> while True:
        ...     step = next(installer)
        ...     # check if finished
        ...     if is_finished(step):
        ...         break
        ...     # process info in step
        ...     # make group and plugin choices
        ...     if user_requested(previous_step):
        ...         # if you need to go back to a previous step
        ...         # just send this dict as answer
        ...         installer.send({'previous_step': True})
        ...     else:
        ...         # when you're done processing, send the resulting answer
        ...         installer.send(answer)
        ...
        >>> # whenever the loop exits the installer is done

    When the installer is primed you should always check for missing
    dependencies on *moduleDependencies* and handle the exception in some way.

    If any exception is raised by this object, the installer is completely
    stopped and considered finished. You'll need to restart the installer by
    re-instancing this class.

    The example loop provides you with a ``step`` variable. This variable is a
    dictionary that holds all the required info for each installation step.
    An example of this::

        {'name': 'Step Name',
         'groups': [{'name': 'Group Name',
                     'id': 'Unique Group ID',
                     'type': 'Group Type',
                     'plugins': [{'name': 'Plugin Name',
                                  'id': 'Unique Plugin ID',
                                  'description': 'Plugin Description',
                                  'image': 'path/to/plugin/image.png',
                                  'type': 'Plugin Type'},
                                 ...]}
                    ...]}

    The user's choices should be comunicated through the ``send`` method of the
    installer.

    To request a previous step the answer should take the form of the dict::

        {'previous_step': True}

    Be aware that the installer will interpret it a request for a previous step
    whenever that specific mapping is included in the answer, regardless of
    other content.

    To answer with the user's choices of plugins, a dictionary of this form
    should be sent::

        {'Group ID': ['Plugin ID', 'Plugin ID', ...],
         ...}

    With each ``id`` corresponding to a user's choice (or in the case of group
    ID, the group in which the choice is present). Care should be taken for
    group and plugin types.

    The mod's metadata can be accessed through several properties of the
    installer. The properties `FomodInstaller.flag_states` and
    `FomodInstaller.collected_files` can be accessed at any time before, during or
    after the installation process to keep track of flag and file changes,
    respectively.
    """
    def __init__(self, info_path, conf_path, dest=None, game_version=None):
        # read metadata
        conf_tree = etree.parse(conf_path)
        self._name = conf_tree.findtext('moduleName', '').strip()
        elem_image = conf_tree.find('moduleImage')
        if elem_image is None:
            self._image = ''
        else:
            self._image = elem_image.get('path', '')
        if info_path is not None:  # info.xml is optional - has only metadata
            info_tree = etree.parse(info_path)
            self._author = info_tree.findtext('Author', '').strip()
            self._version = info_tree.findtext('Version', '').strip()
            self._description = info_tree.findtext('Description', '').strip()
            self._website = info_tree.findtext('Website', '').strip()
        else:
            self._author = ""
            self._version = ""
            self._description = ""
            self._website = ""

        # setup the installer
        self.gen = self._installer(conf_tree, dest, game_version)
        self.send = self.gen.send

        # setup flags and files chain maps
        self._flag_states = ChainMap()
        self._collected_files = _NestedChainMap()
        self._collected_files_cfi = _NestedChainMap()  # for conditionalfileinstalls

    @property
    def name(self):
        """
        str: Returns the name of the mod.
        """
        return self._name

    @property
    def author(self):
        """
        str: Returns the author of the mod.
        """
        return self._author

    @property
    def version(self):
        """
        str: Returns the version of the mod.
        """
        return self._version

    @property
    def description(self):
        """
        str: Returns the description of the mod.
        """
        return self._description

    @property
    def website(self):
        """
        str: Returns the website of the mod.
        """
        return self._website

    @property
    def image(self):
        """
        str: Returns the cover image of the mod.
        """
        return self._image

    @property
    def flag_states(self):
        """
        A dictionary with the current mapping of ("flag name": "flag value").
        """
        return dict(self._flag_states)

    @property
    def collected_files(self):
        """
        A dictionary with the current mapping of
        ("file/folder source": "destination").
        """
        map_copy = _NestedChainMap(*self._collected_files_cfi.maps + self._collected_files.maps)
        sorted_keys = sorted(map_copy.keys(), reverse=True)
        final = ChainMap()
        for key in sorted_keys:
            final.maps.append(map_copy[key])
        return dict(final)

    def __iter__(self):
        return self.gen

    def next(self):
        return next(self.gen)

    def _installer(self, root, dest, game_version):
        """
        install steps should be processed in a "x yield x/yield" pattern

        handle metadata in init.

        -> start
        assert dependencies are ok (raise MissingDependencies otherwise) ...
        collect requiredInstallFiles ...
        yield
        install_step_list = ...
        index = 0
        while True:
            try:
                while True:
                    index += 1
                    if install_step_is_visible(install_step_list[index], ...):
                        break
            except IndexError:
                # when install steps are over
                process conditionalFileInstalls ...
                answer = yield {'finished': True}
                yield
            else:
                answer = yield install_step_list[index]
                # stop here so .send() returns nothing and loop can work.
                yield
            if user_requested_previous_step:
                index = previous_index
                # pop off latest flags and files
                continue
            previous_index = index
            process answer ...
        -> end
        """

        _assert_dependencies(root.find('moduleDependencies'),
                             self.flag_states,
                             dest,
                             game_version)

        _collect_files(root.find('requiredInstallFiles'),
                       self._collected_files)
        # stop here to allow user to catch raised missing dependencies
        yield

        step_list = _ordered_list(root.find('installSteps'))
        previous_index = [0]
        index = -1
        while True:
            # get next visible index
            try:
                while True:
                    index += 1
                    try:
                        _assert_dependencies(step_list[index].find('visible'),
                                             self._flag_states,
                                             dest,
                                             game_version)
                    except MissingDependency:
                        pass
                    else:
                        break
            except IndexError:
                # when install steps are over
                # process conditionalFileInstalls
                pattern_list = _explicit_list(root.find('conditionalFile'
                                                        'Installs/patterns'))
                for pattern in pattern_list:
                    try:
                        _assert_dependencies(pattern.find('dependencies'),
                                             self._flag_states,
                                             dest,
                                             game_version)
                    except MissingDependency:
                        pass
                    else:
                        _collect_files(pattern.find('files'),
                                       self._collected_files_cfi)
                answer = yield {'finished': True}
                yield
            else:

                # id -> plugin element dictionary
                id_dict = {}

                # step processing
                step_dict = {'name': step_list[index].get('name'), 'groups': []}
                groups = _ordered_list(step_list[index].find('optionalFileGroups'))

                # group processing
                for group in groups:
                    group_dict = {'name': group.get('name'),
                                  'type': group.get('type'),
                                  'id': str(uuid.uuid4()),
                                  'plugins': []}
                    plugins = _ordered_list(group.find('plugins'))

                    # plugin processing
                    for plugin in plugins:
                        plugin_dict = {}
                        plugin_dict['id'] = str(uuid.uuid4())
                        plugin_dict['name'] = plugin.get('name')
                        description = plugin.findtext('description', '').strip()
                        plugin_dict['description'] = description

                        image = plugin.find('image')
                        if image is not None:
                            plugin_dict['image'] = image.get('path')
                        else:
                            plugin_dict['image'] = ''

                        type_elem = plugin.find('typeDescriptor')
                        plugin_type = type_elem.find('type')
                        if plugin_type is not None:
                            plugin_dict['type'] = plugin_type.get('name')
                        else:
                            default_type = type_elem.find('dependencyType/de'
                                                          'faultType').get('name')
                            patterns = type_elem.find('dependencyType/patterns')
                            pattern_list = _explicit_list(patterns)
                            for pattern in pattern_list:
                                try:
                                    _assert_dependencies(
                                        pattern.find('dependencies'),
                                        self._flag_states,
                                        dest,
                                        game_version)
                                except MissingDependency:
                                    pass
                                else:
                                    plugin_dict['type'] = \
                                        pattern.find('type').get('name')
                                    break
                            else:
                                plugin_dict['type'] = default_type

                        group_dict['plugins'].append(plugin_dict)
                        id_dict[plugin_dict['id']] = plugin

                    step_dict['groups'].append(group_dict)

                answer = yield step_dict
                yield

            # check if previous step was requested
            if answer.pop('previous_step', False):
                try:
                    index = previous_index.pop() - 1
                except IndexError:
                    index = -1
                # pop off latest flags and files
                # no need to check if last step added any of this
                # because an empty dict will be added to the chainmap anyway
                if len(self._flag_states.maps) > 1:
                    self._flag_states.maps.pop(0)
                if len(self._collected_files.maps) > 2:  # first + reqinstfiles
                    self._collected_files.maps.pop(0)
                continue
            previous_index.append(index)

            # sort groups and plugins in answer
            def from_id(dict_, type_, id_):
                """
                Grabs group/plugin from step_dict via id.
                """
                return next(a for a in dict_[type_] if a['id'] == id_)

            def id_sort(dict_, type_, id_):
                """
                Sorts out plugins/groups via id.
                """
                elem = from_id(dict_, type_, id_)
                return dict_[type_].index(elem)

            for group_id in answer:
                group = from_id(step_dict, 'groups', group_id)
                answer[group_id] = list(set(answer[group_id]))
                answer[group_id] = sorted(answer[group_id],
                                          key=lambda x: id_sort(group,
                                                                'plugins',
                                                                x))
            answer = OrderedDict(sorted(answer.items(),
                                        key=lambda x: id_sort(step_dict,
                                                              'groups',
                                                              x[0])))

            # collect files and flags
            step_file_chain = _NestedChainMap()
            step_flag_chain = ChainMap()
            for plugin_ids in answer.values():
                for plugin_id in plugin_ids:
                    _collect_files(id_dict[plugin_id].find('files'),
                                   step_file_chain)
                    _collect_flags(id_dict[plugin_id].find('conditionFlags'),
                                   step_flag_chain)
            self._collected_files.maps.insert(0, dict(step_file_chain))
            self._flag_states.maps.insert(0, dict(step_flag_chain))

