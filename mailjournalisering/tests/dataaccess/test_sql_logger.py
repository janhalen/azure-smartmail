import pytest
from dataaccess.sql_logger import SQLLogger
import sqlite3
import datetime
import os

@pytest.fixture()
def connection():
    if os.path.exists("test.db"):
        os.remove("test.db")
    conn = sqlite3.connect("test.db")
    conn.execute("""CREATE TABLE auditlog(
	logging_id int IDENTITY(1,1) PRIMARY KEY,
	message_id varchar(500) NULL,
	timestamp_in datetime2(7) NULL,
	timestamp_out datetime2(7) NULL,
	timestamp_email datetime2(7) NULL,
	sender varchar(100) NULL,
	classification varchar(100) NULL,
	confidence float NULL,
	call_type varchar(50) NULL,
	text varchar(5100) NULL,
	sorting_threshold float NULL,
	sorting_threshold_type varchar(500) NULL,
	model_classification varchar(100) NULL,
	customerID int NULL,
	model_version varchar(32) NULL
)""")
    yield conn
    conn.close()
    os.remove("test.db")


@pytest.fixture()
def connection_mock(connection, mocker):
    connection_mock = mocker.patch("pyodbc.connect", return_value=connection)
    mocker.patch("dataaccess.sql_logger.SQLLogger._set_column_properties")
    mocker.patch("dataaccess.sql_logger.SQLLogger.preprocessvalues", lambda x, *args: args)
    return connection_mock, connection

def test_basic_connection(connection_mock):
    connection_mock, connection = connection_mock
    logger = SQLLogger()
    connection_mock.assert_called_once()

def test_log_entry(connection_mock):
    connection_mock, connection = connection_mock
    logger = SQLLogger(table="auditlog")
    data_tuple = ("messageid",
                     datetime.datetime.now(),
                     datetime.datetime.now(),
                     datetime.datetime.now(),
                     "sender@email.com",
                     "classification@domain.com",
                     0.42,
                     "model_call_type",
                     "Email body string",
                     0.9,
                     "default_sorting_threshold",
                     "classification@domain.com",
                     0,
                     "modelversion42")
    logger.log_entry(*data_tuple)
    res = connection.execute("select * from auditlog where message_id=?", ["messageid"]).fetchall()

    assert len(res) == 1
    for table_val, data_val in zip(res[0][1:], data_tuple):
        assert str(table_val) == str(data_val)
