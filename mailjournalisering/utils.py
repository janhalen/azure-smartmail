import exchangelib as ews
import threading



def run_function_with_retry(function, *args, event:threading.Event=None, retry_count=20, sleep_time=10):
    """Helper function for robustly executing function with retry"""

    # handle input
    if event is not None:
        event_set = event.is_set()
    else:
        event_set = False

    # retry calling
    count = 0
    while count < retry_count and not event_set:
        try:
            return function(*args)
        except (ews.errors.ErrorMailboxMoveInProgress, ews.errors.ErrorNoRespondingCASInDestinationSite) as e:
            print(f"Failed to failed to connect to EWS. Error: {e}. Attempt {count + 1} / {retry_count}")
            count += 1
            event.wait(sleep_time)
            if count == retry_count:
                raise