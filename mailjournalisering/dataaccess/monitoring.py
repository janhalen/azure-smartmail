import logging
from opencensus.ext.azure.trace_exporter import AzureExporter
from opencensus.ext.azure import metrics_exporter
from opencensus.trace.samplers import AlwaysOnSampler
from opencensus.trace.tracer import Tracer
from opencensus.trace import config_integration
from opencensus.ext.azure.log_exporter import AzureLogHandler

from datetime import datetime
from opencensus.ext.azure import metrics_exporter
from opencensus.stats import aggregation as aggregation_module
from opencensus.stats import measure as measure_module
from opencensus.stats import stats as stats_module
from opencensus.stats import view as view_module
from opencensus.tags import tag_map as tag_map_module

import time
import asyncio
from azure.eventhub import EventData, EventHubProducerClient
import json
import traceback

# azure monitor, see: https://docs.microsoft.com/en-us/azure/azure-monitor/app/opencensus-python
# event hub, see https://github.com/Azure/azure-sdk-for-python/blob/master/sdk/eventhub/azure-eventhub/samples/async_samples/send_async.py

class monitor:

    def __init__(self, config):

        self.config = config

        self.instrumentationkey = config['APPINSIGHT_INSTRUMENTATIONKEY']
        self.connection_string = f'InstrumentationKey={self.instrumentationkey}'

        self.stats = stats_module.stats
        self.view_manager = self.stats.view_manager
        self.stats_recorder = self.stats.stats_recorder

        # setup measurement of heart beat and email 
        self.heartbeat_measure = measure_module.MeasureInt("heartbeat", "number of heartbeats")
        #self.heartbeat_view = view_module.View("Maildroid heartbeat", "number of heartbeats", [] ,self.heartbeat_measure, aggregation_module.CountAggregation())
        self.heartbeat_view = view_module.View("Maildroid heartbeat", "number of heartbeats", [] ,self.heartbeat_measure, aggregation_module.LastValueAggregation())
        self.view_manager.register_view(self.heartbeat_view)

        self.mmap = self.stats_recorder.new_measurement_map()
        self.tmap = tag_map_module.TagMap()

        self.logger = logging.getLogger('MailDroidLogger')
        self.logger.setLevel(logging.INFO)

        # setup logs, tracers and metrics exporters
        self.tracer = Tracer(exporter=AzureExporter(connection_string=self.connection_string), sampler=AlwaysOnSampler(), )
        self.exporter = metrics_exporter.new_metrics_exporter(connection_string=self.connection_string)

        self.logger.addHandler(AzureLogHandler( connection_string=self.connection_string) )

        # metrics
        self.view_manager.register_exporter(self.exporter)

        # event hub
        self.eventhub_conn_str= config['EVENTHUB_CONN_STR']
        self.eventhub_name=config['EVENTHUB_NAME']


    def exception(self,exception_str, extra={}):
        try:
            properties = extra.copy()
            properties['customerid'] = self.config['CUSTOMERID']
            self.logger.exception(exception_str, extra=properties)
        except Exception as E:
            print(E, flush=True)
            print(traceback.format_exc(), flush=True)
            raise E
        
    def warning(self, warning_str, extra={}):
        try:
            properties = extra.copy()
            properties['customerid'] = self.config['CUSTOMERID']
            self.logger.warning(warning_str, extra=properties)
        except Exception as E:
            print(E, flush=True)
            print(traceback.format_exc(), flush=True)
            raise E

    def info(self, info_str, extra={}):
        try:
            properties = extra.copy()
            properties['customerid'] = self.config['CUSTOMERID']
            self.logger.info(info_str, extra=properties)
        except Exception as E:
            print(E, flush=True)
            print(traceback.format_exc(), flush=True)
            raise E

    def email_trace(self, prep_item, message):
        try:
            # TODO: expand properties to contain more
            custom_dimensions = {'messageid': prep_item.id, 'customerid': self.config['CUSTOMERID'], 'message':message}
            properties = {'custom_dimensions': custom_dimensions }
            self.logger.info('Item trace', extra=properties)
        except Exception as E:
            print(E, flush=True)
            print(traceback.format_exc(), flush=True)
            raise E

    def email_handling_success(self, prep_item):
        try:
            # send email trace
            self.email_trace(prep_item, 'Email handling success')

            # send to event hub
            self.send_event_data_batch({'type':'emails_handled', 'message': 'emails_handled', 'customer_id': self.config['CUSTOMERID'] })
        except Exception as E:
            print(E, flush=True)
            print(traceback.format_exc(), flush=True)
            raise E

    def send_heartbeat(self):
        try:
            self.mmap.measure_int_put(self.heartbeat_measure, 1)
            self.mmap.record(self.tmap)

            # send to event hub
            self.send_event_data_batch({'type':'hearbeat', 'message': 'heartbeat', 'customer_id': self.config['CUSTOMERID'] })
        except Exception as E:
            print(E, flush=True)
            print(traceback.format_exc(), flush=True)
            raise E


    def send_event_data_batch(self, payload):
        # Without specifying partition_id or partition_key
        # the events will be distributed to available partitions via round-robin.
        producer = EventHubProducerClient.from_connection_string(conn_str=self.eventhub_conn_str, eventhub_name=self.eventhub_name)
        with producer:
            event_data_batch = producer.create_batch()
            event_data_batch.add(EventData(json.dumps(payload)))
            producer.send_batch(event_data_batch)


