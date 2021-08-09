if True:
    from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter
    # Use NoVerifyAdapter to avoid SSL check
    BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import exchangelib as ews
import re
import traceback
import os
#import ast
import time
import threading
from classification import ModelHandler
from .preprocessed_item import PreprocessedItem
import dataaccess
import utils
from pytz import timezone
import datetime
import collections
from .mail_distributor import MailDistributor


class MailCheckService(threading.Thread):

    def __init__(self, config):
        """Service for connecting to EWS, checking for emails, calling classifier and distributing.
        
        username (str): Username for credentials with access to all relevant accounts.
        password (str): Password for credentials with access to all relevant accounts.
        method (str): Method to distribute emails by. Use 'move' or 'copy' to distribute to folders or 'forward' to forward to email.
        source_dict (dict): Dictionary with configuration of source. source_dict['account'] contains account name (e.g. email). source_dict['folders'] and source_dict['emails'] contains key-value pairs for either move/copy or forward.
        destination_dict (dict): Dictionary with the same format as source_dict.
        """
        super().__init__()

        # store configuration
        self.config = config
        
        # threading for gracefull shutting down
        self.terminated_event = threading.Event()

        # credentials for Exchange
        # Username might not be the same as the executor account
        if "EXCHANGE_USER_NAME" in config:
            username = config["EXCHANGE_USER_NAME"]
        else:
            username = config["EXECUTOR_ACCOUNT"]
        self.credentials = ews.Credentials(username=username, password=config["EXCHANGE_PW"])

        # configuration of connection to Exchange
        if "EXCHANGE_SERVICE_ENDPOINT" in config and config["EXCHANGE_SERVICE_ENDPOINT"]:
            self.ews_config = ews.Configuration(service_endpoint=config["EXCHANGE_SERVICE_ENDPOINT"], credentials=self.credentials,
                                                retry_policy=ews.FaultTolerance())
        else:
            self.ews_config = ews.Configuration(server=config["EXCHANGE_SERVER_ENDPOINT"], credentials=self.credentials,
                                                retry_policy=ews.FaultTolerance())

        # account for performing actions with the same username used in credentials
        if "EXECUTOR_ACCOUNT" in config:
            primary_smtp_address = config["EXECUTOR_ACCOUNT"]
        else:
            primary_smtp_address = config["EXCHANGE_USER_NAME"]
        self.executor_account = ews.Account(primary_smtp_address=primary_smtp_address, autodiscover=False,
                                            config=self.ews_config, access_type=ews.DELEGATE)

        # source account and source folders where the service checks for new emails
        self.source_account = ews.Account(primary_smtp_address=config["SOURCE_ACCOUNT"], autodiscover=False, config=self.ews_config, access_type=ews.DELEGATE)
        self.source_folders = self._build_folders(self.source_account.root, config["SOURCE_FOLDERS"])
        # TODO: make it a setting in the database 

        # setup auditlog
        self.auditlog = dataaccess.SQLLogger(server=self.config['DATABASE_URI'],
                             port=self.config['DATABASE_PORT'],
                             database=self.config['DATABASE_NAME'],
                             table=self.config['AUDIT_LOG_TABLE_NAME'],
                             username=self.config['DATABASE_USER_NAME'],
                             password=self.config['DATABASE_PASSWORD'])

        # setup mail distributor
        self.distributor = MailDistributor(self.executor_account, self.terminated_event,
                                           mode=config["DISTRIBUTION_MODE"], destinations=config['DESTINATIONS'],
                                           auto_create_folders="AUTO_CREATE_FOLDERS" in config and
                                                               config["AUTO_CREATE_FOLDERS"])

        # init list of processed items
        self.processed_items = processed_item_handler(self.auditlog, self.config)

        # print banner
        self._print_init_banner()


    def _print_init_banner(self):
        """Print a banner with information on the configuration"""

        print(f"      MailCheckService initialiased for customer id {self.config['CUSTOMERID']}")
        print(f"          Transfer method: {self.config['MAIL_TRANSFER_METHOD']}")
        print(f"          Source: {self.config['SOURCE_ACCOUNT']}")

        # print sources
        for key,val in self.source_folders.items():
            print(f"          {key.rjust(40)}:    {val}")
        
        # print destination
        print(f"          Destinations: {self.config['DESTINATION_ACCOUNT']}")
        for key,val in self.distributor.destinations.items():
            print(f"          {key.rjust(40)}:    {val['method'].rjust(8)} {val['mailbox'].rjust(32)} {val['folderparts']}")

        # print rules
        print(f"          Rules:")
        for rule in self.config["RULES"]:
            print(f"              {rule}")


    def new_items(self):
        """Create an item generator for new item in source folders."""
        return item_generator(self.source_folders.values(), self.processed_items, self.config, self.terminated_event)

    def run(self):
        """Look up new emails, classify them and distribute them accordingly."""

        time_zone = timezone(self.config['TIME_ZONE'])

        # The model should be created on the running thread
        model_handler = ModelHandler(self.config)
        classifier_service = model_handler.classify_item

        # TODO: add log here stating that we started processing - should each process have a process id?
        while not self.terminated_event.is_set():
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - Execute mailcheck")

            try:
                # send heartbeat
                self.config['MONITOR'].send_heartbeat()

                # check for unprocessed emails
                for prep_item in self.new_items():
                    if self.terminated_event.is_set():
                        print('Event is terminated')
                        break

                    t_in = datetime.datetime.now(time_zone)

                    classification_successful = False
                    try:
                        # Clunky way of making sure that mails with error during preprocessing are being handled
                        if isinstance(prep_item, ErrorDuringMailRetrieving):
                            e = prep_item.error
                            prep_item = prep_item.prep_item
                            raise e

                        print(f"[{t_in}] MailCheckService:run - Got '{prep_item.subject}' for processing.")
                        # classify
                        classification_dict = classifier_service(prep_item)

                        if (classification_dict["conf"] and
                            classification_dict["conf"] >= self.config["THRESHOLD"]) or \
                                "rule" in classification_dict["call_type"] or \
                                "att_extractor" in classification_dict["call_type"]:
                            key = classification_dict["classification"]
                        else:
                            print(f'Confidence less than {self.config["THRESHOLD"]}, distribute to manual.',
                                    flush=True)
                            key = self.config["FALLBACK_KEY"]

                        classification_successful = True
                    
                    except Exception as e:
                        import traceback
                        # classification failed, use fallback key
                        print("................. Classification failed!")
                        print(e)
                        print(traceback.format_exc(), flush=True)
                        self.config['MONITOR'].exception('MailServices:Run: Classification failed')
                        key = self.config["FALLBACK_KEY"]
                    
                    finally:
                        # distribute and mark them as processed if successfull

                        if isinstance(key, list):
                            success = self.distributor.distribute_to_many(prep_item.item, key)
                        else:
                            success = self.distributor.distribute(prep_item.item, key)

                        t_out = datetime.datetime.now(time_zone)
                        if success:
                            print(f"Succesfully distributed {prep_item.item.id} to {key}.", flush=True)
                            if classification_successful:
                                call_type = classification_dict["call_type"]
                                confidence = classification_dict["conf"]
                                sorting_threshold = self.config["THRESHOLD"]
                                sorting_threshold_type = 'default_threshold'
                                model_classification = classification_dict["model_classification"]
                            else:
                                call_type = "model"
                                confidence = 0.0
                                sorting_threshold = 0.0
                                sorting_threshold_type = 'Model failed prediction'
                                model_classification = None

                            # create entry in auditlog
                            self.auditlog.log_entry(message_id=prep_item.id, t_in=t_in, t_out=t_out,
                                               t_email=prep_item.received_time,
                                               sender= "" if prep_item.sender is None else prep_item.sender.email_address,
                                               clas=key,
                                               conf=confidence,
                                               call_type=call_type,
                                               text=prep_item.extract_text(),
                                               sorting_threshold=sorting_threshold,
                                               sorting_threshold_type=sorting_threshold_type,
                                               model_classification=model_classification,
                                               customer_id=self.config['CUSTOMERID'],
                                               modelversion=self.config['MODEL_VERSION'])

                            # log succesful handling of email
                            self.config['MONITOR'].email_handling_success(prep_item)

                        else:
                            self.config['MONITOR'].exception('Distribution failed!')
                            print(50*"*")
                            print("................. Distribution failed!")
                            print("................. Should not be marked as processed so will be processed again later.")
                            print(50*"*", flush=True)

            except Exception as e:
                import traceback
                print(e, flush=True)
                print(traceback.format_exc(), flush=True)
                self.config['MONITOR'].exception('MailServices:Run: Main loop failed')

            self.terminated_event.wait(self.config["SLEEP_DURATION"])

        print("MailCheckerService exiting.")

    def _build_folders(self, root, names):
        """Build a reference to a folder from a list of strings.

               names: dict with each value is a list of strings describing path 
                      relative to root or a string with a folder id"""

        folders = {}
        for key,value in names.items():
            # check for list of strings            
            if isinstance(value, list) and all([isinstance(s, str) for s in value]):

                folders[key] = root
                # loop over individual folders in list
                for f in value:
                    # __truediv__ operator "/" is overload to be a path operator
                    folders[key] = utils.run_function_with_retry(folders[key].__truediv__, f, event=self.terminated_event)
            
            # check for folder id
            elif isinstance(value, str):
                if value == "Inbox":
                    folders[key] = self.source_account.inbox
                elif value == "Junk":
                    folders[key] = self.source_account.junk
                else:
                    folders[key] = utils.run_function_with_retry(root.get_folder, value, event=self.terminated_event)
            
            # if we get this far then raise an exception
            else:
                raise ValueError(f"Folder names for '{key}' are not a list of strings or folder id's.")

        return folders


class processed_item_handler():
    """Class for containing and handling already processed items"""

    def __init__(self, auditlog, config, maxlen=2000):

        # init
        self.config = config
        self.auditlog = auditlog

        # timezone handling
        # TODO: should be in a specified object that handles preprocessing of items
        #self.time_zone = timezone(self.config['TIME_ZONE'])
        #self.email_time_zone = timezone(self.config['EMAIL_TIME_ZONE'])

        # get alrady processed from DB
        ## TODO: Update this function to get key-pair (id, datetime)
        #processed_in_db = self.auditlog.get_processed_ids(customer_id=self.config['CUSTOMERID'])
        processed_in_db = []

        self.processed_items = collections.deque(processed_in_db, maxlen=maxlen)
        
        

    def __contains__(self, item):
        """Contain method"""

        key = (item.id, item.received_time)
        # check for presence in local list
        if key in self.processed_items:
            return True

        # if not in local list, check DB
        if self._item_in_database(item):
            self.processed_items.append(key)
            return True
        else:
            return False


    def _item_in_database(self, item):
        """Check for item_id in database"""
        return self.auditlog.contains_item(item, self.config['CUSTOMERID'])


class ErrorDuringMailRetrieving:
    """Error type used in case the item_generator throws an exception while handling an email. If this type is yielded
    to MailCheckService it will rethrow the exception and sort the mail to fallback key"""
    def __init__(self, prep_item, error):
        self.prep_item = prep_item
        self.error = error

def item_generator(source_folders, processed_items, config, terminated_event=None):
    """Generator with new items from source folders. First checks against internal list of
    processed items and secondly checks against DB."""

    #print("Item generator for folders:")
    #for folder in source_folders:
    #    print(f"  - {folder.account.primary_smtp_address}/{folder.name}")
    #print()

    # handle INITIAL_RUN before entering folder loop
    if "INITIAL_RUN" in config:
        initial_run = config["INITIAL_RUN"]
    else:
        initial_run = False
    config["INITIAL_RUN"]=False

    for folder in source_folders:

        print(f"[{time.ctime()}] Opening folder: {folder.account.primary_smtp_address}/{folder.name}")

        # refresh folder
        utils.run_function_with_retry(folder.refresh, event=terminated_event)

        # get ids of items in folder
        fields = ('id','subject','datetime_received')
        if "START_TIME" in config:
            if initial_run:
                # it is the initial run, so we use start_time
                start_time = folder.account.default_timezone.localize(ews.EWSDateTime.from_datetime(config["START_TIME"]))
            else:
                # it is no longer the inital run, use a 28 h lookback, but no longer than to start_time
                now = datetime.datetime.now()
                delta = datetime.timedelta(hours=28)
                t = max(now-delta, config["START_TIME"])
                start_time = folder.account.default_timezone.localize(ews.EWSDateTime.from_datetime(t))

            source_queryset = utils.run_function_with_retry(folder.filter(datetime_received__gt=start_time).only, *fields)
        else:
            start_time = folder.account.default_timezone.localize(datetime.datetime(2020,1,1,12,0,0)) # not needed here but we set it to be able to print it
            source_queryset = utils.run_function_with_retry(folder.all().only, *fields)
        

        # init counters
        source_items = list(source_queryset)
        item_count = len(source_items)
        proc_count = 0
        new_count = 0

        for item in source_items:

            # preprocess reduced item - this is mainly to get the timestamp correct wrt timezones
            redud_prep = PreprocessedItem(item, config)

            # check if item is already processed, if not, then get the full item and preprocess it before yielding
            if redud_prep in processed_items:
                proc_count = proc_count + 1
            else:
                new_count = new_count + 1
                
                try:
                    # item is new so get full item from id
                    full_item = utils.run_function_with_retry(_get_item_by_id, folder, item.id)

                    # preprocess item
                    prep = PreprocessedItem(full_item, config)

                    #print("New item. Yielding: ", prep.received_time, prep.subject)
                    config['MONITOR'].email_trace(prep, 'New item. Yielding.')

                    yield prep

                except Exception as e:
                    # error occured, monitor it and continue
                    config['MONITOR'].exception(str(e))

                    print(e, flush=True)
                    print(traceback.format_exc(), flush=True)

                    yield ErrorDuringMailRetrieving(redud_prep, error=e)

                    

        
        print(f"  {folder.account.primary_smtp_address}/{folder.name}: {new_count} new. {proc_count} already processed. {item_count} in total since {start_time.strftime('%Y-%m-%d %H:%m:%S')}.")

def _get_item_by_id(folder, item_id):
    """Helper function for use with retry function"""
    return folder.get(id=item_id)
