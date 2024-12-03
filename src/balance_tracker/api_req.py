import concurrent.futures
import dataclasses
import functools
import json
import logging
import random
import time
from copy import deepcopy
from decimal import Decimal
from functools import cached_property
from itertools import batched
from pathlib import Path
from typing import Iterable

import requests

TokenAddress = str
WalletAddress = str
WalletBalances = dict[WalletAddress, Decimal]


# TODO: rewrite in a way that maximizes update throughput and acurracy
# - [ ] Each request should be handled in a separate thread in perpetuity at the maximum possible rate

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class TokenInfo:
    address: TokenAddress
    name: str
    symbol: str
    chain: str
    balances: WalletBalances
    price: Decimal = Decimal(0)
    liquidity: Decimal = Decimal(0)
    market_cap: Decimal = Decimal(0)
    link: str = ""

    @cached_property
    def balance(self) -> Decimal:
        return Decimal(sum(self.balances.values()))

    @cached_property
    def value(self) -> Decimal:
        return self.balance * self.price

    @cached_property
    def real_value(self):
        if self.liquidity == 0:
            return self.value

        available_liq = self.liquidity / 2
        slippage = (Decimal(1) - (available_liq - self.value) / available_liq) / 2
        return self.value * (Decimal(1) - slippage)

    def to_json_dict(self) -> dict:
        info_dict = dataclasses.asdict(self)
        info_dict["price"] = str(info_dict["price"])
        info_dict["liquidity"] = str(info_dict["liquidity"])
        info_dict["market_cap"] = str(info_dict["market_cap"])
        info_dict["balances"] = {k: str(v) for k, v in info_dict["balances"].items()}
        return info_dict


TokenInfos = dict[TokenAddress, TokenInfo]


def handle_sui_req(req) -> requests.Response:
    resp = req()

    if resp.status_code in (500, 501, 502, 503):
        logger.warning(f"{resp.url[10:]}...\nINTERNAL ERROR:\n{resp.text}\nRetry after 60 seconds")
        time.sleep(60)
        return handle_sui_req(req)
    elif resp.status_code == 429:
        logger.warning(f"{resp.url[10:]}...\nRATE LIMIT ERROR:\n{resp.text}\nRetry after 60 seconds")
        time.sleep(60)
        return handle_sui_req(req)
    else:
        resp.raise_for_status()

    return resp


def get_sui_balances(wallet_address: list[WalletAddress], api_key: str) -> TokenInfos:
    payload = {"objectTypes": ["coin", "nft"]}
    headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "x-api-key": api_key,
    }
    responses = {}
    with requests.Session() as session:
        session.headers.update(headers)
        for wallet in wallet_address:
            url = f"https://api.blockberry.one/sui/v1/accounts/{wallet}/objects"

            req = functools.partial(session.post, url, json=payload, headers=headers)
            resp = handle_sui_req(req)
            responses[wallet] = resp.json().get("coins", [])

            if len(wallet_address) > 1:
                # sleep to account for rate limits
                time.sleep(max(3 - resp.elapsed.total_seconds(), 0))

    token_balances = dict()
    for wallet, coins in responses.items():
        for coin in coins:
            address = coin["coinType"]
            balance = Decimal(coin["totalBalance"]) / (Decimal(10) ** Decimal(coin["decimals"]))
            if balance == 0:
                continue

            if address not in token_balances:
                info = TokenInfo(
                    address=address,
                    name=coin["coinName"],
                    symbol=coin["coinSymbol"],
                    balances={wallet: balance},
                    chain="sui",
                )
                token_balances[address] = info
            else:
                token_balances[address].balances[wallet] = balance

    return token_balances


def get_gecko_price(ticker: str) -> Decimal:
    resp = requests.get(
        url="https://api.coingecko.com/api/v3/simple/price",
        params={
            "ids": ticker,
            "vs_currencies": "usd",
        },
    )

    if resp.status_code == 429:
        logger.warning(f"{resp.url[10:]}...\nRATE LIMITED Response:\n{resp.text}\nRetry after 60 seconds")
        time.sleep(60)
        return get_gecko_price(ticker)
    elif resp.status_code == 500 or resp.status_code == 503:
        logger.warning(f"{resp.url[10:]}...\nINTERNAL ERROR:\n{resp.text}\nRetry after 60 seconds")
        time.sleep(60)
    else:
        resp.raise_for_status()

    return Decimal(resp.json()[ticker]["usd"])


def handle_moralis_req(req) -> dict:
    resp = req()

    if resp.status_code == 500 or resp.status_code == 503:
        logger.warning(f"{resp.url[10:]}...\nINTERNAL ERROR:\n{resp.text}\nRetry after 60 seconds")
        time.sleep(60)
        return handle_moralis_req(req)
    else:
        resp.raise_for_status()

    return resp.json()


def get_native_change_evm(
    evm_wallets: list[WalletAddress],
    evm_chains: list[str],
    moralis_api_key: str,
    native_bal_path: Path,
) -> dict[str, str]:
    """
    Figure out if there has been movements in a wallet since last update
    """
    url = "https://deep-index.moralis.io/api/v2.2/wallets/balances"
    params: dict[str, str | list[str]] = {"wallet_addresses": evm_wallets}
    responses = {}
    header = {
        "accept": "application/json",
        "X-API-Key": moralis_api_key,
    }
    with requests.Session() as session:
        session.headers.update(header)
        for chain in evm_chains:
            params["chain"] = chain
            req = functools.partial(session.get, url, params=params)
            resp = handle_moralis_req(req)
            native_balances = resp[0]["wallet_balances"]
            responses[chain] = {v["address"]: v["balance"] for v in native_balances}

    if native_bal_path.exists():
        with open(native_bal_path) as f:
            previous_responses = json.loads(f.read())
    else:
        previous_responses = {}

    with open(native_bal_path, "w") as f:
        json.dump(responses, f)

    evm_wallets = [w.lower() for w in evm_wallets]
    update_required = {}
    for chain in evm_chains:
        update_required[chain] = []
        for wallet in evm_wallets:
            if not previous_responses.get(chain, {}).get(wallet, False):
                update_required[chain].append(wallet)
            elif responses[chain][wallet] != previous_responses[chain][wallet]:
                update_required[chain].append(wallet)
            else:
                continue

    return update_required


def moralis_get_req(session: requests.Session, url: str, params: dict[str, str]) -> dict:
    resp = session.get(url, params=params)
    # TODO: go oer the docs and see what to do for each error case
    if resp.status_code == 429:
        time.sleep(60)
        return moralis_get_req(session, url, params)
    else:
        resp.raise_for_status()
    return resp.json()


def get_token_balances(
    sol_wallets: list[str],
    evm_wallets: list[str],
    evm_chains: list[str],
    moralis_api_key: str,
    native_bal_path: Path,
    old_balances: TokenInfos | None = None,
) -> TokenInfos:
    old_balances = {} if old_balances is None else deepcopy(old_balances)
    balances = {}
    sol_url = "https://solana-gateway.moralis.io/account/mainnet/{:1}/portfolio"
    evm_url = "https://deep-index.moralis.io/api/v2.2/wallets/{:1}/tokens"
    header = {
        "accept": "application/json",
        "X-API-Key": moralis_api_key,
    }

    SOL_ADDR = "so11111111111111111111111111111111111111112"
    with requests.Session() as session:
        session.headers.update(header)
        params: dict[str, int | str] = {"limit": 100}

        sol_responses = {}
        for wallet in sol_wallets:
            url = sol_url.format(wallet)
            req = functools.partial(session.get, url, params=params)
            data = handle_moralis_req(req)
            sol_responses[wallet] = data

        evm_responses = {}
        update_required = get_native_change_evm(
            evm_wallets=evm_wallets,
            evm_chains=evm_chains,
            moralis_api_key=moralis_api_key,
            native_bal_path=native_bal_path,
        )
        for chain, wallets in update_required.items():
            for wallet in wallets:
                for token in old_balances.values():
                    if wallet in token.balances and token.chain == chain:
                        del token.balances[wallet]

        # Need to keep only evm wallets that will be unchanged by request
        for token in old_balances.values():
            if len(token.balances) != 0 and token.chain in update_required:
                balances[token.address] = token

        params["exclude_spam"] = True
        for chain, wallets in update_required.items():
            params["chain"] = chain
            for wallet in wallets:
                url = evm_url.format(wallet)
                req = functools.partial(session.get, url, params=params)
                data = handle_moralis_req(req)
                evm_responses[(wallet, chain)] = data

    for wallet, data in sol_responses.items():
        for token in data["tokens"]:
            addr = token["mint"]
            balance = Decimal(token["amount"])
            if balance == 0:
                continue
            if addr not in balances:
                info = TokenInfo(
                    address=addr,
                    name=token["name"],
                    symbol=token["symbol"],
                    balances={wallet: balance},
                    chain="solana",
                )
                balances[addr] = info

            else:
                balances[addr].balances[wallet] = balance

        sol_balance = Decimal(data["nativeBalance"]["solana"])
        if SOL_ADDR not in balances:
            native_info = TokenInfo(
                address=SOL_ADDR,
                name="Solana",
                symbol="SOL",
                chain="solana",
                balances={wallet: sol_balance},
            )
            balances[SOL_ADDR] = native_info
        else:
            balances[SOL_ADDR].balances[wallet] = Decimal(data["nativeBalance"]["solana"])

    for (wallet, chain), data in evm_responses.items():
        for token in data["result"]:
            addr = token["token_address"] if not token["native_token"] else chain
            balance = Decimal(token["balance_formatted"])
            if balance == 0:
                continue
            if addr not in balances:
                info = TokenInfo(
                    address=addr,
                    name=token["name"],
                    symbol=token["symbol"],
                    balances={wallet: balance},
                    chain=chain,
                )
                balances[addr] = info

            else:
                balances[addr].balances[wallet] = Decimal(token["balance_formatted"])

    return balances


def handle_dex_req(req) -> dict:
    resp = req()
    if resp.status_code == 500 or resp.status_code == 503:
        logger.warning(f"{resp.url[10:]}...\nINTERNAL ERROR:\n{resp.text}\nRetry after 60 seconds")
        time.sleep(60)
        return handle_dex_req(req)
    elif resp.status_code == 429:
        logger.warning(f"{resp.url[10:]}...\nRATE LIMIT ERROR:\n{resp.text}\nRetry after 60 seconds")
        time.sleep(60)
        return handle_dex_req(req)
    else:
        resp.raise_for_status()

    return resp.json()


def get_token_pair_info(token_contracts: Iterable[TokenAddress]) -> list[dict]:
    URL, N_MAX = "https://api.dexscreener.com/latest/dex/tokens/", 30
    token_contracts = list(token_contracts)
    random.shuffle(token_contracts)  # Shuffle as query result sometimes differs
    splits = batched(token_contracts, N_MAX)  # Split requests into max n of addresses
    all_pairs = []
    with requests.Session() as session:
        for split in splits:
            url = f"{URL}{','.join(split)}"
            req = functools.partial(session.get, url=url)
            data = handle_dex_req(req)
            pairs = data.get("pairs", [])
            if pairs:
                all_pairs.extend(pairs)
    return all_pairs


def is_ca(x, contract: str) -> bool:
    return x["baseToken"]["address"].lower() == contract.lower()


def get_volume_usd(x: dict) -> Decimal:
    return x.get("volume", {}).get("h24", Decimal(0))


def get_liquidity_usd(x: dict) -> Decimal:
    return x.get("liquidity", {}).get("usd", Decimal(0))


def find_token(pair_info: list[dict], address: str) -> dict:
    # find all pairs which have the token
    filter_list = list(filter(lambda x: is_ca(x, address), pair_info))
    if not filter_list:
        return {}
    # get the pair with best liquidity, if liq reading faulty, use 24h volume
    max_liquidity = max(filter_list, key=lambda x: get_liquidity_usd(x))
    if get_liquidity_usd(max_liquidity) == Decimal(0):
        max_volume = max(filter_list, key=lambda x: get_volume_usd(x))
        best_pair = max_volume
    else:
        best_pair = max_liquidity
    return best_pair


def find_tokens(token_contracts, pair_info) -> tuple[dict, set]:
    found_info = {}
    not_found = set()
    for address in token_contracts:
        pair = find_token(pair_info, address)
        if pair:
            name = pair.get("baseToken", {}).get("name", "")
            symbol = pair.get("baseToken", {}).get("symbol", "")
            chain = pair.get("chainId", "")
            price = pair.get("priceUsd", Decimal(0))
            liquidity = pair.get("liquidity", {}).get("usd", Decimal(0))
            market_cap = pair.get("marketCap", Decimal(0))
            link = pair.get("url", "")

            if not price:
                not_found.add(address)
                continue

            found_info[address] = {
                "address": address,
                "name": name,
                "symbol": symbol,
                "chain": chain,
                "price": Decimal(price),
                "liquidity": Decimal(liquidity),
                "market_cap": Decimal(market_cap),
                "link": link,
            }
        else:
            not_found.add(address)

    return found_info, not_found


def get_token_price_info(token_contracts: list[TokenAddress]):
    pair_info = get_token_pair_info(token_contracts)
    found_info_all, not_found = find_tokens(token_contracts, pair_info)
    n_retries = 3
    while not_found and n_retries:
        pair_info = get_token_pair_info(list(not_found))
        found_info, not_found = find_tokens(list(not_found), pair_info)
        found_info_all = {**found_info_all, **found_info}
        n_retries -= 1

    return found_info_all


def get_balance_update(
    evm_wallets,
    sol_wallets,
    sui_wallets,
    evm_info,
    unsupported_balances,
    moralis_api_key,
    sui_api_key,
    old_balances,
    native_bal_path,
) -> tuple:
    def sui_req() -> dict:
        return get_sui_balances(sui_wallets, sui_api_key)

    def gecko_req() -> dict:
        # chains = set(map(lambda x: x.moralis, evm_info.values()))
        gecko_tickers = set(map(lambda x: x.gecko_ticker, evm_info.values()))
        return {gt: get_gecko_price(gt) for gt in gecko_tickers}

    def balances_req() -> dict:
        balances = get_token_balances(
            sol_wallets=sol_wallets,
            evm_wallets=evm_wallets,
            evm_chains=list(evm_info),
            moralis_api_key=moralis_api_key,
            old_balances=old_balances,
            native_bal_path=native_bal_path,
        )

        return balances

    with concurrent.futures.ThreadPoolExecutor() as executor:
        sui_balances_future = executor.submit(sui_req)
        evm_prices_future = executor.submit(gecko_req)
        token_balances_future = executor.submit(balances_req)

        sui_balances = sui_balances_future.result()
        token_balances = token_balances_future.result()
        evm_prices = evm_prices_future.result()

    # set CoinGecko price
    for chain, info in evm_info.items():
        if info.gecko_ticker in evm_prices:
            token_balances[chain].price = evm_prices[chain]

    all_balances = {**sui_balances, **token_balances}
    token_contracts = set(
        {
            **sui_balances,
            **unsupported_balances,
            **token_balances,
        }.keys()
    ).difference(set(evm_info))
    return token_contracts, all_balances


def get_and_set_price_info(token_contracts, unsupported_balances, all_balances):
    price_info = get_token_price_info(list(token_contracts))

    for token, price_info in price_info.items():
        if token in unsupported_balances:
            info = TokenInfo(**price_info, balances={"unknown": unsupported_balances[token]})
            all_balances[token] = info
        else:
            all_balances[token].price = price_info["price"]
            all_balances[token].liquidity = price_info["liquidity"]
            all_balances[token].market_cap = price_info["market_cap"]
            all_balances[token].link = price_info["link"]

    return all_balances
