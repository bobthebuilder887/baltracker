import dataclasses
import json
import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)


class MissingMessageId(Exception):
    pass


@dataclasses.dataclass
class TGMsgBot:
    bot_token: str
    chat_id: str
    session: requests.Session = dataclasses.field(default_factory=requests.Session)
    params: dict = dataclasses.field(default_factory=dict)
    msg_id: int = 0
    is_sending_forever: bool = False

    def __post_init__(self) -> None:
        self.params["parse_mode"] = "markdown"
        self.params["chat_id"] = self.chat_id
        self._edit_url = f"https://api.telegram.org/bot{self.bot_token}/editMessageText"
        self._send_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        self._message_queue = []

    @property
    def message_queue(self) -> list:
        return self._message_queue

    def send_forever(self):
        self.is_sending_forever = True

        def run():
            while self.is_sending_forever or self._message_queue:
                if self._message_queue:
                    message, kwargs = self._message_queue.pop(0)
                    resp = message(**kwargs)
                    if isinstance(resp, requests.Response):
                        time.sleep(1.5)
                else:
                    time.sleep(0.5)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def schedule_send_msg(self, **kwargs):
        self._message_queue.append((self.send_msg, kwargs))

    def schedule_edit_msg(self, **kwargs):
        self._message_queue.append((self.edit_last_msg, kwargs))

    def send_msg(self, msg: str, save_id: bool = True) -> requests.Response:
        # Prepare params
        if "message_id" in self.params:
            del self.params["message_id"]
        self.params["text"] = msg
        self.params["link_preview_options"] = json.dumps({"is_disabled": True})
        # Send message
        resp = requests.post(url=self._send_url, params=self.params)

        if resp.status_code == 429:
            logger.warning(f"{resp.url[10:]}...\nRATE LIMITED Response:\n{resp.text}\nRetry after 10 seconds")
            time.sleep(10)
            return self.send_msg(msg, save_id)

        elif resp.status_code in (500, 501, 502, 503):
            logger.warning(f"{resp.url[10:]}...\nINTERNAL ERROR:\n{resp.text}\nRetry after 10 seconds")
            time.sleep(10)
            return self.send_msg(msg, save_id)

        resp.raise_for_status()

        if save_id:
            self.msg_id = resp.json()["result"]["message_id"]
            self._last_msg = msg
        return resp

    def edit_last_msg(self, msg: str) -> requests.Response | bool:
        if not self.msg_id:
            raise MissingMessageId

        if msg == self._last_msg:
            return True
        else:
            self._last_msg = msg

        # Prepare params
        self.params["message_id"] = self.msg_id
        self.params["text"] = msg

        # Send message
        resp = requests.post(url=self._edit_url, params=self.params)
        if resp.status_code == 429:
            logger.warning(f"{resp.url[10:]}...\nRATE LIMITED Response:\n{resp.text}\nRetry after 10 seconds")
            time.sleep(10)
            return self.edit_last_msg(msg)

        elif resp.status_code in (500, 501, 502, 503):
            logger.warning(f"{resp.url[10:]}...\nINTERNAL ERROR:\n{resp.text}\nRetry after 10 seconds")
            time.sleep(10)
            return self.edit_last_msg(msg)

        resp.raise_for_status()

        return resp


_fmt_str = "🚨 *%(levelname)s* 🚨\n" "%(asctime)s\n\n" "`%(filename)s:%(lineno)d`\n" "```\n%(message)s\n```"


class TelegramLogHandler(logging.Handler):
    def __init__(
        self,
        tg_bot: TGMsgBot,
        level: int,
    ):
        super().__init__(level)
        self.bot = tg_bot

        # Create formatter for messages
        self.formatter = logging.Formatter(_fmt_str, datefmt="%Y-%m-%d %H:%M:%S")

    def emit(self, record: logging.LogRecord) -> None:
        """Send log message to Telegram."""
        try:
            msg = self.formatter.format(record)

            # If message too long cut it short
            if len(msg) > 4000:
                rest = len(msg) - len(record.message)
                record.message = f"{record.message[:4000-rest]}..."
                msg = self.formatter.format(record)

            # Make sure no rate limits
            self.bot.schedule_send_msg(msg=msg, save_id=False)

        except Exception:
            self.handleError(record)
