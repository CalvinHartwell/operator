#!/usr/bin/python3

import os
import unittest
import tempfile
import shutil

from pathlib import Path

from ops.charm import (
    CharmBase,
    CharmMeta,
    CharmEvents,
)
from ops.framework import Framework, EventSource, EventBase
from ops.model import Model, ModelBackend

from .test_helpers import fake_script, fake_script_calls


class TestCharm(unittest.TestCase):

    def setUp(self):
        def restore_env(env):
            os.environ.clear()
            os.environ.update(env)
        self.addCleanup(restore_env, os.environ.copy())

        os.environ['PATH'] = f"{str(Path(__file__).parent / 'bin')}:{os.environ['PATH']}"
        os.environ['JUJU_UNIT_NAME'] = 'local/0'

        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.meta = CharmMeta()

        class CustomEvent(EventBase):
            pass

        class TestCharmEvents(CharmEvents):
            custom = EventSource(CustomEvent)

        # Relations events are defined dynamically and modify the class attributes.
        # We use a subclass temporarily to prevent these side effects from leaking.
        CharmBase.on = TestCharmEvents()

        def cleanup():
            CharmBase.on = CharmEvents()
        self.addCleanup(cleanup)

    def create_framework(self):
        model = Model('local/0', self.meta, ModelBackend())
        framework = Framework(self.tmpdir / "framework.data", self.tmpdir, self.meta, model)
        self.addCleanup(framework.close)
        return framework

    def test_basic(self):

        class MyCharm(CharmBase):

            def __init__(self, *args):
                super().__init__(*args)

                self.started = False
                framework.observe(self.on.start, self)

            def on_start(self, event):
                self.started = True

        events = list(MyCharm.on.events())
        self.assertIn('install', events)
        self.assertIn('custom', events)

        framework = self.create_framework()
        charm = MyCharm(framework, None)
        charm.on.start.emit()

        self.assertEqual(charm.started, True)

    def test_relation_events(self):

        class MyCharm(CharmBase):
            def __init__(self, *args):
                super().__init__(*args)
                self.seen = []
                for rel in ('req1', 'req-2', 'pro1', 'pro-2', 'peer1', 'peer-2'):
                    # Hook up relation events to generic handler.
                    self.framework.observe(self.on[rel].relation_joined, self.on_any_relation)
                    self.framework.observe(self.on[rel].relation_changed, self.on_any_relation)
                    self.framework.observe(self.on[rel].relation_departed, self.on_any_relation)
                    self.framework.observe(self.on[rel].relation_broken, self.on_any_relation)

            def on_any_relation(self, event):
                assert event.relation.name == 'req1'
                assert event.relation.app.name == 'remote'
                self.seen.append(type(event).__name__)

        self.meta = CharmMeta({
            'name': 'my-charm',
            'requires': {
                'req1': {'interface': 'req1'},
                'req-2': {'interface': 'req2'},
            },
            'provides': {
                'pro1': {'interface': 'pro1'},
                'pro-2': {'interface': 'pro2'},
            },
            'peers': {
                'peer1': {'interface': 'peer1'},
                'peer-2': {'interface': 'peer2'},
            },
        })

        charm = MyCharm(self.create_framework(), None)

        rel = charm.framework.model.get_relation('req1', 1)
        unit = charm.framework.model.get_unit('remote/0')
        charm.on['req1'].relation_joined.emit(rel, unit)
        charm.on['req1'].relation_changed.emit(rel, unit)
        charm.on['req-2'].relation_changed.emit(rel, unit)
        charm.on['pro1'].relation_departed.emit(rel, unit)
        charm.on['pro-2'].relation_departed.emit(rel, unit)
        charm.on['peer1'].relation_broken.emit(rel)
        charm.on['peer-2'].relation_broken.emit(rel)

        self.assertEqual(charm.seen, [
            'RelationJoinedEvent',
            'RelationChangedEvent',
            'RelationChangedEvent',
            'RelationDepartedEvent',
            'RelationDepartedEvent',
            'RelationBrokenEvent',
            'RelationBrokenEvent',
        ])

    def test_storage_events(self):

        class MyCharm(CharmBase):
            def __init__(self, *args):
                super().__init__(*args)
                self.seen = []
                self.framework.observe(self.on['stor1'].storage_attached, self)
                self.framework.observe(self.on['stor2'].storage_detaching, self)
                self.framework.observe(self.on['stor3'].storage_attached, self)
                self.framework.observe(self.on['stor-4'].storage_attached, self)

            def on_stor1_storage_attached(self, event):
                self.seen.append(f'{type(event).__name__}')

            def on_stor2_storage_detaching(self, event):
                self.seen.append(f'{type(event).__name__}')

            def on_stor3_storage_attached(self, event):
                self.seen.append(f'{type(event).__name__}')

            def on_stor_4_storage_attached(self, event):
                self.seen.append(f'{type(event).__name__}')

        self.meta = CharmMeta({
            'name': 'my-charm',
            'storage': {
                'stor1': {'type': 'filesystem'},
                'stor2': {
                    'type': 'filesystem',
                    'multiple': {
                        'range': '2',
                    },
                },
                'stor3': {
                    'type': 'filesystem',
                    'multiple': {
                        'range': '2-',
                    },
                },
                'stor-4': {
                    'type': 'filesystem',
                    'multiple': {
                        'range': '2-4',
                    },
                },
            },
        })

        self.assertIsNone(self.meta.storages['stor1'].multiple_range)
        self.assertEqual(self.meta.storages['stor2'].multiple_range, (2, 2))
        self.assertEqual(self.meta.storages['stor3'].multiple_range, (2, None))
        self.assertEqual(self.meta.storages['stor-4'].multiple_range, (2, 4))

        charm = MyCharm(self.create_framework(), None)

        charm.on['stor1'].storage_attached.emit()
        charm.on['stor2'].storage_detaching.emit()
        charm.on['stor3'].storage_attached.emit()
        charm.on['stor-4'].storage_attached.emit()

        self.assertEqual(charm.seen, [
            'StorageAttachedEvent',
            'StorageDetachingEvent',
            'StorageAttachedEvent',
            'StorageAttachedEvent',
        ])

    @classmethod
    def _get_function_test_meta(cls):
        return CharmMeta(
            {'name': 'my-charm'},
            {
                'foo-bar': {
                    'description': 'Foos the bar.',
                    'title': 'foo-bar',
                    'required': 'foo-bar',
                    'params': {
                        'foo-name': {
                            'type': 'string',
                            'description': 'A foo name to bar',
                        },
                        'silent': {
                            'type': 'boolean',
                            'description': '',
                            'default': False,
                        },
                    },
                },
                'start': {
                    'description': 'Start the unit.'
                }
            }
        )

    def _test_function_events(self, cmd_type):

        class MyCharm(CharmBase):

            def __init__(self, *args):
                super().__init__(*args)
                framework.observe(self.on.foo_bar_function, self)
                framework.observe(self.on.start_function, self)

            def on_foo_bar_function(self, event):
                self.seen_function_params = event.params
                event.log('test-log')
                event.set_results({'res': 'val with spaces'})
                event.fail('test-fail')

            def on_start_function(self, event):
                pass

        fake_script(self, f'{cmd_type}-get', """echo '{"foo-name": "name", "silent": true}'""")
        fake_script(self, f'{cmd_type}-set', "")
        fake_script(self, f'{cmd_type}-log', "")
        fake_script(self, f'{cmd_type}-fail', "")
        self.meta = self._get_function_test_meta()

        os.environ[f'JUJU_{cmd_type.upper()}_NAME'] = 'foo-bar'
        framework = self.create_framework()
        charm = MyCharm(framework, None)

        events = list(MyCharm.on.events())
        self.assertIn('foo_bar_function', events)
        self.assertIn('start_function', events)

        charm.on.foo_bar_function.emit()
        self.assertEqual(charm.seen_function_params, {"foo-name": "name", "silent": True})
        self.assertEqual(fake_script_calls(self), [
            [f'{cmd_type}-get', '--format=json'],
            [f'{cmd_type}-log', "test-log"],
            [f'{cmd_type}-set', "res=val with spaces"],
            [f'{cmd_type}-fail', "test-fail"],
        ])

        # Make sure that function events that do not match the current context are
        # not possible to emit by hand.
        with self.assertRaises(RuntimeError):
            charm.on.start_function.emit()

    def test_function_events(self):
        self._test_function_events('function')

    def test_function_events_legacy(self):
        self._test_function_events('action')

    def _test_function_event_defer_fails(self, cmd_type):

        class MyCharm(CharmBase):

            def __init__(self, *args):
                super().__init__(*args)
                framework.observe(self.on.start_function, self)

            def on_start_function(self, event):
                event.defer()

        fake_script(self, f'{cmd_type}-get', """echo '{"foo-name": "name", "silent": true}'""")
        self.meta = self._get_function_test_meta()

        os.environ[f'JUJU_{cmd_type.upper()}_NAME'] = 'start'
        framework = self.create_framework()
        charm = MyCharm(framework, None)

        with self.assertRaises(RuntimeError):
            charm.on.start_function.emit()

    def test_function_event_defer_fails(self):
        self._test_function_event_defer_fails('function')

    def test_function_event_defer_legacy(self):
        self._test_function_event_defer_fails('action')


if __name__ == "__main__":
    unittest.main()
