
class STDOutMonitor:

    def _print(self, type, string):
        print(f"[{type}] {string}")

    def exception(self, exception_str, extra={}):
        self._print("EXCEPTION", exception_str)

    def warning(self, warning_str, extra={}):
        self._print("WARNING", warning_str)

    def info(self, info_str, extra={}):
        self._print("INFO", info_str)

    def email_trace(self, prep_item, message):
        print(f"[EMAIL TRACE] Subject: {prep_item.subject}")

    def email_handling_success(self, prep_item):
        print(f"{prep_item} handled succesfully")

    def send_heartbeat(self):
        print("Sending hearbeat")

    def send_event_data_batch(self, payload):
        print(f"Event data batch: {payload}")