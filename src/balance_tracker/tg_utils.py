import dataclasses
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

    def __post_init__(self) -> None:
        self.params["parse_mode"] = "markdown"
        self.params["chat_id"] = self.chat_id
        self._edit_url = f"https://api.telegram.org/bot{self.bot_token}/editMessageText"
        self._send_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        self._message_queue = []

    def send_forever(self):
        def run():
            while True:
                for message, kwargs in self._message_queue:
                    resp = message(**kwargs)
                    if isinstance(resp, requests.Response):
                        time.sleep(max(1.5 - resp.elapsed.total_seconds(), 0))

                self._message_queue.clear()
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

        # Send message
        resp = requests.post(url=self._send_url, params=self.params)

        if resp.status_code == 429:
            logger.warning(f"{resp.url[10:]}...\nRATE LIMITED Response:\n{resp.text}\nRetry after 10 seconds")
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
        # self.params["text"] = _escape_markdown(msg)
        self.params["text"] = msg

        # Send message
        resp = requests.post(url=self._edit_url, params=self.params)
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
            time.sleep(1)
            self.bot.send_msg(msg, save_id=False)

        except Exception:
            self.handleError(record)