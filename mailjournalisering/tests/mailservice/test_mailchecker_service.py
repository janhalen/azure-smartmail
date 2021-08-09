from mailservice.mailservices import MailCheckService
import pytest

@pytest.fixture()
def connection(mocker):
    sql_logger = mocker.patch("dataaccess.sql_logger.SQLLogger")
    ews_config = mocker.patch("exchangelib.Configuration")
    ews_credentials = mocker.patch("exchangelib.Credentials")
    ews_account = mocker.patch("exchangelib.Account")
    build_folders = mocker.patch("mailservices.mailservices.MailCheckService._build_folders", return_value=[])
    mail_distributor = mocker.patch("mailservice.mail_distributor.MailDistributor")

    class dummy_processed_item_handler:
        def __init__(self, auditlog, config):
            pass

        def __contains__(self, item):
            return False

    mail_distributor = mocker.patch("mailservice.mailservices.processed_item_handler", dummy_processed_item_handler)