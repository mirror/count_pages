#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '2011, Grant Drake <grant.drake@gmail.com>'
__docformat__ = 'restructuredtext en'

import os, traceback
from collections import OrderedDict
from PyQt4.Qt import QProgressDialog, QString, QTimer

from calibre.gui2 import warning_dialog
from calibre.gui2.convert.single import get_available_formats_for_book
from calibre.utils.config import prefs

import calibre_plugins.count_pages.config as cfg

class QueueProgressDialog(QProgressDialog):

    def __init__(self, gui, book_ids, tdir, statistics_cols_map,
                 pages_algorithm, use_goodreads, overwrite_existing, queue, db):
        QProgressDialog.__init__(self, '', QString(), 0, len(book_ids), gui)
        self.setWindowTitle('Queueing books for counting statistics')
        self.setMinimumWidth(500)
        self.book_ids, self.tdir, self.queue, self.db = book_ids, tdir, queue, db
        self.statistics_cols_map = statistics_cols_map
        self.pages_algorithm = pages_algorithm
        self.use_goodreads = use_goodreads
        self.overwrite_existing = overwrite_existing
        self.gui = gui
        self.i, self.books_to_scan = 0, []
        self.bad = OrderedDict()
        self.input_order = [f.lower() for f in prefs['input_format_order']]

        self.page_col_label = self.word_col_label = None
        self.labels_map = dict((col_name, db.field_metadata.key_to_label(col_name))
                               for col_name in statistics_cols_map.itervalues() if col_name)

        QTimer.singleShot(0, self.do_book)
        self.exec_()

    def do_book(self):
        book_id = self.book_ids[self.i]
        self.i += 1

        try:
            title = self.db.title(book_id, index_is_id=True)
            done = False

            statistics_to_run = []
            for statistic, col_name in self.statistics_cols_map.iteritems():
                if not col_name:
                    continue
                lbl = self.labels_map[col_name]
                existing_val = self.db.get_custom(book_id, label=lbl, index_is_id=True)
                if self.overwrite_existing or existing_val is None or existing_val == 0:
                    statistics_to_run.append(statistic)

            if not self.overwrite_existing:
                # Since we are not forcing overwriting an existing value we need
                # to check whether this book has an existing value in each column.
                # No point in performing statistics if book already has values.
                if not statistics_to_run:
                    self.bad[book_id] = 'Book already has all statistics and overwrite is turned off'
                    done = True

            goodreads_id = None
            if not done:
                if cfg.STATISTIC_PAGE_COUNT in statistics_to_run and self.use_goodreads:
                    # We will be attempting to download a page count from goodreads
                    identifiers = self.db.get_identifiers(book_id, index_is_id=True)
                    goodreads_id = identifiers.get('goodreads', None)
                    if not goodreads_id:
                        # No point in continuing with this book
                        self.bad[book_id] = 'No goodreads id'
                        done = True
                    elif len(statistics_to_run) == 1:
                        # Since not counting anything else, we have all we need at this point to continue
                        self.books_to_scan.append((book_id, title, None,
                                                   goodreads_id, statistics_to_run))
                        done = True

            if not done:
                found_format = False
                book_formats = get_available_formats_for_book(self.db, book_id)
                input_formats = [f for f in self.input_order if f in book_formats]
                for bf in input_formats:
                    if self.db.has_format(book_id, bf, index_is_id=True):
                        self.setLabelText(_('Queueing ')+title)
                        try:
                            # Copy the book to the temp directory, using book id as filename
                            dest_file = os.path.join(self.tdir, '%d.%s'%(book_id, bf.lower()))
                            with open(dest_file, 'w+b') as f:
                                self.db.copy_format_to(book_id, bf, f, index_is_id=True)
                            self.books_to_scan.append((book_id, title, dest_file,
                                                       goodreads_id, statistics_to_run))
                            found_format = True
                        except:
                            traceback.print_exc()
                            self.bad[book_id] = traceback.format_exc()
                        # Either found a format or book is bad - stop looking through formats
                        break

                # If we didn't find a compatible format, did we absolutely need one?
                if not found_format:
                    self.bad[book_id] = 'No convertible format found'
        except:
            traceback.print_exc()
            self.bad[book_id] = traceback.format_exc()

        self.setValue(self.i)
        if self.i >= len(self.book_ids):
            return self.do_queue()
        else:
            QTimer.singleShot(0, self.do_book)

    def do_queue(self):
        self.hide()
        if len(self.bad):
            res = []
            for book_id, error in self.bad.iteritems():
                title = self.db.title(book_id, True)
                res.append('%s (%s)'%(title, error))
            msg = '%s' % '\n'.join(res)
            summary_msg = 'Could not analyse %d of %d books, for reasons shown in details below.'
            warning_dialog(self.gui, 'Page/word/statistics warnings',
                summary_msg % (len(res), len(self.book_ids)), msg).exec_()
        self.gui = None
        # Queue a job to process these books
        self.queue(self.tdir, self.books_to_scan, self.statistics_cols_map,
                   self.pages_algorithm, self.use_goodreads)
