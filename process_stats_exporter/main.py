#!/usr/bin/env python

from collections import (
    namedtuple,
    defaultdict)
from itertools import chain

from prometheus_aioexporter.script import PrometheusExporterScript
from prometheus_aioexporter.metric import MetricConfig

from lxstats.process import (
    Collection,
    Collector,
    CommandLineFilter)


ProcessStat = namedtuple(
    'ProcessStat', ['metric', 'type', 'description', 'stat'])

ProcessTasksStat = namedtuple(
    'ProcessTaskStat', ['metric', 'type', 'description'])


class StatsCollector:
    """Describe and collect metrics."""

    @classmethod
    def metrics(cls):
        """Return a list of MetricConfigs."""
        raise NotImplementedError('Subclasses must implement metrics()')

    @classmethod
    def collect(cls, process):
        """Return a dict mapping metric names to values for the process."""
        raise NotImplementedError('Subclasses must implement collect()')


class ProcessStatsCollector(StatsCollector):
    """Collect metrics for a process."""

    _STATS = (
        ProcessStat(
            'process_time_user', 'counter', 'Time scheduled in user mode',
            'stat.utime'),
        ProcessStat(
            'process_time_system', 'counter',
            'Time scheduled in kernel mode', 'stat.stime'),
        ProcessStat(
            'process_mem_rss', 'gauge', 'Memory resident segment size (RSS)',
            'stat.rss'),
        ProcessStat(
            'process_maj_fault', 'counter',
            'Number of major faults that required a page load', 'stat.majflt'),
        ProcessStat(
            'process_min_fault', 'counter',
            'Number of minor faults the not required a page load',
            'stat.minflt'),
        ProcessStat(
            'process_ctx_involuntary', 'counter',
            'Number of involuntary context switches',
            'sched.nr_involuntary_switches'),
        ProcessStat(
            'process_ctx_voluntary', 'counter',
            'Number of voluntary context switches',
            'sched.nr_voluntary_switches'),
        ProcessStat(
            'process_mem_rss_max', 'counter',
            'Maximum memory resident segment size (RSS)', 'status.VmHWM'))

    @classmethod
    def metrics(cls):
        return [
            MetricConfig(
                stat.metric, stat.description, stat.type, {'labels': ['cmd']})
            for stat in cls._STATS]

    @classmethod
    def collect(cls, process):
        process.collect_stats()
        return {stat.metric: process.get(stat.stat) for stat in cls._STATS}


class ProcessTasksStatsCollector(StatsCollector):
    """Collect metrics for a process' tasks."""

    _STATS = (
        ProcessTasksStat(
            'process_tasks_count', 'gauge', 'Number of process tasks'),
        ProcessTasksStat(
            'process_tasks_state_running', 'gauge',
            'Number of process tasks in running state'),
        ProcessTasksStat(
            'process_tasks_state_sleeping', 'gauge',
            'Number of process tasks in sleeping state'),
        ProcessTasksStat(
            'process_tasks_state_uninterruptible_sleep', 'gauge',
            'Number of process tasks in uninterruptible sleep state'),
    )

    @classmethod
    def metrics(cls):
        return [
            MetricConfig(
                stat.metric, stat.description, stat.type, {'labels': ['cmd']})
            for stat in cls._STATS]

    @classmethod
    def collect(cls, process):
        tasks = process.tasks()
        state_counts = defaultdict(int)
        for task in tasks:
            task.collect_stats()
            state_counts[task.get('stat.state')] += 1
        return {
            'process_tasks_count': len(tasks),
            'process_tasks_state_running': state_counts['R'],
            'process_tasks_state_sleeping': state_counts['S'],
            'process_tasks_state_uninterruptible_sleep': state_counts['D']}


class ProcessStatsExporter(PrometheusExporterScript):
    """Prometheus exporter script for process statistics."""

    name = 'process-stats-exporter'

    def configure_argument_parser(self, parser):
        parser.add_argument(
            '-i', '--interval', type=int, default=10,
            help='stats update interval')
        parser.add_argument(
            '-P', '--pids', nargs='+', type=int, metavar='pid',
            help='process PID')
        parser.add_argument(
            '-R', '--name-regexps', nargs='+',
            metavar='name-regexp', help='regexp to match process name')

    def configure(self, args):
        self._pids = args.pids
        self._name_regexps = args.name_regexps
        if self._pids:
            self.logger.info(
                'tracking stats for PIDs [{}]'.format(', '.join(self._pids)))
        elif self._name_regexps:
            self.logger.info(
                'tracking stats for processes [{}]'.format(
                    ', '.join(self._name_regexps)))
        else:
            self.exit('Error: no PID or process names specified')

        metric_configs = ProcessStatsCollector.metrics()
        metric_configs.extend(ProcessTasksStatsCollector.metrics())
        self._metrics = self.create_metrics(metric_configs)

    async def on_application_startup(self, application):
        application.set_metric_update_handler(self._update_metrics)

    def _update_metrics(self, metrics):
        """Update metrics on requests."""
        for process in self._get_process_iterator():
            metric_values = ProcessStatsCollector.collect(process)
            metric_values.update(ProcessTasksStatsCollector.collect(process))
            for metric, value in metric_values.items():
                self._update_metric(process, metric, value)

    def _get_process_iterator(self):
        """Return an iterator yielding Process objects."""
        if self._pids:
            return Collection(collector=Collector(pids=self._pids))
        elif self._name_regexps:
            collections = []
            for name_re in self._name_regexps:
                collection = Collection()
                collection.add_filter(CommandLineFilter(name_re))
                collections.append(collection)
            return chain(*collections)
        else:
            return iter(())

    def _update_metric(self, process, metric_name, value):
        """Update the value for a metrics."""
        if value is None:
            self.logger.warning(
                'emtpy value for metric "{}" on PID {}'.format(
                    metric_name, process.pid))
            return

        metric = self._metrics[metric_name].labels(cmd=process.get('comm'))
        if metric._type == 'counter':
            metric.inc(value)
        elif metric._type == 'gauge':
            metric.set(value)


script = ProcessStatsExporter()
