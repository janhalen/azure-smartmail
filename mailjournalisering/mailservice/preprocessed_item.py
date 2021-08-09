from bs4 import BeautifulSoup
from tika import parser
import exchangelib as ews
import re
from pytz import timezone
import collections
from dataaccess.stdoutmonitor import STDOutMonitor

# start tika
print(f"Tika server endpoint: {parser.ServerEndpoint}", flush=True)


class PreprocessedItem(object):
    """Class for holding text preprocessed Exchange item"""

    def __init__(self, item, config):
        self.config = config
        self.item = item

        try:
            self.body = self._clean_html(item.body)
        except Exception as E:
            print(E)
            import traceback
            print(traceback.format_exc(), flush=True)
            self.body = ' '
            
        self.attachment_texts = self._get_attachment_texts(item, self.config['ALLOWED_CONTENT_TYPES'])

        self.time_zone = timezone(self.config['TIME_ZONE'])
        self.email_time_zone = timezone(self.config['EMAIL_TIME_ZONE'])

        self.received_time = item.datetime_received.replace(tzinfo=self.email_time_zone).astimezone(self.time_zone)

    def __getattribute__(self, attr):
        # if attribute exist in this object then return that, else return the attribute from the item
        if attr in ['item', 'body', 'attachment_texts', 'config', '_clean_html', '_get_text', '_get_attachment_texts',
                    'extract_text', 'time_zone', 'email_time_zone', 'received_time']:
            return object.__getattribute__(self, attr)
        else:
            return self.item.__getattribute__(attr)

    def extract_text(self):
        # concat texts
        return str(self.subject) + " " + str(self.body) + " ".join(self.attachment_texts)

    def _get_attachment_texts(self, item, allowed_content_type):
        """Helper method for getting text from attachments"""

        # set max size of attachment to process to 10 MB
        # TODO: change to a user setting, not hardcoded
        max_attachment_size = 10 * 1024 * 1024

        attachment_texts = []
        for attachment in item.attachments:
            if isinstance(attachment, ews.FileAttachment):
                if (attachment.content_type in allowed_content_type) and (attachment.size < max_attachment_size):

                    # if attachment is a file of relevant type extract text
                    try:
                        text = self._get_text(attachment.content)
                        attachment_texts.append(text)
                    except Exception as e:
                        # extraction failed, return empty string - should also throw an error to log
                        import traceback
                        print(e)
                        print(traceback.format_exc(), flush=True)
                        self.config['MONITOR'].exception(str(e))
                        attachment_texts.append(" ")
                else:
                    # if not, return empty string
                    attachment_texts.append(" ")

            elif isinstance(attachment, ews.ItemAttachment):
                # if attachment is a message then extract subject and body
                if isinstance(attachment.item, ews.Message):
                    try:
                        text = attachment.item.subject
                        text = text + " " + self._clean_html(attachment.item.body) + " " + " ".join(self._get_attachment_texts(attachment.item, allowed_content_type))
                        attachment_texts.append(text)
                    except Exception as e:
                        # if text extraction from item attachment fails, then append an empty string
                        attachment_texts.append(" ")
                        import traceback
                        print(e)
                        print(traceback.format_exc(), flush=True)
                        self.config['MONITOR'].exception(str(e))
                else:
                    # if not a message, return empty string
                    attachment_texts.append(" ")

        return attachment_texts

    # Tika is able to extract both pdf and docx
    def _get_text(self, byte_string, max_string_length=1e30):
        content = ""
        try:
            # try to extract content
            f  = parser.from_buffer(byte_string)
            content = f['content']

            if content is None:
                content = " "
            else:
                # replace white-space, tabs, newlines, etc with a single white-space
                content = re.sub(r'\s+', ' ', content).strip()
        except Exception as e:
            # if an exception occurs, return empty string
            import traceback
            print(e)
            print(traceback.format_exc(), flush=True)
            self.config['MONITOR'].exception(str(e))
            content = " "
        finally:
            return content


    def _clean_html(self, mail):
        """Strip html for anything else but content text"""

        if mail is None:
            return " "

        encoding = re.findall(r"<meta.*charset=([0-9\-a-z]*)\">", mail, flags=re.IGNORECASE)
        if len(encoding) > 0:
            try:
                mail = mail.encode(encoding[0])
            except UnicodeEncodeError:
                msg = "Failed to encode before sending to Tika. Sending with default encoding..."
                print(msg)
                self.config['MONITOR'].warning(msg)

        try:
            # get content by using tika
            return self._get_text(mail)
        except UnicodeEncodeError:
            msg = "Tika failed to parse email. Defaulting to beautiful soup...."
            print(msg)
            self.config['MONITOR'].warning(msg)


        mail = re.sub(r"\n", " ", mail)
        mail = re.sub(r"\r\n", " ", mail)
        mail = re.sub(r"<!--.*-->", "", mail)
        return BeautifulSoup(mail, features="html.parser").get_text()

    def __str__(self):
        return f"timestamp={self.received_time}, sender={'None' if self.sender is None else self.sender.email_address}, subject={self.subject}"


stdoutmonitor = STDOutMonitor()

def PreprocessedItemFromDB(row, config=None):
    """Return a preprocessed item from a DB row from the Emails2 table"""
    item = collections.namedtuple('preprocessed_item_from_db', ['subject', 'body', 'attachments', 'datetime_received'])

    item.subject = row.subject
    item.body = row.rawBody
    item.attachments = []
    item.datetime_received = row.timestamp

    if config is None:
        config = {}
        config['TIME_ZONE'] = 'Europe/Copenhagen'
        config['EMAIL_TIME_ZONE'] = 'Europe/Copenhagen'
        config['ALLOWED_CONTENT_TYPES'] = ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
        config["MONITOR"] = stdoutmonitor

    return PreprocessedItem(item, config)