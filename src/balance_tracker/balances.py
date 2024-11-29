import argparse
from collections import defaultdict
import dataclasses
import datetime
import json
import logging
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Literal, Sequence

import requests
import rich

from balance_tracker.api_req import TokenAddress, TokenInfo, get_balance_update
from balance_tracker.config import Config

# TODO: add support for PF tokens (Dexscreener does not have prices)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    filename="baltracker.log",
    filemode="a",
)

logger = logging.getLogger(__name__)


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

    def line_str(self) -> tuple[str, str]:
        if not self.new:
            return "", ""

        if self.price_change_pct < 0:
            emoji = "🔴"
        elif self.value_change_pct == 100:
            emoji = "🟣"

        elif self.price_change_pct == 0:
            emoji = "🟡"
        else:
            emoji = "🟢"

        sign = ""

        if self.value_change_pct > 0:
            sign = "+"

        # Keep the symbol a certain size
        symbol = self.new.symbol if len(self.new.symbol) < 13 else f"{self.new.symbol[:10]}..."
        mcap_fmt = mcap_str(self.new.market_cap)
        mcap = f"({mcap_fmt})" if self.new.market_cap != 0 else ""
        chain = self.new.chain
        value = f"${self.new.real_value:,.2f}"

        if self.value_change_pct != 0:
            chg = f"{sign}{self.value_change:,.2f}"
            # chg_pct = f"{sign}{self.value_change_pct:.2f}%"
            chg_str = f" ({chg})"
        else:
            chg_str = ""

        return chain, f"{emoji} {symbol} {mcap} | {value}{chg_str}"


def send_tg_msg(msg: str, bot_token: str, chat_id: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendmessage"
    params = {"chat_id": chat_id, "text": msg, "parse_mode": "markdown"}
    logger.info("sending a message to tg bot")
    try:
        resp = requests.post(url, params=params)
        resp.raise_for_status()
        logger.info("message sent")
    except requests.HTTPError as e:
        logger.error(e, exc_info=True)


def save_balances(balances: dict[TokenAddress, TokenInfo], path: Path) -> None:
    balances_json = {k: v.to_json_dict() for k, v in balances.items()}
    with open(path, "w") as f:
        json.dump(balances_json, f)


def load_previous_balance(path: Path) -> dict[TokenAddress, TokenInfo]:
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


def track_balances(cfg: Config) -> None:
    TIME_S = int(time.time())

    PORTFOLIO_PATH = Path(cfg.general.data_path) / "portfolio.csv"
    TOKEN_BAL_PATH = Path(cfg.general.data_path) / "token_balances.json"
    NATIVE_BAL_PATH = Path(cfg.general.data_path) / ".native_balances.json"

    # Fill in coins that don't have dexscreener update due to low activity
    previous_balance = load_previous_balance(TOKEN_BAL_PATH)

    balance_update = get_balance_update(
        evm_wallets=cfg.evm_wallets,
        sol_wallets=cfg.sol_wallets,
        sui_wallets=cfg.sui_wallets,
        unsupported_balances=cfg.unsupported_balances,
        evm_info=cfg.evm_info,
        moralis_api_key=cfg.keys.moralis_api_key,
        sui_api_key=cfg.keys.sui_api_key,
        old_balances=previous_balance,
        native_bal_path=NATIVE_BAL_PATH,
    )

    for address, info in balance_update.items():
        if info.price != 0:
            continue
        info.price = previous_balance.get(address, info).price
        info.liquidity = previous_balance.get(address, info).liquidity
        info.market_cap = previous_balance.get(address, info).market_cap

    if PORTFOLIO_PATH.exists():
        with open(PORTFOLIO_PATH) as f:
            portfolio_prev_usd = Decimal(f.readlines()[-1].strip().split(", ")[-1])
    else:
        portfolio_prev_usd = Decimal(0)

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
        sign = "+" if chg > 0 else ""
        chain_str = f"-------- [{chain.upper()}] -- ${value:,.2f} ({sign}{chg:,.2f})"
        chain_strs[chain] = chain_str

    portfolio_chg = portfolio_usd - portfolio_prev_usd
    portfolio_chg_pct = 100 * (portfolio_usd - portfolio_prev_usd) / portfolio_prev_usd
    sign = "+" if portfolio_chg > 0 else ""

    if portfolio_chg < 0:
        emoji = "🔴"
    elif portfolio_chg == 0:
        emoji = "🟡"
    else:
        emoji = "🟢"

    ts_str = datetime.datetime.fromtimestamp(TIME_S).strftime("%Y-%m-%d %H:%M")
    ts_str = f"--- Portfolio Update | {ts_str} ---"
    portfolio_str = f"{emoji} ${portfolio_usd:,.2f} ({sign}{portfolio_chg:,.2f} ({portfolio_chg_pct:.2f}%))"

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
        chain, line_str = update.line_str()
        if chain_strs[chain] not in msg:
            msg.append(chain_strs[chain])
        msg.append(line_str)

    # Print message
    if cfg.general.verbose:
        rich.print(ts_str)
        rich.print("\n".join(msg))
        rich.print("-" * len(portfolio_str))
        rich.print(portfolio_str)

    # Send message
    if cfg.telegram.send_msg:
        msg_thread = threading.Thread(
            target=send_tg_msg,
            args=(
                "\n".join(
                    (
                        ts_str,
                        "\n".join(msg),
                        "-" * len(portfolio_str),
                        portfolio_str,
                    )
                ),
                cfg.telegram.bot_token,
                str(cfg.telegram.chat_id),
            ),
        )
    else:
        msg_thread = threading.Thread(target=time.sleep, args=(1,))
    msg_thread.start()

    # Save balances
    save_balances(balance_update, TOKEN_BAL_PATH)

    # Store portfolio value
    with open(PORTFOLIO_PATH, "a") as f:
        f.write(f"{TIME_S}, {portfolio_usd}\n")

    msg_thread.join()


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
    INTERVAL_S = args.time_interval if args.time_interval > 0 else cfg.general.time_interval
    RETRY_S = 60

    logger.info(f"Recording portfolio every {INTERVAL_S} seconds")

    try:
        while True:
            try:
                cfg = Config.from_json(args.config_path)
                cfg.general.verbose = args.verbose if args.verbose else cfg.general.verbose
                track_balances(cfg)
                time.sleep(INTERVAL_S)
            # Network error handling
            except requests.HTTPError as e:
                msg_thread = threading.Thread(
                    target=send_tg_msg,
                    args=(
                        str(e),
                        cfg.telegram.bot_token,
                        str(cfg.telegram.chat_id),
                    ),
                )
                msg_thread.start()

                # TODO: make these more localized to the specific api
                logger.error(e, exc_info=True)
                if e.response.status_code == 401:
                    logger.fatal("Forbidden - API ")
                    raise
                elif e.response.status_code == 429:
                    if "moralis" in e.response.url:
                        logger.fatal("Ran out of limits for Moralis")
                        raise
                else:
                    pass

                logger.warning(f"Network error, trying again in {RETRY_S}")
                msg_thread.join()
                time.sleep(RETRY_S)
    except Exception as e:
        logger.error(e, exc_info=True)
        send_tg_msg(
            str(e),
            cfg.telegram.bot_token,
            str(cfg.telegram.chat_id),
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
