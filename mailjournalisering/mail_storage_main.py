import yaml
import datetime
import pyodbc
from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter
import re
from glob import glob
import os
import time
import pathlib
from mailservice import mailservices
import dataaccess

# Use NoVerifyAdapter to avoid SSL check
BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter
import exchangelib as ews
import warnings
warnings.simplefilter("ignore")


class SQLWrapper:

    def __init__(self, secrets, connection_string=None):
        if connection_string is None:
            self.connection_string = "Driver={ODBC Driver 17 for SQL Server};Server=tcp:maildroiddev.database.windows.net,1433;Database=MailDroidTrainingData;Uid=USERNAME_HERE;Pwd={" + secrets['DevDatabasePassword'] + "};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        else:
            self.connection_string = connection_string

        self.conn = pyodbc.connect(self.connection_string, autocommit=True)
        self.cursor = self.conn.cursor()
        self.insert_counter = 1

    def run_command(self, command, *args):
        retry_flag = True
        retry_count = 0
        while retry_count < 60 and retry_flag:
            try:
                self.cursor.execute(command, *args)
                retry_flag = False
            except pyodbc.OperationalError:
                retry_count += 1
                import traceback
                traceback.print_exc()
                self.conn.close()
                self.conn = pyodbc.connect(self.connection_string, autocommit=True)
                self.cursor = self.conn.cursor()
                time.sleep(0.5)


def get_dataset_id(sql_wrapper, extraction_date, customer_id):
    sql_wrapper.run_command("insert into Datasets (creationTime, extractionDate, customerId) output inserted.id  values (?,?,?)", datetime.datetime.now(), extraction_date, customer_id)
    row = sql_wrapper.cursor.fetchone()
    dataset_id = row.id
    return dataset_id


def get_conversation_ids_of_customer(sql_wrapper, customerId):
    sql_wrapper.run_command("select id from Datasets where customerId=?", customerId)
    dataset_ids = [str(row.id) for row in sql_wrapper.cursor.fetchall()]

    dataset_id_str = "(" + ', '.join(dataset_ids) + ")"

    sql_wrapper.run_command(f"select conversationIndex, departmentFolder from Emails2 where datasetId in {dataset_id_str}")

    conv_idx_department_dict = {}
    for row in sql_wrapper.cursor:
        if row.conversationIndex not in conv_idx_department_dict:
            conv_idx_department_dict[row.conversationIndex] = []
        conv_idx_department_dict[row.conversationIndex].append(row.departmentFolder)

    return conv_idx_department_dict


def get_secrets(secret_path):
    """Add secrets from volume to dict and return it"""
    # get list of secrets
    s = pathlib.Path(secret_path).glob('*')
    d = dict()
    for secret in s:
        if secret.is_file():
            with open(secret, 'r') as f:
                key = secret.parts[-1]
                value = f.read()
                d[key] = value
    return d


def run_main():
    print("Starting...")
    secret_path = '/etc/secret-volume'
    secrets = get_secrets(secret_path)
    max_attachment_size = 10 * 1024 * 1024
    sql_wrapper = SQLWrapper(secrets)
    tz = ews.EWSTimeZone.timezone('Europe/Copenhagen')

    # assume there exist a mounted volume on /mnt/storage
    config_files = glob(os.path.join("/mnt", "storage", "storage-config", "*.yaml"))

    print(f"Found {len(config_files)} config files:")
    print('  ' + '\n  '.join(config_files))
    for config_file in config_files:
        print(f"Loading {config_file}")
        config = yaml.load(open(config_file, "r"))
        # add some system config stuff
        config['ALLOWED_CONTENT_TYPES'] = ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
        config['TIME_ZONE'] = 'Europe/Copenhagen'
        config['EMAIL_TIME_ZONE'] = 'GMT'
        config['USE_STD_MONITOR'] = True
        config['MONITOR'] = dataaccess.stdoutmonitor.STDOutMonitor()

        try:
            # try getting value from yaml config
            t = config['start_time']
            config['START_TIME'] = t
            print(f"START_TIME set to config value: {t.ctime()}")
        except Exception as e:
            print("Failed to get start time from config file.")
            print(e)
            
            # if cannot set START_TIME, fix it to a 28 () hours lookback
            now = datetime.datetime.now()
            delta = datetime.timedelta(days=8)
            t = now-delta
            config['START_TIME'] = now-delta
            print(f"START_TIME set to default 8 days look back: {t.ctime()}")


        credentials = ews.Credentials(username=secrets[config["username_key"]], password=secrets[config["password_key"]])
        if 'service_endpoint' in config.keys():
            ews_config = ews.Configuration(service_endpoint=config["service_endpoint"], credentials=credentials)
        else:
            ews_config = ews.Configuration(server=config["server"], credentials=credentials)

        extraction_date = datetime.datetime.now().strftime("%d%m%Y")

        dataset_id = get_dataset_id(sql_wrapper, extraction_date, config["customer_id"])

        conv_idxs_department_dict = get_conversation_ids_of_customer(sql_wrapper, config["customer_id"])

        for mail_address in config["mail_boxes"]:
            # force item generator to use start_time
            config['INITIAL_RUN'] = True
            
            mailbox_name = mail_address

            try:
                account = ews.Account(primary_smtp_address=mail_address, autodiscover=False, config=ews_config, access_type=ews.DELEGATE)
                account.root
                # We extract mails from all subfolders of the inbox and junk and trash
                all_folders = [account.inbox, account.junk, account.trash] + [f for f in account.inbox.glob('**/*') if f.folder_class=="IPF.Note" ]
                item_generator = mailservices.item_generator(all_folders, [], config)
                print(f"Access to: {mail_address}")
            except ews.errors.ErrorNonExistentMailbox as E:
                print(E)
                print(f"No access to: {mail_address}")
                continue
            except Exception as E:
                print(E)
                print(f"Access to: {mail_address} failed")
                continue



            for i, item in enumerate(item_generator):

                try:    
                    # first check if item retrival failed. If yes, print error and continue to next
                    if isinstance(item, mailservices.ErrorDuringMailRetrieving):
                        e = item.error
                        print(e)
                        print(item)
                        continue

                    print(f"{i}, {item.subject}", flush=True)

                    message = item.item

                    if not isinstance(message, ews.Message):
                        continue
                    if message.item_class!='IPM.Note':
                        continue

                    conv_id = str(message.conversation_id.id)
                    if conv_id in conv_idxs_department_dict\
                            and mailbox_name in conv_idxs_department_dict[conv_id]:
                        continue

                    mail_tuple = (conv_id,
                                    message.datetime_received,
                                    "" if message.body is None else str(message.body),
                                    "" if message.body is None else message.body.body_type,
                                    mailbox_name,
                                    "" if item.sender is None else str(message.sender.email_address),
                                    dataset_id,
                                    str(message.subject) if message.subject is not None else "")


                    try:
                        sql_wrapper.run_command(
                            "insert into Emails2 (conversationIndex, timestamp, rawBody, bodyType, departmentFolder, sender, datasetId, subject) values (?, ?, ?, ?, ?, ?, ?, ?)",
                            *mail_tuple)
                    except pyodbc.IntegrityError:  # in case of primary key violation (duplicated conversation index)
                        sql_wrapper.run_command("select timestamp from Emails2 where conversationIndex=? and datasetId=?", conv_id,
                                        dataset_id)
                        row = sql_wrapper.cursor.fetchone()
                        if row.timestamp.timestamp() < message.datetime_received.astimezone(tz).timestamp():
                            sql_wrapper.run_command("delete from Emails2 where conversationIndex=? and datasetId=?",
                                        conv_id, dataset_id)
                            sql_wrapper.run_command(
                                "insert into Emails2 (conversationIndex, timestamp, rawBody, bodyType, departmentFolder, sender, datasetId, subject) values (?, ?, ?, ?, ?, ?, ?, ?)",
                                *mail_tuple)

                    for i,attachment in enumerate(message.attachments):
                        try:
                            attachment_tuple = (conv_id, dataset_id, attachment.name, item.attachment_texts[i])
                            sql_wrapper.run_command(
                                "insert into Attachments (conversationIndex, datasetId, filename, text) values (?, ?, ?, ?)",
                                *attachment_tuple)
                        except Exception as e:
                            print('Failed to insert attachment into database.')
                            print(e)
                            continue

                except Exception as E:
                    # something happenend during read or storage of item, just go to the next one
                    print('Failed to insert attachment into database.')
                    print(e)
                    continue




if __name__ == "__main__":
    try:
        run_main()
    except Exception as e:
        print('Exception occured')
        import traceback
        print(e)
        print(traceback.format_exc(), flush=True)
    finally:
        import time
        print(f'{time.ctime()} Sleep for one hour....')
        time.sleep(3600)