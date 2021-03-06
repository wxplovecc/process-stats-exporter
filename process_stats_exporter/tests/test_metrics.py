import logging
from operator import itemgetter
import re

from fixtures import LoggerFixture
from lxstats.process import Process
from lxstats.testing import TestCase
from prometheus_aioexporter.metric import MetricsRegistry

from ..metrics import ProcessMetricsHandler
from ..label import (
    CmdlineLabeler,
    PidLabeler,
)


class ProcessMetricsHandlerTests(TestCase):

    def setUp(self):
        super().setUp()
        self.labelers_processes = []
        self.logger = self.useFixture(LoggerFixture(level=logging.DEBUG))
        self.handler = ProcessMetricsHandler(
            logging.getLogger('test'), pids=['10', '20'],
            get_process_iterator=lambda **kwargs: self.labelers_processes)

    def test_get_metric_configs(self):
        """MetricConfigs are returned for process metrics."""
        metric_configs = self.handler.get_metric_configs()
        self.assertCountEqual(
            [config.name for config in metric_configs],
            ['proc_ctx_involuntary', 'proc_ctx_voluntary',
             'proc_maj_fault', 'proc_mem_rss', 'proc_mem_rss_max',
             'proc_min_fault', 'proc_tasks_count',
             'proc_tasks_state_running', 'proc_tasks_state_sleeping',
             'proc_tasks_state_uninterruptible_sleep',
             'proc_time_system', 'proc_time_user'])

    def test_get_metric_configs_with_pids(self):
        """If PIDs are specified, metrics include a "pid" label."""
        handler = ProcessMetricsHandler(
            logging.getLogger('test'), pids=['10', '20'],
            get_process_iterator=lambda **kwargs: self.labelers_processes)
        for metric in handler.get_metric_configs():
            self.assertEqual(metric.config['labels'], ['pid'])

    def test_update_metrics(self):
        """Metrics are updated with values from procesess."""
        self.labelers_processes.extend(
            [(CmdlineLabeler(re.compile('exec.*')),
              Process(10, self.tempdir.path / '10')),
             (CmdlineLabeler(re.compile('exec.*')),
              Process(20, self.tempdir.path / '20'))])
        self.make_process_file(10, 'comm', content='exec1')
        self.make_process_file(
            10, 'stat', content=' '.join(str(i) for i in range(45)))
        self.make_process_dir(10, 'task')
        self.make_process_file(20, 'comm', content='exec2')
        self.make_process_file(
            20, 'stat', content=' '.join(str(i) for i in range(45, 90)))
        self.make_process_dir(20, 'task')
        handler = ProcessMetricsHandler(
            logging.getLogger('test'), cmdline_regexps=[re.compile('exec.*')],
            get_process_iterator=lambda **kwargs: self.labelers_processes)
        metrics = MetricsRegistry().create_metrics(
            handler.get_metric_configs())
        handler.update_metrics(metrics)
        # check value of a sample metric
        metric = metrics['proc_min_fault']
        [(_, labels1, value1), (_, labels2, value2)] = sorted(
            metric._samples(), key=itemgetter(2))
        self.assertEqual(labels1, {'cmd': 'exec1'})
        self.assertEqual(value1, 9.0)
        self.assertEqual(labels2, {'cmd': 'exec2'})
        self.assertEqual(value2, 54.0)

    def test_update_metrics_with_pids(self):
        """Metrics include the "pid" label if PIDs are specified."""
        self.labelers_processes.extend(
            [(PidLabeler(),
              Process(10, self.tempdir.path / '10')),
             (PidLabeler(),
              Process(20, self.tempdir.path / '20'))])
        handler = ProcessMetricsHandler(
            logging.getLogger('test'), pids=['10', '20'],
            get_process_iterator=lambda **kwargs: self.labelers_processes)
        self.make_process_file(10, 'comm', content='exec1')
        self.make_process_file(
            10, 'stat', content=' '.join(str(i) for i in range(45)))
        self.make_process_dir(10, 'task')
        self.make_process_file(20, 'comm', content='exec2')
        self.make_process_file(
            20, 'stat', content=' '.join(str(i) for i in range(45, 90)))
        self.make_process_dir(20, 'task')
        metrics = MetricsRegistry().create_metrics(
            handler.get_metric_configs())
        handler.update_metrics(metrics)
        # check value of a sample metric
        metric = metrics['proc_min_fault']
        [(_, labels1, _), (_, labels2, _)] = sorted(
            metric._samples(), key=itemgetter(2))
        self.assertEqual(labels1['pid'], '10')
        self.assertEqual(labels2['pid'], '20')

    def test_log_empty_values(self):
        """A message is logged for empty metric values."""
        self.labelers_processes.extend(
            [(PidLabeler(), Process(10, self.tempdir.path / '10'))])
        self.make_process_dir(10, 'task')
        metrics = MetricsRegistry().create_metrics(
            self.handler.get_metric_configs())
        self.handler.update_metrics(metrics)
        self.assertIn(
            'empty value for metric "proc_time_system" on PID 10',
            self.logger.output)
