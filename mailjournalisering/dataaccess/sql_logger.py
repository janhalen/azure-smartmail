import pyodbc
from datetime import datetime
import random
import time

class TranslationLookup:
    """Translation lookup table for use with str.translate. All utf-8 characters with more than 2 bytes are replaced with a replacement char (default=' ')."""

    def __init__(self, replacementchar=' '):
        self.replacementchar = replacementchar
        if replacementchar=='':
            self.replacementord = None
        else:
            self.replacementord = ord(self.replacementchar)

    def __getitem__(self,c):
        u = chr(c).encode('utf-8')
        if len(u)<=2:
            return c
        else:
            return self.replacementord


class SQLLogger:

    def __init__(self, server = 'tcp:maildroiddev.database.windows.net', port = 1433, database = 'MailDroidDev', table="", username="", password=""):

        # get drivers and select the last one with highest number
        all_drivers = [item for item in pyodbc.drivers() if 'ODBC Driver' in item]
        driver = all_drivers[-1]

        # init variables
        self.server = server
        self.database = database
        self.table = table
        self.conn = None
        self.cursor = None

        # connection string (copied from Azure and modified)
        self.connection_str = f"Driver={{{driver}}};Server={server},{port};Database={database};Uid={{{username}}};Pwd={{{password}}};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        
        # string for inserting values into log
        self.insert_str = f"INSERT INTO {table} (message_id, timestamp_in, timestamp_out, timestamp_email, sender, classification, confidence, call_type, text, sorting_threshold, sorting_threshold_type, model_classification, customerID, model_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"

        # connect
        self.connect()
        self._set_column_properties()


    def _set_column_properties(self):
        # get properties of columns in database
        # from: https://dataedo.com/kb/query/azure-sql/list-columns-names-in-specific-table
        select_str = """select col.name, t.name as data_type, col.max_length, col.is_nullable
            from sys.tables as tab 
              inner join sys.columns as col
                on tab.object_id = col.object_id
              left join sys.types as t
                on col.user_type_id = t.user_type_id
            where tab.name = 'auditlog'"""

        self.column_properties = dict()
        for row in self.cursor.execute(select_str):
            self.column_properties[row.name] = {'data_type': row.data_type, 'max_length': row.max_length,
                                                'is_nullable': row.is_nullable}

    def connect(self, retry=10):
        # open connection to database server and setup cursor. Implements exponential backoff.
        print(f"Open connection to auditlog table '{self.table}' in database '{self.database}' on server '{self.server}'")

        # first force close connection if it is open. This will also try to rollback.
        try:
            self.conn.close()
        except:
            # if we end up here, then no connection exists, we silenty ignore exception and move on to establish one
            pass

        for i in range(retry):
            try:
                # try to establish connection
                self.conn = pyodbc.connect(self.connection_str)
                # if established, immediately break loop and continue
                break
            except:
                # if we are at the last try and still cannot connect, return false. 
                if i==(retry-1):
                    return False
                else:
                    # something went wrong, wait exponentially long (+/- 20%) before trying again, 1 sec, 2 sec, 4 sec, ...
                    # see: https://www.acodersjourney.com/26-handle-transient-errors-in-c/
                    time.sleep(2**i * (0.8 + 0.4*random.random()))

        # if no exception, get cursor and return true
        self.cursor = self.conn.cursor()
        return True


    def alive(self):
        # dummy method for testing connection and reconnecting if lost
        try:
            self.cursor.execute('select 1')
        except:
            self.connect()

    def preprocessvalues(self, message_id, t_in, t_out, t_email, sender, clas, conf, call_type, text, sorting_threshold,
                         sorting_threshold_type, model_classification, customer_id, modelversion):
        """Preprocess values to match the database. For now it is just a truncation of strings to avoid 22001 errors on the database."""

        # create a lookup that replaces utf-8 chars with a size larger than 2 bytes
        lookup = TranslationLookup()

        vals = (message_id[:self.column_properties['message_id']['max_length']],)
        vals = vals + (t_in,)
        vals = vals + (t_out,)
        vals = vals + (t_email,)
        vals = vals + (sender[:self.column_properties['sender']['max_length']],)
        vals = vals + (clas[:self.column_properties['classification']['max_length']],)
        vals = vals + (float(conf),)
        vals = vals + (call_type[:self.column_properties['call_type']['max_length']],)

        # Subtract 200 from the max length of text, as special characters might use more than one byte per chars
        vals = vals + (text[:(self.column_properties['text']['max_length'])].translate(lookup),)
        vals = vals + (sorting_threshold,)
        vals = vals + (sorting_threshold_type[:self.column_properties['sorting_threshold_type']['max_length']],)
        vals = vals + (None if model_classification is None else model_classification[
                                                                 :self.column_properties['model_classification'][
                                                                     'max_length']],)
        vals = vals + (customer_id,)
        vals = vals + (modelversion[:self.column_properties['model_version']['max_length']],)

        return vals

    def log_entry(self, message_id: str, t_in: datetime, t_out: datetime, t_email: datetime, sender: str, clas,
                  conf: float, call_type: str, text: str, sorting_threshold: float, sorting_threshold_type: str,
                  model_classification: str, customer_id: int, modelversion: str):
        if isinstance(clas, list):
            for c in clas:
                self.log_entry(message_id, t_in, t_out, t_email, sender, c, conf, call_type, text, sorting_threshold,
                               sorting_threshold_type, model_classification, customer_id, modelversion)
            return

        # preprocess values to ensure they match the database. The output tuple 'vals' must match self.insert_str
        vals = self.preprocessvalues(message_id, t_in, t_out, t_email, sender, clas, conf, call_type, text,
                                     sorting_threshold, sorting_threshold_type, model_classification, customer_id,
                                     modelversion)

        try:
            # execute insertion into table
            self.cursor.execute(self.insert_str, vals)
        except:
            print(f"Failed at: {vals}")
            # something failed. Wait a few seconds to try to get a decent close of connection, reconnect and execute again
            time.sleep(30)
            self.connect()
            self.cursor.execute(self.insert_str, vals)

        # commit changes
        self.conn.commit()

    def get_processed_ids(self, customer_id, limit=500):
        """Get item ids of alrady processed messages in the auditlog. Limit by default to 500. First item is the oldest"""
        
        id_str = f"SELECT TOP ({limit}) logging_id,message_id,timestamp_email,customerID FROM auditlog where customerID={customer_id} ORDER BY timestamp_email DESC"

        try:
            # execute insertion into table
            self.cursor.execute(id_str)
        except:
            # something failed. Wait a few seconds to try to get a decent close of connection, reconnect and execute again
            time.sleep(30)
            self.connect()
            self.cursor.execute(id_str)

        # retrieve ids as list, flip to get oldest at ids[0] and return
        ids = []
        for row in self.cursor.fetchall():
            ids.append(row.message_id)
        # flip left-right
        ids = ids[::-1]

        return ids

    def contains_id(self, message_id, customer_id):
        """Query database if id exist there"""
        
        #id_str = f"SELECT count(*) FROM auditlog where customerID={customer_id} and message_id='{message_id}'"
        id_str = f"SELECT count(*) FROM auditlog where customerID=? and message_id=?"
        params = (customer_id, message_id)

        try:
            # execute insertion into table
            self.cursor.execute(id_str, params)
        except:
            # something failed. Wait a few seconds to try to get a decent close of connection, reconnect and execute again
            time.sleep(30)
            self.connect()
            self.cursor.execute(id_str, params)

        # get count of id
        count = self.cursor.fetchone()[0]
        print(f"item count in auditlog: {count}")

        id_str = f"SELECT message_id,timestamp_email,text FROM auditlog where customerID=? and message_id=?"
        params = (customer_id, message_id)
        self.cursor.execute(id_str, params)
        alt_count = self.cursor.fetchall()
        print(f"item alt_count in auditlog: {alt_count}")

        return count > 0


    def contains_item(self, item, customer_id):
        """Query database if item exist there"""
        
        # count number of entries from this customer with this customer id and a timestamp within a second
        id_str = "SELECT count(*) FROM auditlog where customerID=? and message_id=? and ABS(DATEDIFF(millisecond,timestamp_email, ?))<1000"
        params = (customer_id, item.id, item.received_time)

        try:
            # execute insertion into table
            self.cursor.execute(id_str, params)
        except:
            # something failed. Wait a few seconds to try to get a decent close of connection, reconnect and execute again
            time.sleep(30)
            self.connect()
            self.cursor.execute(id_str, params)

        # get count of id
        count = self.cursor.fetchone()[0]

        return count > 0
