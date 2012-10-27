#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__ = 'GPL v3'
__copyright__ = '2011, Grant Drake <grant.drake@gmail.com>'
__docformat__ = 'restructuredtext en'

import os, traceback, time

from calibre.customize.ui import quick_metadata
from calibre.ebooks import DRMError
from calibre.ptempfile import cleanup
from calibre.utils.ipc.server import Server
from calibre.utils.ipc.job import ParallelJob

import calibre_plugins.count_pages.config as cfg
from calibre_plugins.count_pages.download import GoodreadsPagesWorker
from calibre_plugins.count_pages.statistics import (get_page_count, get_pdf_page_count,
                                    get_word_count, get_text_analysis, get_gunning_fog_index,
                                    get_flesch_reading_ease, get_flesch_kincaid_grade_level,
                                    get_cbr_page_count, get_cbz_page_count)

def do_count_statistics(books_to_scan, pages_algorithm, use_goodreads,
                        nltk_pickle, cpus, notification=lambda x, y:x):
    '''
    Master job, to launch child jobs to count pages in this list of books
    '''
    server = Server(pool_size=cpus)

    # Queue all the jobs
    for book_id, title, book_path, goodreads_id, statistics_to_run in books_to_scan:
        args = ['calibre_plugins.count_pages.jobs', 'do_statistics_for_book',
                (book_path, pages_algorithm, goodreads_id,
                 use_goodreads, statistics_to_run, nltk_pickle)]
        job = ParallelJob('arbitrary', str(book_id), done=None, args=args)
        job._book_id = book_id
        job._title = title
        job._pages_algorithm = pages_algorithm
        job._goodreads_id = goodreads_id
        job._use_goodreads = use_goodreads
        job._statistics_to_run = statistics_to_run
        server.add_job(job)

    # This server is an arbitrary_n job, so there is a notifier available.
    # Set the % complete to a small number to avoid the 'unavailable' indicator
    notification(0.01, 'Counting Statistics')

    # dequeue the job results as they arrive, saving the results
    total = len(books_to_scan)
    count = 0
    book_stats_map = dict()
    while True:
        job = server.changed_jobs_queue.get()
        # A job can 'change' when it is not finished, for example if it
        # produces a notification. Ignore these.
        job.update()
        if not job.is_finished:
            continue
        # A job really finished. Get the information.
        results = job.result
        book_id = job._book_id
        book_stats_map[book_id] = results
        count = count + 1
        notification(float(count) / total, 'Counting Statistics')

        # Add this job's output to the current log
        print('-------------------------------')
        print('Logfile for book ID %d (%s)' % (book_id, job._title))

        for stat in job._statistics_to_run:
            if stat == cfg.STATISTIC_PAGE_COUNT:
                if job._use_goodreads:
                    if job._goodreads_id is not None:
                        if stat in results and results[stat]:
                            print('\tGoodreads edition has %d pages' % results[stat])
                        else:
                            print('\tFAILED TO GET PAGE COUNT FROM GOODREADS')
                else:
                    if stat in results and results[stat]:
                        print('\tFound %d pages' % results[stat])
            elif stat == cfg.STATISTIC_WORD_COUNT:
                if stat in results and results[stat]:
                    print('\tFound %d words' % results[stat])
            elif stat == cfg.STATISTIC_FLESCH_READING:
                if stat in results and results[stat]:
                    print('\tComputed %.1f Flesch Reading' % results[stat])
            elif stat == cfg.STATISTIC_FLESCH_GRADE:
                if stat in results and results[stat]:
                    print('\tComputed %.1f Flesch-Kincaid Grade' % results[stat])
            elif stat == cfg.STATISTIC_GUNNING_FOG:
                if stat in results and results[stat]:
                    print('\tComputed %.1f Gunning Fog Index' % results[stat])

        print(job.details)

        if count >= total:
            # All done!
            break

    server.close()
    # return the map as the job result
    return book_stats_map


def do_statistics_for_book(book_path, pages_algorithm,
                           goodreads_id, use_goodreads, statistics_to_run,
                           nltk_pickle):
    '''
    Child job, to count statistics in this specific book
    '''
    results = {}
    try:
        iterator = None

        with quick_metadata:
            try:
                extension = ''
                is_comic = False
                if book_path:
                    extension = os.path.splitext(book_path)[1].lower()
                    is_comic = extension in ['.cbr', '.cbz']
                stats = list(statistics_to_run)
                if cfg.STATISTIC_PAGE_COUNT in stats:
                    pages = None
                    stats.remove(cfg.STATISTIC_PAGE_COUNT)
                    if use_goodreads:
                        if goodreads_id:
                            goodreads_worker = GoodreadsPagesWorker(goodreads_id)
                            pages = goodreads_worker.page_count
                    else:
                        if extension == '.pdf':
                            # As an optimisation for PDFs we will read the page count directly
                            pages = get_pdf_page_count(book_path)
                        elif extension == '.cbr':
                            pages = get_cbr_page_count(book_path)
                        elif extension == '.cbz':
                            pages = get_cbz_page_count(book_path)
                        else:
                            iterator, pages = get_page_count(iterator, book_path, pages_algorithm)
                    results[cfg.STATISTIC_PAGE_COUNT] = pages

                if is_comic:
                    if not (len(stats) == 1 and cfg.STATISTIC_PAGE_COUNT in stats):
                        print('Skipping non page count statistics for CBR/CBZ')
                else:
                    if cfg.STATISTIC_WORD_COUNT in stats:
                        stats.remove(cfg.STATISTIC_WORD_COUNT)
                        iterator, words = get_word_count(iterator, book_path)
                        if words == 0:
                            # Something dodgy about the conversion - no point in calculating remaining stats
                            print('ERROR: No words found in this book (conversion error?), word count will not be stored')
                            return results
                        results[cfg.STATISTIC_WORD_COUNT] = words

                    if stats:
                        # The remaining stats are all reading level based
                        # As an optimisation, we will run the text analysis once and
                        # then add the relevant results
                        iterator, text_analysis = get_text_analysis(iterator, book_path, nltk_pickle)
                        if text_analysis['wordCount'] == 0:
                            # Something dodgy about the conversion - no point in calculating remaining stats
                            print('ERROR: No words found in this book (conversion error?) - readability statistics will not be calculated')
                            return results
                        if cfg.STATISTIC_FLESCH_READING in statistics_to_run:
                            results[cfg.STATISTIC_FLESCH_READING] = get_flesch_reading_ease(text_analysis)
                        if cfg.STATISTIC_FLESCH_GRADE in statistics_to_run:
                            results[cfg.STATISTIC_FLESCH_GRADE] = get_flesch_kincaid_grade_level(text_analysis)
                        if cfg.STATISTIC_GUNNING_FOG in statistics_to_run:
                            results[cfg.STATISTIC_GUNNING_FOG] = get_gunning_fog_index(text_analysis)
            finally:
                if iterator:
                    iterator.__exit__()
                    iterator = None
                if book_path is not None:
                    if os.path.exists(book_path):
                        time.sleep(0.1)
                        cleanup(book_path)
        return results
    except DRMError:
        print('\tCannot read pages due to DRM Encryption')
        return results
    except:
        traceback.print_exc()
        return results

