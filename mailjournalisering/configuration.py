import yaml
import utils
import traceback
import ast
import pyodbc
import pathlib
import os
import dataaccess
import datetime

class ConfigurationHandler:

    type_parse_dict = {"dict": ast.literal_eval,
    "list": ast.literal_eval,
    "float": float,
    "int": int,
    "str": lambda x:x,
    "bool": lambda x: x.lower() == "true",
    "datetime": lambda x: datetime.datetime.strptime(x, "%Y-%m-%d %H:%M:%S")}


    def __init__(self,system_config_file, environment, customer_ids):

        self.environment = environment
        self.system_config_file = system_config_file
        self.customer_config = dict()  

        # TODO: Get customer list from database
        
        try:
            with open(self.system_config_file, "r", encoding="utf-8") as f:
                self.system_config = yaml.safe_load(f)[self.environment]
                print(f"Loaded system configuration for {self.environment} from: {self.system_config_file}.")

            # read secrets
            secrets = self._get_secrets(self.system_config["SECRET_PATH"])
            if secrets is not None:
                for k, v in secrets.items():
                    self.system_config[k] = v

            if "DATABASE_PASSWORD" not in self.system_config:
                self.system_config["DATABASE_PASSWORD"] = self.system_config[
                    self.system_config["DATABASE_PASSWORD_VAULT_KEY"]]



            for cid in customer_ids:
                self.customer_config[cid] = self.load_config(cid)

                # Add the settings from SYSTEM_CONFIG to CONFIG without overwriting
                for k, v in self.system_config.items():
                    if k not in self.customer_config[cid]:
                        self.customer_config[cid][k] = v

                if "EXCHANGE_PW" not in self.customer_config[cid]:
                    self.customer_config[cid]["EXCHANGE_PW"] = self.customer_config[cid][
                        self.customer_config[cid]["EXCHANGE_PASSWORD_VAULT_KEY"]]

                # setup monitoring service
                if self.customer_config[cid]["USE_STD_MONITOR"]:
                    self.customer_config[cid]['MONITOR'] = dataaccess.stdoutmonitor.STDOutMonitor()
                else:
                    self.customer_config[cid]['MONITOR'] = dataaccess.monitoring.monitor(self.customer_config[cid])
        
        except Exception as e:
            print(e, flush=True)
            print(traceback.format_exc(), flush=True)
            raise e

    def _get_secrets(self, secret_path):
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
            print(f"Loaded secret: {secret}")
        return d

    def _add_sql_rows_to_config(self, rows, config):
        for row in rows:
            config[row.SettingKey] = self.type_parse_dict[row.PythonValueType](row.Value)

    def load_config(self, customer_id):
        config = {}
        connection_str = "Driver={ODBC Driver 17 for SQL Server};Server="+ self.system_config["DATABASE_URI"] + \
                        ",1433;Database=" + self.system_config["DATABASE_NAME"] + \
                        ";Uid=" + self.system_config["DATABASE_USER_NAME"] + \
                        ";Pwd={" + self.system_config["DATABASE_PASSWORD"] + \
                        "};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        conn = pyodbc.connect(connection_str)
        cursor = conn.cursor()

        cursor.execute(f"select * from Settings where CustomerId=? and Env='default'", customer_id)
        self._add_sql_rows_to_config(cursor.fetchall(), config)

        cursor.execute("select * from Settings where CustomerId=? and Env=?", customer_id, self.environment)
        self._add_sql_rows_to_config(cursor.fetchall(), config)

        # Add recipients to config
        cursor.execute("select * from Recipients where CustomerId=? order by isShared asc", customer_id)
        config["RECIPIENTS"] = {}
        for row in cursor:
            config["RECIPIENTS"][row.name] = row.emailAddress

        # Add destinations to config
        id_str = f"SELECT * FROM destinations where customerID={customer_id}"
        destinations = {}
        for row in cursor.execute(id_str):
            destinations[row.key] = {'method':row.method, 'folderparts':row.folderparts.split(';'), 'mailbox':row.mailbox}

        # Add recipient to destinations dict
        if os.environ["DISTRIBUTION_MODE"] != "test_copy":
            if config["USE_ATT_EXTRACTOR"]:
                for name, email in config["RECIPIENTS"].items():
                    if email.lower() not in destinations:
                        destinations[email.lower()] = {"method": "forward", "folderparts": "", "mailbox": email.lower()}

            # If a rule has a return value not in DESTINATIONS, we forward it.
            for rule in config["RULES"]:
                if isinstance(rule["return_value"], list):
                    address = [a.lower() for a in rule["return_value"]]
                elif isinstance(rule["return_value"], str):
                    address = [rule["return_value"].lower()]
                else:
                    raise TypeError("Unknown type for rule return value")
                for a in address:
                    if a not in destinations:
                        destinations[a] = {"method": "forward", "folderparts": "", "mailbox": a}

        config['DESTINATIONS'] = destinations
        return config
