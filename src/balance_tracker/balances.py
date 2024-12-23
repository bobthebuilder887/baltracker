import argparse
import dataclasses
import datetime
import json
import logging
import os
import signal
import time
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from types import FrameType
from typing import Literal, Sequence

from balance_tracker.api_req import TokenInfo, get_and_set_price_info, get_balance_update
from balance_tracker.config import Config
from balance_tracker.tg_utils import TGMsgBot

TEST_MODE = False

logger = logging.getLogger(__name__)


class SigTerm(SystemExit):
    pass


def term_cb(signal: int, frame: FrameType) -> None:
    raise SigTerm(1)


def mcap_str(mcap: Decimal) -> str:
    """Convert mcap into a readable string format, i.e. 1600000000 -> 1.6B"""
    r = 0
    if mcap < 1000:
        div = 1
        s = ""
    elif mcap < 1000_000:
        div = 1000
        s = "K"
    elif mcap < 1000_000_000:
        div = 1000_000
        s = "M"
        r = 1
    elif mcap < 1000_000_000_000:
        div = 1000_000_000
        s = "B"
        r = 1
    else:
        div = 1000_000_000_000
        s = "T"
        r = 1

    return f"{mcap /div:.{r}f}{s}"


@dataclasses.dataclass
class BalanceUpdate:
    old: TokenInfo | Literal[False] = False
    new: TokenInfo | Literal[False] = False
    value_change: Decimal = dataclasses.field(init=False)
    value_change_pct: Decimal = dataclasses.field(init=False)
    balance_change: Decimal = dataclasses.field(init=False)
    balance_change_pct: Decimal = dataclasses.field(init=False)
    price_change_pct: Decimal = dataclasses.field(init=False)

    def __post_init__(self):
        if not self.old and self.new:
            self.value_change = self.new.real_value
            self.value_change_pct = Decimal(100)
            self.balance_change = self.new.balance
            self.balance_change_pct = Decimal(100)
            self.price_change_pct = Decimal(0)
        elif not self.new and self.old:
            self.value_change = -1 * self.old.real_value
            self.value_change_pct = Decimal(-100)
            self.balance_change = -1 * self.old.balance
            self.price_change_pct = Decimal(0)
        elif self.new and self.old:
            self.balance_change = self.new.balance - self.old.balance
            self.balance_change_pct = 100 * (self.new.balance - self.old.balance) / self.old.balance
            if self.old.price == 0 and self.new.price == 0:
                self.value_change = Decimal(0)
                self.value_change_pct = Decimal(100)
                self.price_change_pct = Decimal(0)
            elif self.old.price == 0:
                self.value_change = self.new.real_value
                self.value_change_pct = Decimal(100)
                self.price_change_pct = 100 * (self.new.price - self.old.price)
            else:
                self.value_change = self.new.real_value - self.old.real_value
                self.value_change_pct = (
                    Decimal(100) * (self.new.real_value - self.old.real_value) / self.old.real_value
                )
                self.price_change_pct = 100 * (self.new.price - self.old.price) / self.old.price

    def line_str(self, hide_balance: bool = False, add_links=True) -> tuple[str, str]:
        if not self.new:
            return "", ""

        if round(self.price_change_pct, 1) < 0:
            emoji = "🔴"
        elif round(self.value_change_pct, 1) == 100:
            emoji = "🟣"

        elif round(self.price_change_pct, 1) == 0:
            emoji = "🟡"
        else:
            emoji = "🟢"

        sign = ""

        if round(self.value_change, 2) > 0:
            sign = "+"

        # Keep the symbol a certain size
        symbol = self.new.symbol if len(self.new.symbol) < 13 else f"{self.new.symbol[:10]}..."
        if add_links:
            symbol = f"[{symbol}]({self.new.link})" if self.new.link else symbol

        mcap_fmt = mcap_str(self.new.market_cap)
        mcap = f"({mcap_fmt})" if self.new.market_cap != 0 else ""
        chain = self.new.chain
        value = f"${self.new.real_value:,.2f}"

        if round(self.value_change, 2) != 0:
            chg = f"{sign}{self.value_change:,.2f}"
            chg_str = f" ({chg})"
        else:
            chg_str = ""

        if chg_str:
            if not self.new.link:
                line_str = f"*{emoji} {symbol} {mcap} | {value}{chg_str}*"
            else:
                line_str = f"*{emoji} *{symbol}* {mcap} | {value}{chg_str}*"
        else:
            line_str = f"{emoji} {symbol} {mcap} | {value}{chg_str}"

        if hide_balance:
            for c in line_str:
                if c.isnumeric():
                    line_str = line_str.replace(c, "9")

        return chain, line_str


def save_balances(balances: dict[str, TokenInfo], path: Path) -> None:
    balances_json = {k: v.to_json_dict() for k, v in balances.items()}
    with open(path, "w") as f:
        json.dump(balances_json, f)


def load_previous_balance(path: Path) -> dict[str, TokenInfo]:
    if not path.exists():
        return {}

    with open(path, "r") as f:
        bal_dict = json.load(f)

    # convert price, liquidity and balance to Decimal
    for v in bal_dict.values():
        v["price"] = Decimal(v["price"])
        v["liquidity"] = Decimal(v["liquidity"])
        v["market_cap"] = Decimal(v["market_cap"])
        v["balances"] = {k: Decimal(v) for k, v in v["balances"].items()}

    return {k: TokenInfo(**v) for k, v in bal_dict.items()}


def gen_bal_update(
    cfg,
    token_contracts,
    all_balances,
    previous_balance,
    time_s,
    portfolio_path,
    token_bal_path,
    portfolio_prev_usd,
) -> str:
    balance_update = get_and_set_price_info(
        token_contracts=token_contracts,
        unsupported_balances=cfg.unsupported_balances,
        all_balances=all_balances,
    )

    # Correct for faulty market data from the Dexscreener API
    for address, info in balance_update.items():
        # If missing price take the previous balance update
        # This means that it likely has no trading volume past 24h
        if info.price == 0:
            info.price = previous_balance.get(address, info).price
            info.liquidity = previous_balance.get(address, info).liquidity
            info.market_cap = previous_balance.get(address, info).market_cap
            continue

        if not (prev_info := previous_balance.get(address, False)):
            continue

        if prev_info.dex != info.dex and prev_info.liquidity > info.liquidity:
            info.price = prev_info.price
            info.liquidity = prev_info.liquidity
            info.market_cap = prev_info.market_cap
            info.dex = prev_info.dex

    portfolio_usd = sum(info.real_value for info in balance_update.values())

    portfolio_by_chain = defaultdict(Decimal)
    for info in balance_update.values():
        portfolio_by_chain[info.chain] += info.real_value

    portfolio_by_chain_old = defaultdict(Decimal)
    for info in previous_balance.values():
        portfolio_by_chain_old[info.chain] += info.real_value

    chain_strs = {}
    for chain in portfolio_by_chain:
        value = portfolio_by_chain[chain]
        value_old = portfolio_by_chain_old[chain]
        chg = value - value_old
        sign = "+" if round(chg, 2) > 0 else ""
        chg_str = f" ({sign}{chg:,.2f})" if round(abs(chg), 2) > 0 else ""
        chain_str = f"*⛓️ [{chain.upper()}] -- [${value:,.2f}{chg_str}]*"
        if not portfolio_prev_usd:
            pass
        elif chg / portfolio_prev_usd > 0.01:
            chain_str += " 🔥"
        elif chg / portfolio_prev_usd < -0.01:
            chain_str += " ❗️"
        if cfg.general.hide_balances:
            for c in chain_str:
                if c.isnumeric():
                    chain_str = chain_str.replace(c, "9")
        chain_strs[chain] = chain_str

    portfolio_chg = portfolio_usd - portfolio_prev_usd
    sign = "+" if round(portfolio_chg, 2) > 0 else ""

    if round(portfolio_chg, 2) < 0:
        emoji = "🔴"
    elif round(portfolio_chg, 2) == 0:
        emoji = "🟡"
    else:
        emoji = "🟢"

    ts_str = datetime.datetime.fromtimestamp(time_s).strftime("%y-%m-%d %H:%M")
    ts_str = f"*{ts_str} PORTFOLIO UPDATE*"
    portfolio_str = f"*{emoji} ${portfolio_usd:,.2f} ({sign}{portfolio_chg:,.2f})*"
    if cfg.general.hide_balances:
        for c in portfolio_str:
            if c.isnumeric():
                portfolio_str = portfolio_str.replace(c, "9")

    all_contracts = set(previous_balance.keys()).union(set(balance_update.keys()))

    updates = list()
    for t_contract in all_contracts:
        update = BalanceUpdate(
            old=previous_balance.get(t_contract, False),
            new=balance_update.get(t_contract, False),
        )
        if not update.new:
            continue
        if update.new.price == 0 or update.new.real_value < cfg.general.min_value_usd:
            continue

        updates.append(update)

    updates = sorted(updates, key=lambda x: (x.new.chain, x.new.real_value), reverse=True)

    msg = []
    for update in updates:
        add_links = True if not cfg.general.verbose else False
        chain, line_str = update.line_str(
            hide_balance=cfg.general.hide_balances,
            add_links=add_links,
        )

        if not portfolio_prev_usd:
            pass
        elif 100 * update.value_change / portfolio_prev_usd > 0.25:
            line_str += " 🔥"
        elif 100 * update.value_change / portfolio_prev_usd < -0.25:
            line_str += " ❗️"

        if chain_strs[chain] not in msg:
            msg.append("----------------")
            msg.append(chain_strs[chain])
            msg.append("----------------")
        msg.append(line_str)

    msg = "\n".join(
        (
            ts_str,
            "\n".join(msg),
            "-" * len(portfolio_str),
            portfolio_str,
        )
    )

    # Save balances
    save_balances(balance_update, token_bal_path)
    # Store portfolio value
    with open(portfolio_path, "a") as f:
        f.write(f"{time_s}, {portfolio_usd}\n")

    return msg


def track_balances(cfg: Config, interval_s: int, tg_bot: None | TGMsgBot) -> None:
    if not Path(cfg.general.data_path).exists():
        Path(cfg.general.data_path).mkdir(parents=True)

    portfolio_path = Path(cfg.general.data_path) / "portfolio.csv"
    token_bal_path = Path(cfg.general.data_path) / "token_balances.json"
    native_bal_path = Path(cfg.general.data_path) / ".native_balances.json"

    # Fill in coins that don't have dexscreener update due to low activity
    previous_balance = load_previous_balance(token_bal_path)

    token_contracts, all_balances = get_balance_update(
        evm_wallets=cfg.evm_wallets,
        sol_wallets=cfg.sol_wallets,
        sui_wallets=cfg.sui_wallets,
        unsupported_balances=cfg.unsupported_balances,
        evm_info=cfg.evm_info,
        moralis_api_key=cfg.keys.moralis_api_key,
        sui_api_key=cfg.keys.sui_api_key,
        old_balances=previous_balance,
        native_bal_path=native_bal_path,
    )

    if portfolio_path.exists():
        with open(portfolio_path) as f:
            portfolio_prev_usd = Decimal(f.readlines()[-1].strip().split(",")[-1].strip())
    else:
        portfolio_prev_usd = Decimal(0)

    # Less than 60 edits per minute
    updates = interval_s  # Keep updating prices until time interval expires
    sent = False
    while updates > 0:
        start = time.perf_counter()
        msg = gen_bal_update(
            cfg=cfg,
            token_contracts=token_contracts,
            all_balances=all_balances,
            previous_balance=previous_balance,
            time_s=int(time.time()),
            portfolio_path=portfolio_path,
            token_bal_path=token_bal_path,
            portfolio_prev_usd=portfolio_prev_usd,
        )

        # Print message
        if cfg.general.verbose:
            print("\x1b[2J\x1b[H", end="")
            print(msg.replace("*", ""))
            print("*" * 20)

        if tg_bot and not sent:
            tg_bot.schedule_send_msg(msg=msg)
            sent = True
        elif tg_bot and getattr(tg_bot, "_last_msg", False):
            tg_bot.schedule_edit_msg(msg=msg)
        else:
            pass

        end = time.perf_counter()
        time_diff = end - start
        updates -= time_diff
        # Make sure the time interval is met with telegram messages
        if time_diff < 5:
            remainder = 5 - time_diff
            time.sleep(remainder)
            updates -= remainder
        else:
            time.sleep(0.5)
            updates -= 0.5


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Track wallet balances")
    parser.add_argument(
        "-t",
        "--time_interval",
        type=int,
        default=0,
        help="Time interval at which to update balances, defaults to 300 seconds",
    )

    parser.add_argument(
        "-c",
        "--config_path",
        type=str,
        default="config.json",
        help="config path, defaults to cfg.json",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="wether to print an output or not",
    )

    args = parser.parse_args()
    cfg = Config.from_json(args.config_path)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler("baltracker.log", mode="a")],
    )

    if cfg.telegram.send_msg:
        tg_bot = TGMsgBot(
            bot_token=cfg.telegram.bot_token,
            backup_token=cfg.telegram.backup_bot_token,
            chat_id=str(cfg.telegram.chat_id),
        )

        tg_bot.send_forever()

        tg_bot.schedule_send_msg(
            msg="Bot has been restarted. If the restarts persit, check logs",
            save_id=False,
        )
        m = "Sending messages to Telegram. To disable, set send_msg to false in config.json and restart the script"
        logger.warning(m)
    else:
        tg_bot = None
    INTERVAL_S = args.time_interval if args.time_interval > 0 else cfg.general.time_interval
    NATIVE_BAL_PATH = Path(cfg.general.data_path) / ".native_balances.json"

    logger.info(f"Recording portfolio every {INTERVAL_S} seconds")
    signal.signal(signal.SIGTERM, term_cb)
    signal.signal(signal.SIGINT, term_cb)
    signal.signal(signal.SIGHUP, term_cb)

    try:
        n_updates = 0
        while True:
            cfg = Config.from_json(args.config_path)
            cfg.general.verbose = args.verbose if args.verbose else cfg.general.verbose
            track_balances(cfg, INTERVAL_S, tg_bot)
            n_updates += 1
            # reload native eth balances roughly every 2 hours (in some instances can fix a balance mis-reading)
            if not TEST_MODE and n_updates == 12:
                os.remove(NATIVE_BAL_PATH)
                n_updates = 0

            if tg_bot and not tg_bot.is_sending_forever:
                tg_bot._message_queue = []
                tg_bot.send_forever()

    except Exception as e:
        logger.error(e, exc_info=True)
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Bot is being shut down")
        time.sleep(1)
        if tg_bot is not None:
            tg_bot.schedule_send_msg(msg="Bot is being shut down!", save_id=False)
            tg_bot.is_sending_forever = False
            logger.info(f"Sending last tg messages. Queue size: {len(tg_bot.message_queue)}")
            time.sleep(1)
            while tg_bot and tg_bot.message_queue:
                time.sleep(1)
            tg_bot.thread.join()

        time.sleep(1)
        logger.info("Bot is shut down")


if __name__ == "__main__":
    main()
