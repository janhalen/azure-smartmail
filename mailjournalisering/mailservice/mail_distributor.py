import utils
import exchangelib as ews
import re

class MailDistributor():

    def __init__(self, account, terminated_event, mode='stdout', destinations={}, auto_create_folders=False):
        """Maildistributor.
                account:            account with access to all destination accounts
                terminated_event:   sig_term event
                mode:               log to [stdout] / run in [test]-mode / run in [production]
        """

        # account with access to all destination accounts
        self.account = account

        # Whether or not unknown folders should be created
        self.auto_create_folders = auto_create_folders

        # distribution factory
        self.distribution_factory = {'stdout': self._distribute_stdout, 'test_copy': self._distribute_test_copy,
                                     'production': self._distribute_production}

        # set mode and distribution handler
        if mode in ['stdout', 'test_copy', 'production']:
            self.mode = mode
        else:
            raise ValueError(f"Mode must be in ['stdout', 'test_copy', 'production'], not '{mode}'")
        self.distribution_handler = self.distribution_factory[self.mode]
        print(self.mode)

        # setup destinations
        self.destinations = destinations
        self.check_destinations()

        # sig_term event
        self.terminated_event = terminated_event

    def check_destinations(self):
        """Read or update destinations from database and """

        # TODO: Perform a check of the new_destinations here before assignmet
        new_destinations = {}

        for key, dest in self.destinations.items():
            # single destination
            if type(dest) is dict:
                # perform check here - simple email check for now
                valid, folder = self._validate_destination(dest)
                if not valid:
                    raise ValueError(f"For key: [{key}]  destination {dest} is not valid.")
                dest['exchange_folder'] = folder
                new_destinations[key] = dest

            # multiple destinations
            elif type(dest) is list:
                destlist = []
                for d in dest:
                    # perform check here - simple email check for now
                    valid, folder = self._validate_destination(dest)
                    if not valid:
                        raise ValueError(f"For key: [{key}]  destination {d} is not valid.")
                    d['exchange_folder'] = folder
                    destlist.append(d)
                new_destinations[key] = dest

        # check for valid fallback key in destinations
        if 'fallback' not in new_destinations.keys():
            raise KeyError("No 'fallback'-key in list of destinations.")

        # check if email forward exists for test mode
        if self.mode == 'test':
            if 'testemail' not in new_destinations.keys():
                raise KeyError("No 'testemail'-key in list of destinations.")

        # if we get this far we can assign new destinations
        self.destinations = new_destinations

    def _move_item(self, item, folder):
        """Move item to folder"""
        utils.run_function_with_retry(self.account.bulk_move, [item], folder, event=self.terminated_event)

    def _copy_item(self, item, folder):
        """Copy item to folder"""
        utils.run_function_with_retry(self.account.bulk_copy, [item], folder, event=self.terminated_event)

    def _forward_item(self, item, smtp_address, comment=""):
        """Forward item to email address"""
        smtp_address = smtp_address if isinstance(smtp_address, list) else [smtp_address]
        utils.run_function_with_retry(item.forward, item.subject, comment, smtp_address, event=self.terminated_event)

    def _distribute_stdout(self, item, destination):
        """Simulate distribution of item, useful for development"""
        print(40 * '=')
        print(f"Item.id      : {item.id}")
        print(f"Item.subject : {item.subject}")
        print()
        print(f"Method       : {destination['method']}")
        print(f"Folder       : {destination['folderparts']}")
        print(f"Mailbox      : {destination['mailbox']}")
        print()
        return True

    def _distribute_test_copy(self, item, destination):
        """Distribute item when mode is 'test_copy', i.e. copy item to a folder."""

        d = f"{destination['mailbox']}/{'/'.join(destination['folderparts'])}"
        print(f"Copy {item.subject} to {d}")
        self._copy_item(item, destination['exchange_folder'])

        return True

    def _distribute_test_forward(self, item, destination):
        """Distribute item when mode is 'test', i.e. forward to specific mailbox with a comment"""

        if destination['method'] == 'move':
            comment = ews.HTMLBody(
                f"Distribute using {destination['method']} to folder {destination['folder']} on account {destination['mailbox']}")
        elif destination['method'] == 'copy':
            comment = ews.HTMLBody(
                f"Distribute using {destination['method']} to folder {destination['folder']} on account {destination['mailbox']}")
        elif destination == 'forward':
            comment = ews.HTMLBody(f"Distribute using {destination['method']} to account {destination['mailbox']}")
        else:
            raise ValueError("destination['method'] must be move, copy or forward.")

        self._forward_item(item, self.destinations['testemail'], comment)

    def _distribute_production(self, item, destination):
        """Distribute item when mode is 'production'"""

        if destination['method'] == 'move':
            self._move_item(item, destination['exchange_folder'])
        elif destination['method'] == 'copy':
            self._copy_item(item, destination['exchange_folder'])
        elif destination['method'] == 'forward':
            self._forward_item(item, destination['mailbox'])
        else:
            raise ValueError("destination['method'] must be move, copy or forward.")

        return True

    def distribute(self, item, destination_key=None, dest=None):
        """Distribute item according to selected method, return True on success and False on failure"""

        # get destinations from list
        if dest is None:
            # TODO: make the destination lookup robust to lower/upper-case
            if destination_key in self.destinations.keys():
                dest = self.destinations[destination_key]
            else:
                dest = self.destinations['fallback']

        success = self.distribution_handler(item, dest)

        print(f"Distributing key: {destination_key}  with method: {self.distribution_handler.__name__}, to: {dest}",
              flush=True)
        return success

    def distribute_to_many(self, item, destination_keys):
        destinations = [self.destinations['fallback'] if destination_key not in self.destinations else
                        self.destinations[destination_key] for destination_key in destination_keys]
        sorting_func = lambda x: 0 if x["method"] == "copy" else 1 if x["method"] == "forward" else 2
        destinations = sorted(destinations, key=sorting_func)

        if sum([d["method"] == "move" for d in destinations]) > 1:
            print("Can't move to multiple mailboxes. Distributing to manuel")
            return self.distribute(item, destination_key="fallback")

        return all([self.distribute(item, dest=d) for d in destinations])

    def _validate_destinations_email(self, destinations: dict):
        # loop over emails in destination, return false if any is not valid
        email_pattern = r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)"
        for key, email in destinations.items():
            # list of emails
            if type(email) is list:
                for e in email:
                    if not re.fullmatch(email_pattern, e):
                        raise ValueError(f'destination["{key}"] = {e} is not a valid email-address.')
            else:
                # assume email string
                if not re.fullmatch(email_pattern, email):
                    raise ValueError(f'destination["{key}"] = {email} is not a valid email-address.')

    def _validate_destinations_folders(self, destinations: dict):
        # loop over folders in destination, return false if any is not valid
        for k in destinations.keys():
            if not isinstance(destinations[k], ews.folders.base.Folder):
                raise ValueError(f'destination["{k}"] = {destinations[k]} is not a valid Exchange folder.')

    def _validate_destination(self, dest):
        """Perform validation of a destination"""

        # assume valid, try to disprove this
        valid = True

        # check email
        #email_pattern = r"(^[a-zA-Z0-9_.+-+&]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)"
        #valid = valid and (re.fullmatch(email_pattern, dest['mailbox']) is not None)

        # check method
        valid = valid and dest['method'] in ['move', 'copy', 'forward']

        # get folder reference
        folder = 'n/a'
        if dest['method'] in ['move', 'copy']:
            account = ews.Account(primary_smtp_address=dest['mailbox'], autodiscover=False,
                                  config=self.account.protocol.config, access_type=ews.DELEGATE)

            if len(dest["folderparts"]) == 1 and dest["folderparts"][0] == "Inbox":
                folder = account.inbox
            else:
                folder = account.root.tois
                for p in dest['folderparts']:
                    try:
                        folder = folder.__truediv__(p)
                    except ews.errors.ErrorFolderNotFound:
                        if self.auto_create_folders:
                            folder = ews.Folder(parent=folder, name=p)
                            folder.folder_class = "IPF.Note"
                            folder.save()
                        else:
                            raise

        return valid, folder