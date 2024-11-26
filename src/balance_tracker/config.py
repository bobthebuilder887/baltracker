import dataclasses
import json
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple, Self

from balance_tracker.api_req import WalletAddress


class WalletInfo(NamedTuple):
    address: WalletAddress
    name: str
    strategy: str


class EVMInfo(NamedTuple):
    gecko_ticker: str
    ticker: str
    moralis: str


class Keys(NamedTuple):
    moralis_api_key: str
    sui_api_key: str


class TgConfig(NamedTuple):
    bot_token: str
    chat_id: int
    send_msg: bool


@dataclasses.dataclass
class General:
    verbose: bool
    min_value_usd: int
    time_interval: int
    data_path: str


@dataclasses.dataclass
class Config:
    keys: Keys
    general: General
    telegram: TgConfig
    evm_wallets: list[WalletAddress] = dataclasses.field(default_factory=list)
    sol_wallets: list[WalletAddress] = dataclasses.field(default_factory=list)
    sui_wallets: list[WalletAddress] = dataclasses.field(default_factory=list)
    apt_wallets: list[WalletAddress] = dataclasses.field(default_factory=list)
    evm_info: dict[str, EVMInfo] = dataclasses.field(default_factory=dict)
    unsupported_balances: dict[str, Decimal] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if not Path(self.general.data_path).exists():
            Path(self.general.data_path).mkdir(parents=True)

    @classmethod
    def from_json(cls, path: Path) -> Self:
        with open(path) as f:
            cfg = json.load(f)

        evm_info = {}

        for info in cfg["evm_info"].values():
            evm_info[info["moralis"]] = EVMInfo(**info)

        unsupported_balances = {}
        for token, balances in cfg["unsupported_balances"].items():
            unsupported_balances[token] = sum(Decimal(b) for b in balances)

        return cls(
            keys=Keys(**cfg["keys"]),
            general=General(**cfg["general"]),
            telegram=TgConfig(**cfg["telegram"]),
            evm_wallets=list(cfg.get("evm_wallets", {})),
            sol_wallets=list(cfg.get("solana_wallets", {})),
            sui_wallets=list(cfg.get("sui_wallets", {})),
            apt_wallets=list(cfg.get("apt_wallets", {})),
            evm_info=evm_info,
            unsupported_balances=unsupported_balances,
        )

    @property
    def evm_chains(self) -> list[str]:
        return list(self.evm_chains)

    def min_sleep_interval(self) -> int:
        CUS = 40_000
        CU_COST = 10
        DAY_S = 24 * 3600
        n_chains = len(self.evm_info)
        n_wallet_req = len(self.evm_wallets) * n_chains + len(self.sol_wallets)
        req_per_day = CUS / CU_COST
        cycles = req_per_day / n_wallet_req
        return int(DAY_S // cycles + 1)
