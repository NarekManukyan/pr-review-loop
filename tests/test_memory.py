#!/usr/bin/env python3
"""Tests for review-memory's `recall` relevance filtering (make_relevant).

Run:  python3 -m unittest discover -s tests -v
  or: python3 tests/test_memory.py

Stdlib only. The fixture mirrors the shape of a real 54-decision Flutter
corpus: every file lives under `lib/` and ends in `.dart`, so 'lib' and 'dart'
are structural (document frequency 54/54) while feature segments discriminate.
That is exactly the shape that broke the old `any(token in haystack)` filter.
"""
import importlib.util
import os
import sys
import unittest

_SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '..', 'payload', 'skills', 'review-memory', 'scripts')
_spec = importlib.util.spec_from_file_location(
    'memory', os.path.join(_SCRIPTS, 'memory.py'))
memory = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(memory)
make_relevant = memory.make_relevant


def _d(file, title, res='disputed', text='', kind=None, **kw):
    e = {'file': file, 'signature': f'{file}::{title}', 'title': title,
         'dev_resolution': res, 'text': text, 'area': file}
    if kind:
        e['kind'] = kind
    e.update(kw)
    return e


def build_corpus():
    """54 decisions across four feature areas, real-corpus shaped.

    27 storage_management (under user_profile/view/pages)
     9 meetings           (under meetings/view)
    11 recording          (the only ones mentioning 'state')
     7 misc
    """
    out = []
    for i in range(27):
        out.append(_d(
            f'lib/features/user_profile/view/pages/storage_management/storage_management_{i}.dart',
            f'storage finding {i}'))
    for i in range(9):
        out.append(_d(f'lib/features/meetings/view/meeting_player_page_{i}.dart',
                      f'meetings finding {i}'))
    for i in range(11):
        out.append(_d(f'lib/features/recording/recording_store_{i}.dart',
                      f'recording finding {i}', text='mobx state store'))
    for i in range(7):
        out.append(_d(f'lib/features/checkout/checkout_page_{i}.dart',
                      f'checkout finding {i}'))
    return out


def count(corpus, area, loose=False):
    pred = make_relevant(corpus, area, loose=loose)
    return sum(1 for e in corpus if pred(e))


def _old_count(corpus, area):
    """The pre-fix filter, kept only so the tests prove the regression."""
    import re
    tokens = [t.lower() for t in re.split(r'[\s,]+', area or '') if t]

    def rel(e):
        if not tokens:
            return True
        hay = (f"{e.get('file','')} {e.get('area','')} {e.get('signature','')} "
               f"{e.get('title','')} {e.get('text','')}").lower()
        return any(t in hay for t in tokens)
    return sum(1 for e in corpus if rel(e))


class TestMakeRelevant(unittest.TestCase):
    def setUp(self):
        self.corpus = build_corpus()
        self.assertEqual(len(self.corpus), 54)

    # 1. Empty --area still returns everything.
    def test_empty_area_returns_all(self):
        self.assertEqual(count(self.corpus, ''), 54)
        self.assertEqual(count(self.corpus, None), 54)

    # 2. A path-only area returns that feature's decisions — not 0, not all.
    #    This is the regression: the old filter never split paths, so a path
    #    that is not verbatim in the corpus substring-matched nothing -> 0.
    #    (No decision file is named exactly `meeting_player_page.dart`; the
    #    corpus has `meeting_player_page_<i>.dart`. Old filter: 0. New: 9.)
    def test_path_only_area_matches_feature_not_zero_not_all(self):
        area = 'lib/features/meetings/view/meeting_player_page.dart'
        self.assertEqual(_old_count(self.corpus, area), 0,
                         'fixture must reproduce the reported false negative')
        n = count(self.corpus, area)
        self.assertEqual(n, 9, 'should match exactly the meetings decisions')
        self.assertNotEqual(n, 0, 'regression: path-only area returned nothing')
        self.assertNotEqual(n, 54)

    def test_path_only_area_storage(self):
        self.assertEqual(
            count(self.corpus,
                  'lib/features/user_profile/view/pages/storage_management '
                  'storage_management_0.dart'),
            27)

    # 3. An area of mostly-generic tokens does NOT return the whole corpus:
    #    'dart'/'lib' are dropped by document frequency, 'state' discriminates.
    def test_generic_tokens_do_not_flood(self):
        n = count(self.corpus, 'dart lib state')
        self.assertEqual(n, 11, "only the 'state' decisions should match")
        self.assertLess(n, 54, 'regression: generic token selected whole corpus')

    def test_bare_keyword_area(self):
        self.assertEqual(count(self.corpus, 'storage_management'), 27)

    # 4. When nothing discriminating survives, fall back to everything
    #    rather than silently hiding memory.
    def test_all_generic_falls_back_to_all(self):
        self.assertEqual(count(self.corpus, 'dart lib'), 54)

    # 5. Watch items stay on the loose filter: a generic token still surfaces
    #    them even though the strict filter drops it.
    def test_loose_filter_surfaces_watch_items(self):
        watch = _d('lib/features/payments/payments_store.dart',
                   'human watch item', res='open', kind='watch')
        corpus = self.corpus + [watch]
        loose = make_relevant(corpus, 'dart', loose=True)
        strict = make_relevant(corpus, 'dart')
        self.assertTrue(loose(watch), 'watch item must survive the loose filter')
        # strict drops 'dart' (df 55/55) and falls back to True; the point is the
        # loose predicate matches on the raw token regardless of frequency.
        self.assertTrue(any(loose(e) for e in corpus))
        self.assertIsNotNone(strict)

    def test_loose_matches_substring_like_old_behaviour(self):
        loose = make_relevant(self.corpus, 'recording', loose=True)
        self.assertEqual(sum(1 for e in self.corpus if loose(e)), 11)

    # Guard the intent: no hardcoded stoplist — a segment is generic only
    # because THIS corpus says so. 'view' is generic here (36/54)...
    def test_generic_is_measured_not_hardcoded(self):
        self.assertEqual(count(self.corpus, 'lib/features/meetings/view/x_0.dart'), 9)
        # ...but in a corpus where 'view' is rare, it must discriminate.
        small = [_d('lib/view/only_here.dart', 'rare view finding')] + [
            _d(f'lib/features/other/other_{i}.dart', f'other {i}') for i in range(9)]
        self.assertEqual(count(small, 'lib/view/only_here.dart'), 1,
                         "'view' must discriminate when the corpus says it's rare")


if __name__ == '__main__':
    unittest.main(verbosity=2)
