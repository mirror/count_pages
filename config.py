#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '2011, Grant Drake <grant.drake@gmail.com>'
__docformat__ = 'restructuredtext en'

import copy
from PyQt4.Qt import (QWidget, QGridLayout, QLabel, QPushButton, QUrl,
                      QGroupBox, QComboBox, QVBoxLayout, QCheckBox)

from calibre.gui2 import open_url
from calibre.utils.config import JSONConfig

from calibre_plugins.count_pages.common_utils import (get_library_uuid, CustomColumnComboBox,
                                     KeyboardConfigDialog, KeyValueComboBox, PrefsViewerDialog)

PREFS_NAMESPACE = 'CountPagesPlugin'
PREFS_KEY_SETTINGS = 'settings'

KEY_PAGES_CUSTOM_COLUMN = 'customColumnPages'
KEY_WORDS_CUSTOM_COLUMN = 'customColumnWords'
KEY_FLESCH_READING_CUSTOM_COLUMN = 'customColumnFleschReading'
KEY_FLESCH_GRADE_CUSTOM_COLUMN = 'customColumnFleschGrade'
KEY_GUNNING_FOG_CUSTOM_COLUMN = 'customColumnGunningFog'

KEY_BUTTON_DEFAULT = 'buttonDefault'
KEY_OVERWRITE_EXISTING = 'overwriteExisting'

STORE_NAME = 'Options'
KEY_PAGES_ALGORITHM = 'algorithmPages'

PAGE_ALGORITHMS = ['Paragraphs (APNX accurate)', 'E-book Viewer (calibre)', 'Adobe Digital Editions (ADE)']
BUTTON_DEFAULTS = {
                   'Estimate':      'Estimate page/word counts',
                   'Goodreads':     'Download page/word counts',
                  }

STATISTIC_PAGE_COUNT = 'PageCount'
STATISTIC_WORD_COUNT = 'WordCount'
STATISTIC_FLESCH_READING = 'FleschReading'
STATISTIC_FLESCH_GRADE = 'FleschGrade'
STATISTIC_GUNNING_FOG = 'GunningFog'
ALL_STATISTICS = {
                  STATISTIC_PAGE_COUNT: KEY_PAGES_CUSTOM_COLUMN,
                  STATISTIC_WORD_COUNT: KEY_WORDS_CUSTOM_COLUMN,
                  STATISTIC_FLESCH_READING: KEY_FLESCH_READING_CUSTOM_COLUMN,
                  STATISTIC_FLESCH_GRADE: KEY_FLESCH_GRADE_CUSTOM_COLUMN,
                  STATISTIC_GUNNING_FOG: KEY_GUNNING_FOG_CUSTOM_COLUMN
                 }

DEFAULT_STORE_VALUES = {
                        KEY_BUTTON_DEFAULT: 'Estimate',
                        KEY_OVERWRITE_EXISTING: True
                       }
DEFAULT_LIBRARY_VALUES = { KEY_PAGES_ALGORITHM: 0,
                           KEY_PAGES_CUSTOM_COLUMN: '',
                           KEY_WORDS_CUSTOM_COLUMN: '',
                           KEY_FLESCH_READING_CUSTOM_COLUMN: '',
                           KEY_FLESCH_GRADE_CUSTOM_COLUMN: '',
                           KEY_GUNNING_FOG_CUSTOM_COLUMN: '' }


KEY_SCHEMA_VERSION = 'SchemaVersion'
DEFAULT_SCHEMA_VERSION = 1.61


# This is where all preferences for this plugin will be stored
plugin_prefs = JSONConfig('plugins/Count Pages')

# Set defaults
plugin_prefs.defaults[STORE_NAME] = DEFAULT_STORE_VALUES


def migrate_library_config_if_required(db, library_config):
    schema_version = library_config.get(KEY_SCHEMA_VERSION, 0)
    if schema_version == DEFAULT_SCHEMA_VERSION:
        return
    # We have changes to be made - mark schema as updated
    library_config[KEY_SCHEMA_VERSION] = DEFAULT_SCHEMA_VERSION

    # Any migration code in future will exist in here.
    if schema_version < 1.61:
        if 'customColumn' in library_config:
            print('Migrating Count Pages plugin custom column for pages to new schema')
            library_config[KEY_PAGES_CUSTOM_COLUMN] = library_config['customColumn']
            del library_config['customColumn']
        store_prefs = plugin_prefs[STORE_NAME]
        if KEY_PAGES_ALGORITHM not in library_config:
            print('Migrating Count Pages plugin algorithm for pages to new schema')
            library_config[KEY_PAGES_ALGORITHM] = store_prefs.get('algorithm', 0)
            # Unfortunately cannot delete since user may have other libraries
        if 'algorithmWords' in store_prefs:
            print('Deleting Count Pages plugin word algorithm')
            del store_prefs['algorithmWords']
            plugin_prefs[STORE_NAME] = store_prefs

    set_library_config(db, library_config)


def get_library_config(db):
    library_id = get_library_uuid(db)
    library_config = None
    # Check whether this is a configuration needing to be migrated from json into database
    if 'libraries' in plugin_prefs:
        libraries = plugin_prefs['libraries']
        if library_id in libraries:
            # We will migrate this below
            library_config = libraries[library_id]
            # Cleanup from json file so we don't ever do this again
            del libraries[library_id]
            if len(libraries) == 0:
                # We have migrated the last library for this user
                del plugin_prefs['libraries']
            else:
                plugin_prefs['libraries'] = libraries

    if library_config is None:
        library_config = db.prefs.get_namespaced(PREFS_NAMESPACE, PREFS_KEY_SETTINGS,
                                                 copy.deepcopy(DEFAULT_LIBRARY_VALUES))
    migrate_library_config_if_required(db, library_config)
    return library_config

def set_library_config(db, library_config):
    db.prefs.set_namespaced(PREFS_NAMESPACE, PREFS_KEY_SETTINGS, library_config)


class AlgorithmComboBox(QComboBox):

    def __init__(self, parent, algorithms, selected_algorithm):
        QComboBox.__init__(self, parent)
        self.populate_combo(algorithms, selected_algorithm)

    def populate_combo(self, algorithms, selected_algorithm):
        self.clear()
        for item in algorithms:
            self.addItem(item)
        self.setCurrentIndex(selected_algorithm)


class ConfigWidget(QWidget):

    def __init__(self, plugin_action):
        QWidget.__init__(self)
        self.plugin_action = plugin_action
        layout = QVBoxLayout(self)
        self.setLayout(layout)

        c = plugin_prefs[STORE_NAME]
        avail_columns = self.get_custom_columns()
        library_config = get_library_config(self.plugin_action.gui.current_db)
        pages_algorithm = library_config.get(KEY_PAGES_ALGORITHM, DEFAULT_LIBRARY_VALUES[KEY_PAGES_ALGORITHM])
        button_default = c.get(KEY_BUTTON_DEFAULT, DEFAULT_STORE_VALUES[KEY_BUTTON_DEFAULT])
        # Fudge the button default to cater for the options no longer supported by plugin as of 1.5
        if button_default in ['Estimate', 'EstimatePage', 'EstimateWord']:
            button_default = 'Estimate'
        else:
            button_default = 'Goodreads'
        overwrite_existing = c.get(KEY_OVERWRITE_EXISTING, DEFAULT_STORE_VALUES[KEY_OVERWRITE_EXISTING])

        # --- Pages ---
        page_group_box = QGroupBox('Page count options:', self)
        layout.addWidget(page_group_box)
        page_group_box_layout = QGridLayout()
        page_group_box.setLayout(page_group_box_layout)

        page_column_label = QLabel('&Custom column:', self)
        page_column_label.setToolTip('Leave this blank if you do not want to count pages')
        page_col = library_config.get(KEY_PAGES_CUSTOM_COLUMN, '')
        self.page_column_combo = CustomColumnComboBox(self, avail_columns, page_col)
        page_column_label.setBuddy(self.page_column_combo)
        page_group_box_layout.addWidget(page_column_label, 0, 0, 1, 1)
        page_group_box_layout.addWidget(self.page_column_combo, 0, 1, 1, 2)

        page_algorithm_label = QLabel('&Algorithm:', self)
        page_algorithm_label.setToolTip('Choose which algorithm to use if you have specified a page count column')
        self.page_algorithm_combo = AlgorithmComboBox(self, PAGE_ALGORITHMS, pages_algorithm)
        page_algorithm_label.setBuddy(self.page_algorithm_combo)
        page_group_box_layout.addWidget(page_algorithm_label, 1, 0, 1, 1)
        page_group_box_layout.addWidget(self.page_algorithm_combo, 1, 1, 1, 2)

        # --- Words ---
        layout.addSpacing(5)
        word_group_box = QGroupBox('Word count options:', self)
        layout.addWidget(word_group_box)
        word_group_box_layout = QGridLayout()
        word_group_box.setLayout(word_group_box_layout)

        word_column_label = QLabel('C&ustom column:', self)
        word_column_label.setToolTip('Leave this blank if you do not want to count words')
        word_col = library_config.get(KEY_WORDS_CUSTOM_COLUMN, '')
        self.word_column_combo = CustomColumnComboBox(self, avail_columns, word_col)
        word_column_label.setBuddy(self.word_column_combo)
        word_group_box_layout.addWidget(word_column_label, 0, 0, 1, 1)
        word_group_box_layout.addWidget(self.word_column_combo, 0, 1, 1, 2)

        # --- Readability ---
        layout.addSpacing(5)
        readability_group_box = QGroupBox('Readability options:', self)
        layout.addWidget(readability_group_box)
        readability_layout = QGridLayout()
        readability_group_box.setLayout(readability_layout)

        readability_label = QLabel('Readability statistics available are <a href="http://en.wikipedia.org/wiki/Flesch–Kincaid_readability_test">Flesch-Kincaid</a> '
                                   'or <a href="http://en.wikipedia.org/wiki/Gunning_fog_index">Gunning Fog Index</a>.', self)
        readability_layout.addWidget(readability_label, 0, 0, 1, 3)
        readability_label.linkActivated.connect(self._link_activated)

        flesch_reading_column_label = QLabel('&Flesch Reading Ease:', self)
        flesch_reading_column_label.setToolTip('Specify the custom column to store a computed Flesch Reading Ease score.\n'
                                     'Leave this blank if you do not want to calculate it')
        flesch_reading_col = library_config.get(KEY_FLESCH_READING_CUSTOM_COLUMN, '')
        self.flesch_reading_column_combo = CustomColumnComboBox(self, avail_columns, flesch_reading_col)
        flesch_reading_column_label.setBuddy(self.flesch_reading_column_combo)
        readability_layout.addWidget(flesch_reading_column_label, 1, 0, 1, 1)
        readability_layout.addWidget(self.flesch_reading_column_combo, 1, 1, 1, 2)

        flesch_grade_column_label = QLabel('Flesch-&Kincaid Grade:', self)
        flesch_grade_column_label.setToolTip('Specify the custom column to store a computed Flesch-Kincaid Grade Level score.\n'
                                     'Leave this blank if you do not want to calculate it')
        flesch_grade_col = library_config.get(KEY_FLESCH_GRADE_CUSTOM_COLUMN, '')
        self.flesch_grade_column_combo = CustomColumnComboBox(self, avail_columns, flesch_grade_col)
        flesch_grade_column_label.setBuddy(self.flesch_grade_column_combo)
        readability_layout.addWidget(flesch_grade_column_label, 2, 0, 1, 1)
        readability_layout.addWidget(self.flesch_grade_column_combo, 2, 1, 1, 2)

        gunning_fog_column_label = QLabel('&Gunning Fox Index:', self)
        gunning_fog_column_label.setToolTip('Specify the custom column to store a computed Gunning Fog Index score.\n'
                                     'Leave this blank if you do not want to calculate it')
        gunning_fog_col = library_config.get(KEY_GUNNING_FOG_CUSTOM_COLUMN, '')
        self.gunning_fog_column_combo = CustomColumnComboBox(self, avail_columns, gunning_fog_col)
        gunning_fog_column_label.setBuddy(self.gunning_fog_column_combo)
        readability_layout.addWidget(gunning_fog_column_label, 3, 0, 1, 1)
        readability_layout.addWidget(self.gunning_fog_column_combo, 3, 1, 1, 2)

        # --- Other options ---
        layout.addSpacing(5)
        other_group_box = QGroupBox('Other options:', self)
        layout.addWidget(other_group_box)
        other_group_box_layout = QGridLayout()
        other_group_box.setLayout(other_group_box_layout)

        button_default_label = QLabel('&Button default:', self)
        button_default_label.setToolTip('If plugin is placed as a toolbar button, choose a default action when clicked on')
        self.button_default_combo = KeyValueComboBox(self, BUTTON_DEFAULTS, button_default)
        button_default_label.setBuddy(self.button_default_combo)
        other_group_box_layout.addWidget(button_default_label, 0, 0, 1, 1)
        other_group_box_layout.addWidget(self.button_default_combo, 0, 1, 1, 2)

        self.overwrite_checkbox = QCheckBox('Always overwrite an existing word/page count', self)
        self.overwrite_checkbox.setToolTip('Uncheck this option if you have manually populated values in\n'
                                           'either of your page/word custom columns, and never want the\n'
                                           'plugin to overwrite it. Acts as a convenience option for users\n'
                                           'who have the toolbar button configured to populate both page\n'
                                           'and word count, but for some books have already assigned values\n'
                                           'into a column and just want the zero/blank column populated.')
        self.overwrite_checkbox.setChecked(overwrite_existing)
        other_group_box_layout.addWidget(self.overwrite_checkbox, 1, 0, 1, 3)

        keyboard_shortcuts_button = QPushButton('Keyboard shortcuts...', self)
        keyboard_shortcuts_button.setToolTip(_(
                    'Edit the keyboard shortcuts associated with this plugin'))
        keyboard_shortcuts_button.clicked.connect(self.edit_shortcuts)
        view_prefs_button = QPushButton('&View library preferences...', self)
        view_prefs_button.setToolTip(_(
                    'View data stored in the library database for this plugin'))
        view_prefs_button.clicked.connect(self.view_prefs)
        layout.addWidget(keyboard_shortcuts_button)
        layout.addWidget(view_prefs_button)
        layout.addStretch(1)

    def save_settings(self):
        new_prefs = {}
        new_prefs[KEY_BUTTON_DEFAULT] = self.button_default_combo.selected_key()
        new_prefs[KEY_OVERWRITE_EXISTING] = self.overwrite_checkbox.isChecked()
        plugin_prefs[STORE_NAME] = new_prefs

        db = self.plugin_action.gui.current_db
        library_config = get_library_config(db)
        library_config[KEY_PAGES_ALGORITHM] = self.page_algorithm_combo.currentIndex()
        library_config[KEY_PAGES_CUSTOM_COLUMN] = self.page_column_combo.get_selected_column()
        library_config[KEY_WORDS_CUSTOM_COLUMN] = self.word_column_combo.get_selected_column()
        library_config[KEY_FLESCH_READING_CUSTOM_COLUMN] = self.flesch_reading_column_combo.get_selected_column()
        library_config[KEY_FLESCH_GRADE_CUSTOM_COLUMN] = self.flesch_grade_column_combo.get_selected_column()
        library_config[KEY_GUNNING_FOG_CUSTOM_COLUMN] = self.gunning_fog_column_combo.get_selected_column()
        set_library_config(db, library_config)

    def get_custom_columns(self):
        column_types = ['float','int']
        custom_columns = self.plugin_action.gui.library_view.model().custom_columns
        available_columns = {}
        for key, column in custom_columns.iteritems():
            typ = column['datatype']
            if typ in column_types:
                available_columns[key] = column
        return available_columns

    def _link_activated(self, url):
        open_url(QUrl(url))

    def edit_shortcuts(self):
        d = KeyboardConfigDialog(self.plugin_action.gui, self.plugin_action.action_spec[0])
        if d.exec_() == d.Accepted:
            self.plugin_action.gui.keyboard.finalize()

    def view_prefs(self):
        d = PrefsViewerDialog(self.plugin_action.gui, PREFS_NAMESPACE)
        d.exec_()
