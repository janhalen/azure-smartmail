import os
#from . import utils
import signal
import configuration
import mailservice


## load configuration
system_config_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "system_config.yaml")

configuration = configuration.ConfigurationHandler(system_config_file, os.environ["ENV"], [os.environ["CUSTOMER_ID"]])

configuration.customer_config[os.environ["CUSTOMER_ID"]]["DISTRIBUTION_MODE"] = os.environ["DISTRIBUTION_MODE"]

# set flag INITIAL_RUN==True, this will be set to False after first run
configuration.customer_config[os.environ["CUSTOMER_ID"]]["INITIAL_RUN"] = True

# init mail checker
configuration.customer_config[os.environ["CUSTOMER_ID"]]["MONITOR"].info('Main: Configauration loaded. Initialising mailchecker.')
mailchecker = mailservice.MailCheckService(configuration.customer_config[os.environ["CUSTOMER_ID"]])


def term(signalNumber, _):
    print(f"Recieved signal {signalNumber}")
    mailchecker.terminated_event.set()
    print("Send kill to mailchecker")
    mailchecker.join()
    print("mailcheck quitted")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, term)
    signal.signal(signal.SIGINT, term)
    mailchecker.start()