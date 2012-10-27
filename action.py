#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)
from calibre_plugins.count_pages.config import ALL_STATISTICS

__license__   = 'GPL v3'
__copyright__ = '2011, Grant Drake <grant.drake@gmail.com>'
__docformat__ = 'restructuredtext en'

from functools import partial
from PyQt4.Qt import QToolButton, QMenu

from calibre.ebooks.metadata.book.base import Metadata
from calibre.gui2 import question_dialog
from calibre.gui2.actions import InterfaceAction
from calibre.gui2.dialogs.message_box import ErrorNotification
from calibre.ptempfile import PersistentTemporaryDirectory, remove_dir

import calibre_plugins.count_pages.config as cfg
from calibre_plugins.count_pages.common_utils import (set_plugin_icon_resources, get_icon,
                                                    create_menu_action_unique)
from calibre_plugins.count_pages.dialogs import QueueProgressDialog

PLUGIN_ICONS = ['images/count_pages.png','images/estimate.png','images/goodreads.png']

class CountPagesAction(InterfaceAction):

    name = 'Count Pages'
    # Create our top-level menu/toolbar action (text, icon_path, tooltip, keyboard shortcut)
    action_spec = ('Count Pages', None, 'Count the number of pages and/or words in a book\n'
                                        'to store in custom column(s)', ())
    popup_type = QToolButton.MenuButtonPopup
    action_type = 'current'

    def genesis(self):
        self.menu = QMenu(self.gui)
        # Read the plugin icons and store for potential sharing with the config widget
        icon_resources = self.load_resources(PLUGIN_ICONS)
        set_plugin_icon_resources(self.name, icon_resources)

        self.rebuild_menus()
        self.nltk_pickle = self._get_nltk_resource()

        # Assign our menu to this action and an icon
        self.qaction.setMenu(self.menu)
        self.qaction.setIcon(get_icon(PLUGIN_ICONS[0]))
        self.qaction.triggered.connect(self.toolbar_triggered)

    def rebuild_menus(self):
        m = self.menu
        m.clear()
        create_menu_action_unique(self, m, '&Estimate page/word counts', 'images/estimate.png',
                                  triggered=partial(self._count_pages_on_selected, 'Estimate'))
        create_menu_action_unique(self, m, '&Download page/word counts', 'images/goodreads.png',
                                  triggered=partial(self._count_pages_on_selected, 'Goodreads'))
        m.addSeparator()
        create_menu_action_unique(self, m, _('&Customize plugin')+'...', 'config.png',
                                  shortcut=False, triggered=self.show_configuration)
        self.gui.keyboard.finalize()

    def toolbar_triggered(self):
        c = cfg.plugin_prefs[cfg.STORE_NAME]
        mode = c.get(cfg.KEY_BUTTON_DEFAULT, cfg.DEFAULT_STORE_VALUES[cfg.KEY_BUTTON_DEFAULT])
        self._count_pages_on_selected(mode)

    def _get_nltk_resource(self):
        # Retrieve the english pickle file. Can't do it from within the nltk code
        # because of our funky situation of executing a plugin from a zip file.
        # So we retrieve it here and pass it through when executing jobs.
        ENGLISH_PICKLE_FILE = 'nltk_lite/english.pickle'
        pickle_data = self.load_resources([ENGLISH_PICKLE_FILE])[ENGLISH_PICKLE_FILE]
        return pickle_data

    def _count_pages_on_selected(self, mode):
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows or len(rows) == 0:
            return
        book_ids = self.gui.library_view.get_selected_ids()

        statistics_to_run = [k for k in ALL_STATISTICS.keys()]
        any_valid, statistics_cols_map = self._get_column_validity(statistics_to_run)
        if not any_valid:
            if not question_dialog(self.gui, 'Configure plugin', '<p>'+
                'You must specify custom column(s) first. Do you want to configure this now?',
                show_copy_button=False):
                return
            self.show_configuration()
            return
        use_goodreads = False
        if mode.startswith('Goodreads'):
            use_goodreads = True
        self._do_count_pages(book_ids, statistics_cols_map, use_goodreads)

    def _get_column_validity(self, statistics_to_run):
        '''
        Given a list of algorithms requested to be run, lookup what custom
        columns are configured and return a dict for each possible statistic
        and its associated custom column (blank if not to be run).
        '''
        db = self.gui.current_db
        all_cols = db.field_metadata.custom_field_metadata()

        library_config = cfg.get_library_config(db)
        statistics_cols_map = {}
        any_valid = False
        for statistic, statistic_col_key in cfg.ALL_STATISTICS.iteritems():
            col = library_config.get(statistic_col_key, '')
            is_requested = statistic in statistics_to_run
            is_valid = is_requested and len(col) > 0 and col in all_cols
            if not is_valid or not col:
                statistics_cols_map[statistic] = ''
            else:
                any_valid = True
                statistics_cols_map[statistic] = col
        return any_valid, statistics_cols_map

    def count_statistics(self, book_ids, statistics_to_run, use_goodreads=False):
        '''
        This function is designed to be called from other plugins
        Note that the statistics functions can only be used if a
        custom column has been configured by the user first.

          book_ids - list of calibre book ids to run the statistics against

          statistics_to_run - list of statistic names to be run. Possible values:
              'PageCount', 'WordCount', 'FleschReading', 'FleschGrade', 'GunningFog'

          use_goodreads - only applies to PageCount, whether to retrieve from
                          Goodreads rather than using an estimation algorithm.
                          Requires each book to have a goodreads identifier.
        '''
        if statistics_to_run is None or len(statistics_to_run) == 0:
            print('Page count called but neither page nor word count requested')
            return

        # Verify we have a custom column configured to store the page/word count in
        any_valid, statistics_cols_map = self._get_column_validity(statistics_to_run)
        if (not any_valid):
            if not question_dialog(self.gui, 'Configure plugin', '<p>'+
                'You must specify custom column(s) first. Do you want to configure this now?',
                show_copy_button=False):
                return
            self.show_configuration()
            return

        self._do_count_pages(book_ids, statistics_cols_map, use_goodreads)

    def _do_count_pages(self, book_ids, statistics_cols_map, use_goodreads):
        # Create a temporary directory to copy all the ePubs to while scanning
        tdir = PersistentTemporaryDirectory('_count_pages', prefix='')

        # Queue all the books and kick off the job
        c = cfg.plugin_prefs[cfg.STORE_NAME]
        db = self.gui.current_db
        library_config = cfg.get_library_config(db)
        pages_algorithm = library_config.get(cfg.KEY_PAGES_ALGORITHM,
                                cfg.DEFAULT_LIBRARY_VALUES[cfg.KEY_PAGES_ALGORITHM])
        overwrite_existing = c.get(cfg.KEY_OVERWRITE_EXISTING,
                                   cfg.DEFAULT_STORE_VALUES[cfg.KEY_OVERWRITE_EXISTING])
        QueueProgressDialog(self.gui, book_ids, tdir, statistics_cols_map,
                            pages_algorithm, use_goodreads,
                            overwrite_existing, self._queue_job, db)

    def _queue_job(self, tdir, books_to_scan, statistics_cols_map,
                   pages_algorithm, use_goodreads):
        if not books_to_scan:
            if tdir:
                # All failed so cleanup our temp directory
                remove_dir(tdir)
            return

        func = 'arbitrary_n'
        cpus = self.gui.job_manager.server.pool_size
        args = ['calibre_plugins.count_pages.jobs', 'do_count_statistics',
                (books_to_scan, pages_algorithm, use_goodreads,
                 self.nltk_pickle, cpus)]
        desc = 'Count Page/Word Statistics'
        job = self.gui.job_manager.run_job(
                self.Dispatcher(self._get_statistics_completed), func, args=args,
                    description=desc)
        job.tdir = tdir
        job.statistics_cols_map = statistics_cols_map
        job.use_goodreads = use_goodreads
        self.gui.status_bar.show_message('Counting statistics in %d books'%len(books_to_scan))

    def _get_statistics_completed(self, job):
        if job.tdir:
            remove_dir(job.tdir)
        if job.failed:
            return self.gui.job_exception(job, dialog_title='Failed to count statistics')
        self.gui.status_bar.show_message('Counting statistics completed', 3000)
        book_statistics_map = job.result

        if len(book_statistics_map) == 0:
            # Must have been some sort of error in processing this book
            msg = 'Failed to generate any statistics. <b>View Log</b> for details'
            p = ErrorNotification(job.details, 'Count log', 'Count Pages failed', msg,
                    show_copy_button=False, parent=self.gui)
            p.show()
        else:
            payload = (job.statistics_cols_map, book_statistics_map)
            all_ids = set(book_statistics_map.keys())
            msg = '<p>Count Pages plugin found <b>%d statistics(s)</b>. ' % len(all_ids) + \
                  'Proceed with updating columns in your library?'
            self.gui.proceed_question(self._update_database_columns,
                    payload, job.details,
                    'Count log', 'Count complete', msg,
                    show_copy_button=False)

    def _update_database_columns(self, payload):
        (statistics_cols_map, book_statistics_map) = payload

        db = self.gui.current_db
        custom_cols = db.field_metadata.custom_field_metadata()

        # At this point we want to re-use code in edit_metadata to go ahead and
        # apply the changes. So we will create empty Metadata objects so only
        # the custom column field gets updated
        id_map = {}
        for book_id, statistics in book_statistics_map.iteritems():
            mi = Metadata(_('Unknown'))
            for statistic, value in statistics.iteritems():
                col_name = statistics_cols_map[statistic]
                col = custom_cols[col_name]
                col['#value#'] = value
                mi.set_user_metadata(col_name, col)
            id_map[book_id] = mi

        edit_metadata_action = self.gui.iactions['Edit Metadata']
        edit_metadata_action.apply_metadata_changes(id_map)

    def show_configuration(self):
        self.interface_action_base_plugin.do_user_config(self.gui)
